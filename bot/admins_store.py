import json
from dataclasses import asdict, dataclass
from pathlib import Path

from . import config

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_FILE = DATA_DIR / "admins.json"


@dataclass
class AdminConfig:
    user_id: int
    is_super: bool = False


def _bootstrap_from_env() -> list[AdminConfig]:
    """Разовая загрузка из ADMIN_IDS в .env — только пока нет файла
    data/admins.json. Дальше админы добавляются/удаляются командой
    /admins, доступной только супер-админу. Первый id из ADMIN_IDS
    становится супер-админом."""
    admins = []
    for i, user_id in enumerate(sorted(config.ADMIN_IDS)):
        admins.append(AdminConfig(user_id=user_id, is_super=(i == 0)))
    return admins


class AdminStore:
    def __init__(self):
        self._admins: list[AdminConfig] = []
        self._load()

    def _load(self) -> None:
        if DATA_FILE.exists():
            raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            self._admins = [AdminConfig(**a) for a in raw]
        else:
            self._admins = _bootstrap_from_env()
            self._save()

    def _save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        DATA_FILE.write_text(
            json.dumps([asdict(a) for a in self._admins], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def all(self) -> list[AdminConfig]:
        return list(self._admins)

    def ids(self) -> list[int]:
        return [a.user_id for a in self._admins]

    def is_admin(self, user_id: int) -> bool:
        return not self._admins or any(a.user_id == user_id for a in self._admins)

    def is_super(self, user_id: int) -> bool:
        return any(a.user_id == user_id and a.is_super for a in self._admins)

    def add(self, user_id: int) -> None:
        if user_id not in self.ids():
            self._admins.append(AdminConfig(user_id=user_id))
            self._save()

    def remove(self, user_id: int) -> None:
        self._admins = [a for a in self._admins if a.user_id != user_id]
        self._save()
