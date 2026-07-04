"""TASK-0102 — тесты конфигурации (pydantic-settings)."""
import pytest

from app.config import Settings


def test_cors_origins_parsing():
    s = Settings(_env_file=None, cors_origins="http://a , http://b,http://c ")
    assert s.cors_origins_list == ["http://a", "http://b", "http://c"]


_STRONG = "x" * 40  # ≥32 символов


def test_production_requires_jwt_secret():
    # дефолтный небезопасный секрет в production — ошибка на старте
    with pytest.raises(Exception):
        Settings(_env_file=None, app_env="production", jwt_secret="dev-secret-change-me")


def test_production_rejects_short_secret():
    # слабый (короткий) секрет в production запрещён, даже если не дефолтный
    with pytest.raises(Exception):
        Settings(_env_file=None, app_env="production", jwt_secret="short-secret",
                 database_url="postgresql+asyncpg://u:p@h:5432/db")


def test_production_requires_cors_origins():
    # пустой CORS_ORIGINS в production запрещён (иначе небезопасный режим)
    with pytest.raises(Exception):
        Settings(_env_file=None, app_env="production", jwt_secret=_STRONG,
                 database_url="postgresql+asyncpg://u:p@h:5432/db", cors_origins="")


def test_production_rejects_weak_db_creds():
    # дефолтные креды remtech:remtech в production запрещены (issue #5)
    with pytest.raises(Exception):
        Settings(_env_file=None, app_env="production", jwt_secret=_STRONG,
                 database_url="postgresql+asyncpg://remtech:remtech@h:5432/db")


def test_production_ok_with_real_secret():
    s = Settings(_env_file=None, app_env="production", jwt_secret=_STRONG,
                 database_url="postgresql+asyncpg://u:strongpass@h:5432/db")
    assert s.is_production and s.jwt_secret == _STRONG


def test_development_allows_defaults():
    s = Settings(_env_file=None, app_env="development")
    assert not s.is_production
    assert s.embed_dim == 1024
