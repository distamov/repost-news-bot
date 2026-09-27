import html
import re

# Известные опечатки, которые модель периодически допускает в узбекской
# кириллице — чиним точечно, по мере того как замечаем новые.
_TYPO_FIXES = {
    r"\bкейингы\b": "кейинги",
}

# Эмодзи для заголовков — ставим сами по кругу, чтобы никогда не шли два
# одинаковых подряд (и чтобы не зависеть от того, что выберет модель).
_EMOJI_POOL = ["⚡", "📌", "🚨", "❗️", "🔔", "📍", "🗞️", "💥", "‼️", "📢"]
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


def _next_emoji() -> str:
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
    headline = f"{_next_emoji()} {headline_text}"

    paragraphs = [
        _strip_trailing_period(_fix_known_typos(p.strip())) for p in body.split("\n\n") if p.strip()
    ]

    parts = [f"<b>{html.escape(headline)}</b>"]
    if paragraphs:
        parts.append("\n\n".join(html.escape(p) for p in paragraphs))
    if signature:
        parts.append(signature)

    return "\n\n".join(parts)
