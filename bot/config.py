import os

from dotenv import load_dotenv

load_dotenv()


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Не задана переменная окружения {name} (см. .env.example)")
    return value


# Если задан (Render и похожие хостинги задают его сами) — запускается
# служебный HTTP-сервер для проверки "жив ли" сервис.
PORT = os.environ.get("PORT")

BOT_TOKEN = _required("BOT_TOKEN")
GEMINI_API_KEY = _required("GEMINI_API_KEY")
PEXELS_API_KEY = _required("PEXELS_API_KEY")

# Необязательный второй источник фото — pixabay.com/api/docs (бесплатно).
# Если не задан, поиск идёт только по Pexels.
PIXABAY_API_KEY = os.environ.get("PIXABAY_API_KEY", "")

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")

# Список каналов публикации теперь хранится и управляется через
# bot/channels_store.py (команда /channels в боте), а не .env — CHANNEL_N_*
# переменные используются только для самой первой загрузки, один раз.

_admin_ids_raw = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = {int(x) for x in _admin_ids_raw.split(",") if x.strip()}

# Автомониторинг каналов-источников (через Telethon user-сессию).
# Всё это опционально: если не заполнено, бот просто не запускает мониторинг
# и работает только в ручном режиме (/rewrite).
_api_id_raw = os.environ.get("TELEGRAM_API_ID", "")
TELEGRAM_API_ID = int(_api_id_raw) if _api_id_raw.strip() else None
TELEGRAM_API_HASH = os.environ.get("TELEGRAM_API_HASH") or None
TELEGRAM_SESSION = os.environ.get("TELEGRAM_SESSION") or None

# Список источников теперь хранится и управляется через bot/sources_store.py
# (команда /sources в боте) — SOURCE_CHANNELS используется только там, для
# самой первой загрузки, один раз.

_moderation_raw = os.environ.get("MODERATION_CHAT_ID", "")
if _moderation_raw.strip():
    MODERATION_CHAT_ID = (
        int(_moderation_raw) if _moderation_raw.lstrip("-").isdigit() else _moderation_raw
    )
else:
    MODERATION_CHAT_ID = None

MONITOR_ENABLED = bool(TELEGRAM_API_ID and TELEGRAM_API_HASH and TELEGRAM_SESSION)

# Публиковать финальный пост в канал через Telethon-аккаунт (а не через
# Bot API) — нужно только для анимации премиум-эмодзи, которую Bot API
# не умеет слать в каналы вообще ни при каких условиях. Требует, чтобы
# у аккаунта из TELEGRAM_SESSION были Telegram Premium и права публикации
# в канале — иначе просто отвалится в Bot API автоматически (см.
# bot/telethon_posting.py). Выключено по умолчанию, пока не подтверждены
# оба условия.
TELETHON_PUBLISH = os.environ.get("TELETHON_PUBLISH", "").strip().lower() in ("1", "true", "yes")
