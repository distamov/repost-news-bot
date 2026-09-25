import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InputMediaPhoto, Message

from ..config import ADMIN_IDS, TARGET_CHANNEL_ID
from ..keyboards import preview_keyboard
from ..llm import LLMService
from ..photos import PhotoService
from ..storage import Storage

router = Router()
logger = logging.getLogger(__name__)


def is_allowed(user_id: int) -> bool:
    return not ADMIN_IDS or user_id in ADMIN_IDS


@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Привет! Я готовлю посты для канала: переписываю текст, перевожу на "
        "узбекский (кириллица) и подбираю фото.\n\n"
        "Как пользоваться (в личке или в группе, куда меня добавили):\n"
        "1. Перешли мне пост или ответь на него командой /rewrite\n"
        "   (или сразу: /rewrite текст новости)\n"
        "2. Я пришлю превью с фото и кнопками\n"
        "3. Нажми «Опубликовать» — и пост уйдёт в канал"
    )


@router.message(Command("rewrite"))
async def cmd_rewrite(
    message: Message,
    command: CommandObject,
    llm: LLMService,
    photos: PhotoService,
    storage: Storage,
):
    if not is_allowed(message.from_user.id):
        await message.reply("У вас нет прав использовать этого бота.")
        return

    source_text = command.args
    if not source_text and message.reply_to_message:
        source_text = message.reply_to_message.text or message.reply_to_message.caption
    if not source_text:
        await message.reply(
            "Пришли текст после команды или ответь этой командой на пост с текстом:\n"
            "/rewrite <текст новости>"
        )
        return

    status = await message.reply("⏳ Переписываю и перевожу...")

    try:
        rewritten, keywords = await llm.rewrite_and_translate(source_text)
    except Exception:
        logger.exception("LLM rewrite failed")
        await status.edit_text("Не получилось переписать текст. Попробуй ещё раз позже.")
        return

    try:
        photo_urls = await photos.search(keywords)
    except Exception:
        logger.exception("Photo search failed")
        photo_urls = []

    item = storage.create(
        text=rewritten,
        keywords=keywords,
        photo_urls=photo_urls,
        chat_id=message.chat.id,
        requester_id=message.from_user.id,
    )

    await status.delete()

    if photo_urls:
        photo_msg = await message.answer_photo(photo_urls[0])
        item.photo_message_id = photo_msg.message_id
    else:
        await message.answer("⚠️ Фото не найдено, будет опубликован только текст.")

    text_msg = await message.answer(rewritten, reply_markup=preview_keyboard(item.id))
    item.text_message_id = text_msg.message_id


async def publish_to_channel(bot: Bot, text: str, photo_url: str | None):
    if photo_url:
        if len(text) <= 1024:
            await bot.send_photo(TARGET_CHANNEL_ID, photo_url, caption=text)
        else:
            await bot.send_photo(TARGET_CHANNEL_ID, photo_url)
            await bot.send_message(TARGET_CHANNEL_ID, text)
    else:
        await bot.send_message(TARGET_CHANNEL_ID, text)


@router.callback_query(F.data.startswith("approve:"))
async def cb_approve(callback: CallbackQuery, storage: Storage, bot: Bot):
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return

    pid = callback.data.split(":", 1)[1]
    item = storage.get(pid)
    if not item:
        await callback.answer("Этот пост уже обработан.", show_alert=True)
        return

    photo_url = item.photo_urls[item.photo_index] if item.photo_urls else None
    try:
        await publish_to_channel(bot, item.text, photo_url)
    except Exception:
        logger.exception("Publish failed")
        await callback.answer("Ошибка публикации, смотри логи.", show_alert=True)
        return

    storage.delete(pid)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.reply("✅ Опубликовано в канал.")
    await callback.answer()


@router.callback_query(F.data.startswith("reject:"))
async def cb_reject(callback: CallbackQuery, storage: Storage):
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return

    pid = callback.data.split(":", 1)[1]
    storage.delete(pid)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.reply("❌ Отклонено.")
    await callback.answer()


@router.callback_query(F.data.startswith("newphoto:"))
async def cb_newphoto(callback: CallbackQuery, storage: Storage, bot: Bot):
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return

    pid = callback.data.split(":", 1)[1]
    item = storage.get(pid)
    if not item:
        await callback.answer("Этот пост уже обработан.", show_alert=True)
        return
    if not item.photo_urls:
        await callback.answer("Других фото не найдено.", show_alert=True)
        return

    item.photo_index = (item.photo_index + 1) % len(item.photo_urls)
    new_url = item.photo_urls[item.photo_index]

    if item.photo_message_id:
        try:
            await bot.edit_message_media(
                chat_id=item.chat_id,
                message_id=item.photo_message_id,
                media=InputMediaPhoto(media=new_url),
            )
        except Exception:
            logger.exception("Failed to update preview photo")

    await callback.answer("Фото обновлено.")
