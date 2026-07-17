"""Чтение ТГ-чатов (Telethon): gating, форматтеры, сбор дайджеста, инструменты."""
import pytest

import app.orchestrator as orch
from app.config import get_settings
from services import telethon_svc


async def _noop(_e):
    pass


def _unconfigure(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "telegram_api_id", 0)
    monkeypatch.setattr(s, "telegram_api_hash", "")
    monkeypatch.setattr(s, "telethon_session", "")


def test_not_configured(monkeypatch):
    _unconfigure(monkeypatch)
    assert telethon_svc.is_configured() is False


async def test_list_dialogs_not_configured_raises(monkeypatch):
    # без настройки дефолтная фабрика клиента бросает TelethonError
    _unconfigure(monkeypatch)
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


async def test_digest_tool_not_configured(monkeypatch):
    # группы заданы явно, но Telethon не настроен → честный отказ
    _unconfigure(monkeypatch)
    res = await orch.Orchestrator()._execute_tool(
        "digest_tg_groups", {"groups": ["@work"], "hours": 12}, _noop, 1, None, None)
    assert "не настроен" in res.lower()


async def test_digest_tool_no_groups(monkeypatch):
    # нет явных групп, нет в БД (несуществующий uid), конфиг пуст → сообщение
    monkeypatch.setattr(get_settings(), "tg_digest_groups", "")
    res = await orch.Orchestrator()._execute_tool(
        "digest_tg_groups", {}, _noop, 987654321, None, None)
    assert "групп" in res.lower() and "пуст" in res.lower()


class _FakeDialog:
    def __init__(self, name, entity):
        self.name, self.entity = name, entity


class _FakeClient:
    def __init__(self, dialogs):
        self._d = dialogs

    async def iter_dialogs(self, *a, **k):
        for d in self._d:
            yield d

    async def get_entity(self, x):
        return ("entity", x)


async def test_resolve_by_name_and_id():
    c = _FakeClient([_FakeDialog("Nova Motion Рем Техника", "NM"), _FakeDialog("Python", "PY")])
    assert await telethon_svc._resolve(c, "nova motion") == "NM"   # подстрока, регистр не важен
    assert await telethon_svc._resolve(c, "Python") == "PY"        # точное совпадение
    assert await telethon_svc._resolve(c, "-100123") == ("entity", -100123)  # id напрямую
    with pytest.raises(telethon_svc.TelethonError):
        await telethon_svc._resolve(c, "нет такой группы")


async def test_read_tg_chat_tool_handles_error(monkeypatch):
    async def boom(target, limit=30):
        raise orch.telethon_svc.TelethonError("не настроен")
    monkeypatch.setattr(orch.telethon_svc, "read_chat", boom)
    res = await orch.Orchestrator()._execute_tool(
        "read_tg_chat", {"target": "@x"}, _noop, 1, None, None)
    assert "недоступно" in res.lower()
