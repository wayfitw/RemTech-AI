"""Веб-канал (WebSocket) — тонкий адаптер над channel-agnostic turn-сервисом (#32).

Канал отвечает только за транспорт и авторизацию (тикет, #4); доменная логика
хода — в app/turn.run_turn. Ход запускается задачей, чтобы цикл приёма параллельно
получал ответ пользователя на запрос подтверждения (issue #30).
"""
import asyncio
import base64
import binascii
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app import repositories as repo
from app.database import SessionLocal
from app.deps import _ws_limiter, log
from app.orchestrator import orchestrator
from app.tickets import tickets
from app.turn import run_turn

router = APIRouter()


@router.websocket("/ws")
async def ws_chat(ws: WebSocket):
    # #4 — авторизация по одноразовому тикету (не long-lived JWT в URL)
    uid_from_ticket = tickets.consume(ws.query_params.get("ticket", ""))
    if not uid_from_ticket:
        await ws.close(code=4401)
        return
    async with SessionLocal() as s:
        u = await repo.get_user(s, uid_from_ticket)
        user = None if not u or not u.active else {
            "user_id": u.id, "username": u.username,
            "name": u.full_name or u.username, "role": u.role}
    if not user:
        await ws.close(code=4401)
        return
    await ws.accept()
    uid = user["user_id"]

    async def emit(event: dict):
        await ws.send_text(json.dumps(event, ensure_ascii=False))

    async def guarded_turn(msg: dict):
        # #15 — причину логируем на сервере, клиенту отдаём обобщённо
        try:
            # #34 — голосовой ввод: аудио приходит как base64 (audio_b64/audio_mime)
            audio = None
            if msg.get("audio_b64"):
                try:
                    audio = base64.b64decode(msg["audio_b64"])
                except (ValueError, binascii.Error):
                    await emit({"type": "error", "text": "Некорректные аудио-данные"})
                    return
            await run_turn(user, msg.get("conversation_id"), msg.get("text", ""),
                           msg.get("file_ids", []), msg.get("agent_id"), emit,
                           audio=audio, audio_mime=msg.get("audio_mime", ""))
        except Exception:
            log.exception("turn failed uid=%s", uid)
            try:
                await emit({"type": "error", "text": "Внутренняя ошибка обработки запроса"})
            except Exception:
                pass

    turn_task = None
    while True:
        # Issue #15 — одна битая рамка/ошибка кадра не рвёт всю WS-сессию.
        try:
            raw = await ws.receive_text()
        except WebSocketDisconnect:
            return
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            await emit({"type": "error", "text": "Некорректный формат сообщения"})
            continue

        # Issue #30 — ответ на запрос подтверждения (приходит во время активного хода)
        if msg.get("type") == "confirm":
            orchestrator.resolve_confirmation(msg.get("conversation_id"), msg.get("approved"))
            continue

        # Issue #3 — лимит частоты сообщений на пользователя
        if not _ws_limiter.allow(str(uid)):
            await emit({"type": "error", "text": "Слишком часто. Подождите немного."})
            continue

        # один ход за раз: пока идёт ответ, новые сообщения не принимаем
        if turn_task and not turn_task.done():
            await emit({"type": "error", "text": "Дождитесь ответа на предыдущее сообщение."})
            continue

        # #32 — ход через channel-agnostic turn-сервис, как задача (#30)
        turn_task = asyncio.create_task(guarded_turn(msg))
