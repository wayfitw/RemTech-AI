"""Alembic — асинхронная конфигурация миграций (TASK-0103)."""
import asyncio
from logging.config import fileConfig

from pgvector.sqlalchemy import Vector
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401 — регистрируем модели в метаданных
from alembic import context
from app.config import get_settings
from app.database import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    return get_settings().database_url


def render_item(type_, obj, autogen_context):
    """Корректный рендер типа Vector в файлах миграций + импорт pgvector."""
    if type_ == "type" and isinstance(obj, Vector):
        autogen_context.imports.add("from pgvector.sqlalchemy import Vector")
        return f"Vector(dim={obj.dim})"
    return False


def _do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_item=render_item,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_online():
    engine = create_async_engine(_url())
    async with engine.connect() as conn:
        await conn.run_sync(_do_run_migrations)
    await engine.dispose()


def run_offline():
    context.configure(
        url=_url(), target_metadata=target_metadata,
        render_item=render_item, literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    asyncio.run(_run_online())
