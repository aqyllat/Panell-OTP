"""
Lamix + ThirdWave OTP Telegram Bot
===================================
Polls Lamix & ThirdWave APIs for WhatsApp OTP messages and forwards them to Telegram.
"""
import re
import os
import json
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from telegram import Update, Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.constants import ParseMode
from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    LAMIX_POLL_INTERVAL,
    LAMIX_API_KEY,
    THIRDWAVE_API_KEY,
    THIRDWAVE_POLL_INTERVAL,
    MARKO_USERNAME,
    MARKO_PASSWORD,
    MARKO_POLL_INTERVAL,
    VORN_USERNAME,
    VORN_PASSWORD,
    VORN_POLL_INTERVAL,
    TELEGRAM_GROUP_LINK,
    TELEGRAM_DISCUSS_LINK,
)
from lamix_client import LamixClient
from thirdwave_client import ThirdWaveClient
from marko_client import MarkoClient
from vorn_client import VornClient
from country_codes import get_country_info

logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("otp-bot")

# ── State ────────────────────────────────────────────────────
lamix_client = LamixClient()
tw_client = ThirdWaveClient()
marko_client = MarkoClient(MARKO_USERNAME, MARKO_PASSWORD) if MARKO_USERNAME else None
vorn_client = VornClient(VORN_USERNAME, VORN_PASSWORD) if VORN_USERNAME else None
chat_ids_list = [cid.strip() for cid in TELEGRAM_CHAT_ID.split(",") if cid.strip()]

seen_keys: set = set()
# Load existing keys if bot restarted
try:
    if os.path.exists("seen_keys.txt"):
        with open("seen_keys.txt", "r") as f:
            seen_keys = set(line.strip() for line in f if line.strip())
except Exception as e:
    logger.error(f"Failed to load seen_keys: {e}")

def save_seen_key(key: str):
    if key in seen_keys:
        return
    seen_keys.add(key)
    try:
        with open("seen_keys.txt", "a") as f:
            f.write(key + "\n")
    except:
        pass

def is_message_recent(ts_str: str, max_minutes=5) -> bool:
    """Check if message is recent (within max_minutes) handling various timezones."""
    if not ts_str: return True
    try:
        clean_ts = str(ts_str).replace("T", " ").split(".")[0].replace("Z", "").strip()
        msg_time = datetime.strptime(clean_ts, "%Y-%m-%d %H:%M:%S")
        
        now_utc = datetime.utcnow()
        # Common offsets: UTC(0), WIB(7), CET(1), CEST(2)
        for offset in [0, 7, 1, 2, 8, -4, -5]:
            now_local = now_utc + timedelta(hours=offset)
            if abs((now_local - msg_time).total_seconds()) <= max_minutes * 60:
                return True
        return False
    except:
        return True # Fallback

otp_history: list = []
lamix_poll_count: int = 0
tw_poll_count: int = 0
marko_poll_count: int = 0
vorn_poll_count: int = 0
auto_forward: bool = True
bot_start_time: datetime = datetime.now(timezone.utc)

def trim_memory():
    """Prevent Out-Of-Memory (OOM) by capping lists."""
    global otp_history, seen_keys
    if len(otp_history) > 2000:
        otp_history = otp_history[-1000:]
    # `seen_keys` set is also trimmed if it gets ridiculously large.
    # 50,000 strings is only a few MB, so it's safe to let it grow,
    # but we can clear it safely if it gets insanely large.
    if len(seen_keys) > 50000:
        seen_keys.clear()

# ── Watchdog Heartbeat ──────────────────────────────────────
last_heartbeat: dict = {}  # panel_name -> datetime (last successful poll)
WATCHDOG_TIMEOUT = 180  # 3 minutes without polling = dead

def heartbeat(panel: str):
    """Update heartbeat timestamp for a panel."""
    last_heartbeat[panel] = datetime.now(timezone.utc)

async def watchdog(app: Application):
    """Kill process if any active panel stops polling for too long."""
    await asyncio.sleep(60)  # Give panels time to start up
    
    while True:
        await asyncio.sleep(60)
        now = datetime.now(timezone.utc)
        
        # Clean up memory occasionally
        trim_memory()
        
        panels_to_check = {}
        if LAMIX_API_KEY:
            panels_to_check["lamix"] = "Lamix"
        if THIRDWAVE_API_KEY:
            panels_to_check["thirdwave"] = "ThirdWave"
        if MARKO_USERNAME:
            panels_to_check["marko"] = "Marko"
        if VORN_USERNAME:
            panels_to_check["vorn"] = "Vorn"
        
        for key, name in panels_to_check.items():
            last = last_heartbeat.get(key)
            if last is None:
                continue  # Hasn't started yet
            diff = (now - last).total_seconds()
            if diff > WATCHDOG_TIMEOUT:
                logger.error(f"🚨 WATCHDOG: {name} hasn't polled in {int(diff)}s! Force restarting...")
                # Notify telegram before dying
                try:
                    for cid in chat_ids_list:
                        await app.bot.send_message(
                            chat_id=cid,
                            text=f"🚨 *Bot Auto-Restart*\n\n⚠️ Panel `{name}` stuck selama `{int(diff)}s`.\n🔄 Restarting...",
                            parse_mode=ParseMode.MARKDOWN,
                        )
                except:
                    pass
                await asyncio.sleep(2)
                os._exit(1)  # Force kill → Railway auto-restart

# ── OTP Extraction ──────────────────────────────────────────
OTP_RE = [
    re.compile(r"code[:\s]*(\d{3}[\-\s]?\d{3})", re.I),
    re.compile(r"(\d{3}[\-\s]\d{3})"),
    re.compile(r"(\d{4,6})"),  # fallback for other OTP formats
]

def extract_otp(text: str) -> str:
    for pat in OTP_RE:
        m = pat.search(text)
        if m:
            return m.group(1)
    return "N/A"

# ── Format Message ──────────────────────────────────────────
from country_codes import get_country_info

def get_language(content: str) -> str:
    c = content.lower()
    if "kode" in c or "adalah" in c: return "#ID"
    if "código" in c or "codigo" in c: return "#ES"
    if "code" in c: return "#EN"
    if "mã" in c: return "#VN"
    if "รหัส" in c: return "#TH"
    return "#EN"

def format_otp_msg(record: dict, source: str = "lamix") -> tuple[str, str]:
    num = str(record.get("number", "")).lstrip("+").strip()
    content = record.get("content", "") or record.get("message", "") or record.get("body", "") or ""

    flag, code = get_country_info(num)
    lang = get_language(content)
    otp = extract_otp(content)

    prefix = f"+{num[:5]}"
    last4 = num[-4:] if len(num) >= 9 else num

    # Custom Emojis
    emoji_api = '<tg-emoji emoji-id="5334964352229321286">🔥</tg-emoji>'
    emoji_ketawa = '<tg-emoji emoji-id="5334665890656954850">😂</tg-emoji>'
    emoji_wa = '<tg-emoji emoji-id="5008044786121179993">🟩</tg-emoji>'

    mask = emoji_api
    
    text = f"{flag} {code} | WA {emoji_wa} {prefix} {mask} {last4} {lang}\n{emoji_ketawa} Not Bang Toyib {emoji_ketawa}\nPrefix: <tg-spoiler>{prefix}</tg-spoiler>"
    return text, otp


# ── Send OTP to Telegram ────────────────────────────────────
async def send_otp_to_telegram(bot: Bot, chat_id: str, record: dict, source: str = "lamix"):
    """Format and send an OTP message to Telegram."""
    text, otp = format_otp_msg(record, source)

    keyboard = [
        [InlineKeyboardButton(text=f"📋 {otp}", api_kwargs={"copy_text": {"text": otp}})],
        [
            InlineKeyboardButton(text="📞 Numbers", url=TELEGRAM_GROUP_LINK),
            InlineKeyboardButton(text="💬 Discuss", url=TELEGRAM_DISCUSS_LINK)
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Telegram send error ({source}): {e}")
    await asyncio.sleep(0.5)


# ── Lamix Polling Task ──────────────────────────────────────
async def poll_lamix(app: Application) -> None:
    global lamix_poll_count
    if not LAMIX_API_KEY:
        logger.info("Lamix API key not set, skipping Lamix polling")
        return

    bot: Bot = app.bot

    while True:
        try:
            now = datetime.now(timezone.utc)
            from_dt = now - timedelta(seconds=max(LAMIX_POLL_INTERVAL * 2, 60))
            params_from = from_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            params_to = now.strftime("%Y-%m-%dT%H:%M:%SZ")

            data = await lamix_client.get_messages(params_from, params_to)
            records = data.get("records", [])
            lamix_poll_count += 1
            heartbeat("lamix")

            new_msgs = []
            for r in records:
                key = f"lamix-{r.get('time','')}-{r.get('number','')}"
                if key not in seen_keys:
                    save_seen_key(key)
                    r["_source"] = "lamix"
                    otp_history.append(r)
                    if is_message_recent(r.get("time", ""), max_minutes=5):
                        new_msgs.append(r)

            if new_msgs and auto_forward and chat_ids_list:
                for msg in new_msgs:
                    for cid in chat_ids_list:
                        await send_otp_to_telegram(bot, cid, msg, "lamix")

            if new_msgs:
                logger.info(f"Lamix Poll #{lamix_poll_count}: {len(new_msgs)} new OTP(s)")
            else:
                if lamix_poll_count % 20 == 0:
                    logger.info(f"Lamix Poll #{lamix_poll_count}: no new messages")

        except Exception as exc:
            logger.error(f"Lamix poll error: {exc}")

        await asyncio.sleep(LAMIX_POLL_INTERVAL)


# ── ThirdWave Polling Task ──────────────────────────────────
async def poll_thirdwave(app: Application) -> None:
    global tw_poll_count
    if not THIRDWAVE_API_KEY:
        logger.info("ThirdWave API key not set, skipping ThirdWave polling")
        return

    bot: Bot = app.bot

    while True:
        try:
            data = await tw_client.get_traffic(page=1, page_size=50)
            rows = data.get("rows", [])
            tw_poll_count += 1
            heartbeat("thirdwave")

            new_msgs = []
            for r in rows:
                # ThirdWave actual field names
                num = r.get("destinationNumber", "")
                ts = r.get("receivedAt", "")
                content = r.get("messageBody", "")
                rec_id = r.get("id", "")

                # Normalize record to our standard format
                normalized = {
                    "number": str(num).lstrip("+"),
                    "content": content,
                    "time": ts,
                    "cli": r.get("sourceAddress", "WhatsApp"),
                    "range": r.get("rangeName", "ThirdWave"),
                    "payout": r.get("rate", 0),
                    "status": r.get("status", "pending"),
                    "_source": "thirdwave",
                }

                key = f"tw-{rec_id}"
                if key not in seen_keys:
                    save_seen_key(key)
                    otp_history.append(normalized)
                    if is_message_recent(ts, max_minutes=5):
                        new_msgs.append(normalized)

            if new_msgs and auto_forward and chat_ids_list:
                for msg in new_msgs:
                    for cid in chat_ids_list:
                        await send_otp_to_telegram(bot, cid, msg, "thirdwave")

            if new_msgs:
                logger.info(f"ThirdWave Poll #{tw_poll_count}: {len(new_msgs)} new OTP(s)")
            else:
                if tw_poll_count % 20 == 0:
                    logger.info(f"ThirdWave Poll #{tw_poll_count}: no new messages")

        except Exception as exc:
            logger.error(f"ThirdWave poll error: {exc}")

        await asyncio.sleep(THIRDWAVE_POLL_INTERVAL)

async def poll_marko(app: Application) -> None:
    global marko_poll_count
    if not marko_client:
        logger.info("Marko credentials not set, skipping Marko polling")
        return

    bot: Bot = app.bot

    while True:
        try:
            data = await marko_client.get_messages()
            records = data.get("records", [])
            marko_poll_count += 1
            heartbeat("marko")

            new_msgs = []
            for r in records:
                # Based on our standard format
                key = f"marko-{r.get('time','')}-{r.get('number','')}-{r.get('sender','')}"
                if key not in seen_keys:
                    save_seen_key(key)
                    otp_history.append(r)
                    if is_message_recent(r.get("time", ""), max_minutes=5):
                        new_msgs.append(r)

            if new_msgs and auto_forward and chat_ids_list:
                for msg in new_msgs:
                    for cid in chat_ids_list:
                        await send_otp_to_telegram(bot, cid, msg, "marko")

            if new_msgs:
                logger.info(f"Marko Poll #{marko_poll_count}: {len(new_msgs)} new OTP(s)")
            else:
                if marko_poll_count % 20 == 0:
                    logger.info(f"Marko Poll #{marko_poll_count}: no new messages")

        except Exception as exc:
            logger.error(f"Marko poll error: {exc}")

        await asyncio.sleep(MARKO_POLL_INTERVAL)

async def poll_vorn(app: Application) -> None:
    global vorn_poll_count
    if not vorn_client:
        logger.info("Vorn credentials not set, skipping Vorn polling")
        return

    bot: Bot = app.bot

    while True:
        try:
            data = await vorn_client.get_messages()
            records = data.get("records", [])
            vorn_poll_count += 1
            heartbeat("vorn")

            new_msgs = []
            for r in records:
                # Based on our standard format
                key = f"vorn-{r.get('time','')}-{r.get('number','')}-{r.get('sender','')}"
                if key not in seen_keys:
                    save_seen_key(key)
                    
                    # Update source name for display purposes
                    r["_source"] = "vorn"
                    otp_history.append(r)
                    if is_message_recent(r.get("time", ""), max_minutes=5):
                        new_msgs.append(r)

            if new_msgs and auto_forward and chat_ids_list:
                for msg in new_msgs:
                    for cid in chat_ids_list:
                        await send_otp_to_telegram(bot, cid, msg, "vorn")

            if new_msgs:
                logger.info(f"Vorn Poll #{vorn_poll_count}: {len(new_msgs)} new OTP(s)")
            else:
                if vorn_poll_count % 20 == 0:
                    logger.info(f"Vorn Poll #{vorn_poll_count}: no new messages")

        except Exception as exc:
            logger.error(f"Vorn poll error: {exc}")

        await asyncio.sleep(VORN_POLL_INTERVAL)


# ── Bot Commands ────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    panels = []
    if LAMIX_API_KEY:
        panels.append(f"🔵 Lamix: `...{LAMIX_API_KEY[-8:]}`")
    if THIRDWAVE_API_KEY:
        panels.append(f"🟣 ThirdWave: `...{THIRDWAVE_API_KEY[-8:]}`")
    if MARKO_USERNAME:
        panels.append(f"🟠 Marko: `{MARKO_USERNAME}`")
    if VORN_USERNAME:
        panels.append(f"🟡 Vorn: `{VORN_USERNAME}`")

    text = (
        "🤖 *OTP Monitor Bot*\n\n"
        "Bot ini monitor SMS OTP dari multi-panel dan forward ke chat ini.\n\n"
        "*Active Panels:*\n" + "\n".join(panels) + "\n\n"
        "*Commands:*\n"
        "/status - Status polling & statistik\n"
        "/recent - 10 OTP terakhir\n"
        "/ranges - Daftar range aktif (Lamix)\n"
        "/otp - Toggle auto-forward ON/OFF\n"
        "/chatid - Lihat Chat ID kamu\n\n"
        f"⏱️ Poll interval: `{LAMIX_POLL_INTERVAL}s`"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def cmd_chatid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    await update.message.reply_text(
        f"📋 *Chat ID:* `{cid}`\n\nCopy ini ke env variable `TELEGRAM_CHAT_ID`",
        parse_mode=ParseMode.MARKDOWN,
    )

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uptime = datetime.now(timezone.utc) - bot_start_time
    hours = int(uptime.total_seconds() // 3600)
    mins = int((uptime.total_seconds() % 3600) // 60)

    lamix_otps = sum(1 for r in otp_history if r.get("_source") == "lamix")
    tw_otps = sum(1 for r in otp_history if r.get("_source") == "thirdwave")
    marko_otps = sum(1 for r in otp_history if r.get("_source") == "marko")
    vorn_otps = sum(1 for r in otp_history if r.get("_source") == "vorn")

    text = (
        f"📊 *OTP Bot Status*\n\n"
        f"⏱️ Uptime: `{hours}h {mins}m`\n"
        f"📡 Auto-forward: `{'ON ✅' if auto_forward else 'OFF ❌'}`\n\n"
        f"🔵 *Lamix:*\n"
        f"  🔄 Polls: `{lamix_poll_count}`\n"
        f"  📬 OTPs: `{lamix_otps}`\n"
        f"  {'🟢 Active' if LAMIX_API_KEY else '⚫ Disabled'}\n\n"
        f"🟣 *ThirdWave:*\n"
        f"  🔄 Polls: `{tw_poll_count}`\n"
        f"  📬 OTPs: `{tw_otps}`\n"
        f"  {'🟢 Active' if THIRDWAVE_API_KEY else '⚫ Disabled'}\n\n"
        f"🟠 *Marko:*\n"
        f"  🔄 Polls: `{marko_poll_count}`\n"
        f"  📬 OTPs: `{marko_otps}`\n"
        f"  {'🟢 Active' if MARKO_USERNAME else '⚫ Disabled'}\n\n"
        f"🟡 *Vorn:*\n"
        f"  🔄 Polls: `{vorn_poll_count}`\n"
        f"  📬 OTPs: `{vorn_otps}`\n"
        f"  {'🟢 Active' if VORN_USERNAME else '⚫ Disabled'}\n\n"
        f"📬 Total OTP: `{len(otp_history)}`\n"
        f"🎯 Tracked keys: `{len(seen_keys)}`"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def cmd_recent(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not otp_history:
        await update.message.reply_text("📭 Belum ada OTP yang diterima.")
        return

    last10 = otp_history[-10:]
    lines = ["📱 *10 OTP Terakhir:*\n"]
    for i, r in enumerate(last10, 1):
        t = r.get("time", "")[:16].replace("T", " ")
        num = r.get("number", "?")
        otp = extract_otp(r.get("content", ""))
        lines.append(f"`{i}.` `{t}` | `+{num}` | 🔑 `{otp}`")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

async def cmd_ranges(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        data = await lamix_client.get_ranges()
        records = data.get("records", [])
        if not records:
            await update.message.reply_text("📭 Tidak ada range aktif.")
            return

        lines = ["🌍 *Active Ranges (Lamix):*\n"]
        for r in records:
            name = r.get("name", "?")
            prefix = r.get("prefix", "?")
            count = r.get("count", 0)
            status = r.get("status", "?")
            icon = "🟢" if status == "active" else "🔴"
            lines.append(f"{icon} `+{prefix}` | {name} | `{count}` numbers")

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def cmd_otp_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global auto_forward
    auto_forward = not auto_forward
    status = "ON ✅" if auto_forward else "OFF ❌"
    await update.message.reply_text(
        f"📡 Auto-forward OTP: *{status}*", parse_mode=ParseMode.MARKDOWN
    )

async def btn_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

# ── Main ────────────────────────────────────────────────────
async def post_init(app: Application):
    """Start polling tasks after bot initializes."""
    # Start Lamix polling
    asyncio.create_task(poll_lamix(app))
    logger.info("Lamix polling task started")

    # Start ThirdWave polling
    asyncio.create_task(poll_thirdwave(app))
    logger.info("ThirdWave polling task started")

    # Start Marko polling
    asyncio.create_task(poll_marko(app))
    logger.info("Marko polling task started")

    # Start Vorn polling
    asyncio.create_task(poll_vorn(app))
    logger.info("Vorn polling task started")

    # Start Watchdog 🐕
    asyncio.create_task(watchdog(app))
    logger.info("Watchdog task started")

    if chat_ids_list:
        panels_active = []
        if LAMIX_API_KEY:
            panels_active.append("🔵 Lamix")
        if THIRDWAVE_API_KEY:
            panels_active.append("🟣 ThirdWave")
        if MARKO_USERNAME:
            panels_active.append("🟠 Marko")
        if VORN_USERNAME:
            panels_active.append("🟡 Vorn")

        for cid in chat_ids_list:
            try:
                await app.bot.send_message(
                    chat_id=cid,
                    text=(
                        "🟢 *OTP Bot Started!*\n\n"
                        f"📡 Panels: {', '.join(panels_active)}\n"
                        f"⏱️ Polling every `{LAMIX_POLL_INTERVAL}s`\n\n"
                        "Ketik /help untuk daftar command."
                    ),
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception as e:
                logger.error(f"Startup msg error for {cid}: {e}")

def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set!")
        return
    if not LAMIX_API_KEY and not THIRDWAVE_API_KEY:
        logger.error("No API keys set! Need at least LAMIX_API_KEY or THIRDWAVE_API_KEY")
        return

    logger.info("Starting Multi-Panel OTP Telegram Bot...")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("recent", cmd_recent))
    app.add_handler(CommandHandler("ranges", cmd_ranges))
    app.add_handler(CommandHandler("otp", cmd_otp_toggle))
    app.add_handler(CommandHandler("chatid", cmd_chatid))
    app.add_handler(CallbackQueryHandler(btn_callback))

    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
