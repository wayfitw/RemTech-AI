"""Issue #22 — фоновые Celery-задачи.

Воркер — синхронный процесс без запущенного event loop, поэтому асинхронный
конвейер запускается через asyncio.run в отдельной короткой сессии.
"""
import asyncio

from app.celery_app import celery_app
from app.logging_config import get_logger

log = get_logger("remtech.tasks")


@celery_app.task(name="kb.ingest", bind=True, max_retries=3, default_retry_delay=30)
def ingest_document_task(self, document_id: int, text: str) -> int:
    """Чанкинг + эмбеддинги + запись kb_chunks для уже созданного документа."""
    from app import kb
    from app.database import SessionLocal
    from app.embeddings import get_embedder

    async def _run() -> int:
        async with SessionLocal() as s:
            n = await kb.ingest_chunks(s, get_embedder(), document_id, text)
            await s.commit()
            return n

    try:
        n = asyncio.run(_run())
        log.info("kb ingest done: doc=%s chunks=%s", document_id, n)
        return n
    except Exception as exc:
        log.exception("kb ingest failed: doc=%s", document_id)
        raise self.retry(exc=exc)


@celery_app.task(name="activity.purge")
def purge_activity_log_task() -> int:
    """Issue #13 — периодическая очистка журнала по сроку хранения (retention)."""
    from app import repositories as repo
    from app.config import get_settings
    from app.database import SessionLocal

    days = get_settings().activity_retention_days

    async def _run() -> int:
        async with SessionLocal() as s:
            n = await repo.purge_old_activity(s, days)
            await s.commit()
            return n

    n = asyncio.run(_run())
    log.info("activity log purged: %s строк старше %s дней", n, days)
    return n
