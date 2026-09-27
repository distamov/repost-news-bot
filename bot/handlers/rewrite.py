import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InputMediaPhoto, InputMediaVideo, Message

from ..channels_store import ChannelStore
from ..config import ADMIN_IDS
from ..formatting import build_post_html
from ..keyboards import channel_picker_keyboard, preview_keyboard
from ..llm import LLMService
from ..photos import PhotoService
from ..pipeline import build_and_send_preview, resend_preview
from ..posting import as_media_input, send_post
from ..storage import MediaItem, Storage

router = Router()
logger = logging.getLogger(__name__)

# Ждём ~1.5с после последнего элемента альбома, прежде чем считать его
# собранным полностью (Bot API не сообщает заранее размер альбома).
ALBUM_DEBOUNCE_SECONDS = 1.5
_pending_debounce: dict[str, asyncio.Task] = {}


class UploadForm(StatesGroup):
    waiting_media = State()


class EditTextForm(StatesGroup):
    waiting_text = State()


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
        "3. Я пришлю превью с фото и кнопками: «Другое фото» — пролистать\n"
        "   варианты, «Оригинал» — вернуть исходное фото/видео поста,\n"
        "   «Своё фото/видео» — прислать своё\n"
        "4. Нажми «Опубликовать» — и пост уйдёт в выбранный канал\n\n"
        "Каналами публикации управляй командой /channels"
    )


@router.message(UploadForm.waiting_media, F.photo | F.video)
async def receive_custom_media(message: Message, state: FSMContext, storage: Storage, bot: Bot):
    data = await state.get_data()
    pid = data.get("pid")

    if message.media_group_id:
        storage.buffer_group_item(message.media_group_id, message)
        _schedule_debounce_finalize(message.media_group_id, pid, state, storage, bot)
        return

    media_item = (
        MediaItem("photo", message.photo[-1].file_id)
        if message.photo
        else MediaItem("video", message.video.file_id)
    )
    await _finalize_custom_upload(bot, storage, storage.get(pid), [media_item])
    await state.clear()


@router.message(F.media_group_id)
async def buffer_media_group(message: Message, storage: Storage):
    """Копит части альбома (несколько фото/видео одним постом), чтобы потом
    /rewrite мог забрать их все, а не только то сообщение, на которое
    ответили."""
    storage.buffer_group_item(message.media_group_id, message)


def _schedule_debounce_finalize(group_id, pid, state: FSMContext, storage: Storage, bot: Bot):
    old_task = _pending_debounce.get(group_id)
    if old_task:
        old_task.cancel()

    async def _wait_and_finalize():
        await asyncio.sleep(ALBUM_DEBOUNCE_SECONDS)
        messages = storage.get_group(group_id)
        storage.delete_group(group_id)
        item = storage.get(pid)
        if item and messages:
            media_items = []
            for m in messages:
                if m.photo:
                    media_items.append(MediaItem("photo", m.photo[-1].file_id))
                elif m.video:
                    media_items.append(MediaItem("video", m.video.file_id))
            if media_items:
                await _finalize_custom_upload(bot, storage, item, media_items)
        await state.clear()
        _pending_debounce.pop(group_id, None)

    _pending_debounce[group_id] = asyncio.create_task(_wait_and_finalize())


async def _finalize_custom_upload(bot: Bot, storage: Storage, item, media_items: list[MediaItem]):
    if not item:
        return
    item.media_options.append(media_items)
    item.option_index = len(item.media_options) - 1
    await resend_preview(bot, storage, item, media_items)


@router.message(Command("rewrite"))
async def cmd_rewrite(
    message: Message,
    command: CommandObject,
    llm: LLMService,
    photos: PhotoService,
    storage: Storage,
    channels: ChannelStore,
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

    all_channels = channels.all()

    if len(all_channels) == 1:
        await message.reply(f"⏳ Готовлю пост для «{all_channels[0].label}»...")
        await build_and_send_preview(
            message.bot,
            llm,
            photos,
            storage,
            all_channels[0],
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
        reply_markup=channel_picker_keyboard(selection.id, all_channels),
    )


@router.callback_query(F.data.startswith("pick:"))
async def cb_pick_channel(
    callback: CallbackQuery,
    llm: LLMService,
    photos: PhotoService,
    storage: Storage,
    bot: Bot,
    channels: ChannelStore,
):
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return

    _, sid, idx_str = callback.data.split(":", 2)
    selection = storage.get_selection(sid)
    if not selection:
        await callback.answer("Это меню уже неактуально.", show_alert=True)
        return

    channel = channels.get(int(idx_str))
    if not channel:
        await callback.answer("Канал не найден.", show_alert=True)
        return

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


async def _apply_media_option(bot: Bot, storage: Storage, item, new_option: list[MediaItem]):
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
                reply_markup=preview_keyboard(item.id, has_original=item.has_original) if has_caption else None,
            )
        except Exception:
            logger.exception("Failed to update preview media")
    else:
        await resend_preview(bot, storage, item, new_option)


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
    await _apply_media_option(bot, storage, item, item.media_options[item.option_index])
    await callback.answer("Медиа обновлено.")


@router.callback_query(F.data.startswith("original:"))
async def cb_use_original(callback: CallbackQuery, storage: Storage, bot: Bot):
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return

    pid = callback.data.split(":", 1)[1]
    item = storage.get(pid)
    if not item or not item.has_original:
        await callback.answer("Оригинал недоступен.", show_alert=True)
        return

    item.option_index = len(item.media_options) - 1
    await _apply_media_option(bot, storage, item, item.media_options[item.option_index])
    await callback.answer("Оставляю оригинал.")


@router.callback_query(F.data.startswith("customupload:"))
async def cb_custom_upload(callback: CallbackQuery, state: FSMContext):
    pid = callback.data.split(":", 1)[1]
    await state.set_state(UploadForm.waiting_media)
    await state.update_data(pid=pid)
    await callback.message.reply(
        "Пришли фото или видео, которые хочешь использовать (можно несколько как альбом)."
    )
    await callback.answer()


@router.callback_query(F.data.startswith("edittext:"))
async def cb_edit_text(callback: CallbackQuery, storage: Storage, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return

    pid = callback.data.split(":", 1)[1]
    if not storage.get(pid):
        await callback.answer("Этот пост уже обработан.", show_alert=True)
        return

    await state.set_state(EditTextForm.waiting_text)
    await state.update_data(pid=pid)
    await callback.message.reply(
        "Пришли новый текст поста (первая строка — заголовок, дальше — сам текст; "
        "подпись канала подставится сама, писать её не нужно)."
    )
    await callback.answer()


@router.message(EditTextForm.waiting_text, F.text)
async def receive_edited_text(message: Message, state: FSMContext, storage: Storage, bot: Bot):
    data = await state.get_data()
    pid = data.get("pid")
    item = storage.get(pid)
    await state.clear()

    if not item:
        await message.reply("Этот пост уже обработан.")
        return

    item.text = build_post_html(message.text, item.signature)
    media = item.media_options[item.option_index] if item.media_options else []
    await resend_preview(bot, storage, item, media)
    await message.reply("Текст обновлён ✅")
