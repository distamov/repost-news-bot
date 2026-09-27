import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InputMediaPhoto, InputMediaVideo, Message

from ..config import ADMIN_IDS, CHANNELS
from ..keyboards import channel_picker_keyboard, preview_keyboard
from ..llm import LLMService
from ..photos import PhotoService
from ..pipeline import build_and_send_preview, resend_preview
from ..posting import as_media_input, send_post
from ..storage import MediaItem, Storage

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
        "3. Я пришлю превью с фото и кнопками (кнопкой «Другое фото» можно\n"
        "   долистать до оригинального фото/видео из исходного поста)\n"
        "4. Нажми «Опубликовать» — и пост уйдёт в выбранный канал"
    )


@router.message(F.media_group_id)
async def buffer_media_group(message: Message, storage: Storage):
    """Копит части альбома (несколько фото/видео одним постом), чтобы потом
    /rewrite мог забрать их все, а не только то сообщение, на которое
    ответили."""
    storage.buffer_group_item(message.media_group_id, message)


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
    group_messages = []
    if source_message and source_message.media_group_id:
        group_messages = storage.get_group(source_message.media_group_id) or [source_message]
        storage.delete_group(source_message.media_group_id)
    elif source_message:
        group_messages = [source_message]

    source_text = command.args
    if not source_text:
        for m in group_messages:
            candidate = m.text or m.caption
            if candidate:
                source_text = candidate
                break

    if not source_text:
        await message.reply(
            "Пришли текст после команды или ответь этой командой на пост с текстом:\n"
            "/rewrite <текст новости>"
        )
        return

    original_media: list[MediaItem] = []
    for m in group_messages:
        if m.photo:
            original_media.append(MediaItem("photo", m.photo[-1].file_id))
        elif m.video:
            original_media.append(MediaItem("video", m.video.file_id))

    source_photo_bytes = None
    first_photo = next((i for i in original_media if i.kind == "photo"), None)
    if first_photo:
        try:
            buf = await message.bot.download(first_photo.data)
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
            original_media=original_media,
        )
        return

    selection = storage.create_selection(
        text=source_text,
        photo_bytes=source_photo_bytes,
        original_media=original_media,
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
        bot,
        llm,
        photos,
        storage,
        channel,
        selection.text,
        selection.photo_bytes,
        selection.chat_id,
        original_media=selection.original_media,
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

    media = item.media_options[item.option_index] if item.media_options else []
    try:
        await send_post(bot, item.target_channel_id, item.text, media=media)
    except Exception:
        logger.exception("Publish failed")
        await callback.answer(
            "Ошибка публикации. Проверь, что бот — админ в этом канале с правом постить.",
            show_alert=True,
        )
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
    if not item.media_options:
        await callback.answer("Других вариантов не найдено.", show_alert=True)
        return

    item.option_index = (item.option_index + 1) % len(item.media_options)
    new_option = item.media_options[item.option_index]

    if len(item.media_message_ids) == 1 and len(new_option) == 1:
        new_item = new_option[0]
        has_caption = item.media_message_ids[0] == item.text_message_id
        media_cls = InputMediaPhoto if new_item.kind == "photo" else InputMediaVideo
        media = media_cls(media=as_media_input(new_item), caption=item.text if has_caption else None)
        try:
            await bot.edit_message_media(
                chat_id=item.chat_id,
                message_id=item.media_message_ids[0],
                media=media,
                reply_markup=preview_keyboard(item.id) if has_caption else None,
            )
        except Exception:
            logger.exception("Failed to update preview media")
    else:
        await resend_preview(bot, storage, item, new_option)

    await callback.answer("Медиа обновлено.")
