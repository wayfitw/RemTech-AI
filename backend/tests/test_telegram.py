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
    # компактно: без расширений, «_»→пробел, одной строкой с 📎
    assert "STOK LiuGong" in sent and "Прайс 2025" in sent
    assert "источник" not in sent                        # заглушки больше нет
    assert "📎" in sent and sent.count("STOK LiuGong") == 1   # дубли схлопнуты


def test_md_to_tg_html_strips_markdown():
    from app.telegram_bot import md_to_tg_html
    src = "### 🏢 Заголовок\n\nЭто **важно** и *курсив*.\n\n---\n\n- пункт один\n- пункт два"
    out = md_to_tg_html(src)
    assert "###" not in out and "**" not in out          # сырого markdown нет
    assert "<b>🏢 Заголовок</b>" in out                   # заголовок → жирный
    assert "<b>важно</b>" in out                          # **bold** → <b>
    assert "• пункт один" in out                          # маркеры списка → •
    assert "---" not in out                               # горизонтальная линия убрана


async def test_start_greets_with_telegram_name(session, monkeypatch):
    """/start подставляет имя из профиля Telegram (first_name), а не из учётки."""
    _bind_test_db(monkeypatch)
    await repo.create_user(session, "buyer", "h$1", full_name="Пётр Учёткин", role="закупки")
    await session.commit()

    tx = FakeTransport()
    bot = TelegramBot(tx, allowmap={777: "buyer"})
    await bot.handle_update({"message": {"chat": {"id": 42},
                                         "from": {"id": 777, "first_name": "Кирилл"},
                                         "text": "/start"}})
    greeting = tx.sent_texts()[0]
    assert "Кирилл" in greeting          # имя из Telegram
    assert "Учёткин" not in greeting      # не имя учётной записи


async def test_new_command_resets_conversation(session, monkeypatch):
    """/new сбрасывает текущий диалог — следующий вопрос начинается с чистого листа."""
    _bind_test_db(monkeypatch)
    await repo.create_user(session, "buyer", "h$1", role="закупки")
    await session.commit()

    async def fake_process(*a, **k):
        pass
    monkeypatch.setattr(tb.orchestrator, "process", fake_process)

    tx = FakeTransport()
    bot = TelegramBot(tx, allowmap={777: "buyer"})
    bot._conv[42] = 999                              # был активный диалог
    await bot.handle_update({"message": {"chat": {"id": 42}, "from": {"id": 777}, "text": "/new"}})
    assert 42 not in bot._conv                        # диалог сброшен
    assert any("новый диалог" in t.lower() for t in tx.sent_texts())


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


# ── Голосовой ответ отключён: бот принимает голос (STT), но отвечает текстом ──

def test_bot_has_no_voice_reply():
    # TTS в Telegram убран — ни озвучки ответа, ни транспортной отправки медиа
    assert not hasattr(TelegramBot, "_send_voice_answer")
    assert not hasattr(tb.TelegramTransport, "send_media")


# ── Персона бота: Telegram = личный ассистент директора (web — сотрудники) ─────

async def test_bot_default_agent_when_unset():
    # без TELEGRAM_AGENT — дефолтный агент (None), БД не трогается
    bot = TelegramBot(FakeTransport(), allowmap={})
    assert await bot.agent_id() is None


async def test_bot_resolves_persona_agent(session, monkeypatch):
    _bind_test_db(monkeypatch)
    from app import repositories as repo
    name = "Персона-Тест"
    async with tb.SessionLocal() as s:   # тот же тестовый БД-маркер, что у бота
        await repo.create_agent(s, name, "промпт", None, None, "")
        await s.commit()
    bot = TelegramBot(FakeTransport(), allowmap={}, agent_name=name)
    aid = await bot.agent_id()
    assert aid is not None
    assert await bot.agent_id() == aid            # результат кэшируется


async def test_bot_missing_persona_falls_back(session, monkeypatch):
    _bind_test_db(monkeypatch)
    bot = TelegramBot(FakeTransport(), allowmap={}, agent_name="Нет-Такого-Агента")
    assert await bot.agent_id() is None            # не найден → дефолтный агент


async def test_bot_sends_generated_image(session, monkeypatch):
    # событие image в ходе → бот отправляет картинку через sendPhoto (не только текст)
    _bind_test_db(monkeypatch)
    from app import storage
    async with tb.SessionLocal() as s:
        u = await repo.create_user(s, "ceo", "hash", role="admin", full_name="CEO")
        conv = await repo.create_conversation(s, u.id, "чат")
        await s.commit()
        rec = await storage.save_bytes(s, u.id, conv.id, "pic.jpg", b"\xff\xd8pic", kind="image")
        await s.commit()
        fid, cid = rec.id, conv.id

    async def fake_run_turn(user, conversation_id, text, files, agent_id, emit, **kw):
        await emit({"type": "image", "file_id": fid, "name": "pic.jpg"})
        await emit({"type": "done", "text": "Готово"})
        return cid
    monkeypatch.setattr(tb, "run_turn", fake_run_turn)

    sent = []

    class Tx(FakeTransport):
        async def send_file(self, chat_id, data, filename, method="sendDocument", field="document"):
            sent.append({"method": method, "field": field, "name": filename})
            return {"ok": True}

    bot = TelegramBot(Tx(), allowmap={100: "ceo"})
    await bot.handle_update({"message": {"chat": {"id": 100}, "from": {"id": 100}, "text": "нарисуй"}})
    assert sent == [{"method": "sendPhoto", "field": "photo", "name": "pic.jpg"}]


async def test_bot_accepts_incoming_document(session, monkeypatch):
    # присланный файл → бот скачивает, сохраняет и передаёт ходу вложением
    _bind_test_db(monkeypatch)
    async with tb.SessionLocal() as s:
        await repo.create_user(s, "ceo2", "h", role="admin", full_name="CEO")
        await s.commit()

    captured = {}

    async def fake_run_turn(user, conversation_id, text, files, agent_id, emit, **kw):
        captured["files"], captured["text"] = files, text
        await emit({"type": "done", "text": "ок"})
        return 1
    monkeypatch.setattr(tb, "run_turn", fake_run_turn)

    class Tx(FakeTransport):
        async def get_file_bytes(self, file_id):
            import io

            from docx import Document
            d = Document()
            d.add_paragraph("Отчёт по XCMG")
            buf = io.BytesIO()
            d.save(buf)
            return buf.getvalue()

    bot = TelegramBot(Tx(), allowmap={200: "ceo2"})
    await bot.handle_update({"message": {"chat": {"id": 200}, "from": {"id": 200},
                                         "document": {"file_id": "f1", "file_name": "report.docx"}}})
    assert captured["files"] and captured["text"]        # файл и текст-подсказка переданы ходу
    async with tb.SessionLocal() as s:
        rec = await repo.get_file_record(s, captured["files"][0])
    assert rec is not None and rec.direction == "input"  # сохранён как входящее вложение
