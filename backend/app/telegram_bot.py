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
import logging

import httpx

from app import repositories as repo
from app.config import get_settings
from app.database import SessionLocal
from app.orchestrator import orchestrator
from app.turn import run_turn

log = logging.getLogger("telegram")

_APPROVE = "confirm:approve"
_REJECT = "confirm:reject"


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

    async def aclose(self) -> None:
        await self._client.aclose()


class TelegramBot:
    def __init__(self, transport, allowmap: dict[int, str], poll_timeout: int = 25):
        self.tx = transport
        self.allowmap = allowmap
        self.poll_timeout = poll_timeout
        self._conv: dict[int, int] = {}          # chat_id → conversation_id (продолжение диалога)
        self._pending_conv: dict[int, int] = {}  # chat_id → cid, ждущий подтверждения (#30)
        self._offset: int | None = None
        self._stop = False

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
        tg_id = (msg.get("from") or {}).get("id")
        text = (msg.get("text") or "").strip()
        voice = msg.get("voice") or msg.get("audio")   # #34 — голосовое/аудио
        if not text and not voice:
            return

        user = await self.resolve_user(tg_id)
        if not user:
            # доступ запрещён: не раскрываем детали, просто просим связать аккаунт
            await self._send(chat_id, "Доступ не настроен. Обратитесь к администратору "
                                      "для привязки вашего Telegram к учётной записи.")
            log.info("rejected non-allowlist tg_id=%s", tg_id)
            return

        if text in ("/start", "/help"):
            await self._send(chat_id, f"Здравствуйте, {user['name']}! Я ИИ-ассистент "
                                      "«Ремтехники». Напишите (или наговорите) вопрос по "
                                      "спецтехнике XCMG, запчастям, КП, сметам или документам.")
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

        await self._run_turn(chat_id, user, text, audio=audio)

    # ── прогон хода через общее ядро ─────────────────────────────────────────
    async def _run_turn(self, chat_id: int, user: dict, text: str,
                        audio: bytes | None = None) -> None:
        await self._chat_action(chat_id, "typing")
        collected: list[str] = []
        sources: list[dict] = []

        async def emit(event: dict) -> None:
            etype = event.get("type")
            if etype == "conversation":
                self._conv[chat_id] = event["id"]
            elif etype == "done":
                if event.get("text"):
                    collected.append(event["text"])
            elif etype == "sources":
                sources.extend(event.get("items") or [])
            elif etype == "awaiting_confirmation":
                # побочное действие требует подтверждения (#30) — спрашиваем кнопками
                self._pending_conv[chat_id] = self._conv.get(chat_id, 0)
                await self._send(
                    chat_id,
                    f"Требуется подтверждение: *{event.get('label') or event.get('tool')}*.",
                    reply_markup={"inline_keyboard": [[
                        {"text": "✅ Подтвердить", "callback_data": _APPROVE},
                        {"text": "❌ Отклонить", "callback_data": _REJECT},
                    ]]},
                )
            elif etype == "error":
                collected.append("⚠️ " + event.get("text", "Ошибка"))

        try:
            cid = await run_turn(user, self._conv.get(chat_id), text, [], None, emit,
                                 audio=audio, audio_mime="audio/ogg")
            self._conv[chat_id] = cid
        except Exception:
            log.exception("telegram turn failed chat=%s", chat_id)
            await self._send(chat_id, "Внутренняя ошибка обработки запроса. Попробуйте ещё раз.")
            return

        answer = "\n".join(collected).strip() or "Готово."
        if sources:
            lines = "\n".join(f"• {s.get('title') or s.get('source') or 'источник'}" for s in sources)
            answer += "\n\n📎 Источники:\n" + lines
        await self._send(chat_id, answer)

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
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            await self.tx.call("sendMessage", payload)
        except Exception:
            # Markdown мог сломаться на спецсимволах — повтор без разметки
            payload.pop("parse_mode", None)
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
            try:
                await self.handle_update(upd)
            except Exception:
                log.exception("update handling failed")
        return len(updates)

    async def run(self) -> None:
        log.info("telegram bot started (allow-list=%d)", len(self.allowmap))
        while not self._stop:
            try:
                await self.poll_once()
            except Exception:
                log.exception("poll error; retry in 3s")
                await asyncio.sleep(3)


def build_bot() -> TelegramBot:
    s = get_settings()
    if not s.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан — бот не может стартовать")
    return TelegramBot(
        TelegramTransport(s.telegram_bot_token),
        s.telegram_allowmap,
        s.telegram_poll_timeout,
    )


def main() -> None:
    logging.basicConfig(level=get_settings().log_level)
    bot = build_bot()
    asyncio.run(bot.run())


if __name__ == "__main__":
    main()
