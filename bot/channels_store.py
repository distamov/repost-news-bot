import json
import os
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_FILE = DATA_DIR / "channels.json"


@dataclass
class ChannelConfig:
    id: object  # int (приватный канал) или "@username" (публичный)
    label: str
    language: str = "uz"  # "ru" или "uz"
    signature: str = ""
    owner_id: int = 0  # telegram user id админа-владельца
    uid: str = ""  # стабильный id записи (для callback_data, не зависит от позиции)


def parse_chat_id(raw: str):
    raw = raw.strip()
    return int(raw) if raw.lstrip("-").isdigit() else raw


def _bootstrap_from_env() -> list[ChannelConfig]:
    """Разовая загрузка из CHANNEL_N_* переменных .env — только пока нет
    файла data/channels.json. Дальше все изменения каналов идут через
    команду /channels в боте и хранятся в этом файле."""
    channels = []
    i = 1
    while True:
        raw_id = os.environ.get(f"CHANNEL_{i}_ID")
        if not raw_id:
            break
        channels.append(
            ChannelConfig(
                id=parse_chat_id(raw_id),
                label=os.environ.get(f"CHANNEL_{i}_LABEL", raw_id),
                language=os.environ.get(f"CHANNEL_{i}_LANG", "uz").strip().lower(),
                signature=os.environ.get(f"CHANNEL_{i}_SIGNATURE", ""),
            )
        )
        i += 1
    return channels


class ChannelStore:
    def __init__(self, default_owner_id: int = 0):
        self._channels: list[ChannelConfig] = []
        self._default_owner_id = default_owner_id
        self._load()

    def _load(self) -> None:
        if DATA_FILE.exists():
            raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            self._channels = [ChannelConfig(**c) for c in raw]
        else:
            self._channels = _bootstrap_from_env()
            self._save()

        # Миграция записей, созданных до появления owner_id/uid (мульти-админка).
        migrated = False
        for ch in self._channels:
            if not ch.uid:
                ch.uid = uuid.uuid4().hex[:8]
                migrated = True
            if not ch.owner_id:
                ch.owner_id = self._default_owner_id
                migrated = True
        if migrated:
            self._save()

    def _save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        DATA_FILE.write_text(
            json.dumps([asdict(c) for c in self._channels], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def all(self) -> list[ChannelConfig]:
        return list(self._channels)

    def all_for(self, owner_id: int) -> list[ChannelConfig]:
        return [c for c in self._channels if c.owner_id == owner_id]

    def get(self, index: int):
        return self._channels[index] if 0 <= index < len(self._channels) else None

    def get_by_uid(self, uid: str):
        return next((c for c in self._channels if c.uid == uid), None)

    def add(self, channel: ChannelConfig) -> None:
        self._channels.append(channel)
        self._save()

    def update(self, index: int, **kwargs) -> None:
        channel = self._channels[index]
        for key, value in kwargs.items():
            setattr(channel, key, value)
        self._save()

    def update_by_uid(self, uid: str, **kwargs) -> None:
        channel = self.get_by_uid(uid)
        if not channel:
            return
        for key, value in kwargs.items():
            setattr(channel, key, value)
        self._save()

    def remove(self, index: int) -> None:
        self._channels.pop(index)
        self._save()

    def remove_by_uid(self, uid: str) -> None:
        self._channels = [c for c in self._channels if c.uid != uid]
        self._save()
