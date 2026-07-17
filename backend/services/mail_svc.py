"""Чтение почты по IMAP (Gmail / Яндекс) для личного ассистента директора.

Единообразно через IMAP + пароль приложения (без OAuth): stdlib imaplib/email.
Только чтение. Источник «не настроен» (нет логина/пароля) → понятный отказ, не падаем.
Байты писем не логируем и наружу не отдаём — только краткая сводка (от/тема/дата/фрагмент).
"""
from __future__ import annotations

import email
import imaplib
import ssl
from email.header import decode_header
from email.utils import parseaddr

from app.config import get_settings

# Источник → IMAP-хост. Логин/пароль приложения — из конфига по источнику.
_HOSTS = {"gmail": "imap.gmail.com", "yandex": "imap.yandex.ru"}
_SNIPPET = 240   # длина текстового фрагмента письма


class MailError(Exception):
    """Почта недоступна: не настроена, ошибка входа или соединения."""


def _creds(source: str) -> tuple[str, str]:
    s = get_settings()
    return {
        "gmail": (s.gmail_imap_user, s.gmail_imap_password),
        "yandex": (s.yandex_imap_user, s.yandex_imap_password),
    }.get(source, ("", ""))


def is_configured(source: str) -> bool:
    u, p = _creds(source)
    return bool(u and p)


def _decode(raw: str | None) -> str:
    """Декодирует MIME-заголовок (=?utf-8?..?=) в читаемую строку."""
    if not raw:
        return ""
    parts = []
    for text, enc in decode_header(raw):
        if isinstance(text, bytes):
            parts.append(text.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(text)
    return "".join(parts).strip()


def _snippet(msg: email.message.Message) -> str:
    """Короткий фрагмент текста письма (первый text/plain)."""
    try:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain" and \
                        "attachment" not in str(part.get("Content-Disposition", "")):
                    body = part.get_payload(decode=True) or b""
                    return _clean_body(body.decode(part.get_content_charset() or "utf-8",
                                                    errors="replace"))
            return ""
        body = msg.get_payload(decode=True) or b""
        return _clean_body(body.decode(msg.get_content_charset() or "utf-8", errors="replace"))
    except Exception:
        return ""


def _clean_body(text: str) -> str:
    return " ".join(text.split())[:_SNIPPET]


def _connect(source: str) -> imaplib.IMAP4_SSL:
    host = _HOSTS.get(source)
    if not host:
        raise MailError(f"неизвестный источник почты «{source}» (доступны: gmail, yandex)")
    user, pwd = _creds(source)
    if not user or not pwd:
        raise MailError(f"почта «{source}» не настроена (нужен логин и пароль приложения)")
    try:
        m = imaplib.IMAP4_SSL(host, ssl_context=ssl.create_default_context())
        m.login(user, pwd)
    except Exception as e:
        raise MailError(f"не удалось подключиться к «{source}»: {type(e).__name__}") from e
    return m


def _parse_email(raw: bytes, unread: bool = False) -> dict:
    msg = email.message_from_bytes(raw)
    name, addr = parseaddr(_decode(msg.get("From")))
    return {
        "from": name or addr,
        "email": addr,
        "subject": _decode(msg.get("Subject")) or "(без темы)",
        "date": _decode(msg.get("Date")),
        "snippet": _snippet(msg),
        "unread": unread,
    }


def _raw_of(msg_data) -> bytes | None:
    return next((p[1] for p in msg_data if isinstance(p, tuple)), None)


def fetch_recent(source: str, count: int = 10, unread_only: bool = False,
                 *, connect=_connect) -> list[dict]:
    """Последние письма из INBOX: список {from, subject, date, snippet, unread}.
    newest-first. connect — фабрика IMAP-клиента (подменяется в тестах)."""
    count = max(1, min(int(count or 10), 30))
    m = connect(source)
    try:
        m.select("INBOX")
        typ, data = m.search(None, "UNSEEN" if unread_only else "ALL")
        ids = (data[0] or b"").split()[-count:]
        out: list[dict] = []
        for mid in reversed(ids):   # свежие сверху
            raw = _raw_of(m.fetch(mid, "(RFC822)")[1])
            if raw:
                out.append(_parse_email(raw, unread_only))
        return out
    except MailError:
        raise
    except Exception as e:
        raise MailError(f"ошибка чтения почты «{source}»: {type(e).__name__}") from e
    finally:
        try:
            m.logout()
        except Exception:
            pass


def newest_uid(source: str, *, connect=_connect) -> int:
    """Наибольший UID в INBOX — стартовая отметка, чтобы не уведомлять старым."""
    m = connect(source)
    try:
        m.select("INBOX")
        uids = [int(x) for x in (m.uid("search", None, "ALL")[1][0] or b"").split()]
        return max(uids) if uids else 0
    except Exception as e:
        raise MailError(f"ошибка почты «{source}»: {type(e).__name__}") from e
    finally:
        try:
            m.logout()
        except Exception:
            pass


def fetch_new(source: str, after_uid: int, *, connect=_connect) -> tuple[int, list[dict]]:
    """Новые письма с UID > after_uid. Возвращает (новый_максимум_UID, [письма]).
    Для уведомлений о новой почте (пуш из фонового цикла)."""
    after_uid = int(after_uid or 0)
    m = connect(source)
    try:
        m.select("INBOX")
        # N:* может вернуть последнее письмо даже если новее нет — фильтруем строго
        found = (m.uid("search", None, f"{after_uid + 1}:*")[1][0] or b"").split()
        uids = sorted(u for u in (int(x) for x in found) if u > after_uid)
        new_max = uids[-1] if uids else after_uid
        emails = []
        for u in uids:
            raw = _raw_of(m.uid("fetch", str(u), "(RFC822)")[1])
            if raw:
                emails.append(_parse_email(raw, unread=True))
        return new_max, emails
    except Exception as e:
        raise MailError(f"ошибка почты «{source}»: {type(e).__name__}") from e
    finally:
        try:
            m.logout()
        except Exception:
            pass
