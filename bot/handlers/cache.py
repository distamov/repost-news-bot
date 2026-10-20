import math
import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..admins_store import AdminStore
from ..storage import Storage
from .rewrite import is_allowed

router = Router()


def _fmt_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.0f} МБ"
    return f"{size / 1024:.0f} КБ"


def _scope(user_id: int, admins: AdminStore):
    """Супер-админ чистит всю очередь, остальные — только свои превью."""
    return None if admins.is_super(user_id) else user_id


@router.message(Command("clearcache"))
async def cmd_clear_cache(message: Message, storage: Storage, admins: AdminStore):
    if not is_allowed(message.from_user.id):
        await message.reply("У вас нет прав.")
        return

    # Чистится только то, что пришло до этой команды: превью, которые бот
    # пришлёт, пока висит подтверждение, останутся.
    before = math.floor(time.time() * 1000) / 1000
    owner_id = _scope(message.from_user.id, admins)
    count, files, size = storage.cache_stats(before, owner_id)
    if not count:
        await message.reply("Очередь превью пуста — чистить нечего.")
        return

    whose = "Во всей очереди" if owner_id is None else "У вас"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="🧹 Очистить", callback_data=f"cacheclear:{before:.3f}"),
            InlineKeyboardButton(text="Отмена", callback_data="cachecancel"),
        ]]
    )
    await message.answer(
        f"{whose} неразобранных превью: {count} ({files} фото/видео, "
        f"{_fmt_size(size)}).\n\n"
        "Удалить их? Кнопки на этих превью перестанут работать. "
        "Отложенные посты не трогаются.",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith("cacheclear:"))
async def cb_clear_cache(callback: CallbackQuery, storage: Storage, admins: AdminStore):
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return

    before = float(callback.data.split(":", 1)[1])
    owner_id = _scope(callback.from_user.id, admins)
    _, _, size = storage.cache_stats(before, owner_id)
    removed = storage.clear_cache(before, owner_id)
    await callback.message.edit_text(
        f"🧹 Очищено: {removed} превью, {_fmt_size(size)}."
    )
    await callback.answer()


@router.callback_query(F.data == "cachecancel")
async def cb_clear_cache_cancel(callback: CallbackQuery):
    await callback.message.edit_text("Очистка отменена.")
    await callback.answer()
