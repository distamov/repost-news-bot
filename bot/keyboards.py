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
            [InlineKeyboardButton(text="🕒 Отложить", callback_data=f"sched:{pid}")],
            [
                InlineKeyboardButton(text="✏️ Править текст", callback_data=f"edittext:{pid}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{pid}"),
            ],
        ]
    )


def schedule_keyboard(pid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📥 В очередь (+30 мин от последнего)", callback_data=f"schedqueue:{pid}")],
            [
                InlineKeyboardButton(text="+1 час", callback_data=f"schedin:{pid}:60"),
                InlineKeyboardButton(text="+3 часа", callback_data=f"schedin:{pid}:180"),
                InlineKeyboardButton(text="+6 часов", callback_data=f"schedin:{pid}:360"),
            ],
            [
                InlineKeyboardButton(text="Завтра 09:00", callback_data=f"schedat:{pid}:09:00"),
                InlineKeyboardButton(text="Завтра 19:00", callback_data=f"schedat:{pid}:19:00"),
            ],
            [InlineKeyboardButton(text="✖️ Отмена", callback_data=f"schedcancel:{pid}")],
        ]
    )
