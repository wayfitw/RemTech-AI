"""Чтение ТГ-чатов (Telethon): gating, форматтеры, сбор дайджеста, инструменты."""
import pytest

import app.orchestrator as orch
from services import telethon_svc


async def _noop(_e):
    pass


def test_not_configured():
    # без API_ID/HASH/сессии — не настроено
    assert telethon_svc.is_configured() is False


async def test_list_dialogs_not_configured_raises():
    # дефолтная фабрика клиента бросает TelethonError, т.к. не настроено
    with pytest.raises(telethon_svc.TelethonError):
        await telethon_svc.list_dialogs()


def test_format_messages():
    msgs = [{"ts": "16.07 09:00", "sender": "Дима", "text": "привет"},
            {"ts": "16.07 09:05", "sender": "Аня", "text": "готово"}]
    out = telethon_svc.format_messages(msgs)
    assert "[16.07 09:00] Дима: привет" in out
    assert "Аня: готово" in out
    assert telethon_svc.format_messages([]) == "Нет текстовых сообщений."


async def test_collect_digest_groups_and_errors():
    async def fake_reader(group, since, limit=200):
        if group == "@bad":
            raise telethon_svc.TelethonError("нет доступа")
        return [{"ts": "16.07 03:00", "sender": "Дима", "text": "ночью написал"}]
    res = await telethon_svc.collect_digest(["@work", "@bad"], hours=12, reader=fake_reader)
    assert "### @work" in res and "ночью написал" in res
    assert "### @bad" in res and "не удалось" in res


async def test_digest_tool_not_configured():
    # группы заданы явно, но Telethon не настроен → честный отказ
    res = await orch.Orchestrator()._execute_tool(
        "digest_tg_groups", {"groups": ["@work"], "hours": 12}, _noop, 1, None, None)
    assert "не настроен" in res.lower()


async def test_digest_tool_no_groups():
    res = await orch.Orchestrator()._execute_tool(
        "digest_tg_groups", {}, _noop, 1, None, None)
    assert "групп" in res.lower() and "не задан" in res.lower()


async def test_read_tg_chat_tool_handles_error(monkeypatch):
    async def boom(target, limit=30):
        raise orch.telethon_svc.TelethonError("не настроен")
    monkeypatch.setattr(orch.telethon_svc, "read_chat", boom)
    res = await orch.Orchestrator()._execute_tool(
        "read_tg_chat", {"target": "@x"}, _noop, 1, None, None)
    assert "недоступно" in res.lower()
