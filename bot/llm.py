import httpx

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
3. Оформи как готовый пост для Telegram: обычный текст без markdown-разметки
   (никаких **, #, __), короткие абзацы, при необходимости 1-2 уместных
   эмодзи.

В самом конце, на отдельной строке после маркера ###KEYWORDS###, напиши
2-4 английских слова через запятую для поиска подходящей иллюстрации к
новости на фотостоке (например: earthquake, damaged building).

Не пиши никаких пояснений от себя — только готовый пост, а затем ключевые
слова."""


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
        response = await self._client.post(
            f"/models/{self.model}:generateContent",
            json={
                "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [{"role": "user", "parts": [{"text": source_text}]}],
            },
        )
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
