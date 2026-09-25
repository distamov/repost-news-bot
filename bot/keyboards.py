from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def preview_keyboard(pid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"approve:{pid}"),
                InlineKeyboardButton(text="🔄 Другое фото", callback_data=f"newphoto:{pid}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{pid}"),
            ]
        ]
    )
