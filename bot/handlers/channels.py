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


def _channels_menu(channels: ChannelStore) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text=f"{ch.label} ({ch.language})", callback_data=f"chview:{i}"),
            InlineKeyboardButton(text="✏️", callback_data=f"chedit:{i}"),
            InlineKeyboardButton(text="🗑", callback_data=f"chdel:{i}"),
        ]
        for i, ch in enumerate(channels.all())
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
    text = "Твои каналы:" if channels.all() else "Каналов пока нет."
    await message.answer(text, reply_markup=_channels_menu(channels))


@router.callback_query(F.data.startswith("chview:"))
async def cb_channel_view(callback: CallbackQuery, channels: ChannelStore):
    ch = channels.get(int(callback.data.split(":", 1)[1]))
    if ch:
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
        ChannelConfig(id=data["id"], label=data["label"], language=data["language"], signature=signature)
    )
    await state.clear()
    await message.reply("Канал добавлен ✅", reply_markup=_channels_menu(channels))


@router.callback_query(F.data.startswith("chdel:"))
async def cb_channel_delete(callback: CallbackQuery):
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return
    idx = callback.data.split(":", 1)[1]
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"chdelyes:{idx}"),
                InlineKeyboardButton(text="Отмена", callback_data="chdelno"),
            ]
        ]
    )
    await callback.message.answer("Удалить этот канал?", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("chdelyes:"))
async def cb_channel_delete_confirm(callback: CallbackQuery, channels: ChannelStore):
    idx = int(callback.data.split(":", 1)[1])
    channels.remove(idx)
    await callback.message.edit_text("Канал удалён ✅")
    await callback.message.answer("Твои каналы:", reply_markup=_channels_menu(channels))
    await callback.answer()


@router.callback_query(F.data == "chdelno")
async def cb_channel_delete_cancel(callback: CallbackQuery):
    await callback.message.edit_text("Отменено.")
    await callback.answer()


@router.callback_query(F.data.startswith("chedit:"))
async def cb_channel_edit(callback: CallbackQuery, channels: ChannelStore):
    idx = int(callback.data.split(":", 1)[1])
    ch = channels.get(idx)
    if not ch:
        await callback.answer("Канал не найден.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="ID", callback_data=f"cheditfield:{idx}:id")],
            [InlineKeyboardButton(text="Название", callback_data=f"cheditfield:{idx}:label")],
            [InlineKeyboardButton(text="Язык", callback_data=f"cheditfield:{idx}:language")],
            [InlineKeyboardButton(text="Подпись", callback_data=f"cheditfield:{idx}:signature")],
        ]
    )
    await callback.message.answer(f"{_channel_card(ch)}\n\nЧто изменить?", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("cheditfield:"))
async def cb_channel_edit_field(callback: CallbackQuery, state: FSMContext):
    _, idx_str, field = callback.data.split(":", 2)

    if field == "language":
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🇷🇺 Русский", callback_data=f"chsetlang:{idx_str}:ru"),
                    InlineKeyboardButton(text="🇺🇿 Узбекский", callback_data=f"chsetlang:{idx_str}:uz"),
                ]
            ]
        )
        await callback.message.answer("Выбери язык:", reply_markup=kb)
        await callback.answer()
        return

    await state.set_state(EditChannelForm.waiting_value)
    await state.update_data(index=int(idx_str), field=field)
    prompts = {
        "id": "Пришли новый ID канала (@username или числовой id).",
        "label": "Пришли новое название.",
        "signature": 'Пришли новую подпись (или "-", чтобы убрать).',
    }
    await callback.message.answer(prompts[field])
    await callback.answer()


@router.callback_query(F.data.startswith("chsetlang:"))
async def cb_channel_set_lang(callback: CallbackQuery, channels: ChannelStore):
    _, idx_str, lang = callback.data.split(":", 2)
    channels.update(int(idx_str), language=lang)
    await callback.message.edit_text(f"Язык обновлён ✅ ({lang})")
    await callback.answer()


@router.message(EditChannelForm.waiting_value, F.text)
async def form_edit_value(message: Message, state: FSMContext, channels: ChannelStore):
    data = await state.get_data()
    field = data["field"]
    raw = message.text.strip()

    if field == "id":
        value = parse_chat_id(raw)
    elif field == "signature":
        value = "" if raw == "-" else message.text
    else:
        value = raw

    channels.update(data["index"], **{field: value})
    await state.clear()
    await message.reply("Обновлено ✅", reply_markup=_channels_menu(channels))
