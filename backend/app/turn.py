"""Issue #32 (ADR-011) — channel-agnostic «прогон одного хода».

Доменная логика хода вынесена из WebSocket-обработчика, чтобы любой канал
(веб/Telegram/голос) переиспользовал её без дублирования.

Контракт канального адаптера:
    канал делает авторизацию (по-своему: тикет для веба, allow-list для Telegram),
    получает `user` (dict: user_id/username/name/role) и входные части сообщения,
    затем вызывает `run_turn(user, conversation_id, text, file_ids, agent_id, emit)`,
    передавая свой колбэк `emit(event: dict)` для доставки доменных событий
    (delta / tool / sources / awaiting_confirmation / conversation / done / error).
Веб (routers/ws.py) — первая реализация контракта.
"""
from app import repositories as repo
from app import storage
from app.database import SessionLocal
from app.deps import role_can_use_agent
from app.media import maybe_transcribe
from app.orchestrator import orchestrator
from services.extract import detect_kind, extract_text


async def _resolve_attachments(s, uid: int, file_ids: list) -> list[dict]:
    """Вложения — только свои файлы владельца (защита от IDOR)."""
    out = []
    for fid in file_ids or []:
        rec = await repo.get_file_record(s, fid)
        if not rec or rec.user_id != uid:
            continue
        res = storage.read_record_bytes(rec)
        if not res:
            continue
        data, name = res
        kind = detect_kind(name)
        if kind == "image":
            txt = ""
        elif kind == "audio":   # #41 — запись звонка → транскрипт (локальный Whisper, #34)
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else "mp3"
            transcript = await maybe_transcribe(data, f"audio/{ext}")
            txt = (f"[Транскрипт аудио «{name}»]\n{transcript}" if transcript
                   else f"[Не удалось распознать аудио «{name}» — проверьте, включён ли STT]")
        else:
            txt = extract_text(data, name)
        out.append({"kind": kind, "name": name, "data": data, "text": txt})
    return out


async def run_turn(user: dict, conversation_id, text: str, file_ids, agent_id, emit,
                   audio: bytes | None = None, audio_mime: str = "",
                   channel: str = "web") -> int | None:
    """Прогоняет один ход пользователя и шлёт доменные события через emit.
    Возвращает conversation_id (может быть создан новый). channel («web»/«telegram»)
    проставляется НОВОМУ диалогу — для изоляции историй по каналу (тг-тг, веб-веб)."""
    uid = user["user_id"]

    # #32/#34 — опциональный STT-хук: голосовой ввод → текст (по умолчанию выключен)
    if audio and not (text or "").strip():
        text = await maybe_transcribe(audio, audio_mime)
        if not (text or "").strip():
            # битое/пустое аудио или STT выключен — честный отказ, ход не падает (#34)
            await emit({"type": "error", "text": "Не удалось распознать голосовое сообщение."})
            return conversation_id

    async with SessionLocal() as s:
        if not conversation_id:
            conv = await repo.create_conversation(s, uid, (text or "Новый чат")[:60], channel=channel)
            await s.commit()
            conversation_id = conv.id
            await emit({"type": "conversation", "id": conversation_id, "title": conv.title})
        else:
            conv = await repo.get_conversation(s, conversation_id)
            if not conv or conv.user_id != uid:
                await emit({"type": "error", "text": "Чат не найден или недоступен"})
                return conversation_id

        # RBAC: роль обязана иметь доступ к выбранному агенту (не только в листинге)
        if agent_id is not None:
            agent = await repo.get_agent(s, agent_id)
            if not agent:
                await emit({"type": "error", "text": "Агент не найден"})
                return conversation_id
            if not role_can_use_agent(user.get("role", "user"), agent):
                await emit({"type": "error", "text": "Недостаточно прав для этого агента"})
                return conversation_id

        attachments = await _resolve_attachments(s, uid, file_ids)

    # админ видит всю базу знаний (roles=None), сотрудник — по своей роли
    roles = None if user.get("role") == "admin" else [user.get("role", "user")]
    # гейт подтверждения побочных действий (#30) — внутри orchestrator.process (ядро, не канал)
    await orchestrator.process(conversation_id, uid, text, attachments, emit, roles, agent_id)
    return conversation_id
