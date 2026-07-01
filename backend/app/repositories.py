"""Cutover — Стадия 1: репозиторный слой (async CRUD над моделями SQLAlchemy).

Заменяет прежний sqlite-модуль db.py. Все функции принимают AsyncSession.
Коммит выполняет вызывающая сторона (обычно на уровне эндпоинта/юнита работы).
"""
import datetime as dt

from sqlalchemy import delete, func, select, update

from app.models import (
    ActivityLog,
    ChatHistory,
    Conversation,
    ModelConfig,  # noqa: F401 — используется агентами позже
    UploadedFile,
    User,
)

# ── Users ──────────────────────────────────────────────────────────────────────

async def get_user(s, user_id: int) -> User | None:
    return await s.get(User, user_id)


async def get_user_by_username(s, username: str) -> User | None:
    return await s.scalar(select(User).where(User.username == username))


async def create_user(s, username: str, password_hash: str, role: str = "user",
                       full_name: str = "") -> User:
    user = User(username=username, password_hash=password_hash, role=role,
                full_name=full_name or None)
    s.add(user)
    await s.flush()
    return user


async def count_registered_users(s) -> int:
    return await s.scalar(
        select(func.count()).select_from(User).where(User.password_hash.is_not(None))
    )


async def list_users(s) -> list[User]:
    res = await s.scalars(
        select(User).where(User.password_hash.is_not(None)).order_by(User.id)
    )
    return list(res)


async def set_user_active(s, user_id: int, active: bool) -> None:
    await s.execute(update(User).where(User.id == user_id).values(active=1 if active else 0))


async def update_password(s, user_id: int, password_hash: str) -> None:
    await s.execute(
        update(User).where(User.id == user_id).values(password_hash=password_hash)
    )


# ── Conversations ────────────────────────────────────────────────────────────

async def create_conversation(s, user_id: int, title: str = "Новый чат") -> Conversation:
    conv = Conversation(user_id=user_id, title=title)
    s.add(conv)
    await s.flush()
    return conv


async def list_conversations(s, user_id: int, limit: int = 50) -> list[Conversation]:
    res = await s.scalars(
        select(Conversation).where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc()).limit(limit)
    )
    return list(res)


async def get_conversation(s, conversation_id: int) -> Conversation | None:
    return await s.get(Conversation, conversation_id)


async def set_conversation_title(s, conversation_id: int, title: str) -> None:
    await s.execute(
        update(Conversation).where(Conversation.id == conversation_id).values(title=title)
    )


async def touch_conversation(s, conversation_id: int) -> None:
    await s.execute(
        update(Conversation).where(Conversation.id == conversation_id)
        .values(updated_at=func.now())
    )


async def delete_conversation(s, conversation_id: int, user_id: int) -> None:
    await s.execute(delete(ChatHistory).where(ChatHistory.conversation_id == conversation_id))
    await s.execute(delete(UploadedFile).where(UploadedFile.conversation_id == conversation_id))
    await s.execute(
        delete(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
    )


# ── Chat history ─────────────────────────────────────────────────────────────

async def save_message(s, conversation_id: int, user_id: int, role: str, content) -> None:
    s.add(ChatHistory(conversation_id=conversation_id, user_id=user_id,
                      role=role, content=content))


async def load_history(s, conversation_id: int, limit: int = 40) -> list[dict]:
    res = await s.scalars(
        select(ChatHistory).where(ChatHistory.conversation_id == conversation_id)
        .order_by(ChatHistory.id.desc()).limit(limit)
    )
    rows = list(res)
    rows.reverse()
    return [{"role": r.role, "content": r.content} for r in rows]


# ── Files ──────────────────────────────────────────────────────────────────────

async def save_file_record(s, user_id: int, file_name: str, file_path: str,
                           kind: str = "other", conversation_id: int | None = None,
                           direction: str = "upload") -> UploadedFile:
    rec = UploadedFile(user_id=user_id, file_name=file_name, file_path=file_path,
                       kind=kind, conversation_id=conversation_id, direction=direction)
    s.add(rec)
    await s.flush()
    return rec


async def get_file_record(s, file_id: int) -> UploadedFile | None:
    return await s.get(UploadedFile, file_id)


async def get_last_uploaded(s, conversation_id: int, kind: str) -> UploadedFile | None:
    return await s.scalar(
        select(UploadedFile).where(
            UploadedFile.conversation_id == conversation_id,
            UploadedFile.kind == kind, UploadedFile.direction == "upload",
        ).order_by(UploadedFile.id.desc()).limit(1)
    )


# ── Activity log ─────────────────────────────────────────────────────────────

async def log_activity(s, user_id: int | None, action: str, detail: str = "") -> None:
    s.add(ActivityLog(user_id=user_id, action=action, detail=detail))


# ── Admin analytics ───────────────────────────────────────────────────────────

async def admin_overview(s) -> dict:
    users = await s.scalar(
        select(func.count()).select_from(User).where(User.password_hash.is_not(None)))
    convs = await s.scalar(select(func.count()).select_from(Conversation))
    msgs = await s.scalar(select(func.count()).select_from(ChatHistory))
    user_msgs = await s.scalar(
        select(func.count()).select_from(ChatHistory).where(ChatHistory.role == "user"))
    files = await s.scalar(
        select(func.count()).select_from(UploadedFile)
        .where(UploadedFile.direction == "output"))
    day_ago = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    active_today = await s.scalar(
        select(func.count(func.distinct(ActivityLog.user_id)))
        .where(ActivityLog.created_at >= day_ago))
    return {"users": users, "conversations": convs, "messages": msgs,
            "user_messages": user_msgs, "generated_files": files,
            "active_today": active_today}


async def admin_user_stats(s) -> list[dict]:
    conv_ct = (select(func.count()).where(Conversation.user_id == User.id)
               .scalar_subquery())
    msg_ct = (select(func.count()).where(
        ChatHistory.user_id == User.id, ChatHistory.role == "user").scalar_subquery())
    last_act = (select(func.max(ActivityLog.created_at))
                .where(ActivityLog.user_id == User.id).scalar_subquery())
    stmt = (select(User, conv_ct.label("conversations"), msg_ct.label("messages"),
                   last_act.label("last_active"))
            .where(User.password_hash.is_not(None))
            .order_by(msg_ct.desc(), User.id))
    rows = (await s.execute(stmt)).all()
    out = []
    for u, conversations, messages, last_active in rows:
        out.append({"id": u.id, "username": u.username, "full_name": u.full_name,
                    "role": u.role, "active": u.active, "created_at": _iso(u.created_at),
                    "conversations": conversations, "messages": messages,
                    "last_active": _iso(last_active)})
    return out


async def messages_per_day(s, days: int = 14) -> list[dict]:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    day = func.date(ChatHistory.created_at)
    stmt = (select(day.label("day"), func.count().label("count"))
            .where(ChatHistory.role == "user", ChatHistory.created_at >= cutoff)
            .group_by(day).order_by(day))
    rows = (await s.execute(stmt)).all()
    return [{"day": str(d), "count": c} for d, c in rows]


async def admin_conversations(s, user_id: int) -> list[dict]:
    msg_ct = (select(func.count()).where(ChatHistory.conversation_id == Conversation.id)
              .scalar_subquery())
    stmt = (select(Conversation, msg_ct.label("messages"))
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc()))
    rows = (await s.execute(stmt)).all()
    return [{"id": c.id, "title": c.title, "created_at": _iso(c.created_at),
             "updated_at": _iso(c.updated_at), "messages": messages}
            for c, messages in rows]


async def activity_log_list(s, limit: int = 200, user_id: int | None = None) -> list[dict]:
    stmt = (select(ActivityLog, User.username, User.full_name)
            .join(User, User.id == ActivityLog.user_id, isouter=True)
            .order_by(ActivityLog.id.desc()).limit(limit))
    if user_id:
        stmt = stmt.where(ActivityLog.user_id == user_id)
    rows = (await s.execute(stmt)).all()
    return [{"id": a.id, "user_id": a.user_id, "username": uname, "full_name": fname,
             "action": a.action, "detail": a.detail, "created_at": _iso(a.created_at)}
            for a, uname, fname in rows]


def _iso(value) -> str | None:
    return value.isoformat(sep=" ", timespec="seconds") if value else None
