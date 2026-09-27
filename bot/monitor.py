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
from .storage import MediaItem, Storage

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

        self.client.add_event_handler(self._on_new_message, events.NewMessage(chats=SOURCE_CHANNELS))
        self.client.add_event_handler(self._on_album, events.Album(chats=SOURCE_CHANNELS))
        logger.info("Мониторинг каналов запущен: %s", ", ".join(SOURCE_CHANNELS))
        await self.client.run_until_disconnected()

    async def _on_new_message(self, event):
        if event.message.grouped_id:
            return  # альбомы обрабатываются отдельно, в _on_album

        text = (event.raw_text or "").strip()
        if len(text) < MIN_TEXT_LENGTH:
            return

        original_media: list[MediaItem] = []
        try:
            if event.message.photo:
                data = await self.client.download_media(event.message, file=bytes)
                if data:
                    original_media.append(MediaItem("photo", data))
            elif event.message.video:
                data = await self.client.download_media(event.message, file=bytes)
                if data:
                    original_media.append(MediaItem("video", data))
        except Exception:
            logger.exception("Не удалось скачать медиа исходного поста")

        await self._handle_post(event, text, original_media)

    async def _on_album(self, event):
        text = (event.text or event.raw_text or "").strip()
        if len(text) < MIN_TEXT_LENGTH:
            return

        original_media: list[MediaItem] = []
        for msg in event.messages:
            try:
                data = await self.client.download_media(msg, file=bytes)
            except Exception:
                logger.exception("Не удалось скачать элемент альбома")
                continue
            if not data:
                continue
            if msg.photo:
                original_media.append(MediaItem("photo", data))
            elif msg.video:
                original_media.append(MediaItem("video", data))

        await self._handle_post(event, text, original_media)

    async def _handle_post(self, event, text, original_media):
        chat = await event.get_chat()
        source_name = getattr(chat, "title", None) or getattr(chat, "username", None) or "источник"

        if self._dedup.is_duplicate(text):
            logger.info("Дубликат новости из %s, пропускаю", source_name)
            return

        logger.info(
            "Новый пост из %s (%s символов, %s медиа)", source_name, len(text), len(original_media)
        )

        if not self._targets:
            logger.warning("Нет получателей для модерации: заполни ADMIN_IDS или MODERATION_CHAT_ID")
            return

        source_photo_bytes = next(
            (item.data for item in original_media if item.kind == "photo"), None
        )

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
                    self.bot,
                    self.llm,
                    self.photos,
                    self.storage,
                    CHANNELS[0],
                    text,
                    source_photo_bytes,
                    target,
                    original_media=original_media,
                )
                continue

            selection = self.storage.create_selection(
                text=text,
                photo_bytes=source_photo_bytes,
                original_media=original_media,
                chat_id=target,
                requester_id=0,
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
