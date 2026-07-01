"""Фикстуры тестов: изолированная тестовая БД в контейнере Postgres+pgvector.

Тесты идут против НАСТОЯЩЕГО Postgres (как в целевом деплое), но в отдельной
базе `remtech_test`, чтобы не задевать рабочие данные.
"""
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
import app.models  # noqa: F401 — регистрируем модели в Base.metadata
from app.database import Base

_base_url = get_settings().database_url
_TEST_DB = "remtech_test"
# .../remtech → .../remtech_test
_TEST_URL = _base_url.rsplit("/", 1)[0] + "/" + _TEST_DB


async def _ensure_test_database() -> None:
    """Создаёт тестовую БД, если её нет (CREATE DATABASE вне транзакции)."""
    admin = create_async_engine(_base_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": _TEST_DB}
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{_TEST_DB}"'))
    finally:
        await admin.dispose()


@pytest_asyncio.fixture
async def session():
    await _ensure_test_database()
    engine = create_async_engine(_TEST_URL, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def client():
    """httpx-клиент против ASGI-приложения с изолированной тестовой БД."""
    import httpx
    from httpx import ASGITransport

    from app.database import get_db
    from app.main import app

    await _ensure_test_database()
    engine = create_async_engine(_TEST_URL, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    TestSession = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_db():
        async with TestSession() as s:
            yield s

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
