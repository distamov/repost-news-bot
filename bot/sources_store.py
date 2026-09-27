import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_FILE = DATA_DIR / "sources.json"

_TME_RE = re.compile(r"t\.me/([A-Za-z0-9_]+)")


@dataclass
class SourceConfig:
    id: str  # "@username" канала-источника


def extract_username(raw: str) -> str:
    """Приводит ссылку (https://t.me/name) или голое имя к виду "@name"."""
    raw = raw.strip()
    match = _TME_RE.search(raw)
    if match:
        return "@" + match.group(1)
    return raw if raw.startswith("@") else "@" + raw.lstrip("@")


def _bootstrap_from_env() -> list[SourceConfig]:
    raw = os.environ.get("SOURCE_CHANNELS", "")
    return [SourceConfig(id=s.strip()) for s in raw.split(",") if s.strip()]


class SourceStore:
    def __init__(self):
        self._sources: list[SourceConfig] = []
        self._load()

    def _load(self) -> None:
        if DATA_FILE.exists():
            raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            self._sources = [SourceConfig(**s) for s in raw]
        else:
            self._sources = _bootstrap_from_env()
            self._save()

    def _save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        DATA_FILE.write_text(
            json.dumps([asdict(s) for s in self._sources], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def all(self) -> list[SourceConfig]:
        return list(self._sources)

    def ids(self) -> list[str]:
        return [s.id for s in self._sources]

    def add(self, source_id: str) -> None:
        source_id = extract_username(source_id)
        if source_id.lower() not in (s.lower() for s in self.ids()):
            self._sources.append(SourceConfig(id=source_id))
            self._save()

    def remove(self, index: int) -> None:
        self._sources.pop(index)
        self._save()

    def get(self, index: int):
        return self._sources[index] if 0 <= index < len(self._sources) else None

    def matches(self, chat) -> bool:
        """Проверяет, входит ли telethon-чат (канал) в список источников."""
        username = (getattr(chat, "username", None) or "").lower()
        chat_id = getattr(chat, "id", None)
        for s in self._sources:
            sid = str(s.id).lstrip("@").lower()
            if username and sid == username:
                return True
            if chat_id is not None and str(chat_id) == str(s.id):
                return True
        return False
