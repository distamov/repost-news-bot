import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InputMediaPhoto, Message

from ..config import ADMIN_IDS, CHANNEL_SIGNATURE, TARGET_CHANNEL_ID
from ..formatting import build_post_html
from ..keyboards import preview_keyboard
from ..llm import LLMService
from ..photos import PhotoService
from ..posting import as_photo_input, send_post
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

    source_message = message.reply_to_message
    source_text = command.args
    if not source_text and source_message:
        source_text = source_message.text or source_message.caption
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

    text = build_post_html(rewritten, CHANNEL_SIGNATURE)

    try:
        photo_urls = await photos.search(keywords)
    except Exception:
        logger.exception("Photo search failed")
        photo_urls = []

    # Фото из исходного поста ставим первым — оно точно совпадает по смыслу,
    # Pexels-варианты остаются как запасные (кнопка «Другое фото»).
    if source_message and source_message.photo:
        photo_urls = [source_message.photo[-1].file_id, *photo_urls]

    item = storage.create(
        text=text,
        keywords=keywords,
        photo_urls=photo_urls,
        chat_id=message.chat.id,
        requester_id=message.from_user.id,
    )

    await status.delete()

    photo = photo_urls[0] if photo_urls else None
    if not photo:
        await message.answer("⚠️ Фото не найдено, будет опубликован только текст.")

    photo_message_id, text_message_id, combined = await send_post(
        message.bot, message.chat.id, text, photo=photo, reply_markup=preview_keyboard(item.id)
    )
    item.photo_message_id = photo_message_id
    item.text_message_id = text_message_id
    item.combined = combined


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

    photo = item.photo_urls[item.photo_index] if item.photo_urls else None
    try:
        await send_post(bot, TARGET_CHANNEL_ID, item.text, photo=photo)
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
    new_photo = as_photo_input(item.photo_urls[item.photo_index])

    if item.photo_message_id:
        try:
            if item.combined:
                media = InputMediaPhoto(media=new_photo, caption=item.text)
                await bot.edit_message_media(
                    chat_id=item.chat_id,
                    message_id=item.photo_message_id,
                    media=media,
                    reply_markup=preview_keyboard(item.id),
                )
            else:
                media = InputMediaPhoto(media=new_photo)
                await bot.edit_message_media(
                    chat_id=item.chat_id, message_id=item.photo_message_id, media=media
                )
        except Exception:
            logger.exception("Failed to update preview photo")

    await callback.answer("Фото обновлено.")
