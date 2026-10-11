"""Получить Telethon session-строку для аккаунта (для TELEGRAM_SESSION или
TELEGRAM_EXTRA_SESSIONS в .env).

Запуск на сервере (интерактивно, нужен доступ к терминалу):
    cd /root/repost-news-bot
    source .venv/bin/activate
    python scripts/generate_session.py

Спросит API ID, API Hash (те же, что уже в .env), номер телефона и код
подтверждения — для каждого аккаунта свой номер телефона. Выведет
готовую session-строку, которую нужно добавить в .env.
"""

import asyncio

from telethon import TelegramClient
from telethon.sessions import StringSession


async def main():
    api_id = int(input("API ID: ").strip())
    api_hash = input("API Hash: ").strip()

    async with TelegramClient(StringSession(), api_id, api_hash) as client:
        me = await client.get_me()
        print(f"\nВошёл как: {me.first_name} (@{me.username or me.id})")
        print("\nSession-строка (сохрани в .env):\n")
        print(client.session.save())


if __name__ == "__main__":
    asyncio.run(main())
