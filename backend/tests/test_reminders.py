"""Напоминания: постановка (инструмент), доставка заблаговременных сигналов, отмена."""
import datetime as dt

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import orchestrator as orch
from app import repositories as repo
from app import telegram_bot as tb
from app.config import get_settings
from app.telegram_bot import TelegramBot


def _maker():
    url = get_settings().database_url.rsplit("/", 1)[0] + "/remtech_test"
    return async_sessionmaker(create_async_engine(url), expire_on_commit=False)


async def _noop(_event):
    pass


async def test_set_reminder_creates(session, monkeypatch):
    user = await repo.create_user(session, "boss", "h$1", role="admin")
    await session.commit()
    monkeypatch.setattr(orch, "SessionLocal", _maker())
    future = (dt.datetime.now() + dt.timedelta(days=1)).replace(second=0, microsecond=0)
    res = await orch.Orchestrator()._execute_tool(
        "set_reminder",
        {"text": "позвонить Диме", "datetime": future.isoformat(timespec="minutes"),
         "lead_minutes": [60, 30, 10]},
        _noop, user.id, None, None)
    assert "#" in res and "Диме" in res
    async with _maker()() as s:
        rems = await repo.list_reminders(s, user.id)
    assert len(rems) == 1
    assert rems[0].text == "позвонить Диме"
    assert set(rems[0].lead_pending) == {60, 30, 10}


async def test_set_reminder_rejects_past(session, monkeypatch):
    user = await repo.create_user(session, "boss_p", "h$1", role="admin")
    await session.commit()
    monkeypatch.setattr(orch, "SessionLocal", _maker())
    past = (dt.datetime.now() - dt.timedelta(hours=1)).isoformat(timespec="minutes")
    res = await orch.Orchestrator()._execute_tool(
        "set_reminder", {"text": "поздно", "datetime": past}, _noop, user.id, None, None)
    assert "прошл" in res.lower()


async def test_reminder_delivery_fires_lead(session, monkeypatch):
    user = await repo.create_user(session, "boss2", "h$1", role="admin")
    due = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)   # событие через 5 мин
    rem = await repo.create_reminder(session, user.id, "позвонить Диме", due, [10, 0])
    await session.commit()
    rid = rem.id
    monkeypatch.setattr(tb, "SessionLocal", _maker())

    sent = []

    class Tx:
        async def call(self, method, payload):
            if method == "sendMessage":
                sent.append(payload.get("text", ""))
            return {"result": []}

    bot = TelegramBot(Tx(), allowmap={500: "boss2"})
    await bot._deliver_reminders()
    assert any("Диме" in t for t in sent)             # лид «за 10 мин» уже наступил → сработал
    async with _maker()() as s:
        r = await repo.get_reminder(s, rid)
    assert r is not None and r.lead_pending == [0]     # 10 убран, «в момент» (0) ждёт события


async def test_reminder_deleted_when_all_fired(session, monkeypatch):
    user = await repo.create_user(session, "boss4", "h$1", role="admin")
    due = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)   # момент только что наступил
    rem = await repo.create_reminder(session, user.id, "пора", due, [0])
    await session.commit()
    rid = rem.id
    monkeypatch.setattr(tb, "SessionLocal", _maker())

    class Tx:
        async def call(self, method, payload):
            return {"result": []}

    bot = TelegramBot(Tx(), allowmap={600: "boss4"})
    await bot._deliver_reminders()
    async with _maker()() as s:
        assert await repo.get_reminder(s, rid) is None   # все сигналы отправлены → удалено


async def test_cancel_reminder(session, monkeypatch):
    user = await repo.create_user(session, "boss3", "h$1", role="admin")
    due = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
    rem = await repo.create_reminder(session, user.id, "тест", due, [30])
    await session.commit()
    monkeypatch.setattr(orch, "SessionLocal", _maker())
    res = await orch.Orchestrator()._execute_tool(
        "cancel_reminder", {"reminder_id": rem.id}, _noop, user.id, None, None)
    assert "отменено" in res.lower()
    async with _maker()() as s:
        assert await repo.get_reminder(s, rem.id) is None
