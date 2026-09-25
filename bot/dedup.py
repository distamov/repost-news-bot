import re
import time
from difflib import SequenceMatcher

_URL_RE = re.compile(r"https?://\S+")
_MENTION_RE = re.compile(r"@\w+")
_WS_RE = re.compile(r"\s+")

SIMILARITY_THRESHOLD = 0.75


def _normalize(text: str) -> str:
    text = _URL_RE.sub("", text)
    text = _MENTION_RE.sub("", text)
    text = text.lower()
    return _WS_RE.sub(" ", text).strip()


class Deduplicator:
    """Отсеивает почти одинаковые новости, которые несколько каналов
    публикуют одновременно (репост одной и той же новости)."""

    def __init__(self, ttl_seconds: int = 24 * 3600):
        self._ttl = ttl_seconds
        self._seen: list[tuple[float, str]] = []

    def is_duplicate(self, text: str) -> bool:
        normalized = _normalize(text)
        now = time.monotonic()
        self._purge(now)

        for _, seen_text in self._seen:
            longer = max(len(seen_text), len(normalized))
            if longer and abs(len(seen_text) - len(normalized)) / longer > 0.5:
                continue
            if SequenceMatcher(None, normalized, seen_text).ratio() >= SIMILARITY_THRESHOLD:
                return True

        self._seen.append((now, normalized))
        return False

    def _purge(self, now: float) -> None:
        cutoff = now - self._ttl
        self._seen = [(ts, t) for ts, t in self._seen if ts >= cutoff]
