"""Issue #22 — Celery-приложение для фоновых задач (конвейер ингеста БЗ).

Брокер и backend — Redis (уже в стеке). Воркер запускается отдельным сервисом
в docker-compose; в dev/тестах ингест идёт inline (KB_ASYNC_INGEST=false), поэтому
воркер не обязателен.
"""
from celery import Celery

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
    },
)
