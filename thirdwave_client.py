"""
ThirdWave API Client - Async HTTP client for ThirdWave panel API
"""
import logging
import asyncio
import httpx
from config import THIRDWAVE_API_KEY, THIRDWAVE_BASE_URL

logger = logging.getLogger(__name__)


class ThirdWaveClient:
    def __init__(self):
        self.base_url = THIRDWAVE_BASE_URL.rstrip("/")
        self.api_key = THIRDWAVE_API_KEY
        self.timeout = httpx.Timeout(15.0, connect=5.0)
        self._client = None

    def _get_client(self):
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def _headers(self):
        return {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",
        }

    async def get_traffic(self, limit=50):
        """Fetch traffic/OTP messages from ThirdWave API."""
        url = f"{self.base_url}/traffic"
        params = {"api_key": self.api_key, "limit": limit}
        client = self._get_client()
        for attempt in range(3):
            try:
                resp = await client.get(url, headers=self._headers(), params=params)
                if resp.status_code == 429:
                    retry = int(resp.headers.get("Retry-After", "5"))
                    logger.warning(f"ThirdWave rate limited, retrying in {retry}s (attempt {attempt+1})")
                    await asyncio.sleep(retry)
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                if attempt == 2:
                    logger.error(f"ThirdWave request error: {e}")
                    raise
                await asyncio.sleep(1)
        return {"items": []}
