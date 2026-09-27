from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telethon.tl.functions.channels import JoinChannelRequest

from ..sources_store import SourceStore, extract_username
from .rewrite import is_allowed

router = Router()


class SourceForm(StatesGroup):
    waiting_id = State()


def _sources_menu(sources: SourceStore) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text=s.id, callback_data="noop"),
            InlineKeyboardButton(text="🗑", callback_data=f"srcdel:{i}"),
        ]
        for i, s in enumerate(sources.all())
    ]
    rows.append([InlineKeyboardButton(text="➕ Добавить источник", callback_data="srcadd")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("sources"))
async def cmd_sources(message: Message, sources: SourceStore):
    if not is_allowed(message.from_user.id):
        await message.reply("У вас нет прав.")
        return
    text = "Каналы-источники (мониторинг):" if sources.all() else "Источников пока нет."
    await message.answer(text, reply_markup=_sources_menu(sources))


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data == "srcadd")
async def cb_source_add(callback: CallbackQuery, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return
    await state.set_state(SourceForm.waiting_id)
    await callback.message.answer(
        "Пришли канал-источник: @username или ссылку https://t.me/username.\n"
        "Можно сразу несколько — через запятую или каждый на новой строке."
    )
    await callback.answer()


@router.message(SourceForm.waiting_id, F.text)
async def form_source_id(message: Message, state: FSMContext, sources: SourceStore, monitor):
    raw_items = [x.strip() for x in message.text.replace("\n", ",").split(",") if x.strip()]
    added = []
    for raw in raw_items:
        username = extract_username(raw)
        sources.add(username)
        added.append(username)
        if monitor is not None:
            try:
                await monitor.client(JoinChannelRequest(username))
            except Exception:
                pass

    await state.clear()
    note = (
        ""
        if monitor is not None
        else "\n\n⚠️ Автомониторинг сейчас выключен (не заполнены TELEGRAM_* в .env) — "
        "список сохранён, но отслеживать эти каналы бот не будет, пока мониторинг не включён."
    )
    await message.reply(
        f"Добавлено: {', '.join(added)}{note}", reply_markup=_sources_menu(sources)
    )


@router.callback_query(F.data.startswith("srcdel:"))
async def cb_source_delete(callback: CallbackQuery, sources: SourceStore):
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return
    idx = int(callback.data.split(":", 1)[1])
    sources.remove(idx)
    await callback.message.edit_text("Источник удалён ✅")
    await callback.message.answer("Каналы-источники:", reply_markup=_sources_menu(sources))
    await callback.answer()
