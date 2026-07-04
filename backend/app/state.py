"""Issue #16 — разделяемое транзиентное состояние диалога.

Оркестратор хранил историю/вложения/блокировки в словарях процесса: это не
масштабируется на несколько воркеров и течёт по памяти. Здесь — абстракция
хранилища с двумя бэкендами:

- MemoryStateStore — процесс-локальный (dev/тесты, один воркер);
- RedisStateStore — общий для всех воркеров, с TTL и распределённой блокировкой.

История диалога больше НЕ кэшируется в памяти — она читается из БД (см.
Orchestrator._load_history), поэтому здесь только транзиентные вложения и локи.
"""
import asyncio

from app.config import get_settings
from app.logging_config import get_logger

log = get_logger("remtech.state")
_SEP = b"\x00"


class MemoryStateStore:
    """Процесс-локальное хранилище (один воркер)."""

    def __init__(self):
        self._img: dict[int, bytes] = {}
        self._docx: dict[int, tuple[bytes, str]] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    async def get_image(self, cid: int) -> bytes | None:
        return self._img.get(cid)

    async def set_image(self, cid: int, data: bytes) -> None:
        self._img[cid] = data

    async def get_docx(self, cid: int) -> tuple[bytes, str] | None:
        return self._docx.get(cid)

    async def set_docx(self, cid: int, data: bytes, name: str) -> None:
        self._docx[cid] = (data, name)

    def lock(self, cid: int):
        return self._locks.setdefault(cid, asyncio.Lock())


class RedisStateStore:
    """Общее хранилище на Redis: вложения с TTL + распределённая блокировка."""

    def __init__(self, url: str, ttl: int = 3600):
        import redis.asyncio as aioredis
        self._r = aioredis.from_url(url)   # decode_responses=False → бинарные данные
        self._ttl = ttl

    async def get_image(self, cid: int) -> bytes | None:
        return await self._r.get(f"img:{cid}")

    async def set_image(self, cid: int, data: bytes) -> None:
        await self._r.set(f"img:{cid}", data, ex=self._ttl)

    async def get_docx(self, cid: int) -> tuple[bytes, str] | None:
        raw = await self._r.get(f"docx:{cid}")
        if not raw:
            return None
        name, _, data = raw.partition(_SEP)
        return data, name.decode()

    async def set_docx(self, cid: int, data: bytes, name: str) -> None:
        await self._r.set(f"docx:{cid}", name.encode() + _SEP + data, ex=self._ttl)

    def lock(self, cid: int):
        # распределённая блокировка на диалог с таймаутом (защита от зависших держателей)
        return self._r.lock(f"lock:{cid}", timeout=180)


def make_state_store():
    s = get_settings()
    if s.orchestrator_state_backend == "redis":
        try:
            store = RedisStateStore(s.redis_url, s.state_ttl_seconds)
            log.info("orchestrator state: redis")
            return store
        except Exception:
            log.exception("redis state store init failed → fallback to memory")
    return MemoryStateStore()
