import html
import logging

from aiogram import Bot
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest

from .config import ADMIN_IDS, CHANNELS, MODERATION_CHAT_ID, SOURCE_CHANNELS
from .dedup import Deduplicator
from .keyboards import channel_picker_keyboard
from .llm import LLMService
from .photos import PhotoService
from .pipeline import build_and_send_preview
from .storage import Storage

logger = logging.getLogger(__name__)

MIN_TEXT_LENGTH = 20


class ChannelMonitor:
    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session: str,
        bot: Bot,
        llm: LLMService,
        photos: PhotoService,
        storage: Storage,
    ):
        self.client = TelegramClient(StringSession(session), api_id, api_hash)
        self.bot = bot
        self.llm = llm
        self.photos = photos
        self.storage = storage
        self._targets = [MODERATION_CHAT_ID] if MODERATION_CHAT_ID else list(ADMIN_IDS)
        self._dedup = Deduplicator()

    async def start(self):
        await self.client.start()

        for channel in SOURCE_CHANNELS:
            try:
                await self.client(JoinChannelRequest(channel))
            except Exception:
                logger.debug("Не удалось вступить в %s (возможно, уже там)", channel, exc_info=True)

        try:
            await self.client.catch_up()
        except Exception:
            logger.debug("catch_up() недоступен в этой версии Telethon, пропускаю", exc_info=True)

        self.client.add_event_handler(
            self._on_new_message, events.NewMessage(chats=SOURCE_CHANNELS)
        )
        logger.info("Мониторинг каналов запущен: %s", ", ".join(SOURCE_CHANNELS))
        await self.client.run_until_disconnected()

    async def _on_new_message(self, event):
        text = (event.raw_text or "").strip()
        if len(text) < MIN_TEXT_LENGTH:
            return

        chat = await event.get_chat()
        source_name = getattr(chat, "title", None) or getattr(chat, "username", None) or "источник"

        if self._dedup.is_duplicate(text):
            logger.info("Дубликат новости из %s, пропускаю", source_name)
            return

        logger.info("Новый пост из %s (%s символов)", source_name, len(text))

        if not self._targets:
            logger.warning("Нет получателей для модерации: заполни ADMIN_IDS или MODERATION_CHAT_ID")
            return

        source_photo_bytes = None
        if event.message.photo:
            try:
                source_photo_bytes = await self.client.download_media(event.message, file=bytes)
            except Exception:
                logger.exception("Не удалось скачать фото исходного поста для анализа")

        header = f"📡 Новый пост из «{html.escape(source_name)}»"

        for target in self._targets:
            if len(CHANNELS) == 1:
                try:
                    await self.bot.send_message(
                        target, f"{header}\n⏳ Готовлю пост для «{CHANNELS[0].label}»..."
                    )
                except Exception:
                    logger.exception("Не удалось отправить сообщение в %s", target)
                    continue
                await build_and_send_preview(
                    self.bot, self.llm, self.photos, self.storage, CHANNELS[0], text, source_photo_bytes, target
                )
                continue

            selection = self.storage.create_selection(
                text=text, photo_bytes=source_photo_bytes, chat_id=target, requester_id=0
            )
            try:
                await self.bot.send_message(
                    target,
                    f"{header}\nДля какого канала готовим пост?",
                    reply_markup=channel_picker_keyboard(selection.id, CHANNELS),
                )
            except Exception:
                logger.exception("Не удалось отправить меню выбора канала в %s", target)
                self.storage.delete_selection(selection.id)
