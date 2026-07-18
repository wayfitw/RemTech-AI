"""Issue #31 (TASK-1001, EPIC-10) — Telegram-ассистент как тонкий клиент API.

Бот НЕ содержит логики агента: только транспорт (Bot API, long polling) и
маршрутизацию к channel-agnostic ядру `app.turn.run_turn`. Вся доменная логика —
агент-цикл, инструменты, RBAC, история, activity_log, гейт подтверждения (#30) —
переиспользуется с бэкенда без дублирования (тот же контракт, что у веб-канала).

Авторизация канала — allow-list: Telegram-ID сопоставляется с активной учётной
записью (config.telegram_allowmap, управляется администратором). Сообщения от
не-сопоставленных ID отклоняются (RBAC не обойти через Telegram).

Запуск отдельным процессом: `python -m app.telegram_bot` (не поднимается вместе
с REST/WS API). 152-ФЗ: разработка/тест разрешены; прод — после закрытия контура.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re

import httpx

from app import repositories as repo
from app import storage
from app.config import get_settings
from app.database import SessionLocal
from app.orchestrator import orchestrator
from app.turn import run_turn
from services import news_digest
from services.extract import detect_kind

log = logging.getLogger("telegram")

_APPROVE = "confirm:approve"
_REJECT = "confirm:reject"

_HR_RE = re.compile(r"^\s*([-*_])\1{2,}\s*$")           # --- *** ___
_HEAD_RE = re.compile(r"^\s*#{1,6}\s+(.*)$")            # markdown-заголовок
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")       # **жирный** / __жирный__
_BULLET_RE = re.compile(r"^(\s*)[-*]\s+")               # маркер списка
_TAG_RE = re.compile(r"<[^>]+>")


def esc(s: str) -> str:
    """HTML-экранирование динамического текста для parse_mode=HTML."""
    return html.escape(s or "", quote=False)


def md_to_tg_html(md: str) -> str:
    """Конвертирует markdown Claude в безопасный Telegram-HTML: заголовки ###/**bold**
    → <b>, маркеры списка → •, горизонтальные линии убираем. Telegram не рендерит
    markdown-заголовки — без этого в чат сыпались сырые ### и **."""
    out = []
    for raw in (md or "").split("\n"):
        line = raw.rstrip()
        if _HR_RE.match(line):
            continue
        m = _HEAD_RE.match(line)
        header = bool(m)
        content = esc(m.group(1) if m else line)
        content = _BOLD_RE.sub(lambda x: f"<b>{x.group(1) or x.group(2)}</b>", content)
        content = _BULLET_RE.sub(r"\1• ", content)
        out.append(f"<b>{content}</b>" if header else content)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


_EXT_RE = re.compile(r"\.(xlsx|xls|docx|doc|pdf|txt|csv|pptx|rtf)$", re.IGNORECASE)


def _source_names(sources: list[dict] | None, limit: int = 5) -> list[str]:
    """Имена документов-источников (#29): дедуп, без расширения, «_»→пробел, лимит."""
    seen: set[str] = set()
    names: list[str] = []
    for s in sources or []:
        raw = s.get("file_name") or s.get("title") or s.get("source") or ""
        name = _EXT_RE.sub("", raw).replace("_", " ").strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    if len(names) > limit:
        names = names[:limit] + [f"ещё {len(names) - limit}"]
    return names


class TelegramTransport:
    """Тонкая обёртка над Bot API (httpx). Инъекция для тестов без сети."""

    def __init__(self, token: str, client: httpx.AsyncClient | None = None):
        self._base = f"https://api.telegram.org/bot{token}"
        # trust_env=False: не использовать системный прокси Windows (VPN-клиент может
        # включать/выключать 127.0.0.1-прокси, что даёт плавающий ConnectError). До
        # api.telegram.org ходим напрямую — соединение стабильно без прокси.
        self._client = client or httpx.AsyncClient(timeout=60.0, trust_env=False)

    async def call(self, method: str, payload: dict) -> dict:
        r = await self._client.post(f"{self._base}/{method}", json=payload)
        r.raise_for_status()
        return r.json()

    async def get_file_bytes(self, file_id: str) -> bytes:
        """Скачивает файл Telegram (голосовое/аудио) по file_id (#34)."""
        info = await self.call("getFile", {"file_id": file_id})
        path = info["result"]["file_path"]
        base = self._base.replace("/bot", "/file/bot")
        r = await self._client.get(f"{base}/{path}")
        r.raise_for_status()
        return r.content

    async def send_file(self, chat_id: int, data: bytes, filename: str,
                        method: str = "sendDocument", field: str = "document") -> dict:
        """Отправляет файл (multipart): sendPhoto для картинок, sendDocument для
        документов/видео. Возвращает ответ Telegram."""
        r = await self._client.post(
            f"{self._base}/{method}",
            data={"chat_id": str(chat_id)},
            files={field: (filename, data)})
        r.raise_for_status()
        return r.json()

    async def aclose(self) -> None:
        await self._client.aclose()


class TelegramBot:
    def __init__(self, transport, allowmap: dict[int, str], poll_timeout: int = 25,
                 agent_name: str = ""):
        self.tx = transport
        self.allowmap = allowmap
        self.poll_timeout = poll_timeout
        self._agent_name = (agent_name or "").strip()   # персона бота (имя агента)
        self._agent_id: int | None = None                # резолвится лениво по имени
        self._agent_resolved = False
        self._conv: dict[int, int] = {}          # chat_id → conversation_id (продолжение диалога)
        self._pending_conv: dict[int, int] = {}  # chat_id → cid, ждущий подтверждения (#30)
        self._offset: int | None = None
        self._stop = False
        # Апдейты обрабатываем как фоновые задачи, чтобы длинный ход (видео, ожидание
        # подтверждения) НЕ блокировал polling-цикл — иначе нажатие кнопки не дойдёт.
        self._bg: set[asyncio.Task] = set()
        self._chat_locks: dict[int, asyncio.Lock] = {}   # серіализация ходов одного чата

    def _lock_for(self, chat_id: int) -> asyncio.Lock:
        lock = self._chat_locks.get(chat_id)
        if lock is None:
            lock = self._chat_locks[chat_id] = asyncio.Lock()
        return lock

    def _spawn(self, coro) -> None:
        """Запускает обработку апдейта фоном (с логом ошибок) и держит ссылку на
        задачу, пока она не завершится (иначе GC может её оборвать)."""
        task = asyncio.create_task(self._guard(coro))
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    @staticmethod
    async def _guard(coro) -> None:
        try:
            await coro
        except Exception:
            log.exception("update handling failed")

    async def agent_id(self) -> int | None:
        """id агента-персоны по имени из конфига (кэш). Нет имени/агента → None
        (дефолтный агент). Личный ассистент директора для Telegram (web — сотрудники)."""
        if self._agent_resolved or not self._agent_name:
            return self._agent_id
        async with SessionLocal() as s:
            for a in await repo.list_agents(s):
                if a.name == self._agent_name:
                    self._agent_id = a.id
                    break
            else:
                log.warning("telegram_agent «%s» не найден — дефолтный агент", self._agent_name)
        self._agent_resolved = True
        return self._agent_id

    # ── авторизация канала (allow-list) ──────────────────────────────────────
    async def resolve_user(self, tg_id: int) -> dict | None:
        username = self.allowmap.get(tg_id)
        if not username:
            return None
        async with SessionLocal() as s:
            u = await repo.get_user_by_username(s, username)
        if not u or not u.active:
            return None
        return {"user_id": u.id, "username": u.username,
                "name": u.full_name or u.username, "role": u.role}

    # ── обработка одного обновления ──────────────────────────────────────────
    async def handle_update(self, update: dict) -> None:
        if "callback_query" in update:
            await self._on_callback(update["callback_query"])
            return
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return
        chat_id = msg["chat"]["id"]
        frm = msg.get("from") or {}
        tg_id = frm.get("id")
        text = (msg.get("text") or "").strip()
        voice = msg.get("voice") or msg.get("audio")   # #34 — голосовое/аудио
        document = msg.get("document")                 # присланный файл (pptx/docx/pdf/…)
        photo = msg.get("photo")                       # присланное фото (список размеров)
        caption = (msg.get("caption") or "").strip()   # подпись к файлу/фото
        if not text and not voice and not document and not photo:
            return

        # Ходы одного чата — строго по очереди (лок), чтобы не пересекались; но
        # callback подтверждения обрабатывается отдельной задачей и лок НЕ ждёт,
        # поэтому кнопка резолвит ожидание даже пока идёт этот ход.
        async with self._lock_for(chat_id):
            await self._dispatch_message(chat_id, frm, tg_id, text,
                                         voice, document, photo, caption)

    async def _dispatch_message(self, chat_id, frm, tg_id, text,
                                voice, document, photo, caption) -> None:
        user = await self.resolve_user(tg_id)
        if not user:
            # доступ запрещён: не раскрываем детали, просто просим связать аккаунт
            await self._send(chat_id, "Доступ не настроен. Обратитесь к администратору "
                                      "для привязки вашего Telegram к учётной записи.")
            log.info("rejected non-allowlist tg_id=%s", tg_id)
            return

        if text in ("/start", "/help"):
            # имя из профиля Telegram (first_name), фолбэк — имя учётной записи
            name = (frm.get("first_name") or "").strip() or user["name"]
            await self._send(chat_id, f"Здравствуйте, {esc(name)}! Я ИИ-ассистент "
                                      "«Ремтехники». Напишите (или запишите) вопрос по "
                                      "спецтехнике XCMG, запчастям, КП, сметам, документам "
                                      "или тендерам.\n\n/new — начать новый диалог.")
            return

        if text == "/new":
            self._conv.pop(chat_id, None)
            self._pending_conv.pop(chat_id, None)
            await self._send(chat_id, "Начат новый диалог. Задайте вопрос.")
            return

        # #34 — голосовой ввод: скачиваем и распознаём тем же ходом (run_turn/STT-хук)
        audio = None
        if voice and not text:
            await self._chat_action(chat_id, "typing")
            try:
                audio = await self.tx.get_file_bytes(voice["file_id"])
            except Exception:
                log.exception("voice download failed chat=%s", chat_id)
                await self._send(chat_id, "Не удалось получить голосовое сообщение.")
                return

        # Входящий файл (документ/фото) → скачиваем и передаём ходу вложением, чтобы
        # модель «увидела» содержимое (презентация/договор/картинка). Подпись — как текст.
        file_ids: list[int] = []
        attach = document or (photo[-1] if photo else None)
        if attach:
            await self._chat_action(chat_id, "typing")
            if (attach.get("file_size") or 0) > 20 * 1024 * 1024:
                await self._send(chat_id, "Файл слишком большой — Telegram отдаёт боту до 20 МБ.")
                return
            fname = (document.get("file_name") if document else "") or "photo.jpg"
            try:
                data = await self.tx.get_file_bytes(attach["file_id"])
            except Exception:
                log.exception("file download failed chat=%s", chat_id)
                await self._send(chat_id, "Не удалось получить файл.")
                return
            async with SessionLocal() as s:
                rec = await storage.save_bytes(s, user["user_id"], self._conv.get(chat_id),
                                               fname, data, kind=detect_kind(fname), direction="input")
                await s.commit()
                file_ids = [rec.id]
            if not text:
                text = caption or "Разбери этот файл."

        await self._run_turn(chat_id, user, text, audio=audio, file_ids=file_ids)

    # ── прогон хода через общее ядро ─────────────────────────────────────────
    async def _run_turn(self, chat_id: int, user: dict, text: str,
                        audio: bytes | None = None, file_ids: list[int] | None = None) -> None:
        await self._chat_action(chat_id, "typing")
        collected: list[str] = []
        sources: list[dict] = []
        media: list[tuple[int, str, str]] = []   # (file_id, name, тип: image|document)

        async def emit(event: dict) -> None:
            etype = event.get("type")
            if etype == "conversation":
                self._conv[chat_id] = event["id"]
            elif etype == "done":
                if event.get("text"):
                    collected.append(event["text"])
            elif etype == "sources":
                sources.extend(event.get("items") or [])
            elif etype in ("image", "document"):
                # сгенерированные картинки/документы (КП, сметы, видео) — шлём файлом
                if event.get("file_id"):
                    media.append((event["file_id"], event.get("name") or "file", etype))
            elif etype == "awaiting_confirmation":
                # побочное действие требует подтверждения (#30) — спрашиваем кнопками
                self._pending_conv[chat_id] = self._conv.get(chat_id, 0)
                await self._send(
                    chat_id,
                    f"Требуется подтверждение: <b>{esc(event.get('label') or event.get('tool') or '')}</b>.",
                    reply_markup={"inline_keyboard": [[
                        {"text": "✅ Подтвердить", "callback_data": _APPROVE},
                        {"text": "❌ Отклонить", "callback_data": _REJECT},
                    ]]},
                )
            elif etype == "error":
                collected.append("⚠️ " + event.get("text", "Ошибка"))

        try:
            cid = await run_turn(user, self._conv.get(chat_id), text, file_ids or [],
                                 await self.agent_id(), emit, audio=audio, audio_mime="audio/ogg",
                                 channel="telegram")
            self._conv[chat_id] = cid
        except Exception:
            log.exception("telegram turn failed chat=%s", chat_id)
            await self._send(chat_id, "Внутренняя ошибка обработки запроса. Попробуйте ещё раз.")
            return

        plain = "\n".join(collected).strip() or "Готово."
        answer = md_to_tg_html(plain)
        names = _source_names(sources)
        if names:
            # компактно: одна строка, имена без расширений, через середину, курсивом
            answer += "\n\n📎 <i>" + esc(" · ".join(names)) + "</i>"
        await self._send(chat_id, answer)
        # Сгенерированные файлы (картинки/КП/сметы/видео) — отправляем после текста.
        for file_id, name, etype in media:
            await self._send_file(chat_id, file_id, name, etype)
        # Голос принимаем на входе (STT), но ответ шлём только текстом — голосовой
        # ответ (TTS) в Telegram-канале отключён по требованию.

    async def _send_file(self, chat_id: int, file_id: int, name: str, etype: str) -> None:
        """Шлёт сгенерированный файл в Telegram: картинку — sendPhoto (с откатом на
        sendDocument), прочее — sendDocument. Ошибка не рвёт ход (текст уже ушёл)."""
        try:
            async with SessionLocal() as s:
                rec = await repo.get_file_record(s, file_id)
            blob = storage.read_record_bytes(rec) if rec else None
            if not blob:
                return
            data, fname = blob
            if etype == "image":
                try:
                    await self.tx.send_file(chat_id, data, fname, "sendPhoto", "photo")
                    return
                except Exception:   # слишком большая/неподдерживаемая картинка — как документ
                    pass
            await self.tx.send_file(chat_id, data, fname, "sendDocument", "document")
        except Exception:
            log.exception("send file failed chat=%s file=%s", chat_id, file_id)
            await self._send(chat_id, f"⚠️ Не удалось отправить файл «{esc(name)}».")

    # ── ответ на кнопку подтверждения ────────────────────────────────────────
    async def _on_callback(self, cq: dict) -> None:
        data = cq.get("data", "")
        chat_id = (((cq.get("message") or {}).get("chat")) or {}).get("id")
        cid = self._pending_conv.pop(chat_id, None)
        if cid:
            orchestrator.resolve_confirmation(cid, data == _APPROVE)
        await self.tx.call("answerCallbackQuery", {
            "callback_query_id": cq.get("id"),
            "text": "Подтверждено" if data == _APPROVE else "Отклонено",
        })

    # ── транспортные помощники ───────────────────────────────────────────────
    async def _send(self, chat_id: int, text: str, reply_markup: dict | None = None) -> None:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            await self.tx.call("sendMessage", payload)
        except Exception:
            # HTML мог сломаться на разметке — повтор чистым текстом без тегов
            payload.pop("parse_mode", None)
            payload["text"] = _TAG_RE.sub("", text)
            await self.tx.call("sendMessage", payload)

    async def _chat_action(self, chat_id: int, action: str) -> None:
        try:
            await self.tx.call("sendChatAction", {"chat_id": chat_id, "action": action})
        except Exception:
            pass

    # ── цикл long polling ────────────────────────────────────────────────────
    async def poll_once(self) -> int:
        payload = {"timeout": self.poll_timeout, "allowed_updates": ["message", "callback_query"]}
        if self._offset is not None:
            payload["offset"] = self._offset
        resp = await self.tx.call("getUpdates", payload)
        updates = resp.get("result", [])
        for upd in updates:
            self._offset = upd["update_id"] + 1
            # Не ждём завершения хода: обрабатываем фоном, чтобы цикл продолжал
            # получать апдейты (в т.ч. нажатие кнопки подтверждения) во время
            # долгой операции (видео/подтверждение). Порядок ходов ОДНОГО чата
            # сохраняется локом внутри handle_update.
            self._spawn(self.handle_update(upd))
        return len(updates)

    # ── доставка напоминаний ─────────────────────────────────────────────────
    async def _deliver_reminders(self) -> None:
        """Один проход: шлёт заблаговременные сигналы, время которых наступило.
        Отправленные смещения убираются; когда все сработали — напоминание удаляется.
        Просроченные больше чем на час — тихо отбрасываем (не спамим устаревшим)."""
        from datetime import datetime, timedelta, timezone
        uname_to_tg = {uname: tg for tg, uname in self.allowmap.items()}
        now = datetime.now(timezone.utc)
        async with SessionLocal() as s:
            for rem in await repo.all_reminders(s):
                user = await repo.get_user(s, rem.user_id)
                tg = uname_to_tg.get(user.username) if user else None
                if tg is None:
                    continue   # пользователь недоступен через этот бот — не трогаем
                pending = list(rem.lead_pending or [])
                fired = []
                for off in pending:
                    trigger = rem.due_at - timedelta(minutes=off)
                    if trigger <= now:
                        if (now - trigger) <= timedelta(hours=1):
                            await self._send_reminder(tg, rem, off)
                        fired.append(off)
                if fired:
                    remaining = [o for o in pending if o not in fired]
                    if remaining:
                        rem.lead_pending = remaining
                    else:
                        await s.delete(rem)
            await s.commit()

    async def _send_reminder(self, chat_id: int, rem, off: int) -> None:
        when = rem.due_at.astimezone().strftime("%H:%M")
        head = f"🔔 Через {off} мин ({when})" if off else "🔔 Пора"
        await self._send(chat_id, f"{head}: {esc(rem.text)}")

    async def _reminder_loop(self) -> None:
        while not self._stop:
            try:
                await self._deliver_reminders()
            except Exception:
                log.exception("reminder delivery error")
            await asyncio.sleep(30)

    # ── утренний дайджест ТГ-групп ───────────────────────────────────────────
    async def _run_digest(self) -> None:
        """Один утренний дайджест: модель собирает и резюмирует сообщения групп за
        ночь (через инструмент digest_tg_groups) и шлёт директору."""
        from services import telethon_svc
        if not (telethon_svc.is_configured() and self.allowmap):
            return
        tg, username = next(iter(self.allowmap.items()))   # адресат — владелец бота
        async with SessionLocal() as s2:
            u = await repo.get_user_by_username(s2, username)
            if not u or not u.active:
                return
            groups = [g.ref for g in await repo.list_digest_groups(s2, u.id)]
        if not (groups or get_settings().tg_digest_group_list):
            return   # нет групп для сводки — не шлём пустое
        user = {"user_id": u.id, "username": u.username,
                "name": u.full_name or u.username, "role": u.role}
        parts: list[str] = []

        async def emit(ev):
            if ev.get("type") == "delta":
                parts.append(ev.get("text", ""))
        await run_turn(user, None,
                       "Собери и пришли краткую сводку сообщений из рабочих групп за прошедшую "
                       "ночь (digest_tg_groups за 12 часов): по каждой группе — ключевые темы, "
                       "решения и что требует моего внимания.", [], await self.agent_id(), emit)
        text = md_to_tg_html("".join(parts).strip() or "За ночь ничего существенного.")
        await self._send(tg, "🌙 <b>Утренний дайджест групп</b>\n\n" + text)

    async def _digest_loop(self) -> None:
        from datetime import datetime
        last_date = None
        while not self._stop:
            try:
                now = datetime.now()
                if now.hour == get_settings().tg_digest_hour and last_date != now.date():
                    await self._run_digest()   # сам проверит наличие групп
                    last_date = now.date()   # раз в сутки
            except Exception:
                log.exception("digest error")
            await asyncio.sleep(300)   # проверка раз в 5 минут

    # ── дайджест новостей по ИИ (#42) ────────────────────────────────────────
    async def _run_news_digest(self) -> None:
        """Доставка дайджеста первому лицу через общий сборщик выпуска (news_digest.
        run_once) — та же функция, что у Celery beat и админ-эндпоинта. Доставку шлём
        своим уже открытым транспортом (self._send)."""
        async def deliver(chat_id: int, text: str) -> None:
            await self._send(chat_id, "📰 <b>Дайджест новостей по ИИ</b>\n\n" + md_to_tg_html(text))

        async with SessionLocal() as s:
            await news_digest.run_once(s, tg_sender=deliver, agent_id=await self.agent_id(),
                                       require_enabled=True)

    async def _news_loop(self) -> None:
        from datetime import datetime
        last_date = None
        while not self._stop:
            try:
                s = get_settings()
                now = datetime.now()
                if s.ai_news_enabled and now.hour == s.ai_news_hour and last_date != now.date():
                    await self._run_news_digest()
                    last_date = now.date()
            except Exception:
                log.exception("news digest error")
            await asyncio.sleep(300)

    # ── уведомления о новых письмах ──────────────────────────────────────────
    def _owner_tg(self) -> int | None:
        """Кому слать личные уведомления (почта/дайджест) — владелец бота."""
        return next(iter(self.allowmap), None)

    async def _notify_email(self, source: str, e: dict) -> None:
        tg = self._owner_tg()
        if tg is None:
            return
        label = {"gmail": "Gmail", "yandex": "Яндекс"}.get(source, source)
        txt = (f"📧 <b>Новое письмо ({label})</b>\n"
               f"От: {esc(e.get('from') or e.get('email') or '?')}\n"
               f"Тема: {esc(e.get('subject') or '(без темы)')}")
        if e.get("snippet"):
            txt += f"\n\n{esc(e['snippet'][:200])}"
        await self._send(tg, txt)

    async def _mail_loop(self) -> None:
        """Пуш-уведомления о новых письмах. На старте берём текущий максимум UID
        (не спамим старым), далее шлём только письма новее последнего виденного."""
        from services import mail_svc
        last: dict[str, int] = {}
        for src in ("gmail", "yandex"):
            if mail_svc.is_configured(src):
                try:
                    last[src] = await asyncio.to_thread(mail_svc.newest_uid, src)
                except Exception:
                    log.exception("mail baseline %s", src)
        while not self._stop:
            for src in list(last):
                try:
                    new_max, emails = await asyncio.to_thread(mail_svc.fetch_new, src, last[src])
                    for e in emails:
                        await self._notify_email(src, e)
                    last[src] = new_max
                except Exception:
                    log.exception("mail poll %s", src)
            await asyncio.sleep(max(30, get_settings().mail_poll_seconds))

    async def run(self) -> None:
        log.info("telegram bot started (allow-list=%d)", len(self.allowmap))
        tasks = [asyncio.create_task(self._reminder_loop()),
                 asyncio.create_task(self._digest_loop()),
                 asyncio.create_task(self._news_loop()),
                 asyncio.create_task(self._mail_loop())]
        try:
            while not self._stop:
                try:
                    await self.poll_once()
                except Exception:
                    log.exception("poll error; retry in 3s")
                    await asyncio.sleep(3)
        finally:
            for t in tasks:
                t.cancel()


def build_bot() -> TelegramBot:
    s = get_settings()
    if not s.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан — бот не может стартовать")
    return TelegramBot(
        TelegramTransport(s.telegram_bot_token),
        s.telegram_allowmap,
        s.telegram_poll_timeout,
        s.telegram_agent,
    )


def main() -> None:
    logging.basicConfig(level=get_settings().log_level)
    bot = build_bot()
    asyncio.run(bot.run())


if __name__ == "__main__":
    main()
