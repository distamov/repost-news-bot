import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Не задана переменная окружения {name} (см. .env.example)")
    return value


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "views"

BOT_TOKEN = _required("BOT_TOKEN")
SOCPROOF_API_KEY = _required("SOCPROOF_API_KEY")
SOCPROOF_API_URL = os.environ.get("SOCPROOF_API_URL", "https://soc-proof.su/api/v2")

_admins_raw = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = {int(x) for x in _admins_raw.split(",") if x.strip()}

# Публичные каналы (username без @), на посты которых заказываются просмотры.
# Если бота добавят админом куда-то ещё — там он ничего не закажет.
CHANNELS = {
    x.strip().lstrip("@").lower()
    for x in _required("VIEWS_CHANNELS").split(",")
    if x.strip()
}

# Один drip-feed заказ на пост: QUANTITY просмотров × RUNS запусков,
# между запусками INTERVAL минут. 65 × 20 через 35 мин = 1300 за ~11 ч.
SERVICE_ID = int(os.environ.get("VIEWS_SERVICE", "728"))
QUANTITY = int(os.environ.get("VIEWS_QUANTITY", "65"))
RUNS = int(os.environ.get("VIEWS_RUNS", "20"))
INTERVAL = int(os.environ.get("VIEWS_INTERVAL", "35"))

# Альбом приходит пачкой отдельных сообщений — ждём, пока придут все.
ALBUM_WAIT_SECONDS = 5
