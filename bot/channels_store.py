import json
import os
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
    def __init__(self):
        self._channels: list[ChannelConfig] = []
        self._load()

    def _load(self) -> None:
        if DATA_FILE.exists():
            raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            self._channels = [ChannelConfig(**c) for c in raw]
        else:
            self._channels = _bootstrap_from_env()
            self._save()

    def _save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        DATA_FILE.write_text(
            json.dumps([asdict(c) for c in self._channels], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def all(self) -> list[ChannelConfig]:
        return list(self._channels)

    def get(self, index: int):
        return self._channels[index] if 0 <= index < len(self._channels) else None

    def add(self, channel: ChannelConfig) -> None:
        self._channels.append(channel)
        self._save()

    def update(self, index: int, **kwargs) -> None:
        channel = self._channels[index]
        for key, value in kwargs.items():
            setattr(channel, key, value)
        self._save()

    def remove(self, index: int) -> None:
        self._channels.pop(index)
        self._save()
