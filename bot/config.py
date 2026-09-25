import os

from dotenv import load_dotenv

load_dotenv()


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Не задана переменная окружения {name} (см. .env.example)")
    return value


BOT_TOKEN = _required("BOT_TOKEN")
ANTHROPIC_API_KEY = _required("ANTHROPIC_API_KEY")
PEXELS_API_KEY = _required("PEXELS_API_KEY")

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

_target_raw = _required("TARGET_CHANNEL_ID")
TARGET_CHANNEL_ID = int(_target_raw) if _target_raw.lstrip("-").isdigit() else _target_raw

_admin_ids_raw = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = {int(x) for x in _admin_ids_raw.split(",") if x.strip()}
