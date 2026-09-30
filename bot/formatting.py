import html
import re

# Известные опечатки, которые модель периодически допускает в узбекской
# кириллице — чиним точечно, по мере того как замечаем новые.
_TYPO_FIXES = {
    r"\bкейингы\b": "кейинги",
}

# Премиум-эмодзи для заголовков (пак NewsEmoji, t.me/addemoji/NewsEmoji) —
# ставим сами по кругу, чтобы никогда не шли два одинаковых подряд (и чтобы
# не зависеть от того, что выберет модель). Каждый — (custom_emoji_id,
# обычный эмодзи-заглушка на случай, если клиент не отрисует анимацию).
# Требует, чтобы у владельца бота в @BotFather была подписка Telegram
# Premium — иначе Telegram отклонит отправку таких сообщений целиком.
_EMOJI_POOL = [
    ("5456140674028019486", "⚡️"),
    ("5397782960512444700", "📌"),
    ("5395695537687123235", "🚨"),
    ("5274099962655816924", "❗️"),
    ("5458603043203327669", "🔔"),
    ("5391032818111363540", "📍"),
    ("5276032951342088188", "💥"),
    ("5440660757194744323", "‼️"),
    ("5424818078833715060", "📣"),
    ("5424972470023104089", "🔥"),
]
_emoji_state = {"index": -1}


def _fix_known_typos(text: str) -> str:
    for pattern, replacement in _TYPO_FIXES.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def _strip_trailing_period(text: str) -> str:
    text = text.rstrip()
    if text.endswith("...") or not text.endswith("."):
        return text
    return text[:-1]


def _strip_leading_symbol(headline: str) -> str:
    """Убирает эмодзи/символ (и любые пробелы после него), которые модель
    могла поставить в начале заголовка сама — дальше подставляется свой,
    из ротации."""
    i = 0
    while i < len(headline) and not headline[i].isalnum() and headline[i] != " ":
        i += 1
    return headline[i:].lstrip()


def _next_emoji() -> tuple[str, str]:
    """Возвращает (custom_emoji_id, эмодзи-заглушка) следующего эмодзи
    в ротации."""
    _emoji_state["index"] = (_emoji_state["index"] + 1) % len(_EMOJI_POOL)
    return _EMOJI_POOL[_emoji_state["index"]]


def build_post_html(raw_text: str, signature: str = "") -> str:
    """Собирает HTML-пост из ответа LLM: первая строка — жирный заголовок
    (с эмодзи, который бот подставляет сам, по кругу, без повторов подряд),
    дальше — обычный текст без точек в конце абзацев, в конце —
    необязательная подпись канала."""
    stripped = raw_text.strip()

    if "\n\n" in stripped:
        headline, body = stripped.split("\n\n", 1)
    elif "\n" in stripped:
        headline, body = stripped.split("\n", 1)
    else:
        headline, body = stripped, ""

    headline_text = _strip_leading_symbol(
        _strip_trailing_period(_fix_known_typos(headline.strip()))
    )
    emoji_id, emoji_fallback = _next_emoji()
    # Тег <tg-emoji> должен остаться настоящим HTML-тегом — экранируем
    # только текст заголовка, не всю строку целиком.
    emoji_html = f'<tg-emoji emoji-id="{emoji_id}">{emoji_fallback}</tg-emoji>'
    headline = f"{emoji_html} {html.escape(headline_text)}"

    paragraphs = [
        _strip_trailing_period(_fix_known_typos(p.strip())) for p in body.split("\n\n") if p.strip()
    ]

    parts = [f"<b>{headline}</b>"]
    if paragraphs:
        parts.append("\n\n".join(html.escape(p) for p in paragraphs))
    if signature:
        parts.append(signature)

    return "\n\n".join(parts)
