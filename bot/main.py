import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from . import config
from .channels_store import ChannelStore
from .handlers.channels import router as channels_router
from .handlers.rewrite import router as rewrite_router
from .handlers.scheduled import router as scheduled_router
from .handlers.sources import router as sources_router
from .health import run_health_server
from .llm import LLMService
from .monitor import ChannelMonitor
from .photos import PhotoService
from .scheduled_store import ScheduledStore
from .scheduler import run_scheduler
from .sources_store import SourceStore
from .storage import Storage

logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand(command="start", description="Как пользоваться ботом"),
    BotCommand(command="rewrite", description="Переписать пост (ответом на сообщение)"),
    BotCommand(command="channels", description="Каналы публикации: добавить/изменить"),
    BotCommand(command="sources", description="Каналы-источники для автомониторинга"),
    BotCommand(command="scheduled", description="Отложенные посты: список и управление"),
]


async def _notify_admins(bot: Bot, text: str):
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            logger.exception("Не удалось уведомить админа %s", admin_id)


async def main():
    logging.basicConfig(level=logging.INFO)

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(channels_router)
    dp.include_router(sources_router)
    dp.include_router(scheduled_router)
    dp.include_router(rewrite_router)

    llm = LLMService(config.GEMINI_API_KEY, config.GEMINI_MODEL)
    photos = PhotoService(config.PEXELS_API_KEY, config.PIXABAY_API_KEY)
    storage = Storage()
    channels = ChannelStore()
    sources = SourceStore()
    scheduled = ScheduledStore()

    monitor = None
    telethon_client = None
    if config.MONITOR_ENABLED:
        monitor = ChannelMonitor(
            api_id=config.TELEGRAM_API_ID,
            api_hash=config.TELEGRAM_API_HASH,
            session=config.TELEGRAM_SESSION,
            bot=bot,
            llm=llm,
            photos=photos,
            storage=storage,
            channels=channels,
            sources=sources,
        )
        telethon_client = monitor.client
    else:
        logger.warning(
            "Автомониторинг каналов выключен: заполни TELEGRAM_API_ID, "
            "TELEGRAM_API_HASH и TELEGRAM_SESSION в .env"
        )

    dp["llm"] = llm
    dp["photos"] = photos
    dp["storage"] = storage
    dp["channels"] = channels
    dp["sources"] = sources
    dp["scheduled"] = scheduled
    dp["monitor"] = monitor
    dp["telethon_client"] = telethon_client

    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_my_commands(BOT_COMMANDS)
    await _notify_admins(bot, "✅ Бот запущен и работает")

    tasks = [dp.start_polling(bot), run_scheduler(bot, scheduled, telethon_client)]

    if config.PORT:
        tasks.append(run_health_server(int(config.PORT)))

    if monitor:
        tasks.append(monitor.start())

    try:
        await asyncio.gather(*tasks)
    except Exception as e:
        logger.exception("Бот упал")
        await _notify_admins(bot, f"🔴 Бот упал с ошибкой: {e}\nПроверь логи на сервере.")
        raise
    finally:
        await photos.close()
        await llm.close()


if __name__ == "__main__":
    asyncio.run(main())
