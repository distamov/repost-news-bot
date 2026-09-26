import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Не задана переменная окружения {name} (см. .env.example)")
    return value


BOT_TOKEN = _required("BOT_TOKEN")
GEMINI_API_KEY = _required("GEMINI_API_KEY")
PEXELS_API_KEY = _required("PEXELS_API_KEY")

# Необязательный второй источник фото — pixabay.com/api/docs (бесплатно).
# Если не задан, поиск идёт только по Pexels.
PIXABAY_API_KEY = os.environ.get("PIXABAY_API_KEY", "")

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")

def _parse_chat_id(raw: str):
    return int(raw) if raw.lstrip("-").isdigit() else raw


@dataclass
class ChannelConfig:
    id: object  # int (приватный канал) или "@username" (публичный)
    label: str
    language: str  # "ru" или "uz"
    signature: str


def _load_channels() -> list[ChannelConfig]:
    channels = []
    i = 1
    while True:
        raw_id = os.environ.get(f"CHANNEL_{i}_ID")
        if not raw_id:
            break
        label = os.environ.get(f"CHANNEL_{i}_LABEL", raw_id)
        language = os.environ.get(f"CHANNEL_{i}_LANG", "uz").strip().lower()
        signature = os.environ.get(f"CHANNEL_{i}_SIGNATURE", "")
        channels.append(
            ChannelConfig(
                id=_parse_chat_id(raw_id), label=label, language=language, signature=signature
            )
        )
        i += 1
    return channels


# Список каналов публикации: CHANNEL_1_ID, CHANNEL_2_ID, ... (см. .env.example).
# Каждый канал — со своим языком (ru/uz) и своей подписью/ссылкой в конце поста.
CHANNELS = _load_channels()
if not CHANNELS:
    raise RuntimeError(
        "Не задано ни одного канала: заполни CHANNEL_1_ID (и опционально "
        "CHANNEL_1_LABEL / CHANNEL_1_LANG / CHANNEL_1_SIGNATURE) в .env"
    )

_admin_ids_raw = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = {int(x) for x in _admin_ids_raw.split(",") if x.strip()}

# Автомониторинг каналов-источников (через Telethon user-сессию).
# Всё это опционально: если не заполнено, бот просто не запускает мониторинг
# и работает только в ручном режиме (/rewrite).
_api_id_raw = os.environ.get("TELEGRAM_API_ID", "")
TELEGRAM_API_ID = int(_api_id_raw) if _api_id_raw.strip() else None
TELEGRAM_API_HASH = os.environ.get("TELEGRAM_API_HASH") or None
TELEGRAM_SESSION = os.environ.get("TELEGRAM_SESSION") or None

_sources_raw = os.environ.get("SOURCE_CHANNELS", "")
SOURCE_CHANNELS = [s.strip() for s in _sources_raw.split(",") if s.strip()]

_moderation_raw = os.environ.get("MODERATION_CHAT_ID", "")
if _moderation_raw.strip():
    MODERATION_CHAT_ID = (
        int(_moderation_raw) if _moderation_raw.lstrip("-").isdigit() else _moderation_raw
    )
else:
    MODERATION_CHAT_ID = None

MONITOR_ENABLED = bool(
    TELEGRAM_API_ID and TELEGRAM_API_HASH and TELEGRAM_SESSION and SOURCE_CHANNELS
)
