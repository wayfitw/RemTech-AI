"""Issue #22 — Celery-приложение для фоновых задач (конвейер ингеста БЗ).

Брокер и backend — Redis (уже в стеке). Воркер запускается отдельным сервисом
в docker-compose; в dev/тестах ингест идёт inline (KB_ASYNC_INGEST=false), поэтому
воркер не обязателен.
"""
from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "remtech",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Issue #13 — ежедневная очистка журнала по сроку хранения (нужен celery beat, флаг -B).
    beat_schedule={
        "purge-activity-log-daily": {
            "task": "activity.purge",
            "schedule": 24 * 60 * 60,   # раз в сутки
        },
        # Issue #37 — опрос подписок на тендеры (новые закупки → веб + Telegram).
        "poll-tenders": {
            "task": "tenders.poll",
            "schedule": settings.tender_poll_interval_seconds,
        },
        # TASK-1004 (#42) — ежедневный дайджест новостей по ИИ в час из конфига
        # (AI_NEWS_HOUR). Сама задача уважает флаг AI_NEWS_ENABLED (выключено → no-op).
        "news-digest-daily": {
            "task": "news.digest",
            "schedule": crontab(minute=0, hour=settings.ai_news_hour),
        },
        # TASK-0905 (#47) — ежедневный контент-дайджест по отслеживаемым ТГ-каналам
        # в час из конфига; задача уважает CONTENT_DIGEST_ENABLED (выключено → no-op).
        "content-digest-daily": {
            "task": "content.digest",
            "schedule": crontab(minute=0, hour=settings.content_digest_hour),
        },
    },
)
