from aiogram import Bot
from aiogram.types import BufferedInputFile

CAPTION_LIMIT = 1024


def as_photo_input(photo):
    """photo может быть: URL (str), Telegram file_id (str) или сырые байты
    картинки (bytes, например скачанные через Telethon) — приводим к тому,
    что понимает aiogram."""
    if isinstance(photo, bytes):
        return BufferedInputFile(photo, filename="photo.jpg")
    return photo


async def send_post(bot: Bot, chat_id, text: str, photo=None, reply_markup=None):
    """Отправляет пост: фото с подписью одним сообщением, если текст влезает
    в лимит подписи Telegram (1024 символа), иначе — фото и текст отдельно.

    Возвращает (photo_message_id, text_message_id, combined) — combined=True,
    если это одно сообщение (фото+подпись)."""
    if photo is None:
        msg = await bot.send_message(chat_id, text, reply_markup=reply_markup)
        return None, msg.message_id, False

    if len(text) <= CAPTION_LIMIT:
        msg = await bot.send_photo(
            chat_id, as_photo_input(photo), caption=text, reply_markup=reply_markup
        )
        return msg.message_id, msg.message_id, True

    photo_msg = await bot.send_photo(chat_id, as_photo_input(photo))
    text_msg = await bot.send_message(chat_id, text, reply_markup=reply_markup)
    return photo_msg.message_id, text_msg.message_id, False
