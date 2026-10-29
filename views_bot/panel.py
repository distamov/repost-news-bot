import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)


class PanelError(Exception):
    """Панель ответила {"error": ...} — заказ точно не создан."""


class PanelUnknownResult(Exception):
    """Запрос ушёл, но ответа нет — заказ мог создаться, а мог и нет."""


class SocProofPanel:
    """Клиент API soc-proof.su (стандартный API SMM-панелей, /api/v2)."""

    def __init__(self, api_url: str, api_key: str):
        self._url = api_url
        self._key = api_key
        self._client = httpx.AsyncClient(timeout=30)

    async def close(self) -> None:
        await self._client.aclose()

    async def _call(self, **params) -> dict | list:
        resp = await self._client.post(self._url, data={"key": self._key, **params})
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("error"):
            raise PanelError(data["error"])
        return data

    async def balance(self) -> float:
        data = await self._call(action="balance")
        return float(data["balance"])

    async def service(self, service_id: int) -> dict:
        for s in await self._call(action="services"):
            if int(s["service"]) == service_id:
                return s
        raise PanelError(f"Услуга {service_id} не найдена в панели")

    async def statuses(self, order_ids: list[int]) -> dict:
        if not order_ids:
            return {}
        return await self._call(action="status", orders=",".join(map(str, order_ids)))

    async def add_dripfeed(
        self, service_id: int, link: str, quantity: int, runs: int, interval: int
    ) -> int:
        """Создаёт drip-feed заказ и возвращает его номер.

        Повторяет запрос, только если соединение не установилось (тогда
        заказ гарантированно не создан). Если ответ просто не дошёл —
        повтор мог бы купить просмотры дважды, поэтому PanelUnknownResult."""
        params = dict(
            action="add", service=service_id, link=link,
            quantity=quantity, runs=runs, interval=interval,
        )
        for attempt in range(1, 4):
            try:
                data = await self._call(**params)
                return int(data["order"])
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                logger.warning("Панель недоступна (попытка %d/3): %s", attempt, e)
                if attempt == 3:
                    raise PanelError(f"панель недоступна: {e}") from e
                await asyncio.sleep(30)
            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500 and attempt < 3:
                    logger.warning("Панель ответила %s (попытка %d/3)", e.response.status_code, attempt)
                    await asyncio.sleep(30)
                    continue
                raise PanelUnknownResult(f"HTTP {e.response.status_code}") from e
            except httpx.HTTPError as e:
                raise PanelUnknownResult(repr(e)) from e
