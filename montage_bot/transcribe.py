import asyncio
from pathlib import Path

import httpx

from .subtitles import Word

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# Подсказка задаёт Whisper'у правильное написание/алфавит — без неё узбекский
# иногда распознаётся как азербайджанский или пишется вперемешку.
_PROMPTS = {
    "ru": "Новости Узбекистана. Ташкент, Самарканд.",
    "uz": "Oʻzbekiston yangiliklari. Toshkent, Samarqand.",
}


async def transcribe(audio_path: Path, language: str, api_key: str) -> list[Word]:
    """Распознаёт речь через Groq Whisper с таймкодами каждого слова."""
    data = {
        "model": "whisper-large-v3",
        "language": language,
        "prompt": _PROMPTS.get(language, ""),
        "response_format": "verbose_json",
        "timestamp_granularities[]": ["word", "segment"],
    }
    async with httpx.AsyncClient(timeout=120) as client:
        for attempt in range(3):
            with open(audio_path, "rb") as f:
                response = await client.post(
                    GROQ_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    data=data,
                    files={"file": (audio_path.name, f, "audio/mpeg")},
                )
            if response.status_code in (429, 500, 502, 503) and attempt < 2:
                await asyncio.sleep(3 * (attempt + 1))
                continue
            response.raise_for_status()
            break
    payload = response.json()
    return [
        Word(float(w["start"]), float(w["end"]), w["word"].strip())
        for w in payload.get("words", [])
        if w.get("word", "").strip()
    ]
