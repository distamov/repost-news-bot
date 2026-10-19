import asyncio
import base64
import logging
import re

import httpx

from .formatting import EMOJI_CATALOG

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {429, 503}  # стоит повторить тот же запрос ещё раз
MODEL_FALLBACK_CODES = {400, 404, 429, 503}  # стоит попробовать следующую модель
RETRY_DELAYS = (3,)  # один быстрый повтор той же модели, дальше — следующая модель

# Перегрузка у Google волнами: бывает, что все модели из списка недоступны
# разом на несколько минут, а потом отпускает. Если весь круг моделей не
# дал ответа — ждём и пробуем список заново, прежде чем сдаться совсем.
ROUNDS = 2
ROUND_PAUSE = 15

# Google иногда перегружает конкретную модель (особенно алиасы вроде
# *-latest) сразу у нескольких моделей одновременно, но редко у всех
# сразу — перебираем по очереди, пока не найдётся живая. Список — только
# актуальные, не снятые с производства модели (проверено вручную).
FALLBACK_MODELS = (
    "gemini-flash-lite-latest",
    "gemini-3.6-flash",
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
    "gemini-flash-latest",
)

_LANGUAGE_LINES = {
    "uz": (
        'Изложи результат на узбекском языке, используя КИРИЛЛИЦУ. Пиши '
        'ПРОСТО и по-человечески, обычными повседневными словами — как будто '
        'пересказываешь новость знакомому, а не пишешь художественный текст. '
        'НЕ используй книжную/поэтичную лексику и красивые эпитеты (никаких '
        'слов в духе "ноёб", "безаган", "тилларанг" и т.п.) — только простые, '
        'понятные слова. Короткие предложения, лаконично, по делу, без "воды" '
        'и без пафоса — в стиле обычных узбекских новостных Telegram-каналов.'
    ),
    "ru": (
        'Изложи результат на русском языке. Пиши ПРОСТО и по-человечески, '
        'обычными разговорными словами — как будто пересказываешь новость '
        'знакомому, а не пишешь литературный текст. НЕ используй книжную '
        'лексику, канцелярит и художественные эпитеты — только простые, '
        'понятные слова. Короткие предложения, лаконично, по делу, без '
        '"воды" и без пафоса — в стиле обычных новостных Telegram-каналов.'
    ),
}


def _build_system_prompt(language: str) -> str:
    language_line = _LANGUAGE_LINES.get(language, _LANGUAGE_LINES["uz"])
    emoji_options = " ".join(EMOJI_CATALOG.keys())
    return f"""Ты — редактор новостного Telegram-канала.
Тебе присылают текст новости на любом языке (русский, английский, узбекский
на латинице и т.д.), иногда вместе с фото к этой новости.

Сделай следующее:
1. НЕ переводи текст дословно и не иди по тем же предложениям в том же
   порядке. Перескажи суть своими словами: поменяй порядок подачи фактов,
   объединяй или разбивай предложения по-своему, используй другие
   формулировки и синонимы. Сохрани все факты, цифры и имена, не добавляй
   ничего, чего не было в оригинале — но результат должен читаться как
   самостоятельный пересказ, а не как построчный перевод оригинала.
2. {language_line}
3. Оформи результат как ДВЕ части, разделённые пустой строкой:
   - Первая строка — короткий цепляющий заголовок (5-9 слов), БЕЗ эмодзи
     в начале (эмодзи добавит сам бот).
   - Дальше — сам текст новости, 1-3 коротких абзаца.
   Никакой markdown-разметки (**, #, __) — только обычный текст, эмодзи
   и разбивку на абзацы через пустую строку. Заголовок и КАЖДЫЙ абзац
   заканчивай БЕЗ точки в конце (без "." на конце строки).

В САМОМ КОНЦЕ ответа — три маркера, каждый на отдельной строке:

###EMOJI###
Один эмодзи из списка ниже, какой лучше всего подходит по смыслу именно
этой новости (только сам эмодзи, без пояснений):
{emoji_options}

###KEYWORDS###
3-6 английских слов через запятую для поиска ПОХОЖЕЙ (но другой, не той же
самой) иллюстрации на фотостоке. Если к сообщению приложено фото — посмотри
на него и опиши именно то, что на нём видно (люди, место, предметы,
обстановка), чтобы найденное фото было похоже по содержанию на приложенное.
Если фото не приложено — опиши ключевые слова по смыслу текста новости.

###CTA###
Придумай ОДНУ короткую цепляющую фразу (не больше 8-10 слов), которая
мотивирует читателя переслать этот пост знакомым или в чат. Пиши на том же
языке, что и сам текст новости. Если получается — свяжи фразу по смыслу с
темой новости, если нет — просто живая цепляющая фраза без воды и пафоса.
Без эмодзи, без кавычек, без markdown — только сам текст фразы.

Не пиши никаких пояснений от себя — только заголовок, текст новости, эмодзи,
ключевые слова и фразу для пересылки."""


class LLMService:
    """Рерайт и перевод через Gemini API (generativelanguage.googleapis.com)."""

    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        self.model = model
        self._models = (model, *(m for m in FALLBACK_MODELS if m != model))
        self._client = httpx.AsyncClient(
            base_url=base_url or "https://generativelanguage.googleapis.com/v1beta",
            params={"key": api_key},
            timeout=60,
        )

    async def rewrite_and_translate(
        self, source_text: str, photo_bytes: bytes | None = None, language: str = "uz"
    ) -> tuple[str, str, str | None, str | None]:
        parts = [{"text": source_text}]
        if photo_bytes:
            parts.insert(
                0,
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": base64.b64encode(photo_bytes).decode("ascii"),
                    }
                },
            )

        payload = {
            "systemInstruction": {"parts": [{"text": _build_system_prompt(language)}]},
            "contents": [{"role": "user", "parts": parts}],
        }

        response = None
        for round_num in range(ROUNDS):
            got_response = False
            for model in self._models:
                for attempt, delay in enumerate((*RETRY_DELAYS, None)):
                    try:
                        response = await self._client.post(
                            f"/models/{model}:generateContent", json=payload
                        )
                    except httpx.TransportError:
                        logger.warning(
                            "Сетевая ошибка/таймаут при обращении к модели %s", model
                        )
                        response = None
                        if delay is not None:
                            await asyncio.sleep(delay)
                        continue
                    if response.status_code not in RETRYABLE_STATUS_CODES or delay is None:
                        break
                    await asyncio.sleep(delay)

                if response is None or response.status_code in MODEL_FALLBACK_CODES:
                    logger.warning(
                        "Модель %s недоступна (%s), пробую следующую: %s",
                        model,
                        response.status_code if response else "нет ответа/таймаут",
                        response.text[:500] if response else "",
                    )
                    continue
                got_response = True
                break

            if got_response:
                break
            if round_num < ROUNDS - 1:
                logger.warning(
                    "Все модели перегружены, жду %s сек и пробую весь список снова", ROUND_PAUSE
                )
                await asyncio.sleep(ROUND_PAUSE)

        if response is None:
            raise RuntimeError("Gemini API недоступен: все попытки завершились таймаутом")
        if response.status_code >= 400:
            logger.error(
                "Gemini API вернул %s для модели %s: %s",
                response.status_code, model, response.text[:2000],
            )
        response.raise_for_status()
        data = response.json()
        raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()

        emoji_choice = None
        keywords = "news"
        cta_text = None

        chunks = re.split(r"(###EMOJI###|###KEYWORDS###|###CTA###)", raw)
        body = chunks[0].strip()
        sections = {}
        for i in range(1, len(chunks) - 1, 2):
            sections[chunks[i]] = chunks[i + 1].strip()

        if "###EMOJI###" in sections:
            emoji_choice = sections["###EMOJI###"] or None
        if "###KEYWORDS###" in sections:
            keywords = sections["###KEYWORDS###"] or "news"
        if "###CTA###" in sections:
            cta_text = sections["###CTA###"] or None

        return body, keywords, emoji_choice, cta_text

    async def close(self):
        await self._client.aclose()
