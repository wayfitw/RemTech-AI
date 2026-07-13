"""Issue #31 — Telegram-ассистент как тонкий клиент API.

Проверяем: allow-list (не-сопоставленный ID отклонён, агент не вызван);
авторизованный запрос доходит до ядра и ответ уходит пользователю; связывание
управляется allow-list из конфига; ответ на кнопку резолвит подтверждение (#30).
"""
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import repositories as repo
from app import telegram_bot as tb
from app import turn
from app.config import Settings, get_settings
from app.telegram_bot import TelegramBot


class FakeTransport:
    """Мок Bot API: копит вызовы, сети нет."""
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def call(self, method: str, payload: dict) -> dict:
        self.calls.append((method, payload))
        return {"result": []}

    def sent_texts(self) -> list[str]:
        return [p["text"] for m, p in self.calls if m == "sendMessage"]


def _bind_test_db(monkeypatch):
    """SessionLocal у бота и у ядра хода → тестовая БД."""
    base = get_settings().database_url
    test_url = base.rsplit("/", 1)[0] + "/remtech_test"
    engine = create_async_engine(test_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(tb, "SessionLocal", maker)
    monkeypatch.setattr(turn, "SessionLocal", maker)
    return engine


def test_allowlist_parsing():
    s = Settings(telegram_allowlist="111:ivan, 222 : petrov ,broken,333:")
    assert s.telegram_allowmap == {111: "ivan", 222: "petrov"}


async def test_reject_non_allowlist(session, monkeypatch):
    _bind_test_db(monkeypatch)
    called = {"n": 0}

    async def fake_process(*a, **k):
        called["n"] += 1
    monkeypatch.setattr(tb.orchestrator, "process", fake_process)

    tx = FakeTransport()
    bot = TelegramBot(tx, allowmap={})   # никого нет в allow-list
    await bot.handle_update({"message": {"chat": {"id": 5}, "from": {"id": 999}, "text": "привет"}})

    assert called["n"] == 0                                  # агент НЕ вызван
    assert any("администратору" in t for t in tx.sent_texts())  # отказ пользователю


async def test_authorized_reaches_agent(session, monkeypatch):
    engine = _bind_test_db(monkeypatch)
    ivan = await repo.create_user(session, "ivan", "h$1", role="user")
    await session.commit()

    async def fake_process(cid, uid, text, attachments, emit, roles, agent_id):
        assert uid == ivan.id and text == "сколько стоит экскаватор"
        await emit({"type": "done", "text": "Экскаватор XCMG — от 5 млн ₽."})
    monkeypatch.setattr(tb.orchestrator, "process", fake_process)

    tx = FakeTransport()
    bot = TelegramBot(tx, allowmap={777: "ivan"})
    await bot.handle_update({"message": {"chat": {"id": 42}, "from": {"id": 777},
                                         "text": "сколько стоит экскаватор"}})

    texts = tx.sent_texts()
    assert any("5 млн" in t for t in texts)                  # ответ агента доставлен
    assert 42 in bot._conv                                   # диалог сохранён для продолжения
    await engine.dispose()


async def test_inactive_user_rejected(session, monkeypatch):
    _bind_test_db(monkeypatch)
    u = await repo.create_user(session, "fired", "h$1")
    u.active = 0
    await session.commit()

    async def fake_process(*a, **k):
        raise AssertionError("не должно вызываться для неактивного")
    monkeypatch.setattr(tb.orchestrator, "process", fake_process)

    tx = FakeTransport()
    bot = TelegramBot(tx, allowmap={1: "fired"})
    await bot.handle_update({"message": {"chat": {"id": 9}, "from": {"id": 1}, "text": "?"}})
    assert any("администратору" in t for t in tx.sent_texts())


async def test_sources_show_document_names(monkeypatch):
    """#29/#31 — источники в Telegram выводятся именами документов, с дедупом,
    а не заглушкой «источник» (регресс)."""
    async def fake_run_turn(user, cid, text, files, agent, emit, **kw):
        await emit({"type": "done", "text": "Вот ответ."})
        await emit({"type": "sources", "items": [
            {"document_id": 1, "file_name": "STOK_LiuGong.xlsx"},
            {"document_id": 1, "file_name": "STOK_LiuGong.xlsx"},   # дубль → схлопнуть
            {"document_id": 2, "file_name": "Прайс_2025.pdf"},
        ]})
        return 5
    monkeypatch.setattr(tb, "run_turn", fake_run_turn)

    tx = FakeTransport()
    bot = TelegramBot(tx, allowmap={})
    await bot._run_turn(1, {"user_id": 1, "name": "X", "role": "admin"}, "вопрос")

    sent = "\n".join(tx.sent_texts())
    assert "STOK_LiuGong.xlsx" in sent and "Прайс_2025.pdf" in sent
    assert "• источник\n" not in sent and not sent.endswith("• источник")
    assert sent.count("STOK_LiuGong.xlsx") == 1          # дубли схлопнуты


async def test_confirmation_callback_resolves(session, monkeypatch):
    _bind_test_db(monkeypatch)
    resolved = {}

    def fake_resolve(cid, approved):
        resolved.update(cid=cid, approved=approved)
    monkeypatch.setattr(tb.orchestrator, "resolve_confirmation", fake_resolve)

    tx = FakeTransport()
    bot = TelegramBot(tx, allowmap={})
    bot._pending_conv[42] = 7                                 # ждём подтверждения по беседе 7
    await bot._on_callback({"id": "cq1", "data": "confirm:approve",
                            "message": {"chat": {"id": 42}}})
    assert resolved == {"cid": 7, "approved": True}
    assert any(m == "answerCallbackQuery" for m, _ in tx.calls)
