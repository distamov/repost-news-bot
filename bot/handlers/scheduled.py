import re
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..scheduled_store import (
    QUEUE_INTERVAL_MINUTES,
    ScheduledStore,
    format_tashkent,
    parse_tashkent_time,
)
from ..telethon_posting import publish
from .rewrite import is_allowed

router = Router()

_TAG_RE = re.compile(r"<[^>]+>")


class RetimeForm(StatesGroup):
    waiting_time = State()


def _short_label(html_text: str, limit: int = 40) -> str:
    plain = _TAG_RE.sub("", html_text).strip()
    first_line = plain.splitlines()[0] if plain else "(без текста)"
    return (first_line[:limit] + "…") if len(first_line) > limit else first_line


def _list_keyboard(posts) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{format_tashkent(datetime.fromtimestamp(p.publish_at, tz=timezone.utc))} — {_short_label(p.text)}",
                callback_data=f"spview:{p.id}",
            )
        ]
        for p in sorted(posts, key=lambda x: x.publish_at)
    ]
    if not rows:
        rows = [[InlineKeyboardButton(text="Пусто", callback_data="splist")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _detail_keyboard(pid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Выложить сейчас", callback_data=f"spnow:{pid}")],
            [InlineKeyboardButton(text="🕒 Изменить время", callback_data=f"spretime:{pid}")],
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"spdel:{pid}")],
            [InlineKeyboardButton(text="⬅️ К списку", callback_data="splist")],
        ]
    )


def _retime_keyboard(pid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📥 +30 мин от последнего в очереди", callback_data=f"spqueue:{pid}")],
            [
                InlineKeyboardButton(text="+1 час", callback_data=f"spin:{pid}:60"),
                InlineKeyboardButton(text="+3 часа", callback_data=f"spin:{pid}:180"),
                InlineKeyboardButton(text="+6 часов", callback_data=f"spin:{pid}:360"),
            ],
            [
                InlineKeyboardButton(text="Завтра 09:00", callback_data=f"spat:{pid}:09:00"),
                InlineKeyboardButton(text="Завтра 19:00", callback_data=f"spat:{pid}:19:00"),
            ],
            [InlineKeyboardButton(text="✖️ Отмена", callback_data=f"spview:{pid}")],
        ]
    )


async def _show_list(message_to_edit, scheduled: ScheduledStore):
    posts = scheduled.all()
    text = "Отложенные посты:" if posts else "Отложенных постов нет."
    await message_to_edit.edit_text(text, reply_markup=_list_keyboard(posts))


@router.message(Command("scheduled"))
async def cmd_scheduled(message: Message, scheduled: ScheduledStore):
    if not is_allowed(message.from_user.id):
        await message.reply("У вас нет прав.")
        return
    posts = scheduled.all()
    text = "Отложенные посты:" if posts else "Отложенных постов нет."
    await message.answer(text, reply_markup=_list_keyboard(posts))


@router.callback_query(F.data == "splist")
async def cb_list(callback: CallbackQuery, scheduled: ScheduledStore):
    await _show_list(callback.message, scheduled)
    await callback.answer()


@router.callback_query(F.data.startswith("spview:"))
async def cb_view(callback: CallbackQuery, scheduled: ScheduledStore):
    pid = callback.data.split(":", 1)[1]
    post = scheduled.get(pid)
    if not post:
        await callback.answer("Пост уже опубликован или удалён.", show_alert=True)
        await _show_list(callback.message, scheduled)
        return
    when = format_tashkent(datetime.fromtimestamp(post.publish_at, tz=timezone.utc))
    preview = post.text if len(post.text) < 500 else post.text[:500] + "…"
    await callback.message.edit_text(
        f"🕒 Выйдет: {when} (Ташкент)\n\n{preview}",
        reply_markup=_detail_keyboard(pid),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("spnow:"))
async def cb_publish_now(callback: CallbackQuery, scheduled: ScheduledStore, telethon_client=None):
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return
    pid = callback.data.split(":", 1)[1]
    post = scheduled.get(pid)
    if not post:
        await callback.answer("Этот пост уже обработан.", show_alert=True)
        return
    try:
        media = scheduled.load_media(post)
        await publish(callback.bot, telethon_client, post.target_chat_id, post.text, media=media)
    except Exception:
        await callback.answer(
            "Ошибка публикации. Проверь, что бот — админ в этом канале.", show_alert=True
        )
        return
    scheduled.remove(pid)
    await callback.message.edit_text("✅ Опубликовано в канал.")
    await callback.answer()


@router.callback_query(F.data.startswith("spdel:"))
async def cb_delete(callback: CallbackQuery, scheduled: ScheduledStore):
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return
    pid = callback.data.split(":", 1)[1]
    scheduled.remove(pid)
    await callback.message.edit_text("🗑 Удалено из очереди.")
    await callback.answer()


@router.callback_query(F.data.startswith("spretime:"))
async def cb_retime_menu(callback: CallbackQuery, scheduled: ScheduledStore, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return
    pid = callback.data.split(":", 1)[1]
    if not scheduled.get(pid):
        await callback.answer("Этот пост уже обработан.", show_alert=True)
        return
    await state.set_state(RetimeForm.waiting_time)
    await state.update_data(pid=pid)
    await callback.message.edit_text(
        "Новое время публикации (по Ташкенту) — выбери вариант или напиши точное время "
        "сообщением: `19:30` или `29.09 08:00`.",
        reply_markup=_retime_keyboard(pid),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("spqueue:"))
async def cb_retime_queue(callback: CallbackQuery, scheduled: ScheduledStore, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return
    pid = callback.data.split(":", 1)[1]
    post = scheduled.get(pid)
    if not post:
        await callback.answer("Этот пост уже обработан.", show_alert=True)
        return

    now_utc = datetime.now(timezone.utc)
    others = [
        p.publish_at
        for p in scheduled.all()
        if p.target_chat_id == post.target_chat_id and p.id != pid
    ]
    base = max(datetime.fromtimestamp(max(others), tz=timezone.utc), now_utc) if others else now_utc
    publish_at = base + timedelta(minutes=QUEUE_INTERVAL_MINUTES)

    scheduled.update_time(pid, publish_at)
    await state.clear()
    await callback.message.edit_text(
        f"🕒 Перенесено на {format_tashkent(publish_at)} (Ташкент).",
        reply_markup=_detail_keyboard(pid),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("spin:"))
async def cb_retime_in(callback: CallbackQuery, scheduled: ScheduledStore, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return
    _, pid, minutes_str = callback.data.split(":", 2)
    if not scheduled.get(pid):
        await callback.answer("Этот пост уже обработан.", show_alert=True)
        return

    publish_at = datetime.now(timezone.utc) + timedelta(minutes=int(minutes_str))
    scheduled.update_time(pid, publish_at)
    await state.clear()
    await callback.message.edit_text(
        f"🕒 Перенесено на {format_tashkent(publish_at)} (Ташкент).",
        reply_markup=_detail_keyboard(pid),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("spat:"))
async def cb_retime_at(callback: CallbackQuery, scheduled: ScheduledStore, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return
    _, pid, hh, mm = callback.data.split(":", 3)
    if not scheduled.get(pid):
        await callback.answer("Этот пост уже обработан.", show_alert=True)
        return

    now_utc = datetime.now(timezone.utc)
    publish_at = parse_tashkent_time(f"{hh}:{mm}", now_utc)
    if publish_at and publish_at <= now_utc + timedelta(hours=1):
        publish_at += timedelta(days=1)

    scheduled.update_time(pid, publish_at)
    await state.clear()
    await callback.message.edit_text(
        f"🕒 Перенесено на {format_tashkent(publish_at)} (Ташкент).",
        reply_markup=_detail_keyboard(pid),
    )
    await callback.answer()


@router.message(RetimeForm.waiting_time, F.text)
async def receive_retime_text(message: Message, state: FSMContext, scheduled: ScheduledStore):
    data = await state.get_data()
    pid = data.get("pid")
    if not scheduled.get(pid):
        await state.clear()
        await message.reply("Этот пост уже обработан.")
        return

    publish_at = parse_tashkent_time(message.text)
    if not publish_at:
        await message.reply("Не понял время. Формат: `19:30` или `29.09 08:00`.")
        return

    scheduled.update_time(pid, publish_at)
    await state.clear()
    await message.reply(
        f"🕒 Перенесено на {format_tashkent(publish_at)} (Ташкент).",
        reply_markup=_detail_keyboard(pid),
    )
