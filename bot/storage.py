import json
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional, Union

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MEDIA_DIR = DATA_DIR / "pending_media"
DATA_FILE = DATA_DIR / "pending.json"

# Данные медиа-элемента — либо URL/file_id (str), либо сырые байты (bytes).
MediaData = Union[str, bytes]


@dataclass
class MediaItem:
    kind: str  # "photo" или "video"
    data: MediaData


@dataclass
class PendingPost:
    id: str
    text: str
    keywords: str
    # Варианты медиа для поста: несколько стоковых фото по одному в списке,
    # плюс, если есть, оригинал(ы) из исходного поста последним вариантом
    # (может быть несколько элементов — например альбом из пары видео).
    media_options: list[list[MediaItem]]
    chat_id: int
    requester_id: int
    target_channel_id: object
    option_index: int = 0
    media_message_ids: list = field(default_factory=list)
    text_message_id: Optional[int] = None
    has_original: bool = False
    signature: str = ""
    # Время создания превью (unix). У записей, сохранённых до появления
    # поля, остаётся 0 — они считаются самыми старыми.
    created_at: float = 0.0


@dataclass
class PendingSelection:
    """Пост, для которого ещё не выбрали канал публикации."""

    id: str
    text: str
    photo_bytes: Optional[bytes]
    original_media: list
    chat_id: int
    requester_id: int
    created_at: float = 0.0


def _serialize_media_options(pid: str, media_options: list[list[MediaItem]]) -> list[list[dict]]:
    """Байтовые данные (скачанные оригиналы) пишутся на диск, строковые
    (file_id/URL) остаются инлайн в JSON — как в ScheduledStore."""
    records = []
    for opt_idx, option in enumerate(media_options):
        option_records = []
        for item_idx, item in enumerate(option):
            if isinstance(item.data, bytes):
                folder = MEDIA_DIR / pid
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / f"{opt_idx}_{item_idx}.bin"
                path.write_bytes(item.data)
                option_records.append(
                    {"kind": item.kind, "file_path": str(path.relative_to(DATA_DIR))}
                )
            else:
                option_records.append({"kind": item.kind, "file_id": item.data})
        records.append(option_records)
    return records


def _deserialize_media_options(records: list[list[dict]]) -> list[list[MediaItem]]:
    media_options = []
    for option_records in records:
        option = []
        for rec in option_records:
            if rec.get("file_path"):
                data = (DATA_DIR / rec["file_path"]).read_bytes()
                option.append(MediaItem(rec["kind"], data))
            else:
                option.append(MediaItem(rec["kind"], rec["file_id"]))
        media_options.append(option)
    return media_options


class Storage:
    def __init__(self):
        self._items: dict[str, PendingPost] = {}
        self._selections: dict[str, PendingSelection] = {}
        self._group_buffers: dict[str, list] = {}
        self._load()

    def _load(self) -> None:
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        if DATA_FILE.exists():
            raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            for rec in raw:
                rec = dict(rec)
                rec["media_options"] = _deserialize_media_options(rec["media_options"])
                self._items[rec["id"]] = PendingPost(**rec)

    def _save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        records = []
        for item in self._items.values():
            rec = asdict(item)
            rec["media_options"] = _serialize_media_options(item.id, item.media_options)
            records.append(rec)
        DATA_FILE.write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def save(self, pid: str) -> None:
        """Вызывать после любой мутации полей PendingPost (его дата-класс
        мутируется на месте, напрямую через присваивание атрибутов) —
        чтобы изменение пережило рестарт бота."""
        self._save()

    def create(self, **kwargs) -> PendingPost:
        pid = uuid.uuid4().hex[:8]
        kwargs.setdefault("created_at", time.time())
        item = PendingPost(id=pid, **kwargs)
        self._items[pid] = item
        self._save()
        return item

    def get(self, pid: str) -> Optional[PendingPost]:
        return self._items.get(pid)

    def delete(self, pid: str) -> None:
        self._items.pop(pid, None)
        self._save()
        folder = MEDIA_DIR / pid
        if folder.exists():
            for f in folder.iterdir():
                f.unlink(missing_ok=True)
            folder.rmdir()

    def _matching(self, before: float, owner_id: Optional[int]):
        """Превью и незавершённые выборы канала, созданные не позже `before`.
        owner_id=None — чьи угодно (для супер-админа), иначе только свои."""
        def ok(x) -> bool:
            return x.created_at <= before and (owner_id is None or x.requester_id == owner_id)

        posts = [p for p in self._items.values() if ok(p)]
        selections = [s for s in self._selections.values() if ok(s)]
        return posts, selections

    def cache_stats(self, before: float, owner_id: Optional[int]) -> tuple[int, int, int]:
        """(сколько превью, сколько медиафайлов, сколько байт) попадёт под очистку."""
        posts, selections = self._matching(before, owner_id)
        files = size = 0
        for p in posts:
            for option in p.media_options:
                for m in option:
                    if isinstance(m.data, bytes):
                        files += 1
                        size += len(m.data)
        for s in selections:
            # photo_bytes обычно тот же объект, что и фото в original_media.
            blobs = {id(b): b for b in [s.photo_bytes] + [m.data for m in s.original_media]}
            for b in blobs.values():
                if isinstance(b, bytes):
                    files += 1
                    size += len(b)
        return len(posts) + len(selections), files, size

    def clear_cache(self, before: float, owner_id: Optional[int]) -> int:
        """Удаляет превью (с их фото/видео на диске) и незавершённые выборы
        канала, созданные не позже `before`. Отложенные посты не трогает.
        Сохраняет очередь один раз, а не на каждое удаление."""
        posts, selections = self._matching(before, owner_id)
        for p in posts:
            self._items.pop(p.id, None)
        for s in selections:
            self._selections.pop(s.id, None)
        self._save()
        for p in posts:
            shutil.rmtree(MEDIA_DIR / p.id, ignore_errors=True)
        if owner_id is None and MEDIA_DIR.exists():
            # Папки, на которые не ссылается ни одно оставшееся превью, —
            # мусор от старых версий бота.
            for folder in MEDIA_DIR.iterdir():
                if folder.is_dir() and folder.name not in self._items:
                    shutil.rmtree(folder, ignore_errors=True)
        return len(posts) + len(selections)

    def create_selection(self, **kwargs) -> PendingSelection:
        sid = uuid.uuid4().hex[:8]
        kwargs.setdefault("created_at", time.time())
        item = PendingSelection(id=sid, **kwargs)
        self._selections[sid] = item
        return item

    def get_selection(self, sid: str) -> Optional[PendingSelection]:
        return self._selections.get(sid)

    def delete_selection(self, sid: str) -> None:
        self._selections.pop(sid, None)

    def buffer_group_item(self, group_id, message) -> None:
        self._group_buffers.setdefault(str(group_id), []).append(message)

    def get_group(self, group_id) -> list:
        return list(self._group_buffers.get(str(group_id), []))

    def delete_group(self, group_id) -> None:
        self._group_buffers.pop(str(group_id), None)
