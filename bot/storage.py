import uuid
from dataclasses import dataclass
from typing import Optional


@dataclass
class PendingPost:
    id: str
    text: str
    keywords: str
    photo_urls: list[str]
    chat_id: int
    requester_id: int
    photo_index: int = 0
    photo_message_id: Optional[int] = None
    text_message_id: Optional[int] = None


class Storage:
    def __init__(self):
        self._items: dict[str, PendingPost] = {}

    def create(self, **kwargs) -> PendingPost:
        pid = uuid.uuid4().hex[:8]
        item = PendingPost(id=pid, **kwargs)
        self._items[pid] = item
        return item

    def get(self, pid: str) -> Optional[PendingPost]:
        return self._items.get(pid)

    def delete(self, pid: str) -> None:
        self._items.pop(pid, None)
