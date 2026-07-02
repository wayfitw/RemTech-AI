"""Cutover Стадия 3b — тесты оркестратора: чистые функции + сквозной process()."""
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import orchestrator as orch
from app import repositories as repo
from app.config import get_settings
from app.orchestrator import _safe_content, _sanitize_history


def test_safe_content_keeps_text_and_tooluse():
    class T:
        type = "text"; text = "привет"
    class TU:
        type = "tool_use"; id = "1"; name = "create_docx"; input = {"filename": "x"}
    class Junk:
        type = "server_tool_use"
    out = _safe_content([T(), TU(), Junk()])
    assert out == [
        {"type": "text", "text": "привет"},
        {"type": "tool_use", "id": "1", "name": "create_docx", "input": {"filename": "x"}},
    ]


def test_sanitize_collapses_tool_exchanges():
    history = [
        {"role": "user", "content": "сделай кп"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "1", "name": "create_docx", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "1", "content": "ок"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "готово"}]},
    ]
    clean = _sanitize_history(history)
    # осиротевших tool_use/tool_result не остаётся
    for m in clean:
        c = m.get("content")
        if isinstance(c, list):
            for b in c:
                assert b.get("type") not in ("tool_use", "tool_result")
    assert clean[0]["role"] == "user"
    assert any("готово" in (m["content"] if isinstance(m["content"], str) else "") for m in clean)


def test_sanitize_drops_leading_non_user():
    history = [
        {"role": "assistant", "content": "привет"},
        {"role": "user", "content": "вопрос"},
    ]
    clean = _sanitize_history(history)
    assert clean[0]["role"] == "user"


# ── Сквозной прогон агент-лупа со стаб-моделью ────────────────────────────────

class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Final:
    stop_reason = "end_turn"

    def __init__(self, text):
        self.content = [_Block(text)]


class _StubGateway:
    async def run(self, alias, system, tools, messages, on_delta):
        await on_delta("гото")
        await on_delta("во")
        return _Final("готово")


async def test_process_persists_dialog(session, monkeypatch):
    """process() стримит ответ и сохраняет диалог (user + assistant) в БД."""
    user = await repo.create_user(session, "u", "h$1")
    conv = await repo.create_conversation(session, user.id, "Новый чат")
    await session.commit()

    # оркестратор пишет через свой SessionLocal — направим на ту же тестовую БД
    base = get_settings().database_url
    test_url = base.rsplit("/", 1)[0] + "/remtech_test"
    engine = create_async_engine(test_url)
    monkeypatch.setattr(orch, "SessionLocal", async_sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr(orch, "gateway", _StubGateway())

    events = []
    async def emit(e):
        events.append(e)

    await orch.Orchestrator().process(conv.id, user.id, "привет", [], emit)

    done = [e for e in events if e["type"] == "done"]
    assert done and done[0]["text"] == "готово"
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "готово"

    hist = await repo.load_history(session, conv.id)
    assert [m["role"] for m in hist] == ["user", "assistant"]
    assert hist[1]["content"] == "готово"
    await engine.dispose()


async def test_search_knowledge_base_tool(session, monkeypatch):
    """Инструмент search_knowledge_base ищет в БЗ и возвращает релевантный фрагмент."""
    from app import kb
    from app.embeddings import FakeEmbedder

    await kb.ingest_document(session, FakeEmbedder(1024), "cat.txt",
                             "Гусеничный экскаватор XCMG XE215C для земляных работ.")
    await session.commit()

    base = get_settings().database_url
    test_url = base.rsplit("/", 1)[0] + "/remtech_test"
    engine = create_async_engine(test_url)
    monkeypatch.setattr(orch, "SessionLocal", async_sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr("app.embeddings.get_embedder", lambda: FakeEmbedder(1024))

    async def emit(e):
        pass

    res = await orch.Orchestrator()._execute_tool(
        "search_knowledge_base", {"query": "нужен экскаватор для земли"}, emit, 1, 1, None)
    assert "экскаватор" in res.lower()
    await engine.dispose()


async def test_create_proposal_tool(session, monkeypatch):
    """Инструмент create_proposal генерирует КП, сохраняет файл и шлёт событие document."""
    user = await repo.create_user(session, "u", "h$1")
    conv = await repo.create_conversation(session, user.id, "Новый чат")
    await session.commit()

    base = get_settings().database_url
    test_url = base.rsplit("/", 1)[0] + "/remtech_test"
    engine = create_async_engine(test_url)
    monkeypatch.setattr(orch, "SessionLocal", async_sessionmaker(engine, expire_on_commit=False))

    events = []
    async def emit(e):
        events.append(e)

    params = {"filename": "КП_XE215C", "title": "Экскаватор", "client": "ООО Тест",
              "markup_percent": 12, "items": [{"name": "XCMG XE215C", "qty": 1, "price": 9850000}]}
    res = await orch.Orchestrator()._execute_tool("create_proposal", params, emit, user.id, conv.id, None)
    assert "КП" in res
    docs = [e for e in events if e["type"] == "document"]
    assert docs and docs[0]["name"] == "КП_XE215C.docx"

    rec = await repo.get_file_record(session, docs[0]["file_id"])
    assert rec is not None and rec.kind == "docx" and rec.direction == "output"
    await engine.dispose()
