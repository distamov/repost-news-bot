import html
import logging

from aiogram import Bot
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest

from .config import MODERATION_CHAT_ID, ADMIN_IDS, CHANNEL_SIGNATURE, SOURCE_CHANNELS
from .dedup import Deduplicator
from .formatting import build_post_html
from .keyboards import preview_keyboard
from .llm import LLMService
from .photos import PhotoService
from .posting import send_post
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

        try:
            rewritten, keywords = await self.llm.rewrite_and_translate(text)
        except Exception:
            logger.exception("Не удалось переписать пост из %s", source_name)
            return

        formatted = build_post_html(rewritten, CHANNEL_SIGNATURE)

        try:
            photo_urls = await self.photos.search(keywords)
        except Exception:
            logger.exception("Не удалось найти фото")
            photo_urls = []

        # Фото из исходного поста ставим первым — оно точно совпадает по
        # смыслу, Pexels-варианты остаются как запасные.
        if event.message.photo:
            try:
                source_photo = await self.client.download_media(event.message, file=bytes)
                if source_photo:
                    photo_urls = [source_photo, *photo_urls]
            except Exception:
                logger.exception("Не удалось скачать фото из исходного поста")

        for target in self._targets:
            await self._send_preview(target, source_name, formatted, keywords, photo_urls)

    async def _send_preview(self, chat_id, source_name, text, keywords, photo_urls):
        item = self.storage.create(
            text=text,
            keywords=keywords,
            photo_urls=photo_urls,
            chat_id=chat_id,
            requester_id=0,
        )

        try:
            await self.bot.send_message(chat_id, f"📡 Новый пост из «{html.escape(source_name)}»")

            photo = photo_urls[0] if photo_urls else None
            if not photo:
                await self.bot.send_message(chat_id, "⚠️ Фото не найдено, будет опубликован только текст.")

            photo_message_id, text_message_id, combined = await send_post(
                self.bot, chat_id, text, photo=photo, reply_markup=preview_keyboard(item.id)
            )
            item.photo_message_id = photo_message_id
            item.text_message_id = text_message_id
            item.combined = combined
        except Exception:
            logger.exception("Не удалось отправить превью в чат %s", chat_id)
            self.storage.delete(item.id)
