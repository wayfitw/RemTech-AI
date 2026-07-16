"""Чтение ТГ-чатов/групп от лица пользователя (Telethon, MTProto).

Бот НЕ может читать историю групп, где его не было, — поэтому используем
пользовательский сеанс (аккаунт директора). Сессия хранится строкой (StringSession)
в конфиге TELETHON_SESSION; создаётся входом по QR: python -m scripts.telethon_login.

Только чтение (+ список диалогов). Не настроено/не авторизовано → понятный
TelethonError, ход не падает. Тексты сообщений наружу не логируем.
"""
from __future__ import annotations

import datetime as dt

from app.config import get_settings


class TelethonError(Exception):
    """Telethon не настроен, не авторизован или недоступен."""


def is_configured() -> bool:
    s = get_settings()
    return bool(s.telegram_api_id and s.telegram_api_hash and s.telethon_session)


async def _client():
    """Подключённый авторизованный TelegramClient (StringSession). Иначе TelethonError.
    Вызывающий обязан вызвать await client.disconnect()."""
    s = get_settings()
    if not is_configured():
        raise TelethonError("Telethon не настроен (нужны API_ID/API_HASH и сессия — "
                            "вход по QR: python -m scripts.telethon_login)")
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        client = TelegramClient(StringSession(s.telethon_session),
                                s.telegram_api_id, s.telegram_api_hash)
        await client.connect()
    except Exception as e:
        raise TelethonError(f"не удалось подключиться: {type(e).__name__}") from e
    if not await client.is_user_authorized():
        await client.disconnect()
        raise TelethonError("сессия недействительна — войдите заново (scripts.telethon_login)")
    return client


def _sender_name(msg) -> str:
    s = getattr(msg, "sender", None)
    if s is None:
        return "?"
    name = f"{getattr(s, 'first_name', '') or ''} {getattr(s, 'last_name', '') or ''}".strip()
    return name or getattr(s, "username", "") or str(getattr(msg, "sender_id", "?"))


def format_messages(msgs: list[dict]) -> str:
    """Список {ts, sender, text} → построчный текст (старые сверху)."""
    lines = [f"[{m['ts']}] {m['sender']}: {m['text']}" for m in msgs if m.get("text")]
    return "\n".join(lines) if lines else "Нет текстовых сообщений."


async def list_dialogs(limit: int = 30, *, client_factory=_client) -> str:
    client = await client_factory()
    try:
        out = []
        async for d in client.iter_dialogs(limit=limit):
            unread = f" [{d.unread_count} непроч.]" if getattr(d, "unread_count", 0) else ""
            kind = "группа" if getattr(d, "is_group", False) else (
                "канал" if getattr(d, "is_channel", False) else "чат")
            out.append(f"• {d.name or 'без имени'} ({kind}, id {d.id}){unread}")
        return "\n".join(out) if out else "Диалогов нет."
    finally:
        await client.disconnect()


async def read_chat(target, limit: int = 30, *, client_factory=_client) -> str:
    client = await client_factory()
    try:
        msgs = []
        async for m in client.iter_messages(target, limit=limit):
            if getattr(m, "text", None):
                msgs.append({"ts": m.date.astimezone().strftime("%d.%m %H:%M"),
                             "sender": _sender_name(m), "text": m.text[:500]})
        msgs.reverse()   # старые сверху
        return format_messages(msgs)
    finally:
        await client.disconnect()


async def read_since(target, since: dt.datetime, limit: int = 200,
                     *, client_factory=_client) -> list[dict]:
    """Сообщения чата за период (позже since). Возвращает список {ts, sender, text}."""
    client = await client_factory()
    try:
        out = []
        async for m in client.iter_messages(target, limit=limit):
            mdate = m.date if m.date.tzinfo else m.date.replace(tzinfo=dt.timezone.utc)
            if mdate < since:
                break   # дальше только старее (итерация новых→старых)
            if getattr(m, "text", None):
                out.append({"ts": mdate.astimezone().strftime("%d.%m %H:%M"),
                            "sender": _sender_name(m), "text": m.text[:500]})
        out.reverse()
        return out
    finally:
        await client.disconnect()


async def collect_digest(groups: list[str], hours: int = 12,
                         *, reader=read_since) -> str:
    """Собирает сообщения из групп за последние N часов в один текст по разделам.
    Пустые/недоступные группы отмечаются, но не роняют сбор."""
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=max(1, hours))
    blocks = []
    for g in groups:
        try:
            msgs = await reader(g, since)
        except Exception as e:
            blocks.append(f"### {g}\n[не удалось прочитать: {type(e).__name__}]")
            continue
        blocks.append(f"### {g} ({len(msgs)} сообщ.)\n" +
                      (format_messages(msgs) if msgs else "нет новых сообщений"))
    return "\n\n".join(blocks) if blocks else "Группы для дайджеста не заданы."
