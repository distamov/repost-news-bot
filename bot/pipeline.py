import logging

from aiogram import Bot

from .config import ChannelConfig
from .formatting import build_post_html
from .keyboards import preview_keyboard
from .llm import LLMService
from .photos import PhotoService
from .posting import send_post
from .storage import Storage

logger = logging.getLogger(__name__)


async def build_and_send_preview(
    bot: Bot,
    llm: LLMService,
    photos: PhotoService,
    storage: Storage,
    channel: ChannelConfig,
    source_text: str,
    photo_bytes,
    chat_id,
):
    """Переписывает текст под язык конкретного канала, подбирает фото и
    присылает превью с кнопками модерации в chat_id."""
    try:
        rewritten, keywords = await llm.rewrite_and_translate(
            source_text, photo_bytes, language=channel.language
        )
    except Exception:
        logger.exception("LLM rewrite failed")
        await bot.send_message(chat_id, "Не получилось переписать текст. Попробуй ещё раз позже.")
        return

    text = build_post_html(rewritten, channel.signature)

    try:
        photo_urls = await photos.search(keywords)
    except Exception:
        logger.exception("Photo search failed")
        photo_urls = []

    item = storage.create(
        text=text,
        keywords=keywords,
        photo_urls=photo_urls,
        chat_id=chat_id,
        requester_id=0,
        target_channel_id=channel.id,
    )

    photo = photo_urls[0] if photo_urls else None
    if not photo:
        await bot.send_message(chat_id, "⚠️ Фото не найдено, будет опубликован только текст.")

    photo_message_id, text_message_id, combined = await send_post(
        bot, chat_id, text, photo=photo, reply_markup=preview_keyboard(item.id)
    )
    item.photo_message_id = photo_message_id
    item.text_message_id = text_message_id
    item.combined = combined
