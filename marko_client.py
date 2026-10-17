import httpx
import re
import logging
import time
from datetime import datetime

logger = logging.getLogger("otp-bot.marko")

class MarkoClient:
    def __init__(self, username, password):
        self.base_url = "http://51.75.144.178/ints"
        self.username = username
        self.password = password
        self.client = None
        self.is_logged_in = False
        self._last_fail_time = 0

    def _get_client(self):
        if self.client is None or self.client.is_closed:
            self.client = httpx.AsyncClient(
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Origin": "http://51.75.144.178",
                    "Referer": "http://51.75.144.178/ints/login",
                },
                follow_redirects=True,
                timeout=25.0
            )
        return self.client

    async def login(self):
        # Don't spin in a tight failure loop if credentials are wrong
        now = time.time()
        if now - self._last_fail_time < 60:
            return False

        client = self._get_client()
        try:
            # 1. Get Login Page & Captcha
            r1 = await client.get(f"{self.base_url}/login")
            m = re.search(r'What is (\d+)\s*\+\s*(\d+)\s*=\s*\?', r1.text)
            if not m:
                logger.error("Marko: Captcha not found on login page.")
                self._last_fail_time = time.time()
                return False
            
            capt = str(int(m.group(1)) + int(m.group(2)))
            
            # 2. Submit Login
            data = {
                "username": self.username,
                "password": self.password,
                "capt": capt
            }
            r2 = await client.post(
                f"{self.base_url}/signin", 
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            
            if "Invalid" in r2.text or "Error" in r2.text:
                logger.warning("Marko: Login failed! Invalid Username/Password. Retrying in 60s...")
                self.is_logged_in = False
                self._last_fail_time = time.time()
                return False
            
            logger.info("Marko: Successfully logged in.")
            self.is_logged_in = True
            return True
            
        except Exception as e:
            logger.error(f"Marko login error: {e}")
            self._last_fail_time = time.time()
            return False

    async def get_messages(self):
        if not self.is_logged_in:
            success = await self.login()
            if not success:
                return {"records": []}
        
        client = self._get_client()
        try:
            # 1. Fetch SMSCDRReports page to obtain dynamic sAjaxSource containing active sesskey
            r_page = await client.get(f"{self.base_url}/agent/SMSCDRReports")
            if "login" in str(r_page.url) or "What is" in r_page.text:
                logger.info("Marko: Session expired, re-logging in...")
                self.is_logged_in = False
                success = await self.login()
                if not success:
                    return {"records": []}
                r_page = await client.get(f"{self.base_url}/agent/SMSCDRReports")

            # Extract sAjaxSource containing active sesskey and date parameters
            m = re.search(r'"sAjaxSource":\s*"([^"]+)"', r_page.text)
            if m:
                ajax_url = m.group(1).lstrip("/")
                if not ajax_url.startswith("http"):
                    ajax_url = f"{self.base_url}/agent/{ajax_url}"
            else:
                now = datetime.now()
                d_start = now.strftime("%Y-%m-%d 00:00:00")
                d_end = now.strftime("%Y-%m-%d 23:59:59")
                ajax_url = f"{self.base_url}/agent/res/data_smscdr.php?fdate1={d_start}&fdate2={d_end}&fg=0"

            req_headers = {
                "X-Requested-With": "XMLHttpRequest", 
                "Referer": f"{self.base_url}/agent/SMSCDRReports"
            }
            
            r = await client.get(ajax_url, headers=req_headers)
            
            # Check if session expired or empty
            if "Direct Script Access Not Allowed" in r.text or r.status_code != 200 or not r.text.strip():
                logger.warning("Marko: Empty or invalid response from CDR endpoint.")
                return {"records": []}
                
            data = r.json()
            aaData = data.get("aaData", [])
            
            records = []
            for row in aaData:
                # Based on standard DataTables: 
                # row[0]=Date, row[1]=Range, row[2]=Number, row[3]=CLI/Sender, row[4]=Client, row[5]=SMS Message, row[6]=Currency, row[7]=Rate
                if not row or not isinstance(row, list) or len(row) < 6:
                    continue
                if isinstance(row[0], str) and row[0].startswith("0,"):
                    continue
                if str(row[2]) == "0" and str(row[5]) == "0":
                    continue
                    
                sms_text = str(row[5])
                # Remove any HTML tags just in case
                sms_text = re.sub(r'<[^>]+>', '', sms_text)
                
                records.append({
                    "time": str(row[0]),
                    "range": str(row[1]) if len(row) > 1 else "Marko",
                    "number": str(row[2]),
                    "sender": str(row[3]) if len(row) > 3 else "WhatsApp",
                    "content": sms_text,
                    "payout": row[7] if len(row) > 7 else 0,
                    "_source": "marko"
                })
            return {"records": records}
            
        except Exception as e:
            logger.error(f"Marko get_messages error: {e}")
            self.is_logged_in = False  # Force re-login next try
            return {"records": []}
