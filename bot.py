import asyncio
import aiohttp
import time
import random
import string
import logging
import json
import threading
import zlib
from urllib.request import Request, urlopen
from urllib.parse import urlencode

# ============================
# CONFIG
# ============================
BOT_TOKEN = "8640503315:AAEhs3cmht25QNtmCIunWaE8uGInrusqJMQ"
OWNER_ID = 7876142027
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(
    format="%(asctime)s - %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

# ============================
# TELEGRAM API (RAW)
# ============================
def api_call(method, params=None, timeout=30):
    url = f"{API_URL}/{method}"
    try:
        data = urlencode(params).encode("utf-8") if params else b""
        req = Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        resp = urlopen(req, timeout=timeout)
        return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log.error(f"API error {method}: {e}")
        return {"ok": False, "error": str(e)}

def send_msg(chat_id, text):
    return api_call("sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true"
    })

# ============================
# STATS (use dict to avoid global issues)
# ============================
STATS = {"checked": 0, "found": 0, "taken": 0, "errors": 0}
FOUND_LIST = []
HUNT_STATE = {"start_time": None, "is_hunting": False}
LAST_UPDATE_ID = 0

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
        ]),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15), ssl=False) as resp:
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
    except Exception:
        return "conn_error"

# ============================
# HUNT LOOP (FIXED - uses dict!)
# ============================
def run_hunt(chat_id):
    HUNT_STATE["is_hunting"] = True
    HUNT_STATE["start_time"] = time.time()
    STATS["checked"] = 0
    STATS["found"] = 0
    STATS["taken"] = 0
    STATS["errors"] = 0
    FOUND_LIST.clear()
    
    log.info("HUNT THREAD STARTED!")
    send_msg(chat_id, "Hunt thread started! Beginning scan...")
    
    async def hunt():
        log.info("Creating aiohttp session...")
        connector = aiohttp.TCPConnector(limit=10, force_close=True, enable_cleanup_closed=True)
        async with aiohttp.ClientSession(connector=connector) as session:
            log.info("Session created! Starting combo loop...")
            batch = []
            last_update = time.time()
            batch_num = 0
            
            for combo in generate_combos():
                if not HUNT_STATE["is_hunting"]:
                    log.info("Hunt stopped by user.")
                    break
                
                batch.append(combo)
                
                if len(batch) >= 8:
                    batch_num += 1
                    log.info(f"Batch #{batch_num}: checking {batch[:2]}... (total: {STATS['checked']})")
                    
                    tasks = [check_username(session, u) for u in batch]
                    try:
                        results = await asyncio.gather(*tasks, return_exceptions=True)
                    except Exception as e:
                        log.error(f"Batch error: {e}")
                        STATS["errors"] += len(batch)
                        batch = []
                        continue
                    
                    for i, result in enumerate(results):
                        username = batch[i]
                        STATS["checked"] += 1
                        
                        if isinstance(result, Exception):
                            STATS["errors"] += 1
                            log.error(f"Exception @{username}: {result}")
                            continue
                        
                        if result == "available":
                            STATS["found"] += 1
                            FOUND_LIST.append(username)
                            log.info(f"*** FOUND AVAILABLE: @{username} ***")
                            send_msg(chat_id,
                                f"FOUND AVAILABLE!\n\n@{username}\n\nhttps://www.tiktok.com/@{username}")
                        elif result == "taken":
                            STATS["taken"] += 1
                        elif result == "rate_limit":
                            STATS["errors"] += 1
                            log.warning("Rate limited! Sleeping 5s...")
                            await asyncio.sleep(5)
                        elif result == "timeout":
                            STATS["errors"] += 1
                            log.warning(f"Timeout @{username}")
                        elif result == "conn_error":
                            STATS["errors"] += 1
                            log.warning(f"Conn error @{username}")
                        else:
                            STATS["errors"] += 1
                    
                    batch = []
                    
                    now = time.time()
                    if now - last_update >= 30:
                        last_update = now
                        elapsed = now - HUNT_STATE["start_time"]
                        speed = STATS["checked"] / elapsed if elapsed > 0 else 0
                        remaining = 46656 - STATS["checked"]
                        eta = remaining / speed if speed > 0 else 0
                        h = int(eta // 3600)
                        m = int((eta % 3600) // 60)
                        log.info(f"Progress: {STATS['checked']}/46656 | Speed: {speed:.1f}/sec")
                        send_msg(chat_id,
                            f"PROGRESS\n\n"
                            f"Checked: {STATS['checked']}/46656\n"
                            f"Found: {STATS['found']} | Taken: {STATS['taken']}\n"
                            f"Errors: {STATS['errors']}\n"
                            f"Speed: {speed:.1f}/sec\n"
                            f"ETA: {h}h {m}m")
                    
                    await asyncio.sleep(0.2)
            
            HUNT_STATE["is_hunting"] = False
            elapsed = time.time() - HUNT_STATE["start_time"]
            speed = STATS["checked"] / elapsed if elapsed > 0 else 0
            log.info(f"HUNT DONE: {STATS['checked']} checked, {STATS['found']} found")
            send_msg(chat_id,
                f"HUNT COMPLETE!\n\n"
                f"Checked: {STATS['checked']}/46656\n"
                f"Found: {STATS['found']}\n"
                f"Taken: {STATS['taken']}\n"
                f"Errors: {STATS['errors']}\n"
                f"Speed: {speed:.1f}/sec\n"
                f"Time: {int(elapsed//3600)}h {int((elapsed%3600)//60)}m")
    
    try:
        asyncio.run(hunt())
    except Exception as e:
        log.error(f"HUNT CRASHED: {e}")
        HUNT_STATE["is_hunting"] = False
        send_msg(chat_id, f"Hunt crashed: {str(e)}")

# ============================
# COMMAND HANDLERS
# ============================
def handle_command(chat_id, user_id, command, args):
    if user_id != OWNER_ID:
        return
    
    if command == "/start":
        send_msg(chat_id,
            "SYRIA HUB - TikTok Username Hunter V3.8\n\n"
            "Commands:\n"
            "/test <username> - Check single username\n"
            "/debug <username> - Debug detection\n"
            "/hunt3 - Hunt 3-char combos (46656)\n"
            "/status - Show progress\n"
            "/found - Show found usernames\n"
            "/stop - Stop current hunt")
    
    elif command == "/test":
        if not args:
            send_msg(chat_id, "Usage: /test <username>")
            return
        username = args[0].replace("@", "")
        send_msg(chat_id, f"Checking @{username}...")
        
        async def do_check():
            connector = aiohttp.TCPConnector(force_close=True)
            async with aiohttp.ClientSession(connector=connector) as session:
                return await check_username(session, username)
        
        result = asyncio.run(do_check())
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
        send_msg(chat_id, f"@{username} = {status_map.get(result, '[?] UNKNOWN')}")
    
    elif command == "/debug":
        if not args:
            send_msg(chat_id, "Usage: /debug <username>")
            return
        username = args[0].replace("@", "")
        send_msg(chat_id, f"Debugging @{username}...")
        
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
                    async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15), ssl=False) as resp:
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
        
        result = asyncio.run(do_debug())
        send_msg(chat_id, result[:4000])
    
    elif command == "/hunt3":
        if HUNT_STATE["is_hunting"]:
            send_msg(chat_id, "Already hunting! Use /stop first.")
            return
        send_msg(chat_id,
            "Starting 3-char hunt!\n"
            "Total: 46,656 combos\n"
            "Pattern: [a-z0-9]{3}\n\n"
            "Use /status to check progress\n"
            "Use /stop to stop")
        t = threading.Thread(target=run_hunt, args=(chat_id,), daemon=True)
        t.start()
        log.info("Hunt thread launched!")
    
    elif command == "/status":
        c = STATS["checked"]
        f = STATS["found"]
        t = STATS["taken"]
        e = STATS["errors"]
        remaining = 46656 - c
        speed = 0
        eta_str = "N/A"
        if HUNT_STATE["start_time"] and c > 0:
            elapsed = time.time() - HUNT_STATE["start_time"]
            if elapsed > 0:
                speed = c / elapsed
                eta_sec = remaining / speed if speed > 0 else 0
                h = int(eta_sec // 3600)
                m = int((eta_sec % 3600) // 60)
                eta_str = f"{h}h {m}m"
        hunting_status = "HUNTING" if HUNT_STATE["is_hunting"] else "STOPPED"
        send_msg(chat_id,
            f"STATUS [{hunting_status}]\n\n"
            f"Checked: {c}/46656\n"
            f"Found: {f} | Taken: {t}\n"
            f"Errors: {e}\n"
            f"Speed: {speed:.1f}/sec\n"
            f"ETA: {eta_str}")
    
    elif command == "/found":
        if not FOUND_LIST:
            send_msg(chat_id,
                f"No available usernames found yet.\n\n"
                f"Checked: {STATS['checked']} | Taken: {STATS['taken']}\n"
                f"Keep hunting!")
        else:
            lines = "\n".join([f"@{u}" for u in FOUND_LIST[:50]])
            send_msg(chat_id, f"Found {len(FOUND_LIST)} usernames:\n\n{lines}")
    
    elif command == "/stop":
        HUNT_STATE["is_hunting"] = False
        send_msg(chat_id, "Hunt stopped!")

# ============================
# POLLING LOOP (RAW)
# ============================
def polling_loop():
    global LAST_UPDATE_ID
    log.info("Bot is running! Polling for updates...")
    
    while True:
        try:
            params = {
                "timeout": 30,
                "offset": LAST_UPDATE_ID + 1,
                "allowed_updates": json.dumps(["message"])
            }
            result = api_call("getUpdates", params, timeout=35)
            
            if result.get("ok") and result.get("result"):
                for update in result["result"]:
                    LAST_UPDATE_ID = update["update_id"]
                    msg = update.get("message", {})
                    if not msg:
                        continue
                    chat_id = msg.get("chat", {}).get("id", 0)
                    user_id = msg.get("from", {}).get("id", 0)
                    text = msg.get("text", "").strip()
                    if not text.startswith("/"):
                        continue
                    parts = text.split()
                    command = parts[0].split("@")[0]
                    args = parts[1:] if len(parts) > 1 else []
                    log.info(f"Command: {command} from user {user_id}")
                    handle_command(chat_id, user_id, command, args)
            elif not result.get("ok"):
                log.error(f"getUpdates failed: {result.get('error')}")
                time.sleep(5)
        except Exception as e:
            log.error(f"Polling error: {e}")
            time.sleep(5)

# ============================
# MAIN
# ============================
def main():
    log.info("=" * 50)
    log.info("SYRIA HUB TikTok Hunter V3.8 (Raw API)")
    log.info("=" * 50)
    polling_loop()

if __name__ == "__main__":
    main()
