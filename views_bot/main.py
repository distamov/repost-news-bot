import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.types import BotCommand, Message

from . import config
from .panel import PanelError, PanelUnknownResult, SocProofPanel
from .store import OrderStore

logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand(command="start", description="Настройки накрутки и баланс"),
    BotCommand(command="balance", description="Баланс soc-proof"),
    BotCommand(command="last", description="Последние заказы и их статус"),
]

# Посты, у которых в канале есть счётчик просмотров. Служебные сообщения
# (закреп, смена названия/аватарки и т.п.) сюда не входят.
POST_CONTENT_TYPES = {
    "text", "photo", "video", "animation", "audio", "document", "voice",
    "video_note", "poll", "sticker", "story", "paid_media", "location",
    "venue", "contact", "dice",
}

router = Router()


class ViewsOrderer:
    def __init__(self, bot: Bot, panel: SocProofPanel, store: OrderStore):
        self.bot = bot
        self.panel = panel
        self.store = store
        self.rate: float | None = None  # ₽ за 1000, подтягивается из панели при старте
        self._albums: dict[str, list[int]] = {}
        self._album_tasks: dict[str, asyncio.Task] = {}

    @property
    def total(self) -> int:
        return config.QUANTITY * config.RUNS

    @property
    def cost(self) -> float | None:
        return self.total * self.rate / 1000 if self.rate else None

    def settings_text(self) -> str:
        cost = f", ~{self.cost:.2f} ₽ на пост" if self.cost else ""
        return (
            f"Услуга {config.SERVICE_ID}: {config.QUANTITY} × {config.RUNS} запусков "
            f"каждые {config.INTERVAL} мин = {self.total} просмотров{cost}"
        )

    async def load_rate(self) -> None:
        service = await self.panel.service(config.SERVICE_ID)
        self.rate = float(service["rate"])
        if not service.get("dripfeed"):
            logger.warning("У услуги %s в панели выключен drip-feed", config.SERVICE_ID)
        if not int(service["min"]) <= config.QUANTITY <= int(service["max"]):
            logger.warning(
                "VIEWS_QUANTITY=%s вне лимитов услуги (%s–%s)",
                config.QUANTITY, service["min"], service["max"],
            )

    async def notify(self, text: str) -> None:
        for admin_id in config.ADMIN_IDS:
            try:
                await self.bot.send_message(admin_id, text)
            except Exception:
                logger.exception("Не удалось уведомить админа %s (нажал ли он /start?)", admin_id)

    def add_album_item(self, channel: str, group_id: str, msg_id: int) -> None:
        """Альбом приходит отдельными сообщениями. Под альбомом Telegram
        показывает просмотры ПОСЛЕДНЕГО из них — на него и заказываем,
        когда пачка перестала приходить."""
        key = f"{channel}/album/{group_id}"
        self._albums.setdefault(key, []).append(msg_id)
        task = self._album_tasks.pop(key, None)
        if task:
            task.cancel()
        self._album_tasks[key] = asyncio.create_task(self._flush_album(channel, key))

    async def _flush_album(self, channel: str, key: str) -> None:
        await asyncio.sleep(config.ALBUM_WAIT_SECONDS)
        self._album_tasks.pop(key, None)
        await self.order(channel, key, max(self._albums.pop(key)))

    async def order(self, channel: str, key: str, msg_id: int) -> None:
        link = f"https://t.me/{channel}/{msg_id}"
        if not self.store.claim(key, link):
            logger.info("На %s просмотры уже заказаны — пропускаю", link)
            return

        try:
            order_id = await self.panel.add_dripfeed(
                config.SERVICE_ID, link, config.QUANTITY, config.RUNS, config.INTERVAL
            )
        except PanelError as e:
            logger.error("Заказ на %s не создан: %s", link, e)
            self.store.set_error(key, str(e))
            await self.notify(f"❌ Не удалось заказать просмотры на {link}\nПанель ответила: {e}")
            return
        except PanelUnknownResult as e:
            logger.error("Неизвестно, создан ли заказ на %s: %s", link, e)
            self.store.set_error(key, f"неизвестно: {e}")
            await self.notify(
                f"⚠️ Не знаю, создался ли заказ на {link} — панель не ответила ({e}).\n"
                "Проверь в «Заказах» на soc-proof и, если его нет, закажи вручную."
            )
            return

        self.store.set_order(key, order_id)
        logger.info("Заказ #%s на %s", order_id, link)

        text = (
            f"✅ {link}\nЗаказ #{order_id}: {config.QUANTITY} × {config.RUNS} "
            f"каждые {config.INTERVAL} мин = {self.total} просмотров"
        )
        if self.cost:
            text += f", ~{self.cost:.2f} ₽"
        try:
            balance = await self.panel.balance()
            text += f"\nБаланс: {balance:.2f} ₽"
            if self.cost:
                text += f" (хватит на {int(balance // self.cost)} постов)"
                if balance < self.cost:
                    text += "\n⚠️ На следующий пост уже не хватит — пополни баланс"
        except Exception:
            logger.exception("Не удалось получить баланс")
        await self.notify(text)


def _is_admin(message: Message) -> bool:
    return bool(message.from_user) and message.from_user.id in config.ADMIN_IDS


@router.channel_post()
async def on_channel_post(message: Message, orderer: ViewsOrderer):
    channel = (message.chat.username or "").lower()
    if channel not in config.CHANNELS:
        logger.info("Пост в канале %s (%s) — не из VIEWS_CHANNELS, пропускаю",
                    message.chat.id, channel or "без username")
        return
    if message.content_type not in POST_CONTENT_TYPES:
        return
    if message.media_group_id:
        orderer.add_album_item(channel, message.media_group_id, message.message_id)
        return
    await orderer.order(channel, f"{channel}/{message.message_id}", message.message_id)


@router.message(Command("start"), F.chat.type == "private")
async def cmd_start(message: Message, orderer: ViewsOrderer):
    if not _is_admin(message):
        return
    channels = ", ".join(f"@{c}" for c in sorted(config.CHANNELS))
    await message.answer(
        "👁 Накрутка просмотров на каждый новый пост\n\n"
        f"Каналы: {channels}\n{orderer.settings_text()}\n\n"
        "Альбом считается одним постом. Сюда приходят уведомления о каждом "
        "заказе и об ошибках.\n\n"
        "/balance — баланс soc-proof\n/last — последние заказы"
    )


@router.message(Command("balance"), F.chat.type == "private")
async def cmd_balance(message: Message, orderer: ViewsOrderer):
    if not _is_admin(message):
        return
    try:
        balance = await orderer.panel.balance()
    except Exception as e:
        await message.answer(f"Не удалось получить баланс: {e}")
        return
    text = f"Баланс: {balance:.2f} ₽"
    if orderer.cost:
        text += f"\nХватит на {int(balance // orderer.cost)} постов по ~{orderer.cost:.2f} ₽"
    await message.answer(text)


@router.message(Command("last"), F.chat.type == "private")
async def cmd_last(message: Message, orderer: ViewsOrderer):
    if not _is_admin(message):
        return
    items = orderer.store.last(10)
    if not items:
        await message.answer("Заказов пока не было.")
        return
    try:
        statuses = await orderer.panel.statuses([i["order"] for i in items if i["order"]])
    except Exception:
        logger.exception("Не удалось получить статусы заказов")
        statuses = {}
    lines = []
    for item in reversed(items):
        if not item["order"]:
            lines.append(f"• {item['link']} — ❌ {item['error'] or 'заказ не создан'}")
            continue
        st = statuses.get(str(item["order"]), {})
        status = st.get("status") or st.get("error") or "?"
        runs = f", запусков {st['runs']}/{config.RUNS}" if st.get("runs") else ""
        lines.append(f"• {item['link']} — #{item['order']}, {status}{runs}")
    await message.answer("\n".join(lines))


async def main():
    logging.basicConfig(level=logging.INFO)

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(link_preview_is_disabled=True),
    )
    panel = SocProofPanel(config.SOCPROOF_API_URL, config.SOCPROOF_API_KEY)
    orderer = ViewsOrderer(bot, panel, OrderStore(config.DATA_DIR))

    dp = Dispatcher()
    dp.include_router(router)
    dp["orderer"] = orderer

    try:
        await orderer.load_rate()
    except Exception:
        logger.exception("Не удалось получить цену услуги — уведомления будут без суммы")

    await bot.set_my_commands(BOT_COMMANDS)
    # Апдейты, пришедшие пока бот лежал, не выбрасываем: посты из них
    # тоже надо накрутить, а повторы отсекает OrderStore.
    await bot.delete_webhook(drop_pending_updates=False)
    await orderer.notify(f"✅ Бот просмотров запущен\n{orderer.settings_text()}")

    try:
        await dp.start_polling(bot, allowed_updates=["message", "channel_post"])
    finally:
        await panel.close()


if __name__ == "__main__":
    asyncio.run(main())
