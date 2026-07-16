"""Вход в Telegram по QR-коду для чтения чатов ассистентом (Telethon, StringSession).

Запускать ЛОКАЛЬНО на машине с терминалом:
    TELEGRAM_API_ID=... TELEGRAM_API_HASH=... python -m scripts.telethon_login

Открой на телефоне: Telegram → Настройки → Устройства → Подключить устройство →
отсканируй QR. После входа скрипт печатает строку сессии — впиши её в .env:
    TELETHON_SESSION=<строка>

Сессия = доступ к твоему аккаунту (чтение чатов). Храни как секрет; .env в git не попадает.
"""
import asyncio
import base64
import os

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession


def _print_qr(token_bytes: bytes) -> None:
    url = "tg://login?token=" + base64.urlsafe_b64encode(token_bytes).decode().rstrip("=")
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except ImportError:
        print(f"\n(qrcode не установлен — открой ссылку с телефона)\n{url}\n")


async def main() -> None:
    api_id = int(os.getenv("TELEGRAM_API_ID") or 0)
    api_hash = os.getenv("TELEGRAM_API_HASH") or ""
    if not api_id or not api_hash:
        print("Задай TELEGRAM_API_ID и TELEGRAM_API_HASH (с my.telegram.org).")
        return

    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        print("\nОткрой: Telegram → Настройки → Устройства → Подключить устройство\n")
        while True:
            qr = await client.qr_login()
            _print_qr(qr.token)
            print("QR обновляется каждые ~25 сек — успей отсканировать.")
            try:
                await qr.wait(timeout=25)
                break
            except SessionPasswordNeededError:
                await client.sign_in(password=input("Пароль двухфакторной аутентификации: "))
                break
            except Exception:
                print("Обновляю QR...")

    me = await client.get_me()
    print(f"\n✅ Вход выполнен: {me.first_name} (@{me.username or me.phone})")
    print("\nВпиши в .env строку сессии (это секрет!):\n")
    print("TELETHON_SESSION=" + client.session.save())
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
