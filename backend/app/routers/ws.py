"""Роутер WebSocket-чата: авторизация по тикету, лимит частоты, агент-цикл.

Ход (turn) запускается как задача, чтобы цикл приёма мог параллельно получать
ответ пользователя на запрос подтверждения действия (issue #30).
"""
import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app import repositories as repo
from app import storage
from app.database import SessionLocal
from app.deps import _ws_limiter, log, role_can_use_agent
from app.orchestrator import orchestrator
from app.tickets import tickets
from services.extract import detect_kind, extract_text

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

        try:
            text = msg.get("text", "")
            conversation_id = msg.get("conversation_id")
            file_ids = msg.get("file_ids", [])
            agent_id = msg.get("agent_id")

            async with SessionLocal() as s:
                if not conversation_id:
                    conv = await repo.create_conversation(s, uid, (text or "Новый чат")[:60])
                    await s.commit()
                    conversation_id = conv.id
                    await emit({"type": "conversation", "id": conversation_id, "title": conv.title})
                else:
                    conv = await repo.get_conversation(s, conversation_id)
                    if not conv or conv.user_id != uid:
                        await emit({"type": "error", "text": "Чат не найден или недоступен"})
                        continue

                # RBAC: роль обязана иметь доступ к выбранному агенту (не только в листинге)
                if agent_id is not None:
                    agent = await repo.get_agent(s, agent_id)
                    if not agent:
                        await emit({"type": "error", "text": "Агент не найден"})
                        continue
                    if not role_can_use_agent(user.get("role", "user"), agent):
                        await emit({"type": "error", "text": "Недостаточно прав для этого агента"})
                        continue

                # вложения — только свои файлы (защита от IDOR)
                attachments = []
                for fid in file_ids:
                    rec = await repo.get_file_record(s, fid)
                    if not rec or rec.user_id != uid:
                        continue
                    res = storage.read_record_bytes(rec)
                    if not res:
                        continue
                    data, name = res
                    kind = detect_kind(name)
                    txt = "" if kind == "image" else extract_text(data, name)
                    attachments.append({"kind": kind, "name": name, "data": data, "text": txt})

            # админ видит всю базу знаний (roles=None), сотрудник — по своей роли
            roles = None if user.get("role") == "admin" else [user.get("role", "user")]
            # #30 — ход как задача: цикл продолжает принимать сообщения (в т.ч. confirm)
            turn_task = asyncio.create_task(
                orchestrator.process(conversation_id, uid, text, attachments, emit, roles, agent_id))
        except WebSocketDisconnect:
            return
        except Exception:
            # #15 — причину логируем на сервере, клиенту отдаём обобщённо (без внутренних деталей)
            log.exception("ws message handling failed uid=%s", uid)
            try:
                await emit({"type": "error", "text": "Внутренняя ошибка обработки запроса"})
            except Exception:
                return
