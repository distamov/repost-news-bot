import asyncio
import logging

from aiogram import Bot, Dispatcher

from . import config
from .handlers.rewrite import router
from .llm import LLMService
from .photos import PhotoService
from .storage import Storage


async def main():
    logging.basicConfig(level=logging.INFO)

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    dp["llm"] = LLMService(config.ANTHROPIC_API_KEY, config.ANTHROPIC_MODEL)
    dp["photos"] = PhotoService(config.PEXELS_API_KEY)
    dp["storage"] = Storage()

    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        await dp["photos"].close()


if __name__ == "__main__":
    asyncio.run(main())
