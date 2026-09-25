import httpx


class PhotoService:
    def __init__(self, api_key: str):
        self._client = httpx.AsyncClient(
            base_url="https://api.pexels.com/v1",
            headers={"Authorization": api_key},
            timeout=15,
        )

    async def search(self, query: str, per_page: int = 6) -> list[str]:
        response = await self._client.get(
            "/search", params={"query": query, "per_page": per_page}
        )
        response.raise_for_status()
        data = response.json()
        return [photo["src"]["large"] for photo in data.get("photos", [])]

    async def close(self):
        await self._client.aclose()
