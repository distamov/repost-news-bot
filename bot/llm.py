from anthropic import AsyncAnthropic

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
    def __init__(self, api_key: str, model: str):
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model

    async def rewrite_and_translate(self, source_text: str) -> tuple[str, str]:
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": source_text}],
        )
        raw = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()

        if "###KEYWORDS###" in raw:
            body, keywords = raw.split("###KEYWORDS###", 1)
        else:
            body, keywords = raw, "news"

        return body.strip(), keywords.strip()
