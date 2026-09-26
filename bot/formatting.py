import html


def _strip_trailing_period(text: str) -> str:
    text = text.rstrip()
    if text.endswith("...") or not text.endswith("."):
        return text
    return text[:-1]


def _ensure_emoji_space(headline: str) -> str:
    """Если заголовок начинается с эмодзи/символа без пробела перед текстом
    (модель иногда так делает) — добавляет пробел."""
    if len(headline) >= 2 and not headline[0].isalnum() and headline[1] != " ":
        return f"{headline[0]} {headline[1:].lstrip()}"
    return headline


def build_post_html(raw_text: str, signature: str = "") -> str:
    """Собирает HTML-пост из ответа LLM: первая строка — жирный заголовок,
    дальше — обычный текст без точек в конце абзацев, в конце —
    необязательная подпись канала."""
    stripped = raw_text.strip()

    if "\n\n" in stripped:
        headline, body = stripped.split("\n\n", 1)
    elif "\n" in stripped:
        headline, body = stripped.split("\n", 1)
    else:
        headline, body = stripped, ""

    headline = _ensure_emoji_space(_strip_trailing_period(headline.strip()))
    paragraphs = [_strip_trailing_period(p.strip()) for p in body.split("\n\n") if p.strip()]

    parts = [f"<b>{html.escape(headline)}</b>"]
    if paragraphs:
        parts.append("\n\n".join(html.escape(p) for p in paragraphs))
    if signature:
        parts.append(signature)

    return "\n\n".join(parts)
