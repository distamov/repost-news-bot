import logging

import httpx

logger = logging.getLogger(__name__)


class PhotoService:
    """Ищет иллюстрации сразу в нескольких бесплатных фотостоках (Pexels,
    Pixabay — если задан ключ, и Openverse — без ключа вообще) и берёт
    только горизонтальные фото, чтобы пост не растягивался по вертикали."""

    def __init__(self, pexels_api_key: str, pixabay_api_key: str = ""):
        self._pexels = httpx.AsyncClient(
            base_url="https://api.pexels.com/v1",
            headers={"Authorization": pexels_api_key},
            timeout=15,
        )
        self._pixabay_key = pixabay_api_key
        self._pixabay = httpx.AsyncClient(base_url="https://pixabay.com/api", timeout=15)
        self._openverse = httpx.AsyncClient(base_url="https://api.openverse.org/v1", timeout=15)

    async def search(self, query: str, per_page: int = 6) -> list[str]:
        results: list[str] = []

        try:
            results += await self._search_pexels(query, per_page)
        except Exception:
            logger.exception("Pexels search failed")

        if self._pixabay_key:
            try:
                results += await self._search_pixabay(query, per_page)
            except Exception:
                logger.exception("Pixabay search failed")

        try:
            results += await self._search_openverse(query, per_page)
        except Exception:
            logger.exception("Openverse search failed")

        return results

    async def _search_pexels(self, query: str, per_page: int) -> list[str]:
        response = await self._pexels.get(
            "/search",
            params={"query": query, "per_page": per_page, "orientation": "landscape"},
        )
        response.raise_for_status()
        data = response.json()
        return [photo["src"]["large"] for photo in data.get("photos", [])]

    async def _search_pixabay(self, query: str, per_page: int) -> list[str]:
        response = await self._pixabay.get(
            "/",
            params={
                "key": self._pixabay_key,
                "q": query,
                "per_page": max(per_page, 3),  # у Pixabay минимум 3
                "orientation": "horizontal",
                "safesearch": "true",
                "image_type": "photo",
            },
        )
        response.raise_for_status()
        data = response.json()
        return [hit["largeImageURL"] for hit in data.get("hits", [])]

    async def _search_openverse(self, query: str, per_page: int) -> list[str]:
        response = await self._openverse.get(
            "/images/",
            params={
                "q": query,
                "page_size": per_page,
                "aspect_ratio": "wide",
                "license_type": "commercial",
            },
        )
        response.raise_for_status()
        data = response.json()
        return [item["url"] for item in data.get("results", []) if item.get("url")]

    async def close(self):
        await self._pexels.aclose()
        await self._pixabay.aclose()
        await self._openverse.aclose()
