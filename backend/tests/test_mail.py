"""Чтение почты (IMAP): парсинг писем, порядок, не настроено, инструмент агента."""
from email.message import EmailMessage

import pytest

import app.orchestrator as orch
from app.config import get_settings
from services import mail_svc


def _clear_creds(monkeypatch, source="gmail"):
    s = get_settings()
    monkeypatch.setattr(s, f"{source}_imap_user", "")
    monkeypatch.setattr(s, f"{source}_imap_password", "")


def _raw(frm: str, subject: str, body: str) -> bytes:
    m = EmailMessage()
    m["From"] = frm
    m["Subject"] = subject
    m["Date"] = "Wed, 16 Jul 2026 10:00:00 +0700"
    m.set_content(body)
    return m.as_bytes()


class FakeIMAP:
    def __init__(self, messages):
        self._msgs = messages   # oldest-first, как в IMAP (id = индекс+1)

    def select(self, mbox):
        return ("OK", [str(len(self._msgs)).encode()])

    def search(self, charset, criterion):
        ids = " ".join(str(i + 1) for i in range(len(self._msgs))).encode()
        return ("OK", [ids])

    def fetch(self, mid, spec):
        return ("OK", [(b"hdr", self._msgs[int(mid) - 1]), b")"])

    def logout(self):
        pass


def test_fetch_recent_parses_and_orders():
    msgs = [_raw("Дима <d@ya.ru>", "Отчёт Q2", "Прибыль выросла на 18 процентов."),
            _raw("Anna <a@gmail.com>", "Счёт на оплату", "Оплатите счёт 2455.")]
    res = mail_svc.fetch_recent("yandex", count=10, connect=lambda s: FakeIMAP(msgs))
    assert len(res) == 2
    assert res[0]["subject"] == "Счёт на оплату"      # newest-first
    assert "Дима" in res[1]["from"] and res[1]["email"] == "d@ya.ru"
    assert res[1]["subject"] == "Отчёт Q2"            # MIME-заголовок декодирован
    assert "Прибыль" in res[1]["snippet"]


def test_fetch_recent_count_limit():
    msgs = [_raw(f"u{i}@ya.ru", f"тема {i}", "тело") for i in range(10)]
    res = mail_svc.fetch_recent("yandex", count=3, connect=lambda s: FakeIMAP(msgs))
    assert len(res) == 3                               # только 3 последних


def test_not_configured_raises(monkeypatch):
    # источник без логина/пароля → понятный отказ, без сети
    _clear_creds(monkeypatch, "gmail")
    with pytest.raises(mail_svc.MailError):
        mail_svc.fetch_recent("gmail")


def test_unknown_source_raises():
    with pytest.raises(mail_svc.MailError):
        mail_svc.fetch_recent("outlook")


def test_is_configured(monkeypatch):
    _clear_creds(monkeypatch, "gmail")
    assert mail_svc.is_configured("gmail") is False
    s = get_settings()
    monkeypatch.setattr(s, "gmail_imap_user", "x@gmail.com")
    monkeypatch.setattr(s, "gmail_imap_password", "pw")
    assert mail_svc.is_configured("gmail") is True


class UidIMAP:
    """Мок IMAP c UID-поиском/выборкой для уведомлений о новой почте."""
    def __init__(self, msgs):   # msgs: list[(uid, raw_bytes)]
        self._msgs = msgs

    def select(self, mbox):
        return ("OK", [b"x"])

    def logout(self):
        pass

    def uid(self, cmd, *a):
        if cmd == "search":
            crit = a[-1]
            uids = [u for u, _ in self._msgs]
            if crit != "ALL":
                lo = int(str(crit).split(":")[0])
                uids = [u for u in uids if u >= lo]
            return ("OK", [" ".join(map(str, uids)).encode()])
        if cmd == "fetch":
            uid = int(a[0])
            raw = next((r for u, r in self._msgs if u == uid), None)
            return ("OK", [(b"hdr", raw), b")"])
        return ("OK", [b""])


def test_newest_uid():
    msgs = [(10, _raw("a@ya.ru", "t", "b")), (12, _raw("b@ya.ru", "t", "b"))]
    assert mail_svc.newest_uid("yandex", connect=lambda s: UidIMAP(msgs)) == 12


def test_fetch_new_returns_only_newer():
    msgs = [(10, _raw("Old", "Старое", "x")),
            (12, _raw("Иван <n@ya.ru>", "Новое письмо", "привет"))]
    new_max, emails = mail_svc.fetch_new("yandex", 10, connect=lambda s: UidIMAP(msgs))
    assert new_max == 12
    assert len(emails) == 1 and emails[0]["subject"] == "Новое письмо"
    assert emails[0]["unread"] is True


def test_fetch_new_none_when_no_newer():
    msgs = [(10, _raw("a@ya.ru", "t", "b"))]
    new_max, emails = mail_svc.fetch_new("yandex", 10, connect=lambda s: UidIMAP(msgs))
    assert new_max == 10 and emails == []


async def test_read_email_tool_formats(monkeypatch):
    monkeypatch.setattr(orch.mail_svc, "fetch_recent",
                        lambda src, count, unread: [
                            {"from": "Дима", "email": "d@ya.ru", "subject": "Отчёт",
                             "date": "Wed, 16 Jul 2026", "snippet": "суть письма", "unread": False}])

    async def emit(_e):
        pass
    res = await orch.Orchestrator()._execute_tool(
        "read_email", {"source": "yandex"}, emit, 1, None, None)
    assert "Дима" in res and "Отчёт" in res


async def test_read_email_tool_handles_unconfigured(monkeypatch):
    def boom(src, count, unread):
        raise orch.mail_svc.MailError("почта «gmail» не настроена")
    monkeypatch.setattr(orch.mail_svc, "fetch_recent", boom)

    async def emit(_e):
        pass
    res = await orch.Orchestrator()._execute_tool(
        "read_email", {"source": "gmail"}, emit, 1, None, None)
    assert "недоступна" in res.lower()
