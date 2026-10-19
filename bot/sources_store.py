import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_FILE = DATA_DIR / "sources.json"

_TME_RE = re.compile(r"t\.me/([A-Za-z0-9_]+)")


@dataclass
class SourceConfig:
    id: str  # "@username" канала-источника
    owner_id: int = 0  # telegram user id админа-владельца
    uid: str = ""  # стабильный id записи (для callback_data, не зависит от позиции)


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
    def __init__(self, default_owner_id: int = 0):
        self._sources: list[SourceConfig] = []
        self._default_owner_id = default_owner_id
        self._load()

    def _load(self) -> None:
        if DATA_FILE.exists():
            raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            self._sources = [SourceConfig(**s) for s in raw]
        else:
            self._sources = _bootstrap_from_env()
            self._save()

        # Миграция записей, созданных до появления owner_id/uid (мульти-админка).
        migrated = False
        for s in self._sources:
            if not s.uid:
                s.uid = uuid.uuid4().hex[:8]
                migrated = True
            if not s.owner_id:
                s.owner_id = self._default_owner_id
                migrated = True
        if migrated:
            self._save()

    def _save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        DATA_FILE.write_text(
            json.dumps([asdict(s) for s in self._sources], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def all(self) -> list[SourceConfig]:
        return list(self._sources)

    def all_for(self, owner_id: int) -> list[SourceConfig]:
        return [s for s in self._sources if s.owner_id == owner_id]

    def ids(self) -> list[str]:
        return [s.id for s in self._sources]

    def add(self, source_id: str, owner_id: int = 0) -> None:
        source_id = extract_username(source_id)
        if source_id.lower() not in (s.lower() for s in self.ids()):
            self._sources.append(
                SourceConfig(id=source_id, owner_id=owner_id, uid=uuid.uuid4().hex[:8])
            )
            self._save()

    def remove(self, index: int) -> None:
        self._sources.pop(index)
        self._save()

    def remove_by_uid(self, uid: str) -> None:
        self._sources = [s for s in self._sources if s.uid != uid]
        self._save()

    def get(self, index: int):
        return self._sources[index] if 0 <= index < len(self._sources) else None

    def get_by_uid(self, uid: str):
        return next((s for s in self._sources if s.uid == uid), None)

    def matches(self, chat) -> Optional[SourceConfig]:
        """Возвращает SourceConfig, если telethon-чат (канал) входит в
        список источников, иначе None."""
        username = (getattr(chat, "username", None) or "").lower()
        chat_id = getattr(chat, "id", None)
        for s in self._sources:
            sid = str(s.id).lstrip("@").lower()
            if username and sid == username:
                return s
            if chat_id is not None and str(chat_id) == str(s.id):
                return s
        return None
