from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def channel_picker_keyboard(selection_id: str, channels) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=channel.label, callback_data=f"pick:{selection_id}:{i}")]
        for i, channel in enumerate(channels)
    ]
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data=f"pickcancel:{selection_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
