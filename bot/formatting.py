import html
import random
import re

# Известные опечатки, которые модель периодически допускает в узбекской
# кириллице — чиним точечно, по мере того как замечаем новые.
_TYPO_FIXES = {
    r"\bкейингы\b": "кейинги",
}

# Премиум-эмодзи для заголовков (пак NewsEmoji, t.me/addemoji/NewsEmoji).
# Модель сама выбирает эмодзи по смыслу конкретной новости из этого
# каталога (см. llm.py); код гарантирует лишь то, что два поста подряд не
# получат один и тот же — если модель промахнулась мимо каталога или
# выбрала то же, что было в прошлый раз, берётся следующий по кругу.
# Требует, чтобы у владельца бота в @BotFather была подписка Telegram
# Premium — иначе Telegram отклонит отправку таких сообщений целиком.
EMOJI_CATALOG = {
    "⚡️": "5456140674028019486",  # срочно / энергично
    "🚨": "5395695537687123235",  # происшествие / ЧП
    "⚠️": "5447644880824181073",  # предупреждение
    "🔥": "5424972470023104089",  # горячая тема
    "💥": "5276032951342088188",  # резонансное событие
    "📌": "5397782960512444700",  # важное объявление
    "📣": "5424818078833715060",  # официальное заявление
    "🔔": "5458603043203327669",  # уведомление
    "💵": "5409048419211682843",  # деньги / финансы
    "📈": "5244837092042750681",  # рост
    "📉": "5246762912428603768",  # падение
    "🏠": "5416041192905265756",  # недвижимость / жильё
    "☀️": "5402477260982731644",  # погода — солнечно
    "🌧": "5399913388845322366",  # погода — дождь
    "❄️": "5449449325434266744",  # погода — холод
    "🖥": "5282843764451195532",  # технологии
    "🌐": "5447410659077661506",  # интернет / связь
    "🛡": "5251203410396458957",  # безопасность
    "🗓": "5413879192267805083",  # расписание / дата
    "🎉": "5461151367559141950",  # праздник / культура
    "🥇": "5440539497383087970",  # спорт / победа
    "💡": "5422439311196834318",  # идея / инновация
    "📊": "5231200819986047254",  # статистика
    "🚩": "5460755126761312667",  # важная веха
    "🆕": "5382357040008021292",  # новое
}
_NORMALIZED_CATALOG = {k.replace("️", ""): k for k in EMOJI_CATALOG}
_emoji_state = {"last_id": None, "fallback_index": -1}


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


def extract_leading_emoji(text: str) -> str | None:
    """Достаёт эмодзи/символ в самом начале ИСХОДНОГО поста источника —
    если он совпадает с чем-то из нашего каталога, его можно предложить
    как один из вариантов (в виде нашей анимированной версии), наравне
    с выбором модели по смыслу — для разнообразия, а не вместо него."""
    stripped = text.lstrip()
    i = 0
    while i < len(stripped) and not stripped[i].isalnum() and stripped[i] != " ":
        i += 1
    candidate = stripped[:i].strip()
    return candidate or None


def _pick_emoji(suggested: str | None, source_hint: str | None) -> tuple[str, str]:
    """Возвращает (custom_emoji_id, эмодзи-заглушка). Кандидаты — эмодзи,
    предложенный моделью по смыслу новости, и эмодзи исходного поста
    источника (если он есть в каталоге) — оба варианта равноправны и
    перемешиваются, чтобы не скатываться в одну и ту же схему выбора.
    Если ни один не подошёл (нет кандидатов или оба совпадают с прошлым
    эмодзи) — берётся следующий по кругу из всего каталога."""
    candidates = []
    if source_hint:
        matched = _NORMALIZED_CATALOG.get(source_hint.replace("️", ""))
        if matched:
            candidates.append(matched)
    if suggested and suggested.strip() in EMOJI_CATALOG:
        candidates.append(suggested.strip())
    random.shuffle(candidates)

    for fallback in candidates:
        emoji_id = EMOJI_CATALOG[fallback]
        if emoji_id != _emoji_state["last_id"]:
            _emoji_state["last_id"] = emoji_id
            return emoji_id, fallback

    items = list(EMOJI_CATALOG.items())
    for _ in range(len(items)):
        _emoji_state["fallback_index"] = (_emoji_state["fallback_index"] + 1) % len(items)
        fallback, emoji_id = items[_emoji_state["fallback_index"]]
        if emoji_id != _emoji_state["last_id"]:
            _emoji_state["last_id"] = emoji_id
            return emoji_id, fallback

    fallback, emoji_id = items[0]  # каталог длиннее 1, сюда не дойдём
    _emoji_state["last_id"] = emoji_id
    return emoji_id, fallback


def build_post_html(
    raw_text: str,
    signature: str = "",
    suggested_emoji: str | None = None,
    source_text: str | None = None,
) -> str:
    """Собирает HTML-пост из ответа LLM: первая строка — жирный заголовок
    (с эмодзи — либо по смыслу новости, либо иногда как в исходном посте,
    либо по кругу, если ни то ни другое не подошло — но никогда не
    повторяется два раза подряд), дальше — обычный текст без точек в конце
    абзацев, в конце — необязательная подпись канала."""
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
    source_hint = extract_leading_emoji(source_text) if source_text else None
    emoji_id, emoji_fallback = _pick_emoji(suggested_emoji, source_hint)
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
