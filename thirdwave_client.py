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

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",
        }

    async def get_traffic(self, page=1, page_size=50):
        """Fetch traffic/OTP messages from ThirdWave API."""
        url = f"{self.base_url}/traffic"
        params = {"page": page, "pageSize": page_size}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(3):
                resp = await client.get(url, headers=self._headers(), params=params)
                if resp.status_code == 429:
                    retry = int(resp.headers.get("Retry-After", "5"))
                    logger.warning(f"ThirdWave rate limited, retrying in {retry}s (attempt {attempt+1})")
                    await asyncio.sleep(retry)
                    continue
                resp.raise_for_status()
                return resp.json()
        return {"rows": [], "total": 0}
