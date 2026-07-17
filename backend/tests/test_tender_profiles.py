"""Профили тендеров (#44): владелец, список/удаление с правами, «искать сейчас», RBAC."""
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.orchestrator as orch
from app import repositories as repo
from app.config import get_settings


def _bind(monkeypatch):
    url = get_settings().database_url.rsplit("/", 1)[0] + "/remtech_test"
    monkeypatch.setattr(orch, "SessionLocal",
                        async_sessionmaker(create_async_engine(url), expire_on_commit=False))


async def _noop(_e):
    pass


async def test_profile_repo_owner_scope(session):
    a = await repo.create_user(session, "buyerA", "h", role="user")
    b = await repo.create_user(session, "buyerB", "h", role="user")
    await session.commit()
    await repo.create_subscription(session, "Экскаваторы", "экскаватор", owner_id=a.id)
    await repo.create_subscription(session, "Чужой", "бульдозер", owner_id=b.id)
    await session.commit()
    mine = await repo.list_subscriptions_for_user(session, a.id)
    assert len(mine) == 1 and mine[0].name == "Экскаваторы"
    assert len(await repo.list_subscriptions_for_user(session, a.id, is_admin=True)) >= 2
    sub_b = (await repo.list_subscriptions_for_user(session, b.id))[0]
    assert await repo.delete_subscription(session, sub_b.id, owner_id=a.id) is False   # чужой
    assert await repo.delete_subscription(session, sub_b.id, owner_id=b.id) is True    # свой


async def test_profile_tools_save_list_search_delete(session, monkeypatch):
    u = await repo.create_user(session, "buyerC", "h", role="user")
    await session.commit()
    _bind(monkeypatch)
    roles = ["закупки"]

    save = await orch.Orchestrator()._execute_tool(
        "save_tender_profile", {"name": "XCMG", "keywords": "экскаватор XCMG", "budget_max": 20000000},
        _noop, u.id, None, roles)
    assert "сохранён" in save.lower()

    lst = await orch.Orchestrator()._execute_tool("list_tender_profiles", {}, _noop, u.id, None, roles)
    assert "XCMG" in lst

    import services.tenders as tenders_mod
    monkeypatch.setattr(tenders_mod, "search_tenders",
                        lambda kw, region, customer, bmin, bmax: [
                            {"number": "123", "name": "Экскаватор XCMG XE215",
                             "price": 5000000.0, "deadline": "20.07.2026", "link": "http://x"}])
    found = await orch.Orchestrator()._execute_tool(
        "search_tender_profile", {"profile": "XCMG"}, _noop, u.id, None, roles)
    assert "123" in found and "Экскаватор" in found

    async with orch.SessionLocal() as s:
        pid = (await repo.list_subscriptions_for_user(s, u.id))[0].id
    dele = await orch.Orchestrator()._execute_tool(
        "delete_tender_profile", {"profile_id": pid}, _noop, u.id, None, roles)
    assert "удалён" in dele.lower()


def test_profile_rbac():
    from agent.registry import role_can_use_tool
    assert role_can_use_tool("закупки", "save_tender_profile") is True
    assert role_can_use_tool("руководство", "search_tender_profile") is True
    assert role_can_use_tool("admin", "list_tender_profiles") is True
    assert role_can_use_tool("продажи", "save_tender_profile") is False
    assert role_can_use_tool("user", "list_tender_profiles") is False
