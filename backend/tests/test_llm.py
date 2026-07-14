"""EPIC-02 (2a) — тесты реестра моделей/агентов и маршрутизации шлюза."""
import pytest

from app import llm
from app import repositories as repo


async def test_model_config_repo(session):
    mc = await repo.create_model_config(session, "claude", "anthropic",
                                        "claude-sonnet-4-6", fallback_to="yandex")
    await session.commit()
    got = await repo.get_model_config_by_alias(session, "claude")
    assert got.provider == "anthropic"
    assert got.endpoint == "claude-sonnet-4-6"
    assert got.fallback_to == "yandex"
    assert len(await repo.list_model_configs(session)) == 1
    await repo.delete_model_config(session, mc.id)
    await session.commit()
    assert await repo.get_model_config_by_alias(session, "claude") is None


async def test_agent_repo(session):
    mc = await repo.create_model_config(session, "claude", "anthropic")
    agent = await repo.create_agent(session, "Продажник", "Ты менеджер",
                                    ["create_docx", "search_knowledge_base"],
                                    mc.id, "user,admin")
    await session.commit()
    got = (await repo.list_agents(session))[0]
    assert got.name == "Продажник"
    assert "create_docx" in got.tools
    assert got.default_model == mc.id
    assert (await repo.get_agent(session, agent.id)).allowed_roles == "user,admin"


class _Stub:
    def __init__(self, result="ok", fail=False):
        self.result, self.fail, self.calls = result, fail, 0

    async def run(self, system, tools, messages, on_delta):
        self.calls += 1
        if self.fail:
            raise RuntimeError("provider down")
        await on_delta("chunk")
        return self.result


async def test_resolve_route_reads_config(session):
    # #18 — resolve_route берёт маршрут из БД по переданной сессии (шлюз БД не трогает)
    await repo.create_model_config(session, "claude-fast", "anthropic", "claude-haiku")
    await repo.create_model_config(session, "claude", "anthropic", "claude-sonnet",
                                   fallback_to="claude-fast")
    await session.commit()
    route = await llm.resolve_route(session, "claude")
    assert route.provider == "anthropic" and route.model == "claude-sonnet"
    assert route.fallback_provider == "anthropic" and route.fallback_model == "claude-haiku"


async def test_gateway_default_provider(monkeypatch):
    stub = _Stub("final")
    monkeypatch.setattr(llm, "make_provider", lambda provider, model: stub)

    chunks = []
    async def on_delta(c):
        chunks.append(c)

    route = llm.ModelRoute("anthropic", "claude-x")
    res = await llm.gateway.run(route, "sys", [], [], on_delta)
    assert res == "final" and chunks == ["chunk"] and stub.calls == 1


async def test_gateway_fallback_on_failure(monkeypatch):
    primary, fallback = _Stub(fail=True), _Stub("fb-result")
    monkeypatch.setattr(llm, "make_provider",
                        lambda provider, model: fallback if model == "claude-y" else primary)

    async def on_delta(c):
        pass

    route = llm.ModelRoute("anthropic", "claude-x", "anthropic", "claude-y")
    res = await llm.gateway.run(route, "sys", [], [], on_delta)
    assert res == "fb-result"
    assert primary.calls == 1 and fallback.calls == 1


async def test_gateway_reraises_primary_when_fallback_unavailable(monkeypatch):
    # #21 — если fallback-провайдер не реализован, наружу идёт ИСХОДНАЯ ошибка,
    # а не NotImplementedError, маскирующий первопричину.
    def make(provider, model):
        if provider == "yandex":
            raise NotImplementedError("yandex не реализован (стадия 2b)")
        return _Stub(fail=True)   # основной падает RuntimeError("provider down")
    monkeypatch.setattr(llm, "make_provider", make)

    async def on_delta(c):
        pass

    route = llm.ModelRoute("anthropic", "claude-x", "yandex", "y-model")
    with pytest.raises(RuntimeError, match="provider down"):
        await llm.gateway.run(route, "sys", [], [], on_delta)
