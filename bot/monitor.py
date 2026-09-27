import html
import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest

from .channels_store import ChannelStore
from .config import ADMIN_IDS, MODERATION_CHAT_ID
from .dedup import Deduplicator
from .keyboards import channel_picker_keyboard
from .llm import LLMService
from .photos import PhotoService
from .pipeline import build_and_send_preview
from .sources_store import SourceStore
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
        channels: ChannelStore,
        sources: SourceStore,
    ):
        self.client = TelegramClient(StringSession(session), api_id, api_hash)
        self.bot = bot
        self.llm = llm
        self.photos = photos
        self.storage = storage
        self.channels = channels
        self.sources = sources
        self._targets = [MODERATION_CHAT_ID] if MODERATION_CHAT_ID else list(ADMIN_IDS)
        self._dedup = Deduplicator()

    async def start(self):
        await self.client.start()

        for source in self.sources.all():
            try:
                await self.client(JoinChannelRequest(source.id))
            except Exception:
                logger.debug("Не удалось вступить в %s (возможно, уже там)", source.id, exc_info=True)

        try:
            await self.client.catch_up()
        except Exception:
            logger.debug("catch_up() недоступен в этой версии Telethon, пропускаю", exc_info=True)

        # Без chats=... — список источников теперь может меняться на лету
        # через /sources, без перезапуска; фильтруем прямо в обработчиках.
        self.client.add_event_handler(self._on_new_message, events.NewMessage())
        self.client.add_event_handler(self._on_album, events.Album())
        logger.info(
            "Мониторинг каналов запущен: %s",
            ", ".join(s.id for s in self.sources.all()) or "(источники пока не заданы)",
        )
        await self.client.run_until_disconnected()

    async def _on_new_message(self, event):
        if event.message.grouped_id:
            return  # альбомы обрабатываются отдельно, в _on_album

        chat = await event.get_chat()
        if not self.sources.matches(chat):
            return

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

        await self._handle_post(chat, text, original_media)

    async def _on_album(self, event):
        chat = await event.get_chat()
        if not self.sources.matches(chat):
            return

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

        await self._handle_post(chat, text, original_media)

    async def _handle_post(self, chat, text, original_media):
        source_name = getattr(chat, "title", None) or getattr(chat, "username", None) or "источник"

        if not self._targets:
            logger.warning("Нет получателей для модерации: заполни ADMIN_IDS или MODERATION_CHAT_ID")
            return

        duplicate_source = self._dedup.find_duplicate(text)

        source_photo_bytes = next(
            (item.data for item in original_media if item.kind == "photo"), None
        )

        for target in self._targets:
            selection = self.storage.create_selection(
                text=text,
                photo_bytes=source_photo_bytes,
                original_media=original_media,
                chat_id=target,
                requester_id=0,
            )

            if duplicate_source:
                await self._send_duplicate_prompt(target, source_name, duplicate_source, selection.id)
                continue

            header = f"📡 Новый пост из «{html.escape(source_name)}»"
            all_channels = self.channels.all()

            if len(all_channels) == 1:
                self.storage.delete_selection(selection.id)
                try:
                    await self.bot.send_message(
                        target, f"{header}\n⏳ Готовлю пост для «{all_channels[0].label}»..."
                    )
                except Exception:
                    logger.exception("Не удалось отправить сообщение в %s", target)
                    continue
                await build_and_send_preview(
                    self.bot,
                    self.llm,
                    self.photos,
                    self.storage,
                    all_channels[0],
                    text,
                    source_photo_bytes,
                    target,
                    original_media=original_media,
                )
                continue

            try:
                await self.bot.send_message(
                    target,
                    f"{header}\nДля какого канала готовим пост?",
                    reply_markup=channel_picker_keyboard(selection.id, all_channels),
                )
            except Exception:
                logger.exception("Не удалось отправить меню выбора канала в %s", target)
                self.storage.delete_selection(selection.id)

        if not duplicate_source:
            self._dedup.add(text, source_name)

    async def _send_duplicate_prompt(self, target, source_name, duplicate_source, selection_id):
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="▶️ Обработать", callback_data=f"dupok:{selection_id}"),
                    InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"dupskip:{selection_id}"),
                ]
            ]
        )
        try:
            await self.bot.send_message(
                target,
                f"📡 Пост из «{html.escape(source_name)}» очень похож на уже обработанный "
                f"ранее (из «{html.escape(duplicate_source)}»). Обработать всё равно?",
                reply_markup=keyboard,
            )
        except Exception:
            logger.exception("Не удалось отправить запрос про дубликат в %s", target)
