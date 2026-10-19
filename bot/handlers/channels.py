import uuid

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..channels_store import ChannelConfig, ChannelStore, parse_chat_id
from .rewrite import is_allowed

router = Router()


class ChannelForm(StatesGroup):
    waiting_id = State()
    waiting_label = State()
    waiting_signature = State()


class EditChannelForm(StatesGroup):
    waiting_value = State()


def _channels_menu(channel_list: list[ChannelConfig]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text=f"{ch.label} ({ch.language})", callback_data=f"chview:{ch.uid}"),
            InlineKeyboardButton(text="✏️", callback_data=f"chedit:{ch.uid}"),
            InlineKeyboardButton(text="🗑", callback_data=f"chdel:{ch.uid}"),
        ]
        for ch in channel_list
    ]
    rows.append([InlineKeyboardButton(text="➕ Добавить канал", callback_data="chadd")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _channel_card(ch: ChannelConfig) -> str:
    return (
        f"<b>{ch.label}</b>\n"
        f"ID: <code>{ch.id}</code>\n"
        f"Язык: {ch.language}\n"
        f"Подпись: {ch.signature or '—'}"
    )


@router.message(Command("channels"))
async def cmd_channels(message: Message, channels: ChannelStore):
    if not is_allowed(message.from_user.id):
        await message.reply("У вас нет прав.")
        return
    channel_list = channels.all_for(message.from_user.id)
    text = "Твои каналы:" if channel_list else "Каналов пока нет."
    await message.answer(text, reply_markup=_channels_menu(channel_list))


@router.callback_query(F.data.startswith("chview:"))
async def cb_channel_view(callback: CallbackQuery, channels: ChannelStore):
    ch = channels.get_by_uid(callback.data.split(":", 1)[1])
    if ch and ch.owner_id == callback.from_user.id:
        await callback.message.answer(_channel_card(ch))
    await callback.answer()


@router.callback_query(F.data == "chadd")
async def cb_channel_add(callback: CallbackQuery, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return
    await state.set_state(ChannelForm.waiting_id)
    await callback.message.answer(
        "Пришли ID канала: @username (публичный) или числовой id вида "
        "-1001234567890 (приватный).\n"
        "Не забудь заранее добавить бота в этот канал администратором "
        "с правом отправки сообщений — иначе публикация не пройдёт."
    )
    await callback.answer()


@router.message(ChannelForm.waiting_id, F.text)
async def form_channel_id(message: Message, state: FSMContext):
    await state.update_data(id=parse_chat_id(message.text))
    await state.set_state(ChannelForm.waiting_label)
    await message.reply("Как назвать канал (для кнопки выбора)? Например: 🇷🇺 Новости РФ")


@router.message(ChannelForm.waiting_label, F.text)
async def form_channel_label(message: Message, state: FSMContext):
    await state.update_data(label=message.text.strip())
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data="chlang:ru"),
                InlineKeyboardButton(text="🇺🇿 Узбекский", callback_data="chlang:uz"),
            ]
        ]
    )
    await message.reply("На каком языке готовить посты для этого канала?", reply_markup=kb)


@router.callback_query(ChannelForm.waiting_label, F.data.startswith("chlang:"))
async def form_channel_lang(callback: CallbackQuery, state: FSMContext):
    lang = callback.data.split(":", 1)[1]
    await state.update_data(language=lang)
    await state.set_state(ChannelForm.waiting_signature)
    await callback.message.answer(
        'Пришли подпись/ссылку в конце поста (можно с HTML, например '
        '<a href="https://t.me/channel">Текст</a>), или отправь "-", чтобы пропустить.'
    )
    await callback.answer()


@router.message(ChannelForm.waiting_signature, F.text)
async def form_channel_signature(message: Message, state: FSMContext, channels: ChannelStore):
    signature = "" if message.text.strip() == "-" else message.text
    data = await state.get_data()
    channels.add(
        ChannelConfig(
            id=data["id"],
            label=data["label"],
            language=data["language"],
            signature=signature,
            owner_id=message.from_user.id,
            uid=uuid.uuid4().hex[:8],
        )
    )
    await state.clear()
    channel_list = channels.all_for(message.from_user.id)
    await message.reply("Канал добавлен ✅", reply_markup=_channels_menu(channel_list))


@router.callback_query(F.data.startswith("chdel:"))
async def cb_channel_delete(callback: CallbackQuery):
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return
    uid = callback.data.split(":", 1)[1]
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"chdelyes:{uid}"),
                InlineKeyboardButton(text="Отмена", callback_data="chdelno"),
            ]
        ]
    )
    await callback.message.answer("Удалить этот канал?", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("chdelyes:"))
async def cb_channel_delete_confirm(callback: CallbackQuery, channels: ChannelStore):
    uid = callback.data.split(":", 1)[1]
    ch = channels.get_by_uid(uid)
    if not ch or ch.owner_id != callback.from_user.id:
        await callback.answer("Канал не найден.", show_alert=True)
        return
    channels.remove_by_uid(uid)
    await callback.message.edit_text("Канал удалён ✅")
    channel_list = channels.all_for(callback.from_user.id)
    await callback.message.answer("Твои каналы:", reply_markup=_channels_menu(channel_list))
    await callback.answer()


@router.callback_query(F.data == "chdelno")
async def cb_channel_delete_cancel(callback: CallbackQuery):
    await callback.message.edit_text("Отменено.")
    await callback.answer()


@router.callback_query(F.data.startswith("chedit:"))
async def cb_channel_edit(callback: CallbackQuery, channels: ChannelStore):
    uid = callback.data.split(":", 1)[1]
    ch = channels.get_by_uid(uid)
    if not ch or ch.owner_id != callback.from_user.id:
        await callback.answer("Канал не найден.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="ID", callback_data=f"cheditfield:{uid}:id")],
            [InlineKeyboardButton(text="Название", callback_data=f"cheditfield:{uid}:label")],
            [InlineKeyboardButton(text="Язык", callback_data=f"cheditfield:{uid}:language")],
            [InlineKeyboardButton(text="Подпись", callback_data=f"cheditfield:{uid}:signature")],
        ]
    )
    await callback.message.answer(f"{_channel_card(ch)}\n\nЧто изменить?", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("cheditfield:"))
async def cb_channel_edit_field(callback: CallbackQuery, state: FSMContext):
    _, uid, field = callback.data.split(":", 2)

    if field == "language":
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🇷🇺 Русский", callback_data=f"chsetlang:{uid}:ru"),
                    InlineKeyboardButton(text="🇺🇿 Узбекский", callback_data=f"chsetlang:{uid}:uz"),
                ]
            ]
        )
        await callback.message.answer("Выбери язык:", reply_markup=kb)
        await callback.answer()
        return

    await state.set_state(EditChannelForm.waiting_value)
    await state.update_data(uid=uid, field=field)
    prompts = {
        "id": "Пришли новый ID канала (@username или числовой id).",
        "label": "Пришли новое название.",
        "signature": 'Пришли новую подпись (или "-", чтобы убрать).',
    }
    await callback.message.answer(prompts[field])
    await callback.answer()


@router.callback_query(F.data.startswith("chsetlang:"))
async def cb_channel_set_lang(callback: CallbackQuery, channels: ChannelStore):
    _, uid, lang = callback.data.split(":", 2)
    ch = channels.get_by_uid(uid)
    if not ch or ch.owner_id != callback.from_user.id:
        await callback.answer("Канал не найден.", show_alert=True)
        return
    channels.update_by_uid(uid, language=lang)
    await callback.message.edit_text(f"Язык обновлён ✅ ({lang})")
    await callback.answer()


@router.message(EditChannelForm.waiting_value, F.text)
async def form_edit_value(message: Message, state: FSMContext, channels: ChannelStore):
    data = await state.get_data()
    field = data["field"]
    uid = data["uid"]
    raw = message.text.strip()

    ch = channels.get_by_uid(uid)
    if not ch or ch.owner_id != message.from_user.id:
        await state.clear()
        await message.reply("Канал не найден.")
        return

    if field == "id":
        value = parse_chat_id(raw)
    elif field == "signature":
        value = "" if raw == "-" else message.text
    else:
        value = raw

    channels.update_by_uid(uid, **{field: value})
    await state.clear()
    channel_list = channels.all_for(message.from_user.id)
    await message.reply("Обновлено ✅", reply_markup=_channels_menu(channel_list))
