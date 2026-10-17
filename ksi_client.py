"""
KSI IPRN API Client - Async HTTP client for KSI IPRN panel API (https://ksiiprn.com/api/v1/iprn)
"""
import logging
import asyncio
import httpx
from config import KSI_API_KEY, KSI_BASE_URL

logger = logging.getLogger("otp-bot.ksi")


class KsiClient:
    def __init__(self):
        self.base_url = KSI_BASE_URL.rstrip("/")
        self.api_key = KSI_API_KEY
        self.timeout = httpx.Timeout(20.0, connect=10.0)
        self._client = None

    def _get_client(self):
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",
        }

    async def get_messages(self, page=1, per_page=50):
        """Fetch messages from KSI IPRN /messages endpoint."""
        if not self.api_key:
            return {"records": []}

        url = f"{self.base_url}/messages"
        params = {"page": page, "per_page": per_page}

        try:
            client = self._get_client()
            for attempt in range(2):
                resp = await client.get(url, headers=self._headers(), params=params)
                if resp.status_code == 429:
                    retry = int(resp.headers.get("Retry-After", "60"))
                    logger.warning(f"KSI rate limited (429), retry after {retry}s")
                    return {"records": []}

                if resp.status_code != 200:
                    logger.error(f"KSI error {resp.status_code}: {resp.text[:200]}")
                    return {"records": []}

                    data = resp.json()
                    raw_items = data.get("data", [])
                    records = []
                    for r in raw_items:
                        num = str(r.get("number") or r.get("destination_number") or r.get("to") or r.get("phone") or "").lstrip("+").strip()
                        content = str(r.get("message") or r.get("text") or r.get("content") or r.get("body") or "").strip()
                        time_val = str(r.get("received_at") or r.get("created_at") or r.get("time") or r.get("timestamp") or r.get("date") or "")
                        sender = str(r.get("sender") or r.get("from") or r.get("source") or r.get("cli") or "WhatsApp")
                        rec_id = str(r.get("id") or r.get("message_id") or f"{num}-{time_val}")

                        records.append({
                            "id": rec_id,
                            "number": num,
                            "content": content,
                            "time": time_val,
                            "cli": sender,
                            "range": str(r.get("range_name") or r.get("range") or "KSI"),
                            "payout": r.get("a2p_rate") or r.get("rate") or r.get("payout") or 0,
                            "status": r.get("status", "received"),
                            "_source": "ksi"
                        })
                    return {"records": records}
        except Exception as e:
            logger.error(f"KSI get_messages error: {e}")
            return {"records": []}
