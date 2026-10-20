import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from telethon import TelegramClient
from telethon.sessions import StringSession

from . import config
from .admins_store import AdminStore
from .channels_store import ChannelStore
from .handlers.admins import router as admins_router
from .handlers.cache import router as cache_router
from .handlers.channels import router as channels_router
from .handlers.rewrite import init_admin_store, router as rewrite_router
from .handlers.scheduled import router as scheduled_router
from .handlers.sources import router as sources_router
from .health import run_health_server
from .llm import LLMService
from .monitor import ChannelMonitor
from .photos import PhotoService
from .pipeline import init_admin_store as init_pipeline_admin_store
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
    BotCommand(command="admins", description="Управление админами (только супер-админ)"),
    BotCommand(command="clearcache", description="Очистить неразобранные превью и их фото/видео"),
]


async def _notify_admins(bot: Bot, text: str, admins: AdminStore):
    for admin_id in admins.ids():
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
    dp.include_router(admins_router)
    dp.include_router(cache_router)
    dp.include_router(channels_router)
    dp.include_router(sources_router)
    dp.include_router(scheduled_router)
    dp.include_router(rewrite_router)

    admins = AdminStore()
    init_admin_store(admins)
    init_pipeline_admin_store(admins)
    default_owner_id = admins.ids()[0] if admins.ids() else 0

    llm = LLMService(config.GEMINI_API_KEY, config.GEMINI_MODEL, base_url=config.GEMINI_BASE_URL)
    photos = PhotoService(config.PEXELS_API_KEY, config.PIXABAY_API_KEY)
    storage = Storage()
    channels = ChannelStore(default_owner_id=default_owner_id)
    sources = SourceStore(default_owner_id=default_owner_id)
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

    extra_reaction_clients = []
    for session_str in config.TELEGRAM_EXTRA_SESSIONS:
        client = TelegramClient(
            StringSession(session_str), config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH
        )
        try:
            await client.start()
            me = await client.get_me()
            logger.info(
                "Доп. аккаунт для реакций подключён: %s (@%s)", me.first_name, me.username
            )
            extra_reaction_clients.append(client)
        except Exception:
            logger.exception("Не удалось подключить дополнительный аккаунт для реакций")

    dp["llm"] = llm
    dp["photos"] = photos
    dp["storage"] = storage
    dp["channels"] = channels
    dp["sources"] = sources
    dp["scheduled"] = scheduled
    dp["admins"] = admins
    dp["monitor"] = monitor
    dp["telethon_client"] = telethon_client
    dp["extra_reaction_clients"] = extra_reaction_clients

    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_my_commands(BOT_COMMANDS)
    await _notify_admins(bot, "✅ Бот запущен и работает", admins)

    tasks = [
        dp.start_polling(bot),
        run_scheduler(bot, scheduled, telethon_client, extra_reaction_clients),
    ]

    if config.PORT:
        tasks.append(run_health_server(int(config.PORT)))

    if monitor:
        tasks.append(monitor.start())

    try:
        await asyncio.gather(*tasks)
    except Exception as e:
        logger.exception("Бот упал")
        await _notify_admins(bot, f"🔴 Бот упал с ошибкой: {e}\nПроверь логи на сервере.", admins)
        raise
    finally:
        await photos.close()
        await llm.close()
        for client in extra_reaction_clients:
            await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
