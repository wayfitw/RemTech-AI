"""TASK-0103 — Асинхронный слой доступа к PostgreSQL.

SQLAlchemy 2.0 async + asyncpg: движок, фабрика сессий, зависимость get_db,
базовый класс моделей с naming convention (для стабильных миграций Alembic),
инициализация расширения pgvector.
"""
from collections.abc import AsyncGenerator

from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

# Единая схема именования ограничений — предсказуемые имена для Alembic.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(AsyncAttrs, DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# asyncpg: command_timeout ограничивает время запроса; ssl — TLS к внешней БД (#17)
_connect_args: dict = {"command_timeout": settings.db_command_timeout}
if settings.db_ssl:
    _connect_args["ssl"] = True

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=settings.db_pool_recycle,
    connect_args=_connect_args,
    future=True,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI-зависимость: сессия на запрос."""
    async with SessionLocal() as session:
        yield session


async def init_extensions() -> None:
    """Гарантирует наличие расширения pgvector (на случай, если init-скрипт БД
    не применялся — например, при подключении к внешнему Postgres)."""
    if engine.dialect.name != "postgresql":
        return
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
