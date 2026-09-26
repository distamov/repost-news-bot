import asyncio

import httpx

RETRYABLE_STATUS_CODES = {429, 503}
RETRY_DELAYS = (2, 5, 10)

SYSTEM_PROMPT = """Ты — редактор узбекского новостного Telegram-канала.
Тебе присылают текст новости на любом языке (русский, английский, узбекский
на латинице и т.д.).

Сделай следующее:
1. Перескажи содержание своими словами (рерайт, а не дословный перевод),
   сохранив все факты, цифры и имена, не добавляя ничего, чего не было
   в оригинале.
2. Изложи результат на узбекском языке, используя КИРИЛЛИЦУ, в стиле,
   привычном для узбекских новостных Telegram-каналов: лаконично, по делу,
   без "воды".
3. Оформи результат как ДВЕ части, разделённые пустой строкой:
   - Первая строка — короткий цепляющий заголовок (5-9 слов) с одним уместным
     эмодзи в начале (например ⚡ или 📌).
   - Дальше — сам текст новости, 1-3 коротких абзаца.
   Никакой markdown-разметки (**, #, __) — только обычный текст, эмодзи
   и разбивку на абзацы через пустую строку.

В самом конце, на отдельной строке после маркера ###KEYWORDS###, напиши
2-4 английских слова через запятую для поиска подходящей иллюстрации к
новости на фотостоке (например: earthquake, damaged building).

Не пиши никаких пояснений от себя — только заголовок, текст новости, а затем
ключевые слова."""


class LLMService:
    """Рерайт и перевод через Gemini API (generativelanguage.googleapis.com)."""

    def __init__(self, api_key: str, model: str):
        self.model = model
        self._client = httpx.AsyncClient(
            base_url="https://generativelanguage.googleapis.com/v1beta",
            params={"key": api_key},
            timeout=60,
        )

    async def rewrite_and_translate(self, source_text: str) -> tuple[str, str]:
        payload = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": source_text}]}],
        }

        for attempt, delay in enumerate((*RETRY_DELAYS, None)):
            response = await self._client.post(
                f"/models/{self.model}:generateContent", json=payload
            )
            if response.status_code not in RETRYABLE_STATUS_CODES or delay is None:
                break
            await asyncio.sleep(delay)

        response.raise_for_status()
        data = response.json()
        raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()

        if "###KEYWORDS###" in raw:
            body, keywords = raw.split("###KEYWORDS###", 1)
        else:
            body, keywords = raw, "news"

        return body.strip(), keywords.strip()

    async def close(self):
        await self._client.aclose()
