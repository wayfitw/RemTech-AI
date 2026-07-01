"""TASK-0102 — Конфигурация приложения (pydantic-settings).

Все параметры читаются из окружения (.env), типобезопасно. Критичные секреты
в production обязательны — иначе понятная ошибка на старте. Синглтон через lru_cache.
"""
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_JWT = "dev-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # ── app ──────────────────────────────────────────────────────────────────
    app_env: str = "development"  # development | production

    # ── auth ─────────────────────────────────────────────────────────────────
    jwt_secret: str = _DEFAULT_JWT
    jwt_ttl_hours: int = 168

    # ── db / очереди ───────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://remtech:remtech@localhost:5432/remtech"
    redis_url: str = "redis://localhost:6379/0"

    # ── шлюз моделей (LLM gateway) ─────────────────────────────────────────────
    anthropic_api_key: str = ""
    model: str = "claude-sonnet-4-6"
    model_fast: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 16000
    egress_proxy_url: str = ""       # обратный прокси к зарубежным моделям
    default_model: str = "claude"    # алиас основной модели (per-agent override)
    fallback_model: str = "yandex"   # резерв при недоступности прокси
    vllm_base_url: str = ""          # локальная модель (RAG/приватное)

    # ── медиа ──────────────────────────────────────────────────────────────────
    replicate_api_token: str = ""

    # ── RAG / TEI ──────────────────────────────────────────────────────────────
    tei_url: str = ""                # эмбеддинги/реранкер (bge-m3) на GPU
    embed_dim: int = 1024

    # ── файлы / документы ──────────────────────────────────────────────────────
    files_dir: str = "data/files"
    pdf_font_path: str = ""
    logo_path: str = ""

    # ── CORS ───────────────────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @model_validator(mode="after")
    def _require_prod_secrets(self) -> "Settings":
        if self.is_production:
            missing = []
            if not self.jwt_secret or self.jwt_secret == _DEFAULT_JWT:
                missing.append("JWT_SECRET")
            if not self.database_url:
                missing.append("DATABASE_URL")
            if missing:
                raise ValueError(
                    "В production обязательны переменные: " + ", ".join(missing)
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
