import json
import time
from pathlib import Path

# Сколько последних постов помнить — чтобы не заказать просмотры дважды
# (например, если Telegram повторно пришлёт апдейт после рестарта).
KEEP_LAST = 2000


class OrderStore:
    """data/views/orders.json: ключ "channel/msg_id" → заказ на этот пост.

    Запись делается ДО запроса в панель: если бот упадёт посередине, пост
    лучше пропустить, чем оплатить дважды."""

    def __init__(self, data_dir: Path):
        self._file = data_dir / "orders.json"
        data_dir.mkdir(parents=True, exist_ok=True)
        self._items: dict[str, dict] = {}
        if self._file.exists():
            self._items = json.loads(self._file.read_text(encoding="utf-8"))

    def _save(self) -> None:
        if len(self._items) > KEEP_LAST:
            for key in list(self._items)[: len(self._items) - KEEP_LAST]:
                del self._items[key]
        self._file.write_text(
            json.dumps(self._items, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def claim(self, key: str, link: str) -> bool:
        """Помечает пост как взятый в работу. False — уже был."""
        if key in self._items:
            return False
        self._items[key] = {"link": link, "order": None, "error": None, "at": time.time()}
        self._save()
        return True

    def set_order(self, key: str, order_id: int) -> None:
        self._items[key]["order"] = order_id
        self._save()

    def set_error(self, key: str, error: str) -> None:
        self._items[key]["error"] = error
        self._save()

    def last(self, n: int) -> list[dict]:
        return list(self._items.values())[-n:]
