from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..admins_store import AdminStore
from .rewrite import is_allowed

router = Router()


class AdminForm(StatesGroup):
    waiting_id = State()


def _admins_menu(admins: AdminStore) -> InlineKeyboardMarkup:
    rows = []
    for a in admins.all():
        label = f"{a.user_id}{' 👑' if a.is_super else ''}"
        row = [InlineKeyboardButton(text=label, callback_data="noop")]
        if not a.is_super:
            row.append(InlineKeyboardButton(text="🗑", callback_data=f"admdel:{a.user_id}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="➕ Добавить админа", callback_data="admadd")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("admins"))
async def cmd_admins(message: Message, admins: AdminStore):
    if not is_allowed(message.from_user.id):
        await message.reply("У вас нет прав.")
        return
    if not admins.is_super(message.from_user.id):
        await message.reply("Эта команда доступна только супер-админу.")
        return
    await message.answer("Админы бота:", reply_markup=_admins_menu(admins))


@router.callback_query(F.data == "admadd")
async def cb_admin_add(callback: CallbackQuery, state: FSMContext, admins: AdminStore):
    if not admins.is_super(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return
    await state.set_state(AdminForm.waiting_id)
    await callback.message.answer(
        "Перешли сюда любое сообщение от нового админа, либо пришли его числовой "
        "Telegram user id.\n\n"
        "⚠️ Важно: новый админ должен сам хотя бы раз нажать /start в диалоге с этим "
        "ботом — иначе бот не сможет написать ему первым."
    )
    await callback.answer()


@router.message(AdminForm.waiting_id)
async def form_admin_id(message: Message, state: FSMContext, admins: AdminStore):
    user_id = None
    if message.forward_from:
        user_id = message.forward_from.id
    elif message.text and message.text.strip().lstrip("-").isdigit():
        user_id = int(message.text.strip())

    await state.clear()
    if user_id is None:
        await message.reply(
            "Не понял, кого добавлять — пришли пересланное сообщение или числовой id."
        )
        return

    admins.add(user_id)
    await message.reply(f"Админ {user_id} добавлен ✅", reply_markup=_admins_menu(admins))


@router.callback_query(F.data.startswith("admdel:"))
async def cb_admin_delete(callback: CallbackQuery, admins: AdminStore):
    if not admins.is_super(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return
    user_id = int(callback.data.split(":", 1)[1])
    admins.remove(user_id)
    await callback.message.edit_text("Админ удалён ✅")
    await callback.message.answer("Админы бота:", reply_markup=_admins_menu(admins))
    await callback.answer()
