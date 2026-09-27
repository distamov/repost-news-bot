from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def channel_picker_keyboard(selection_id: str, channels) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=channel.label, callback_data=f"pick:{selection_id}:{i}")]
        for i, channel in enumerate(channels)
    ]
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data=f"pickcancel:{selection_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def preview_keyboard(pid: str, has_original: bool = False) -> InlineKeyboardMarkup:
    extra_row = []
    if has_original:
        extra_row.append(InlineKeyboardButton(text="📎 Оригинал", callback_data=f"original:{pid}"))
    extra_row.append(InlineKeyboardButton(text="📤 Своё фото/видео", callback_data=f"customupload:{pid}"))

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"approve:{pid}"),
                InlineKeyboardButton(text="🔄 Другое фото", callback_data=f"newphoto:{pid}"),
            ],
            extra_row,
            [
                InlineKeyboardButton(text="✏️ Править текст", callback_data=f"edittext:{pid}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{pid}"),
            ],
        ]
    )
