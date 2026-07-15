"""Cutover — Стадия 1: репозиторный слой (async CRUD над моделями SQLAlchemy).

Заменяет прежний sqlite-модуль db.py. Все функции принимают AsyncSession.
Коммит выполняет вызывающая сторона (обычно на уровне эндпоинта/юнита работы).
"""
import datetime as dt

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import (
    ActivityLog,
    Agent,
    ChatHistory,
    Conversation,
    KBChunk,
    KBDocument,
    ModelConfig,
    Notification,
    TenderSeen,
    TenderSubscription,
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
    # issue #4 — смена/сброс пароля отзывает все прежние токены (сдвиг версии)
    await s.execute(
        update(User).where(User.id == user_id)
        .values(password_hash=password_hash, token_version=User.token_version + 1)
    )


async def revoke_tokens(s, user_id: int) -> None:
    """Issue #4 — отзыв всех токенов пользователя (logout на сервере, форс-разлогин)."""
    await s.execute(
        update(User).where(User.id == user_id)
        .values(token_version=User.token_version + 1)
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


async def list_output_files(s, conversation_id: int) -> list[UploadedFile]:
    """Сгенерированные файлы беседы (КП/сметы/документы) — чтобы восстановить
    кнопки скачивания при переоткрытии чата (в истории привязки файла к сообщению нет)."""
    res = await s.scalars(
        select(UploadedFile).where(
            UploadedFile.conversation_id == conversation_id,
            UploadedFile.direction == "output",
        ).order_by(UploadedFile.id)
    )
    return list(res)


# ── Activity log ─────────────────────────────────────────────────────────────

async def log_activity(s, user_id: int | None, action: str, detail: str = "") -> None:
    s.add(ActivityLog(user_id=user_id, action=action, detail=detail))


async def purge_old_activity(s, days: int) -> int:
    """Issue #13 — удаляет записи журнала старше N дней (retention ПДн, 152-ФЗ)."""
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    res = await s.execute(delete(ActivityLog).where(ActivityLog.created_at < cutoff))
    return res.rowcount or 0


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


# ── Model configs (шлюз моделей) ───────────────────────────────────────────────

async def create_model_config(s, alias: str, provider: str, endpoint: str = "",
                              fallback_to: str | None = None) -> ModelConfig:
    mc = ModelConfig(alias=alias, provider=provider, endpoint=endpoint or None,
                     fallback_to=fallback_to)
    s.add(mc)
    await s.flush()
    return mc


async def get_model_config(s, mc_id: int) -> ModelConfig | None:
    return await s.get(ModelConfig, mc_id)


async def get_model_config_by_alias(s, alias: str) -> ModelConfig | None:
    return await s.scalar(select(ModelConfig).where(ModelConfig.alias == alias))


async def list_model_configs(s) -> list[ModelConfig]:
    return list(await s.scalars(select(ModelConfig).order_by(ModelConfig.id)))


async def delete_model_config(s, mc_id: int) -> None:
    await s.execute(delete(ModelConfig).where(ModelConfig.id == mc_id))


# ── Agents (конструктор агентов) ────────────────────────────────────────────────

async def create_agent(s, name: str, system_prompt: str = "", tools: list | None = None,
                       default_model: int | None = None, allowed_roles: str = "") -> Agent:
    agent = Agent(name=name, system_prompt=system_prompt or None, tools=tools,
                  default_model=default_model, allowed_roles=allowed_roles or None)
    s.add(agent)
    await s.flush()
    return agent


async def get_agent(s, agent_id: int) -> Agent | None:
    return await s.get(Agent, agent_id)


async def list_agents(s) -> list[Agent]:
    return list(await s.scalars(select(Agent).order_by(Agent.id)))


async def delete_agent(s, agent_id: int) -> None:
    await s.execute(delete(Agent).where(Agent.id == agent_id))


# ── База знаний (RAG) ──────────────────────────────────────────────────────────

async def create_kb_document(s, file_name: str, source: str = "",
                             owner_role: str | None = None) -> KBDocument:
    doc = KBDocument(file_name=file_name, source=source or None, owner_role=owner_role)
    s.add(doc)
    await s.flush()
    return doc


async def add_chunks(s, document_id: int, chunks: list[tuple[str, list[float], dict | None]]) -> int:
    """chunks: [(chunk_text, embedding, meta)]. Возвращает число добавленных."""
    for text, emb, meta in chunks:
        s.add(KBChunk(document_id=document_id, chunk_text=text, embedding=emb, meta=meta))
    await s.flush()
    return len(chunks)


async def list_kb_documents(s) -> list[dict]:
    cnt = (select(func.count()).where(KBChunk.document_id == KBDocument.id).scalar_subquery())
    rows = (await s.execute(
        select(KBDocument, cnt.label("chunks")).order_by(KBDocument.id.desc()))).all()
    return [{"id": d.id, "file_name": d.file_name, "source": d.source,
             "owner_role": d.owner_role, "chunks": chunks, "created_at": _iso(d.created_at)}
            for d, chunks in rows]


async def delete_kb_document(s, document_id: int) -> None:
    await s.execute(delete(KBChunk).where(KBChunk.document_id == document_id))
    await s.execute(delete(KBDocument).where(KBDocument.id == document_id))


async def search_chunks(s, embedding: list[float], roles: list[str] | None = None,
                        k: int = 5) -> list[dict]:
    """Векторный поиск ближайших чанков с фильтром по ролям. roles=None → без фильтра
    (админ видит всё). Документы с owner_role=NULL доступны всем."""
    dist = KBChunk.embedding.cosine_distance(embedding)
    stmt = select(KBChunk, KBDocument.file_name, dist.label("distance")).join(
        KBDocument, KBDocument.id == KBChunk.document_id)
    if roles is not None:
        stmt = stmt.where(
            (KBDocument.owner_role.is_(None)) | (KBDocument.owner_role.in_(roles)))
    stmt = stmt.order_by(dist).limit(k)
    rows = (await s.execute(stmt)).all()
    return [{"document_id": c.document_id, "file_name": fname, "text": c.chunk_text,
             "distance": float(distance), "meta": c.meta}
            for c, fname, distance in rows]


def _iso(value) -> str | None:
    return value.isoformat(sep=" ", timespec="seconds") if value else None


# Публичный алиас (issue #18 — эндпоинты не должны обращаться к приватному _iso).
iso = _iso


# ── Issue #37 (TASK-0802) — подписки на тендеры, дедуп, уведомления ───────────
async def create_subscription(s, name, keywords, region=None, budget_min=None,
                              budget_max=None, customer=None,
                              recipient_roles="закупки") -> TenderSubscription:
    sub = TenderSubscription(
        name=name, keywords=keywords, region=region, budget_min=budget_min,
        budget_max=budget_max, customer=customer, recipient_roles=recipient_roles)
    s.add(sub)
    await s.flush()
    return sub


async def list_subscriptions(s, only_active=True) -> list[TenderSubscription]:
    stmt = select(TenderSubscription)
    if only_active:
        stmt = stmt.where(TenderSubscription.active == 1)
    return list((await s.execute(stmt.order_by(TenderSubscription.id))).scalars())


async def delete_subscription(s, sub_id: int) -> None:
    await s.execute(delete(TenderSeen).where(TenderSeen.subscription_id == sub_id))
    await s.execute(delete(TenderSubscription).where(TenderSubscription.id == sub_id))


async def mark_tender_seen(s, subscription_id: int, reg_number: str) -> bool:
    """Атомарно фиксирует закупку как «виденную». True — если новая (вставлена),
    False — если уже была (дедуп по (subscription_id, reg_number))."""
    stmt = (pg_insert(TenderSeen)
            .values(subscription_id=subscription_id, reg_number=reg_number)
            .on_conflict_do_nothing(index_elements=["subscription_id", "reg_number"]))
    res = await s.execute(stmt)
    return res.rowcount > 0


async def add_notification(s, recipient_role, title, body=None, link=None) -> Notification:
    n = Notification(recipient_role=recipient_role, title=title, body=body, link=link)
    s.add(n)
    await s.flush()
    return n


async def list_notifications(s, role: str, limit: int = 50) -> list[Notification]:
    """Лента уведомлений роли; admin видит все."""
    stmt = select(Notification)
    if role != "admin":
        stmt = stmt.where(Notification.recipient_role == role)
    stmt = stmt.order_by(Notification.id.desc()).limit(limit)
    return list((await s.execute(stmt)).scalars())


async def usernames_by_roles(s, roles: list[str]) -> list[str]:
    """Активные пользователи с указанными ролями — для адресации уведомлений."""
    if not roles:
        return []
    stmt = select(User.username).where(User.role.in_(roles), User.active == 1)
    return list((await s.execute(stmt)).scalars())
