import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from . import config
from .handlers.rewrite import router
from .health import run_health_server
from .llm import LLMService
from .monitor import ChannelMonitor
from .photos import PhotoService
from .storage import Storage

logger = logging.getLogger(__name__)


async def main():
    logging.basicConfig(level=logging.INFO)

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)

    llm = LLMService(config.GEMINI_API_KEY, config.GEMINI_MODEL)
    photos = PhotoService(config.PEXELS_API_KEY, config.PIXABAY_API_KEY)
    storage = Storage()

    dp["llm"] = llm
    dp["photos"] = photos
    dp["storage"] = storage

    await bot.delete_webhook(drop_pending_updates=True)

    tasks = [dp.start_polling(bot)]

    if config.PORT:
        tasks.append(run_health_server(int(config.PORT)))

    if config.MONITOR_ENABLED:
        monitor = ChannelMonitor(
            api_id=config.TELEGRAM_API_ID,
            api_hash=config.TELEGRAM_API_HASH,
            session=config.TELEGRAM_SESSION,
            bot=bot,
            llm=llm,
            photos=photos,
            storage=storage,
        )
        tasks.append(monitor.start())
    else:
        logger.warning(
            "Автомониторинг каналов выключен: заполни TELEGRAM_API_ID, "
            "TELEGRAM_API_HASH, TELEGRAM_SESSION и SOURCE_CHANNELS в .env"
        )

    try:
        await asyncio.gather(*tasks)
    finally:
        await photos.close()
        await llm.close()


if __name__ == "__main__":
    asyncio.run(main())
