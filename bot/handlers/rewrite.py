import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InputMediaPhoto, Message

from ..config import ADMIN_IDS, CHANNELS
from ..keyboards import channel_picker_keyboard, preview_keyboard
from ..llm import LLMService
from ..photos import PhotoService
from ..pipeline import build_and_send_preview
from ..posting import as_photo_input, send_post
from ..storage import Storage

router = Router()
logger = logging.getLogger(__name__)


def is_allowed(user_id: int) -> bool:
    return not ADMIN_IDS or user_id in ADMIN_IDS


@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Привет! Я готовлю посты для каналов: переписываю текст, перевожу "
        "(если нужно) и подбираю фото.\n\n"
        "Как пользоваться (в личке или в группе, куда меня добавили):\n"
        "1. Перешли мне пост или ответь на него командой /rewrite\n"
        "   (или сразу: /rewrite текст новости)\n"
        "2. Выбери канал, для которого готовится пост\n"
        "3. Я пришлю превью с фото и кнопками\n"
        "4. Нажми «Опубликовать» — и пост уйдёт в выбранный канал"
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

    source_photo_bytes = None
    if source_message and source_message.photo:
        try:
            buf = await message.bot.download(source_message.photo[-1].file_id)
            source_photo_bytes = buf.read()
        except Exception:
            logger.exception("Не удалось скачать фото исходного поста для анализа")

    if len(CHANNELS) == 1:
        await message.reply(f"⏳ Готовлю пост для «{CHANNELS[0].label}»...")
        await build_and_send_preview(
            message.bot,
            llm,
            photos,
            storage,
            CHANNELS[0],
            source_text,
            source_photo_bytes,
            message.chat.id,
        )
        return

    selection = storage.create_selection(
        text=source_text,
        photo_bytes=source_photo_bytes,
        chat_id=message.chat.id,
        requester_id=message.from_user.id,
    )
    await message.reply(
        "Для какого канала готовим пост?",
        reply_markup=channel_picker_keyboard(selection.id, CHANNELS),
    )


@router.callback_query(F.data.startswith("pick:"))
async def cb_pick_channel(
    callback: CallbackQuery, llm: LLMService, photos: PhotoService, storage: Storage, bot: Bot
):
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return

    _, sid, idx_str = callback.data.split(":", 2)
    selection = storage.get_selection(sid)
    if not selection:
        await callback.answer("Это меню уже неактуально.", show_alert=True)
        return

    idx = int(idx_str)
    if idx >= len(CHANNELS):
        await callback.answer("Канал не найден.", show_alert=True)
        return

    channel = CHANNELS[idx]
    storage.delete_selection(sid)
    await callback.message.edit_text(f"⏳ Готовлю пост для «{channel.label}»...")

    await build_and_send_preview(
        bot, llm, photos, storage, channel, selection.text, selection.photo_bytes, selection.chat_id
    )
    await callback.answer()


@router.callback_query(F.data.startswith("pickcancel:"))
async def cb_pick_cancel(callback: CallbackQuery, storage: Storage):
    sid = callback.data.split(":", 1)[1]
    storage.delete_selection(sid)
    await callback.message.edit_text("Отменено.")
    await callback.answer()


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
        await send_post(bot, item.target_channel_id, item.text, photo=photo)
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
