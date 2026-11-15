import asyncio
import aiohttp
import gzip
import zlib
import time
import random
import string
import logging
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

# ============================
# CONFIG
# ============================
BOT_TOKEN = "8640503315:AAEhs3cmht25QNtmCIunWaE8uGInrusqJMQ"
OWNER_ID = 7876142027

logging.basicConfig(
    format="%(asctime)s - %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

# ============================
# STATS
# ============================
STATS = {
    "checked": 0,
    "found": 0,
    "taken": 0,
    "errors": 0,
}

FOUND_LIST = []
HUNT_START_TIME = None
IS_HUNTING = False

# ============================
# COMBO GENERATOR (lazy)
# ============================
def generate_combos():
    chars = string.ascii_lowercase + string.digits
    for c1 in chars:
        for c2 in chars:
            for c3 in chars:
                yield c1 + c2 + c3

# ============================
# CHECK USERNAME
# ============================
async def check_username(session, username):
    url = f"https://www.tiktok.com/@{username}"
    headers = {
        "User-Agent": random.choice([
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        ]),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10), ssl=False) as resp:
            if resp.status == 200:
                raw = await resp.read()
                try:
                    body = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw).decode("utf-8", errors="ignore")
                except Exception:
                    body = raw.decode("utf-8", errors="ignore")
                if "couldn't find this account" in body.lower():
                    return "available"
                elif "couldn&#x27;t find this account" in body.lower():
                    return "available"
                elif "user_not_found" in body.lower():
                    return "available"
                elif "statusCode\":10221" in body:
                    return "available"
                elif "uniqueId" in body:
                    return "taken"
                elif "followerCount" in body:
                    return "taken"
                else:
                    return "unknown"
            elif resp.status == 429:
                return "rate_limit"
            elif resp.status == 403:
                return "blocked"
            elif resp.status == 404:
                return "available"
            else:
                return "error"
    except asyncio.TimeoutError:
        return "timeout"
    except Exception as e:
        return "conn_error"

# ============================
# HUNT LOOP
# ============================
def run_hunt(chat_id, bot, pattern_len=3):
    global IS_HUNTING, HUNT_START_TIME
    IS_HUNTING = True
    HUNT_START_TIME = time.time()
    STATS["checked"] = 0
    STATS["found"] = 0
    STATS["taken"] = 0
    STATS["errors"] = 0
    FOUND_LIST.clear()
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def hunt():
        connector = aiohttp.TCPConnector(limit=10, force_close=True)
        async with aiohttp.ClientSession(connector=connector) as session:
            batch = []
            last_update = time.time()
            for combo in generate_combos():
                if not IS_HUNTING:
                    break
                batch.append(combo)
                if len(batch) >= 8:
                    tasks = [check_username(session, u) for u in batch]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for i, result in enumerate(results):
                        username = batch[i]
                        STATS["checked"] += 1
                        if result == "available":
                            STATS["found"] += 1
                            FOUND_LIST.append(username)
                            log.info(f"FOUND AVAILABLE: @{username}")
                            try:
                                bot.send_message(
                                    chat_id=chat_id,
                                    text=f"FOUND AVAILABLE!\n\n@{username}\n\nhttps://www.tiktok.com/@{username}"
                                )
                            except Exception:
                                pass
                        elif result == "taken":
                            STATS["taken"] += 1
                        elif result == "rate_limit":
                            STATS["errors"] += 1
                            await asyncio.sleep(5)
                        else:
                            STATS["errors"] += 1
                    batch = []
                    now = time.time()
                    if now - last_update >= 30:
                        last_update = now
                        elapsed = now - HUNT_START_TIME
                        speed = STATS["checked"] / elapsed if elapsed > 0 else 0
                        remaining = 46656 - STATS["checked"]
                        eta = remaining / speed if speed > 0 else 0
                        h = int(eta // 3600)
                        m = int((eta % 3600) // 60)
                        try:
                            bot.send_message(
                                chat_id=chat_id,
                                text=(
                                    f"PROGRESS\n\n"
                                    f"Checked: {STATS['checked']}/46656\n"
                                    f"Found: {STATS['found']} | Taken: {STATS['taken']}\n"
                                    f"Errors: {STATS['errors']}\n"
                                    f"Speed: {speed:.1f}/sec\n"
                                    f"ETA: {h}h {m}m"
                                )
                            )
                        except Exception:
                            pass
                    await asyncio.sleep(0.1)
            IS_HUNTING = False
            elapsed = time.time() - HUNT_START_TIME
            speed = STATS["checked"] / elapsed if elapsed > 0 else 0
            try:
                bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"HUNT COMPLETE!\n\n"
                        f"Checked: {STATS['checked']}/46656\n"
                        f"Found: {STATS['found']}\n"
                        f"Taken: {STATS['taken']}\n"
                        f"Errors: {STATS['errors']}\n"
                        f"Speed: {speed:.1f}/sec\n"
                        f"Time: {int(elapsed//3600)}h {int((elapsed%3600)//60)}m"
                    )
                )
            except Exception:
                pass
    
    loop.run_until_complete(hunt())
    loop.close()

# ============================
# COMMAND HANDLERS (v13)
# ============================
def start_cmd(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID:
        return
    update.message.reply_text(
        "SYRIA HUB - TikTok Username Hunter V3.5\n\n"
        "Commands:\n"
        "/test <username> - Check single username\n"
        "/debug <username> - Debug detection\n"
        "/hunt3 - Hunt 3-char combos (46656)\n"
        "/status - Show progress\n"
        "/found - Show found usernames\n"
        "/stop - Stop current hunt"
    )

def test_cmd(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        update.message.reply_text("Usage: /test <username>")
        return
    username = context.args[0].replace("@", "")
    update.message.reply_text(f"Checking @{username}...")
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def do_check():
        connector = aiohttp.TCPConnector(force_close=True)
        async with aiohttp.ClientSession(connector=connector) as session:
            return await check_username(session, username)
    
    result = loop.run_until_complete(do_check())
    loop.close()
    
    status_map = {
        "available": "[OK] AVAILABLE!",
        "taken": "[X] TAKEN",
        "rate_limit": "[~] RATE LIMITED",
        "blocked": "[!] BLOCKED",
        "timeout": "[~] TIMEOUT",
        "unknown": "[?] UNKNOWN",
        "error": "[!] ERROR",
        "conn_error": "[!] CONN ERROR",
    }
    msg = status_map.get(result, "[?] UNKNOWN")
    update.message.reply_text(f"@{username} = {msg}")

def debug_cmd(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        update.message.reply_text("Usage: /debug <username>")
        return
    username = context.args[0].replace("@", "")
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def do_debug():
        connector = aiohttp.TCPConnector(force_close=True)
        async with aiohttp.ClientSession(connector=connector) as session:
            url = f"https://www.tiktok.com/@{username}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate",
            }
            try:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10), ssl=False) as resp:
                    raw = await resp.read()
                    try:
                        body = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw).decode("utf-8", errors="ignore")
                    except Exception:
                        body = raw.decode("utf-8", errors="ignore")
                    markers = []
                    if "couldn't find this account" in body.lower():
                        markers.append("couldn't find this account -> available")
                    if "user_not_found" in body.lower():
                        markers.append("user_not_found -> available")
                    if "uniqueId" in body:
                        markers.append("uniqueId -> taken")
                    if "followerCount" in body:
                        markers.append("followerCount -> taken")
                    if "statusCode\":10221" in body:
                        markers.append("statusCode 10221 -> available")
                    detect = await check_username(session, username)
                    msg = (
                        f"DEBUG @{username}\n\n"
                        f"HTTP Status: {resp.status}\n"
                        f"Body Length: {len(body)}\n"
                        f"Detect: {detect}\n\n"
                        f"Markers found:\n"
                    )
                    if markers:
                        for m in markers:
                            msg += f"  [+] {m}\n"
                    else:
                        msg += "  [-] None\n"
                    snippet_idx = body.lower().find("couldn")
                    if snippet_idx == -1:
                        snippet_idx = body.lower().find("uniqueid")
                    if snippet_idx >= 0:
                        s = max(0, snippet_idx - 50)
                        e = min(len(body), snippet_idx + 100)
                        msg += f"\nSnippet:\n{body[s:e]}"
                    return msg
            except Exception as e:
                return f"Error: {str(e)}"
    
    result = loop.run_until_complete(do_debug())
    loop.close()
    update.message.reply_text(result[:4000])

def hunt3_cmd(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID:
        return
    global IS_HUNTING
    if IS_HUNTING:
        update.message.reply_text("Already hunting! Use /stop first.")
        return
    update.message.reply_text(
        "Starting 3-char hunt!\n"
        "Total: 46,656 combos\n"
        "Pattern: [a-z0-9]{3}\n\n"
        "Use /status to check progress\n"
        "Use /stop to stop"
    )
    import threading
    t = threading.Thread(target=run_hunt, args=(update.effective_chat.id, context.bot))
    t.daemon = True
    t.start()

def status_cmd(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID:
        return
    c = STATS["checked"]
    f = STATS["found"]
    t = STATS["taken"]
    e = STATS["errors"]
    remaining = 46656 - c
    speed = 0
    eta_str = "N/A"
    if HUNT_START_TIME and c > 0:
        elapsed = time.time() - HUNT_START_TIME
        if elapsed > 0:
            speed = c / elapsed
            eta_sec = remaining / speed if speed > 0 else 0
            h = int(eta_sec // 3600)
            m = int((eta_sec % 3600) // 60)
            eta_str = f"{h}h {m}m"
    hunting_status = "HUNTING" if IS_HUNTING else "STOPPED"
    msg = (
        f"STATUS [{hunting_status}]\n\n"
        f"Checked: {c}/46656\n"
        f"Found: {f} | Taken: {t}\n"
        f"Errors: {e}\n"
        f"Speed: {speed:.1f}/sec\n"
        f"ETA: {eta_str}"
    )
    update.message.reply_text(msg)

def found_cmd(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID:
        return
    if not FOUND_LIST:
        update.message.reply_text(
            f"No available usernames found yet.\n\n"
            f"Checked: {STATS['checked']} | Taken: {STATS['taken']}\n"
            f"Keep hunting!"
        )
    else:
        lines = "\n".join([f"@{u}" for u in FOUND_LIST[:50]])
        update.message.reply_text(
            f"Found {len(FOUND_LIST)} usernames:\n\n{lines}"
        )

def stop_cmd(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID:
        return
    global IS_HUNTING
    IS_HUNTING = False
    update.message.reply_text("Hunt stopped!")

# ============================
# MAIN (v13 API)
# ============================
def main():
    updater = Updater(token=BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start_cmd))
    dp.add_handler(CommandHandler("test", test_cmd))
    dp.add_handler(CommandHandler("debug", debug_cmd))
    dp.add_handler(CommandHandler("hunt3", hunt3_cmd))
    dp.add_handler(CommandHandler("status", status_cmd))
    dp.add_handler(CommandHandler("found", found_cmd))
    dp.add_handler(CommandHandler("stop", stop_cmd))
    
    log.info("Bot is running!")
    updater.start_polling(drop_pending_updates=True)
    updater.idle()

if __name__ == "__main__":
    main()
