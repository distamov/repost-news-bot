import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .storage import MediaItem

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MEDIA_DIR = DATA_DIR / "scheduled_media"
DATA_FILE = DATA_DIR / "scheduled.json"

TASHKENT_TZ = timezone(timedelta(hours=5))  # Узбекистан не переходит на летнее время

_TIME_ONLY_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_DATE_TIME_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\s+(\d{1,2}):(\d{2})$")


def parse_tashkent_time(raw: str, now_utc: Optional[datetime] = None) -> Optional[datetime]:
    """Разбирает "19:30" (сегодня/завтра) или "29.09 08:00" как время в
    Ташкенте, возвращает datetime в UTC (или None, если не удалось понять)."""
    raw = raw.strip()
    now_utc = now_utc or datetime.now(timezone.utc)
    now_tash = now_utc.astimezone(TASHKENT_TZ)

    match = _TIME_ONLY_RE.match(raw)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        if not (0 <= hour < 24 and 0 <= minute < 60):
            return None
        candidate = now_tash.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now_tash:
            candidate += timedelta(days=1)
        return candidate.astimezone(timezone.utc)

    match = _DATE_TIME_RE.match(raw)
    if match:
        day, month, hour, minute = (int(g) for g in match.groups())
        if not (1 <= month <= 12 and 1 <= day <= 31 and 0 <= hour < 24 and 0 <= minute < 60):
            return None
        try:
            candidate = now_tash.replace(
                month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0
            )
        except ValueError:
            return None
        if candidate <= now_tash:
            try:
                candidate = candidate.replace(year=candidate.year + 1)
            except ValueError:
                return None
        return candidate.astimezone(timezone.utc)

    return None


def format_tashkent(dt_utc: datetime) -> str:
    local = dt_utc.astimezone(TASHKENT_TZ)
    return local.strftime("%d.%m %H:%M")


@dataclass
class ScheduledPost:
    id: str
    target_chat_id: int
    text: str
    media: list = field(default_factory=list)  # [{"kind":..., "file_id" | "file_path": ...}]
    publish_at: float = 0.0  # unix timestamp, UTC
    moderation_chat_id: Optional[int] = None
    moderation_message_id: Optional[int] = None


class ScheduledStore:
    def __init__(self):
        self._posts: dict[str, ScheduledPost] = {}
        self._load()

    def _load(self) -> None:
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        if DATA_FILE.exists():
            raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            self._posts = {p["id"]: ScheduledPost(**p) for p in raw}

    def _save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        DATA_FILE.write_text(
            json.dumps([asdict(p) for p in self._posts.values()], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(
        self,
        target_chat_id,
        text: str,
        media: list[MediaItem],
        publish_at_utc: datetime,
        moderation_chat_id=None,
        moderation_message_id: Optional[int] = None,
    ) -> ScheduledPost:
        pid = uuid.uuid4().hex[:10]
        media_records = []
        for i, item in enumerate(media):
            if isinstance(item.data, bytes):
                folder = MEDIA_DIR / pid
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / f"{i}.bin"
                path.write_bytes(item.data)
                media_records.append(
                    {"kind": item.kind, "file_path": str(path.relative_to(DATA_DIR))}
                )
            else:
                media_records.append({"kind": item.kind, "file_id": item.data})

        post = ScheduledPost(
            id=pid,
            target_chat_id=target_chat_id,
            text=text,
            media=media_records,
            publish_at=publish_at_utc.timestamp(),
            moderation_chat_id=moderation_chat_id,
            moderation_message_id=moderation_message_id,
        )
        self._posts[pid] = post
        self._save()
        return post

    def all(self) -> list[ScheduledPost]:
        return list(self._posts.values())

    def due(self, now_ts: float) -> list[ScheduledPost]:
        return [p for p in self._posts.values() if p.publish_at <= now_ts]

    def get(self, pid: str) -> Optional[ScheduledPost]:
        return self._posts.get(pid)

    def remove(self, pid: str) -> None:
        self._posts.pop(pid, None)
        self._save()
        folder = MEDIA_DIR / pid
        if folder.exists():
            for f in folder.iterdir():
                f.unlink(missing_ok=True)
            folder.rmdir()

    def load_media(self, post: ScheduledPost) -> list[MediaItem]:
        items = []
        for rec in post.media:
            if rec.get("file_path"):
                data = (DATA_DIR / rec["file_path"]).read_bytes()
                items.append(MediaItem(rec["kind"], data))
            else:
                items.append(MediaItem(rec["kind"], rec["file_id"]))
        return items
