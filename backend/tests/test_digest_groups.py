"""Управление группами утренней сводки: репозиторий + инструменты (add/list/remove)."""
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.orchestrator as orch
from app import repositories as repo
from app.config import get_settings


def _bind(monkeypatch):
    url = get_settings().database_url.rsplit("/", 1)[0] + "/remtech_test"
    monkeypatch.setattr(orch, "SessionLocal",
                        async_sessionmaker(create_async_engine(url), expire_on_commit=False))


async def test_digest_group_repo(session):
    u = await repo.create_user(session, "dgr", "h", role="admin")
    await session.commit()
    await repo.add_digest_group(session, u.id, "-100", "Рабочая группа")
    dup = await repo.add_digest_group(session, u.id, "-100", "Рабочая группа")   # идемпотентно
    await session.commit()
    assert dup is None
    rows = await repo.list_digest_groups(session, u.id)
    assert len(rows) == 1 and rows[0].title == "Рабочая группа"
    title = await repo.delete_digest_group(session, u.id, "рабоч")   # по подстроке названия
    await session.commit()
    assert title == "Рабочая группа"
    assert await repo.list_digest_groups(session, u.id) == []


async def test_add_list_remove_tools(session, monkeypatch):
    u = await repo.create_user(session, "dgt", "h", role="admin")
    await session.commit()
    _bind(monkeypatch)

    async def fake_find(name):
        return "-1005474779783", "Nova Motion Рем Техника"
    monkeypatch.setattr(orch.telethon_svc, "find_dialog", fake_find)
    monkeypatch.setattr(orch.telethon_svc, "is_configured", lambda: True)

    async def emit(_e):
        pass
    add = await orch.Orchestrator()._execute_tool(
        "add_digest_group", {"group": "Nova"}, emit, u.id, None, None)
    assert "добавил" in add.lower() and "Nova Motion" in add

    lst = await orch.Orchestrator()._execute_tool("list_digest_groups", {}, emit, u.id, None, None)
    assert "Nova Motion Рем Техника" in lst

    rm = await orch.Orchestrator()._execute_tool(
        "remove_digest_group", {"group": "nova"}, emit, u.id, None, None)
    assert "убрал" in rm.lower()


async def test_add_digest_group_not_configured(session, monkeypatch):
    u = await repo.create_user(session, "dgt2", "h", role="admin")
    await session.commit()
    _bind(monkeypatch)
    monkeypatch.setattr(orch.telethon_svc, "is_configured", lambda: False)

    async def emit(_e):
        pass
    res = await orch.Orchestrator()._execute_tool(
        "add_digest_group", {"group": "X"}, emit, u.id, None, None)
    assert "не настроен" in res.lower()
