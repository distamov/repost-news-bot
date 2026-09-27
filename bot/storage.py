import uuid
from dataclasses import dataclass, field
from typing import Optional, Union

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


@dataclass
class PendingSelection:
    """Пост, для которого ещё не выбрали канал публикации."""

    id: str
    text: str
    photo_bytes: Optional[bytes]
    original_media: list
    chat_id: int
    requester_id: int


class Storage:
    def __init__(self):
        self._items: dict[str, PendingPost] = {}
        self._selections: dict[str, PendingSelection] = {}
        self._group_buffers: dict[str, list] = {}

    def create(self, **kwargs) -> PendingPost:
        pid = uuid.uuid4().hex[:8]
        item = PendingPost(id=pid, **kwargs)
        self._items[pid] = item
        return item

    def get(self, pid: str) -> Optional[PendingPost]:
        return self._items.get(pid)

    def delete(self, pid: str) -> None:
        self._items.pop(pid, None)

    def create_selection(self, **kwargs) -> PendingSelection:
        sid = uuid.uuid4().hex[:8]
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
