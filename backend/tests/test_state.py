"""Issue #16 — тесты разделяемого состояния оркестратора (memory + redis)."""
import pytest

from app.state import MemoryStateStore


async def test_memory_store_roundtrip():
    st = MemoryStateStore()
    assert await st.get_image(1) is None
    await st.set_image(1, b"img-bytes")
    assert await st.get_image(1) == b"img-bytes"

    assert await st.get_docx(1) is None
    await st.set_docx(1, b"doc-data", "file.docx")
    assert await st.get_docx(1) == (b"doc-data", "file.docx")


def test_memory_lock_is_reused_per_conversation():
    st = MemoryStateStore()
    a, b, c = st.lock(5), st.lock(5), st.lock(6)
    assert a is b and a is not c


async def test_redis_store_roundtrip_if_available():
    from app.config import get_settings
    from app.state import RedisStateStore
    st = RedisStateStore(get_settings().redis_url, ttl=60)
    try:
        await st._r.ping()
    except Exception:
        pytest.skip("redis недоступен")
    cid = 987654
    await st.set_image(cid, b"\x00\x01binary")
    assert await st.get_image(cid) == b"\x00\x01binary"
    # имя с кириллицей + данные с нулевым байтом (проверяем разбор по первому \x00)
    await st.set_docx(cid, b"\x00docdata", "КП.docx")
    assert await st.get_docx(cid) == (b"\x00docdata", "КП.docx")
    await st._r.delete(f"img:{cid}", f"docx:{cid}")
