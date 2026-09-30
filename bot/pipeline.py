import logging

from aiogram import Bot

from .channels_store import ChannelConfig
from .config import ADMIN_IDS
from .formatting import build_post_html
from .keyboards import preview_keyboard
from .llm import LLMService
from .photos import PhotoService
from .posting import send_post
from .storage import MediaItem, Storage

logger = logging.getLogger(__name__)

# Если рерайт подряд ломается столько раз — разово шлём алерт админам
# (например кончилась квота Gemini или ключ стал недействителен).
FAILURE_ALERT_THRESHOLD = 3
_consecutive_failures = 0
_failure_alert_sent = False


async def _alert_admins(bot: Bot, text: str):
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            logger.exception("Не удалось отправить алерт админу %s", admin_id)


async def build_and_send_preview(
    bot: Bot,
    llm: LLMService,
    photos: PhotoService,
    storage: Storage,
    channel: ChannelConfig,
    source_text: str,
    photo_bytes,
    chat_id,
    original_media: list[MediaItem] | None = None,
):
    """Переписывает текст под язык конкретного канала, подбирает фото и
    присылает превью с кнопками модерации в chat_id. Если у исходного
    поста было своё фото/видео (original_media), оно добавляется последним
    вариантом — до него можно долистать кнопкой «Другое фото»."""
    global _consecutive_failures, _failure_alert_sent
    original_media = original_media or []

    try:
        rewritten, keywords, emoji_choice = await llm.rewrite_and_translate(
            source_text, photo_bytes, language=channel.language
        )
    except Exception:
        logger.exception("LLM rewrite failed")
        _consecutive_failures += 1
        await bot.send_message(chat_id, "Не получилось переписать текст. Попробуй ещё раз позже.")
        if _consecutive_failures >= FAILURE_ALERT_THRESHOLD and not _failure_alert_sent:
            _failure_alert_sent = True
            await _alert_admins(
                bot,
                f"⚠️ Рерайт не проходит уже {_consecutive_failures} раз(а) подряд — "
                "похоже, сломался Gemini API (квота/ключ). Проверь логи на сервере.",
            )
        return

    _consecutive_failures = 0
    _failure_alert_sent = False

    text = build_post_html(rewritten, channel.signature, emoji_choice, source_text)

    try:
        photo_urls = await photos.search(keywords)
    except Exception:
        logger.exception("Photo search failed")
        photo_urls = []

    media_options = [[MediaItem("photo", url)] for url in photo_urls]
    if original_media:
        media_options.append(original_media)

    item = storage.create(
        text=text,
        keywords=keywords,
        media_options=media_options,
        chat_id=chat_id,
        requester_id=0,
        target_channel_id=channel.id,
        has_original=bool(original_media),
        signature=channel.signature,
    )

    media = media_options[0] if media_options else []
    if not media:
        await bot.send_message(chat_id, "⚠️ Медиа не найдено, будет опубликован только текст.")

    media_message_ids, text_message_id = await send_post(
        bot, chat_id, text, media=media, reply_markup=preview_keyboard(item.id, has_original=item.has_original)
    )
    item.media_message_ids = media_message_ids
    item.text_message_id = text_message_id


async def resend_preview(bot: Bot, storage: Storage, item, media: list[MediaItem]):
    """Пересылает превью с другим медиа взамен старого (нужно, когда нельзя
    просто отредактировать медиа на месте — например переключение на
    альбом или обратно)."""
    ids_to_delete = set(item.media_message_ids)
    if item.text_message_id:
        ids_to_delete.add(item.text_message_id)
    for mid in ids_to_delete:
        try:
            await bot.delete_message(item.chat_id, mid)
        except Exception:
            pass

    media_message_ids, text_message_id = await send_post(
        bot, item.chat_id, item.text, media=media, reply_markup=preview_keyboard(item.id, has_original=item.has_original)
    )
    item.media_message_ids = media_message_ids
    item.text_message_id = text_message_id
