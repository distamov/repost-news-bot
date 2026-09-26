import uuid
from dataclasses import dataclass
from typing import Optional, Union

# Элемент фото — либо URL/file_id (str), либо сырые байты картинки (bytes).
Photo = Union[str, bytes]


@dataclass
class PendingPost:
    id: str
    text: str
    keywords: str
    photo_urls: list[Photo]
    chat_id: int
    requester_id: int
    target_channel_id: object
    photo_index: int = 0
    photo_message_id: Optional[int] = None
    text_message_id: Optional[int] = None
    combined: bool = False


@dataclass
class PendingSelection:
    """Пост, для которого ещё не выбрали канал публикации."""

    id: str
    text: str
    photo_bytes: Optional[bytes]
    chat_id: int
    requester_id: int


class Storage:
    def __init__(self):
        self._items: dict[str, PendingPost] = {}
        self._selections: dict[str, PendingSelection] = {}

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
