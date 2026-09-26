import html


def build_post_html(raw_text: str, signature: str = "") -> str:
    """Собирает HTML-пост из ответа LLM: первая строка — жирный заголовок,
    дальше — обычный текст, в конце — необязательная подпись канала."""
    stripped = raw_text.strip()

    if "\n\n" in stripped:
        headline, body = stripped.split("\n\n", 1)
    elif "\n" in stripped:
        headline, body = stripped.split("\n", 1)
    else:
        headline, body = stripped, ""

    parts = [f"<b>{html.escape(headline.strip())}</b>"]
    if body.strip():
        parts.append(html.escape(body.strip()))
    if signature:
        parts.append(signature)

    return "\n\n".join(parts)
