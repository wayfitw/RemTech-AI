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
    log_level: str = "INFO"
    max_upload_mb: int = 25             # лимит размера загружаемого файла (issue #7)
    activity_retention_days: int = 90   # срок хранения записей журнала (issue #13)

    # ── auth ─────────────────────────────────────────────────────────────────
    jwt_secret: str = _DEFAULT_JWT
    jwt_ttl_hours: int = 24    # совместимость; access/refresh TTL ниже (#38)
    # #38 — короткий access + долгий refresh с ротацией.
    access_ttl_minutes: int = 30       # access-токен (httpOnly-cookie), короткий
    refresh_ttl_hours: int = 168       # refresh-токен (7 дней), ротируется при обновлении
    # issue #4 — хранение токена: httpOnly-cookie (XSS не читает) + CSRF (double-submit).
    # Secure=True для https-прода; на http-localhost браузер отбросит Secure-cookie,
    # поэтому дефолт False (в проде за HTTPS задать COOKIE_SECURE=true).
    cookie_secure: bool = False
    auth_cookie_name: str = "rt_access"
    refresh_cookie_name: str = "rt_refresh"
    csrf_cookie_name: str = "rt_csrf"

    # ── db / очереди ───────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://remtech:remtech@localhost:5432/remtech"
    db_command_timeout: int = 30     # таймаут запроса (сек), issue #17
    db_pool_recycle: int = 1800      # пересоздание соединений (сек), issue #17
    db_ssl: bool = False             # TLS к внешнему Postgres (issue #17)
    redis_url: str = "redis://localhost:6379/0"
    # состояние оркестратора: memory (один процесс) | redis (масштабирование, issue #16)
    orchestrator_state_backend: str = "memory"
    state_ttl_seconds: int = 3600

    # ── шлюз моделей (LLM gateway) ─────────────────────────────────────────────
    anthropic_api_key: str = ""
    model: str = "claude-sonnet-4-6"
    model_fast: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 16000
    egress_proxy_url: str = ""            # обратный прокси к зарубежным моделям (стадия 2b)
    default_model: str = "claude"         # алиас основной модели (per-agent override)
    # Реальный резерв: быстрая модель того же провайдера при перегрузке основной.
    # Yandex/vLLM как fallback — стадия 2b (нужны ключи/локальный сервер), см. issue #21.
    fallback_model: str = "claude-fast"
    vllm_base_url: str = ""               # локальная модель (RAG/приватное) — стадия 2b

    # ── медиа ──────────────────────────────────────────────────────────────────
    replicate_api_token: str = ""

    # ── RAG / эмбеддинги ───────────────────────────────────────────────────────
    tei_url: str = ""                # TEI-реранкер (bge-reranker) на GPU (#39); пусто → одностадийный поиск
    embed_backend: str = "ollama"    # ollama | fake (fake — для тестов/без GPU)
    ollama_url: str = "http://localhost:11434"
    embed_model: str = "bge-m3"
    embed_dim: int = 1024
    kb_top_k: int = 5
    # #39 — двухстадийный поиск: косинус top-N кандидатов → реранк TEI → финальный top_k
    kb_rerank_candidates: int = 20
    kb_async_ingest: bool = False    # True → ингест через Celery-воркер (issue #22)

    # ── Голос (EPIC-10, issue #32/#34) — в вебе выключено; STT=Whisper, TTS=Silero ──
    stt_enabled: bool = False
    tts_enabled: bool = False
    # Issue #34 — локальный STT. backend: null (заглушка) | whisper (faster-whisper).
    # Модель local, без egress: держит голос/ПДн в контуре (ADR-010/011).
    stt_backend: str = "null"
    stt_model: str = "small"          # tiny|base|small|medium|large-v3 (баланс CPU/качество)
    stt_language: str = "ru"          # язык распознавания (пусто → автоопределение)
    stt_device: str = "cpu"           # cpu | cuda
    stt_compute_type: str = "int8"    # int8 (CPU) | float16 (GPU)
    # Лимит извлечения текста для ингеста БЗ: длинные договоры/КП не режем на 20k (аудит БЗ)
    kb_extract_max_chars: int = 200_000

    # ── Telegram-канал (EPIC-10, issue #31) — тонкий клиент API ──────────────────
    # Секрет только из окружения (в коде/репозитории нет). Пустой токен → бот не стартует.
    telegram_bot_token: str = ""
    telegram_poll_timeout: int = 25       # long polling getUpdates timeout, сек
    # Allow-list связывания: "<tg_id>:<username>,<tg_id>:<username>". Управляется
    # администратором через окружение; сообщения от не-сопоставленных ID отклоняются.
    telegram_allowlist: str = ""
    # Issue #37 — как часто Celery beat опрашивает подписки на тендеры (сек)
    tender_poll_interval_seconds: int = 3600

    @property
    def telegram_allowmap(self) -> dict[int, str]:
        out: dict[int, str] = {}
        for pair in self.telegram_allowlist.split(","):
            pair = pair.strip()
            if not pair or ":" not in pair:
                continue
            tid, _, uname = pair.partition(":")
            tid, uname = tid.strip(), uname.strip()
            if tid.lstrip("-").isdigit() and uname:
                out[int(tid)] = uname
        return out

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
        """В production критичные секреты обязательны и должны быть сильными.
        Не полагаемся только на факт установки APP_ENV: дефолтный секрет из
        репозитория запрещён, требуется минимальная длина/энтропия."""
        if self.is_production:
            missing = []
            if not self.jwt_secret or self.jwt_secret == _DEFAULT_JWT:
                missing.append("JWT_SECRET (задан дефолт из репозитория)")
            elif len(self.jwt_secret) < 32:
                missing.append("JWT_SECRET (минимум 32 символа)")
            if not self.database_url:
                missing.append("DATABASE_URL")
            elif "remtech:remtech@" in self.database_url:
                missing.append("DATABASE_URL (слабые дефолтные креды remtech:remtech)")
            if not self.cors_origins_list:
                missing.append("CORS_ORIGINS (пустой список запрещён в production)")
            if missing:
                raise ValueError(
                    "В production обязательны корректные переменные: " + ", ".join(missing)
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
