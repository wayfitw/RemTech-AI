"""TASK-0104 — Модели данных по ER-диаграмме
(02_Техническая архитектура/Схемы/Remtechnika_AI_ER_Database.svg).

Таблицы: users, conversations, chat_history, uploaded_files, activity_log,
kb_documents, kb_chunks (embedding vector(1024)), agents, model_configs.
Индекс HNSW для kb_chunks.embedding выносится в EPIC-03 (после ингеста).
"""
import datetime as dt

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import get_settings
from app.database import Base

EMBED_DIM = get_settings().embed_dim


def _now_col() -> Mapped[dt.datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(Text)
    password_hash: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="user", server_default="user")
    active: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # Issue #4 — версия токена для отзыва: инкремент инвалидирует все ранее выданные
    # JWT пользователя (logout на сервере, смена/сброс пароля, форс-разлогин).
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[dt.datetime] = _now_col()

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="user")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="Новый чат")
    # Канал происхождения диалога: "web" | "telegram". Изоляция историй по каналу —
    # веб показывает только web-диалоги, бот ведёт свои (тг-тг, веб-веб).
    channel: Mapped[str] = mapped_column(String(16), default="web", server_default="web", index=True)
    created_at: Mapped[dt.datetime] = _now_col()
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="conversations")
    messages: Mapped[list["ChatHistory"]] = relationship(back_populates="conversation")


class ChatHistory(Base):
    __tablename__ = "chat_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[dict | list | str] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = _now_col()

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str | None] = mapped_column(String(30))
    file_name: Mapped[str] = mapped_column(Text)
    file_path: Mapped[str] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(String(20), default="upload")  # upload | output
    created_at: Mapped[dt.datetime] = _now_col()


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(50))
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class KBDocument(Base):
    __tablename__ = "kb_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_name: Mapped[str] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)
    owner_role: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[dt.datetime] = _now_col()

    chunks: Mapped[list["KBChunk"]] = relationship(back_populates="document")


class KBChunk(Base):
    __tablename__ = "kb_chunks"
    # HNSW-индекс для косинусного поиска (issue #14 / TASK-0302): без него —
    # полный скан на каждый RAG-запрос. Метрика должна совпадать с cosine_distance.
    __table_args__ = (
        Index(
            "ix_kb_chunks_embedding_hnsw", "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("kb_documents.id"), index=True)
    chunk_text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM))
    # 'metadata' зарезервировано в DeclarativeBase → атрибут meta, колонка metadata
    meta: Mapped[dict | None] = mapped_column("metadata", JSONB)

    document: Mapped["KBDocument"] = relationship(back_populates="chunks")


class ModelConfig(Base):
    __tablename__ = "model_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    alias: Mapped[str] = mapped_column(String(50), unique=True)
    provider: Mapped[str] = mapped_column(String(50))
    endpoint: Mapped[str | None] = mapped_column(Text)
    fallback_to: Mapped[str | None] = mapped_column(String(50))


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    system_prompt: Mapped[str | None] = mapped_column(Text)
    tools: Mapped[list | None] = mapped_column(JSON)
    default_model: Mapped[int | None] = mapped_column(
        ForeignKey("model_configs.id"), index=True
    )
    allowed_roles: Mapped[str | None] = mapped_column(Text)

    model: Mapped["ModelConfig"] = relationship()


# ── Issue #37 (TASK-0802) — уведомления о новых тендерах ──────────────────────
class TenderSubscription(Base):
    """Сохранённый критерий поиска закупок + получатели (профиль тендеров, #37/#44).
    user_id — владелец профиля (свои профили; admin видит все); NULL — админ-профиль."""
    __tablename__ = "tender_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    keywords: Mapped[str] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(String(200))
    budget_min: Mapped[int | None] = mapped_column(Integer)
    budget_max: Mapped[int | None] = mapped_column(Integer)
    customer: Mapped[str | None] = mapped_column(String(200))
    recipient_roles: Mapped[str] = mapped_column(Text, default="закупки")  # comma-sep
    active: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[dt.datetime] = _now_col()


class TenderSeen(Base):
    """Реестр уже отправленных закупок (дедуп по реестровому номеру в рамках подписки)."""
    __tablename__ = "tender_seen"
    __table_args__ = (Index("ix_tender_seen_uniq", "subscription_id", "reg_number", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("tender_subscriptions.id"), index=True)
    reg_number: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = _now_col()


class Notification(Base):
    """Веб-лента уведомлений; адресуется по роли получателя."""
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_role: Mapped[str] = mapped_column(String(20), index=True)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(Text)
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = _now_col()


class Reminder(Base):
    """Напоминание пользователя (личный ассистент в Telegram). due_at — время события
    (в UTC); lead_pending — ещё не сработавшие заблаговременные сигналы в минутах до
    события (напр. [60, 30, 10, 0], 0 = в момент). Строка удаляется, когда все сигналы
    отправлены."""
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    due_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    lead_pending: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[dt.datetime] = _now_col()


class DigestGroup(Base):
    """Группа ТГ в утренней сводке пользователя (управляется из бота). ref — стабильный
    идентификатор для чтения (id или @username), title — отображаемое имя."""
    __tablename__ = "digest_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True)
    ref: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = _now_col()
