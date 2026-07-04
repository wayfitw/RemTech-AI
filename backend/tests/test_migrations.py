"""TASK-0103 — тест миграций Alembic: upgrade head и downgrade base проходят.
Использует изолированную БД remtech_migtest, чтобы не задевать рабочую."""
import asyncio
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings

BACKEND = Path(__file__).resolve().parent.parent
BASE_URL = get_settings().database_url
MIG_DB = "remtech_migtest"
MIG_URL = BASE_URL.rsplit("/", 1)[0] + "/" + MIG_DB


async def _ensure_db():
    admin = create_async_engine(BASE_URL, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as c:
            exists = await c.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": MIG_DB})
            if not exists:
                await c.execute(text(f'CREATE DATABASE "{MIG_DB}"'))
    finally:
        await admin.dispose()


def _alembic(*args):
    env = {**os.environ, "DATABASE_URL": MIG_URL}
    return subprocess.run([sys.executable, "-m", "alembic", *args],
                          cwd=BACKEND, capture_output=True, text=True, env=env)


def test_migration_upgrade_then_downgrade():
    asyncio.run(_ensure_db())
    up = _alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr
    down = _alembic("downgrade", "base")
    assert down.returncode == 0, down.stderr


def test_no_migration_drift():
    """Issue #20 — схема из миграций совпадает с моделями (autogenerate-diff пуст)."""
    asyncio.run(_ensure_db())
    up = _alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr
    chk = _alembic("check")
    assert chk.returncode == 0, "дрейф миграций/моделей:\n" + chk.stdout + chk.stderr
