import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Не задана переменная окружения {name} (см. .env.example)")
    return value


ROOT = Path(__file__).resolve().parent.parent

MONTAGE_BOT_TOKEN = _required("MONTAGE_BOT_TOKEN")
GROQ_API_KEY = _required("GROQ_API_KEY")
TELEGRAM_API_ID = int(_required("TELEGRAM_API_ID"))
TELEGRAM_API_HASH = _required("TELEGRAM_API_HASH")

_admins_raw = os.environ.get("MONTAGE_ADMIN_IDS") or os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = {int(x) for x in _admins_raw.split(",") if x.strip()}

DATA_DIR = ROOT / "data" / "montage"
WORK_DIR = Path(os.environ.get("MONTAGE_WORK_DIR") or Path(tempfile.gettempdir()) / "montage")
FONT_PATH = Path(__file__).resolve().parent / "assets" / "Montserrat-Bold.otf"

LOGO_PATH = DATA_DIR / "logo.png"
MUSIC_PATH = DATA_DIR / "music.m4a"

# Положение и размер лого/субтитров замерены по готовым роликам канала (720×1280).
LOGO_WIDTH = int(os.environ.get("MONTAGE_LOGO_WIDTH", "146"))
LOGO_Y = int(os.environ.get("MONTAGE_LOGO_Y", "249"))
MUSIC_VOLUME_DB = float(os.environ.get("MONTAGE_MUSIC_DB", "-25"))
