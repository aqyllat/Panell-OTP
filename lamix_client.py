"""
Lamix API Client - Async HTTP client for Lamix panel API
"""
import logging
import asyncio
import httpx
from config import LAMIX_API_KEY, LAMIX_BASE_URL

logger = logging.getLogger(__name__)


class LamixClient:
    def __init__(self):
        self.base_url = LAMIX_BASE_URL.rstrip("/")
        self.api_key = LAMIX_API_KEY
        self.timeout = httpx.Timeout(15.0, connect=5.0)

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

    async def _get(self, endpoint, params=None):
        """GET request with retry on 429."""
        url = f"{self.base_url}/{endpoint}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(3):
                resp = await client.get(url, headers=self._headers(), params=params)
                if resp.status_code == 429:
                    retry = int(resp.headers.get("Retry-After", "5"))
                    logger.warning(f"Rate limited, retrying in {retry}s (attempt {attempt+1})")
                    await asyncio.sleep(retry)
                    continue
                resp.raise_for_status()
                return resp.json()
        return {"records": [], "count": 0}

    async def get_messages(self, from_ts, to_ts, limit=500, cli=None):
        """Fetch messages from Lamix API."""
        params = {"from": from_ts, "to": to_ts, "limit": limit}
        if cli:
            params["cli"] = cli
        return await self._get("messages", params)

    async def get_ranges(self):
        """Fetch active ranges."""
        return await self._get("ranges")

    async def get_numbers(self, limit=100):
        """Fetch numbers."""
        return await self._get("numbers", {"limit": limit})
