import os

# Lamix
LAMIX_API_KEY = os.getenv("LAMIX_API_KEY", "")
LAMIX_BASE_URL = os.getenv("LAMIX_BASE_URL", "https://panel.lamix.org/api/v1")
LAMIX_POLL_INTERVAL = int(os.getenv("LAMIX_POLL_INTERVAL", "15"))

# ThirdWave
THIRDWAVE_API_KEY = os.getenv("THIRDWAVE_API_KEY", "")
THIRDWAVE_BASE_URL = os.getenv("THIRDWAVE_BASE_URL", "https://clients.thirdwave.im/api/v1")
THIRDWAVE_POLL_INTERVAL = int(os.getenv("THIRDWAVE_POLL_INTERVAL", "15"))

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_GROUP_LINK = os.getenv("TELEGRAM_GROUP_LINK", "https://t.me/Toyibfilenumber")
TELEGRAM_DISCUSS_LINK = os.getenv("TELEGRAM_DISCUSS_LINK", "https://t.me/Toyibdiskusi")
