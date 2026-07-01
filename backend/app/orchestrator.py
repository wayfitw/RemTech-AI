"""Cutover Стадия 3b — агент-луп на async-слое (PostgreSQL + async storage).

Транспорт — emit() события WebSocket. DB-операции — через короткие async-сессии
(SessionLocal), файлы — через app.storage.
"""
import asyncio
import base64
from datetime import datetime
from typing import Awaitable, Callable

import anthropic

from agent.tools import TOOLS
from app import repositories as repo
from app import storage
from app.config import get_settings
from app.database import SessionLocal
from services import docgen, replicate_svc, websearch

Emit = Callable[[dict], Awaitable[None]]
settings = get_settings()
client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key or "missing")

SYSTEM_PROMPT = """Ты корпоративный ИИ-ассистент компании «Ремтехника» (продажа спецтехники XCMG и запчастей). Отвечаешь на русском языке.

Правила:
- Ты умный агент — сам решаешь какой инструмент вызвать, когда и сколько раз. Можешь вызывать несколько инструментов подряд для одной задачи.
- Отвечай кратко и по делу.
- Перед вызовом инструмента пиши одну короткую строку что делаешь. Итог пиши ПОСЛЕ всех инструментов.
- ПОЛНОТА: если спросили A и B — ответь на A и B. Не пропускай части запроса.
- Когда инструмент не сработал — объясни конкретно что и почему, и что делать дальше.

Работа с документами:
- Если пользователь загрузил .docx и просит изменить — сначала read_doc (параграфы с hash-ID), затем apply_doc_edits. НЕ используй create_docx для правки загруженного файла.
- create_docx — только для НОВЫХ документов с нуля."""


def _safe_content(content):
    if not isinstance(content, list):
        return content

    def _get(block, attr, default=None):
        if hasattr(block, attr):
            return getattr(block, attr)
        if isinstance(block, dict):
            return block.get(attr, default)
        return default

    result = []
    for block in content:
        btype = _get(block, "type")
        if btype == "text":
            text = _get(block, "text", "")
            if text:
                result.append({"type": "text", "text": text})
        elif btype == "tool_use":
            result.append({"type": "tool_use", "id": _get(block, "id", ""),
                           "name": _get(block, "name", ""), "input": _get(block, "input", {})})
    return result or content


def _sanitize_history(history: list) -> list:
    while history and history[0]["role"] != "user":
        history = history[1:]

    def _has_tool_use(msg):
        c = msg.get("content", [])
        return isinstance(c, list) and any(
            isinstance(b, dict) and b.get("type") == "tool_use" for b in c)

    def _has_tool_result(msg):
        c = msg.get("content", [])
        return isinstance(c, list) and any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in c)

    def _text(msg):
        c = msg.get("content", "")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return " ".join(b.get("text", "") for b in c
                            if isinstance(b, dict) and b.get("type") == "text").strip()
        return ""

    clean, i = [], 0
    while i < len(history):
        msg = history[i]
        if msg["role"] == "assistant" and _has_tool_use(msg):
            if i + 1 < len(history) and _has_tool_result(history[i + 1]):
                t = _text(msg)
                skip = 2
                if not t and i + 2 < len(history) and history[i + 2]["role"] == "assistant" \
                        and not _has_tool_use(history[i + 2]):
                    t = _text(history[i + 2]); skip = 3
                if t:
                    clean.append({"role": "assistant", "content": t})
                i += skip
                continue
            i += 1
            continue
        if _has_tool_result(msg):
            i += 1
            continue
        clean.append(msg)
        i += 1
    while clean and clean[0]["role"] != "user":
        clean = clean[1:]
    return clean


class Orchestrator:
    def __init__(self):
        self._histories: dict[int, list] = {}
        self._current_image: dict[int, bytes] = {}
        self._current_docx: dict[int, tuple[bytes, str]] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    async def process(self, conversation_id, user_id, text, attachments, emit: Emit):
        lock = self._locks.setdefault(conversation_id, asyncio.Lock())
        async with lock:
            try:
                await self._run(conversation_id, user_id, text, attachments, emit)
            except Exception as e:
                await emit({"type": "error", "text": f"Ошибка: {e}"})

    async def _load_history(self, cid) -> list:
        if cid not in self._histories:
            async with SessionLocal() as s:
                self._histories[cid] = await repo.load_history(s, cid, limit=40)
        return self._histories[cid]

    def _build_user_content(self, cid, text, attachments):
        parts, doc_context = [], []
        for att in attachments or []:
            if att["kind"] == "image":
                self._current_image[cid] = att["data"]
                parts.append({"type": "image", "source": {
                    "type": "base64", "media_type": "image/jpeg",
                    "data": base64.standard_b64encode(att["data"]).decode()}})
            else:
                if att["kind"] == "docx":
                    self._current_docx[cid] = (att["data"], att["name"])
                if att.get("text"):
                    doc_context.append(f"Файл «{att['name']}»:\n{att['text']}")
        body = text
        if doc_context:
            body = "\n\n---\n\n".join(doc_context) + "\n\n---\n\n" + text
        if parts:
            parts.append({"type": "text", "text": body})
            return parts
        return body

    async def _run(self, cid, uid, text, attachments, emit):
        history = await self._load_history(cid)
        user_content = self._build_user_content(cid, text, attachments)
        history.append({"role": "user", "content": user_content})

        async with SessionLocal() as s:
            await repo.save_message(s, cid, uid, "user", user_content)
            await repo.touch_conversation(s, cid)
            conv = await repo.get_conversation(s, cid)
            if conv and conv.title == "Новый чат" and len(history) == 1:
                await repo.set_conversation_title(s, cid, (text or "Чат")[:60])
            await s.commit()

        history[:] = _sanitize_history(history)

        system = [
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": f"Сейчас: {datetime.now().strftime('%d.%m.%Y %H:%M, %A')}"},
        ]
        cached_tools = list(TOOLS)
        if cached_tools:
            last = dict(cached_tools[-1]); last["cache_control"] = {"type": "ephemeral"}
            cached_tools[-1] = last

        await emit({"type": "status", "text": "Думаю..."})

        final_text = ""
        while True:
            response = await self._stream_once(system, cached_tools, history, emit)
            history.append({"role": "assistant", "content": _safe_content(response.content)})

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if getattr(block, "type", None) == "tool_use":
                        await emit({"type": "tool", "name": block.name, "label": _tool_label(block.name)})
                        result_text = await self._execute_tool(block.name, block.input, emit, uid, cid)
                        tool_results.append({"type": "tool_result", "tool_use_id": block.id,
                                             "content": result_text})
                history.append({"role": "user", "content": tool_results})
                continue

            for block in response.content:
                if getattr(block, "type", None) == "text":
                    final_text = block.text
            if response.stop_reason == "max_tokens":
                final_text = (final_text or "") + "\n\n⚠️ Ответ был обрезан по длине."
            break

        async with SessionLocal() as s:
            await repo.save_message(s, cid, uid, "assistant", final_text)
            await repo.log_activity(s, uid, "message", text[:200])
            await s.commit()
        await emit({"type": "done", "text": final_text})

    async def _stream_once(self, system, tools, history, emit):
        last_err = None
        for attempt in range(4):
            try:
                async with client.messages.stream(
                    model=settings.model, max_tokens=settings.max_tokens,
                    system=system, tools=tools, messages=history, timeout=120.0,
                ) as stream:
                    async for chunk in stream.text_stream:
                        await emit({"type": "delta", "text": chunk})
                    return await stream.get_final_message()
            except Exception as e:
                last_err = e
                err = str(e).lower()
                if "rate_limit" in err or "529" in err or "overloaded" in err:
                    await emit({"type": "status", "text": "Сервис занят, повтор..."})
                    await asyncio.sleep(30 if attempt == 0 else 60)
                else:
                    raise
        raise last_err

    async def _save_file(self, uid, cid, name, data, kind, emit, event_type):
        async with SessionLocal() as s:
            rec = await storage.save_bytes(s, uid, cid, name, data, kind=kind)
            await s.commit()
            fid = rec.id
        await emit({"type": event_type, "file_id": fid, "name": name})

    async def _execute_tool(self, name, params, emit, uid, cid):
        try:
            if name == "read_url":
                return await asyncio.to_thread(websearch.read_url, params["url"])

            if name == "generate_image":
                img = await replicate_svc.generate_image_flux(params["prompt"])
                if not img:
                    return "Ошибка генерации: FLUX недоступен (вероятно нет баланса Replicate)."
                self._current_image[cid] = img
                await self._save_file(uid, cid, "image.jpg", img, "image", emit, "image")
                return "Изображение сгенерировано и отправлено пользователю."

            if name == "edit_image":
                cur = self._current_image.get(cid)
                if not cur:
                    return "Нет изображения для редактирования. Сначала загрузи или сгенерируй картинку."
                edited = await replicate_svc.edit_image_flux(cur, params["instruction"])
                if not edited:
                    return "Ошибка редактирования: FLUX недоступен."
                self._current_image[cid] = edited
                await self._save_file(uid, cid, "image_edited.jpg", edited, "image", emit, "image")
                return "Изображение отредактировано и отправлено пользователю."

            if name == "generate_video":
                cur = self._current_image.get(cid)
                video = await replicate_svc.generate_video(params["prompt"], cur, params.get("duration", 5))
                if not video:
                    return "Ошибка генерации видео: Kling недоступен."
                await self._save_file(uid, cid, "video.mp4", video, "other", emit, "document")
                return "Видео готово и отправлено пользователю."

            if name == "create_docx":
                if self._current_docx.get(cid):
                    _, nm = self._current_docx[cid]
                    return (f"СТОП. Уже есть активный документ «{nm}». Для правок — read_doc + apply_doc_edits.")
                data = await asyncio.to_thread(docgen.create_docx, params["content"], params["filename"])
                fname = params["filename"] + ".docx"
                self._current_docx[cid] = (data, fname)
                await self._save_file(uid, cid, fname, data, "docx", emit, "document")
                return f"Документ «{fname}» создан. Для правок — read_doc + apply_doc_edits."

            if name == "create_pdf":
                data = await asyncio.to_thread(docgen.create_pdf, params["content"], params["filename"])
                fname = params["filename"] + ".pdf"
                await self._save_file(uid, cid, fname, data, "pdf", emit, "document")
                return f"PDF «{fname}» создан и отправлен пользователю."

            if name == "read_doc":
                cur = self._current_docx.get(cid)
                if not cur:
                    return "Нет загруженного DOCX. Попроси пользователя прислать .docx файл."
                from utils.doc_editor import read_doc
                return await asyncio.to_thread(read_doc, cur[0])

            if name == "apply_doc_edits":
                cur = self._current_docx.get(cid)
                if not cur:
                    return "Нет загруженного DOCX. Попроси пользователя прислать .docx файл."
                ops = params.get("operations", [])
                if not ops:
                    return "Список операций пустой."
                from utils.doc_editor import apply_doc_edits
                out, diff = await asyncio.to_thread(apply_doc_edits, cur[0], ops)
                base = cur[1].replace(".docx", "")
                fname = (params.get("filename") or base + "_правки") + ".docx"
                self._current_docx[cid] = (out, fname)
                await self._save_file(uid, cid, fname, out, "docx", emit, "document")
                return f"Документ обновлён. {diff}"

            return f"Инструмент {name} не реализован."
        except Exception as e:
            return f"Ошибка при выполнении {name}: {e}"


def _tool_label(name: str) -> str:
    return {
        "read_url": "🌐 Читаю страницу...", "web_search": "🔍 Ищу в интернете...",
        "generate_image": "🎨 Рисую...", "edit_image": "🖼 Редактирую изображение...",
        "generate_video": "🎬 Генерирую видео...", "create_docx": "📝 Создаю документ...",
        "create_pdf": "📄 Создаю PDF...", "read_doc": "📖 Читаю документ...",
        "apply_doc_edits": "📝 Редактирую документ...",
    }.get(name, "⚙️ Делаю...")


orchestrator = Orchestrator()
