"""
Одноразовая утилита для получения TELEGRAM_SESSION (Telethon StringSession).

Логин в Telegram делается в два шага, потому что код подтверждения
приходит в само приложение Telegram и должен быть введён отдельно:

  1) python scripts/telethon_login.py request <API_ID> <API_HASH> <телефон>
     Отправит код подтверждения на телефон (в Telegram-приложение или SMS).

  2) python scripts/telethon_login.py confirm <API_ID> <API_HASH> <телефон> <код> [пароль_2FA]
     Завершит вход и напечатает готовую строку — её нужно вставить в .env
     как TELEGRAM_SESSION. Пароль нужен только если включена
     двухфакторная аутентификация.

Телефон указывать в международном формате, например +998901234567.
"""
import asyncio
import json
import sys
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

STATE_FILE = Path(__file__).parent / ".telethon_login_state.json"


async def request_code(api_id: int, api_hash: str, phone: str):
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    sent = await client.send_code_request(phone)
    STATE_FILE.write_text(
        json.dumps(
            {"phone_code_hash": sent.phone_code_hash, "session": client.session.save()}
        )
    )
    await client.disconnect()
    print("Код отправлен. Запусти: confirm <API_ID> <API_HASH> <телефон> <код>")


async def confirm_code(api_id: int, api_hash: str, phone: str, code: str, password: str | None):
    state = json.loads(STATE_FILE.read_text())
    client = TelegramClient(StringSession(state["session"]), api_id, api_hash)
    await client.connect()

    try:
        await client.sign_in(phone, code, phone_code_hash=state["phone_code_hash"])
    except SessionPasswordNeededError:
        if not password:
            print("Включена двухфакторная аутентификация — добавь пароль последним аргументом.")
            await client.disconnect()
            sys.exit(1)
        await client.sign_in(password=password)

    session_string = client.session.save()
    await client.disconnect()
    STATE_FILE.unlink(missing_ok=True)

    print("Готово! Вставь это значение в .env как TELEGRAM_SESSION:")
    print(session_string)


def main():
    if len(sys.argv) < 5:
        print(__doc__)
        sys.exit(1)

    action = sys.argv[1]
    api_id = int(sys.argv[2])
    api_hash = sys.argv[3]
    phone = sys.argv[4]

    if action == "request":
        asyncio.run(request_code(api_id, api_hash, phone))
    elif action == "confirm":
        if len(sys.argv) < 6:
            print(__doc__)
            sys.exit(1)
        code = sys.argv[5]
        password = sys.argv[6] if len(sys.argv) > 6 else None
        asyncio.run(confirm_code(api_id, api_hash, phone, code, password))
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
