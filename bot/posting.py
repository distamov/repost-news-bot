from aiogram import Bot
from aiogram.types import BufferedInputFile, InputMediaPhoto, InputMediaVideo

from .storage import MediaItem

CAPTION_LIMIT = 1024


def as_media_input(item: MediaItem):
    if isinstance(item.data, bytes):
        filename = "photo.jpg" if item.kind == "photo" else "video.mp4"
        return BufferedInputFile(item.data, filename=filename)
    return item.data


def _input_media(item: MediaItem, caption: str | None = None):
    cls = InputMediaPhoto if item.kind == "photo" else InputMediaVideo
    return cls(media=as_media_input(item), caption=caption)


async def send_post(bot: Bot, chat_id, text: str, media: list[MediaItem] | None = None, reply_markup=None):
    """Отправляет пост.

    Без медиа — просто текст. Один элемент — фото или видео с подписью
    одним сообщением (если влезает в лимит Telegram), иначе медиа и текст
    отдельно. Несколько элементов — альбом (sendMediaGroup); Telegram не
    даёт прикрепить кнопки к альбому, поэтому кнопки уходят отдельным
    сообщением следом.

    Возвращает (media_message_ids, text_message_id).
    """
    media = media or []

    if not media:
        msg = await bot.send_message(chat_id, text, reply_markup=reply_markup)
        return [], msg.message_id

    if len(media) == 1:
        item = media[0]
        sender = bot.send_photo if item.kind == "photo" else bot.send_video
        content = as_media_input(item)
        if len(text) <= CAPTION_LIMIT:
            msg = await sender(chat_id, content, caption=text, reply_markup=reply_markup)
            return [msg.message_id], msg.message_id
        media_msg = await sender(chat_id, content)
        text_msg = await bot.send_message(chat_id, text, reply_markup=reply_markup)
        return [media_msg.message_id], text_msg.message_id

    group = [
        _input_media(item, caption=text if i == 0 and len(text) <= CAPTION_LIMIT else None)
        for i, item in enumerate(media)
    ]
    messages = await bot.send_media_group(chat_id, media=group)
    media_message_ids = [m.message_id for m in messages]

    if len(text) <= CAPTION_LIMIT and reply_markup is None:
        # Текст уже поместился подписью к первому фото/видео — отдельное
        # сообщение не нужно (кнопок к альбому всё равно не прикрепить,
        # но при финальной публикации в канал кнопок и не будет).
        return media_message_ids, None

    extra_text = text if len(text) > CAPTION_LIMIT else "⬆️ Пост выше"
    text_msg = await bot.send_message(chat_id, extra_text, reply_markup=reply_markup)
    return media_message_ids, text_msg.message_id
