"""Issue #30 — кодовый гейт подтверждения действий."""
import asyncio

import pytest

from agent.registry import needs_confirm
from app import orchestrator as orch


def test_needs_confirm_flag():
    assert needs_confirm("generate_video") is True
    assert needs_confirm("create_docx") is False
    assert needs_confirm("search_knowledge_base") is False


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def commit(self):
        pass


async def _noop(*a, **k):
    pass


@pytest.fixture
def gated(monkeypatch):
    # изолируем запись в журнал от реальной БД
    monkeypatch.setattr(orch, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(orch.repo, "log_activity", _noop)
    return orch.Orchestrator()


async def test_non_gated_tool_runs_without_confirm(gated):
    async def emit(e):
        pass
    assert await gated._confirm_if_needed("create_docx", 1, 1, emit) is True


async def test_gated_tool_waits_and_approves(gated):
    events = []

    async def emit(e):
        events.append(e)

    task = asyncio.create_task(gated._confirm_if_needed("generate_video", 5, 1, emit))
    await asyncio.sleep(0.05)
    assert any(e["type"] == "awaiting_confirmation" for e in events)
    gated.resolve_confirmation(5, True)
    assert await task is True


async def test_gated_tool_rejected(gated):
    async def emit(e):
        pass
    task = asyncio.create_task(gated._confirm_if_needed("generate_video", 6, 1, emit))
    await asyncio.sleep(0.05)
    gated.resolve_confirmation(6, False)
    assert await task is False
