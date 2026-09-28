import re
import time
from difflib import SequenceMatcher
from typing import Optional

_URL_RE = re.compile(r"https?://\S+")
_MENTION_RE = re.compile(r"@\w+")
_WS_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[a-zA-Zа-яёўғқҳА-ЯЁЎҒҚҲ0-9]+")

SIMILARITY_THRESHOLD = 0.75
WORD_OVERLAP_THRESHOLD = 0.35
MIN_SIGNIFICANT_WORD_LEN = 4
STEM_PREFIX_LEN = 5  # грубый стемминг: узбекский и русский — с окончаниями,
# сравнение по первым буквам корня ловит "осмонида"/"осмонда" как одно слово


def _normalize(text: str) -> str:
    text = _URL_RE.sub("", text)
    text = _MENTION_RE.sub("", text)
    text = text.lower()
    return _WS_RE.sub(" ", text).strip()


def _significant_words(normalized: str) -> set[str]:
    return {
        w[:STEM_PREFIX_LEN]
        for w in _WORD_RE.findall(normalized)
        if len(w) >= MIN_SIGNIFICANT_WORD_LEN
    }


class Deduplicator:
    """Находит одну и ту же новость, даже если разные каналы-источники
    пересказали её собственными, непохожими по тексту словами (например,
    один и тот же инфоповод — суперлуние, ДТП и т.п.)."""

    def __init__(self, ttl_seconds: int = 24 * 3600):
        self._ttl = ttl_seconds
        # (время, нормализованный текст, значимые слова, источник, ссылка на пост)
        self._seen: list[tuple[float, str, set[str], str, Optional[str]]] = []

    def find_duplicate(self, text: str) -> Optional[tuple[str, Optional[str]]]:
        """Возвращает (название источника, ссылка на исходный пост) для уже
        обработанной похожей новости, или None, если дубликатов не найдено."""
        normalized = _normalize(text)
        words = _significant_words(normalized)
        now = time.monotonic()
        self._purge(now)

        for _, seen_text, seen_words, source_name, source_link in self._seen:
            if SequenceMatcher(None, normalized, seen_text).ratio() >= SIMILARITY_THRESHOLD:
                return source_name, source_link
            if words and seen_words:
                overlap = len(words & seen_words) / min(len(words), len(seen_words))
                if overlap >= WORD_OVERLAP_THRESHOLD:
                    return source_name, source_link
        return None

    def add(self, text: str, source_name: str, source_link: Optional[str] = None) -> None:
        normalized = _normalize(text)
        self._seen.append(
            (time.monotonic(), normalized, _significant_words(normalized), source_name, source_link)
        )

    def _purge(self, now: float) -> None:
        cutoff = now - self._ttl
        self._seen = [(ts, t, w, s, link) for ts, t, w, s, link in self._seen if ts >= cutoff]
