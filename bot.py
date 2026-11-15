import asyncio
import aiohttp
import gzip
import zlib
import random
import string
import time
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = "8640503315:AAEhs3cmht25QNtmCIunWaE8uGInrusqJMQ"
OWNER_ID = 7876142027

logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

HEADERS_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

WORKERS = 10
BATCH_SIZE = 5
DELAY_MIN = 0.1
DELAY_MAX = 0.4
READ_LIMIT = 65536

hunt_stats = {"checked": 0, "found": 0, "taken": 0, "errors": 0, "start_time": 0, "running": False}
found_usernames = []
hunting = False


def get_header():
    return {
        "User-Agent": random.choice(HEADERS_LIST),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }


def decompress_data(data, encoding):
    try:
        if encoding and "gzip" in encoding:
            d = zlib.decompressobj(16 + zlib.MAX_WBITS)
            return d.decompress(data)
        elif encoding and "deflate" in encoding:
            return zlib.decompress(data)
        return data
    except Exception:
        try:
            return gzip.decompress(data)
        except Exception:
            return data


def detect_username(html):
    if not html:
        return "error"
    h = html.lower()
    taken_markers = ["couldn't find this account", "couldn&#39;t find this account",
                     "page not available", "sorry, this page isn't available",
                     "the page you were looking for doesn't exist",
                     '"accountnotfound"', "user not found", "404"]
    for m in taken_markers:
        if m in h:
            return "taken"
    available_markers = ["uniqueId", "unique_id", "followerCount", "follower_count",
                         "heartcount", "heart_count", "diggcount", "digg_count",
                         "@", "tiktok", "profile", "video"]
    for m in available_markers:
        if m in h:
            return "available"
    return "unknown"


async def check_username(session, username):
    for attempt in range(2):
        try:
            url = f"https://www.tiktok.com/@{username}"
            async with session.get(url, headers=get_header(), timeout=aiohttp.ClientTimeout(total=15),
                                   ssl=False) as resp:
                if resp.status == 200:
                    chunks = []
                    total = 0
                    async for chunk in resp.content.iter_chunked(8192):
                        chunks.append(chunk)
                        total += len(chunk)
                        if total >= READ_LIMIT:
                            break
                    raw = b"".join(chunks)
                    html = decompress_data(raw, resp.headers.get("Content-Encoding", ""))
                    try:
                        html = html.decode("utf-8", errors="ignore")
                    except Exception:
                        html = str(html)
                    return detect_username(html)
                elif resp.status == 404:
                    return "taken"
                elif resp.status == 429:
                    hunt_stats["errors"] += 1
                    await asyncio.sleep(random.uniform(2, 5))
                    continue
                elif resp.status == 403:
                    hunt_stats["errors"] += 1
                    await asyncio.sleep(random.uniform(1, 3))
                    continue
                else:
                    hunt_stats["errors"] += 1
                    if attempt == 1:
                        return "error"
        except asyncio.TimeoutError:
            hunt_stats["errors"] += 1
            if attempt == 1:
                return "timeout"
        except Exception:
            hunt_stats["errors"] += 1
            if attempt == 1:
                return "conn"
    return "error"


def generate_combos(length, prefix="", chars=None):
    if chars is None:
        chars = string.ascii_lowercase + string.digits
    if length == 0:
        yield prefix
    else:
        for c in chars:
            for combo in generate_combos(length - 1, prefix + c, chars):
                yield combo


async def hunt_worker(session, queue, update, context):
    global hunting
    while hunting:
        try:
            username = await asyncio.wait_for(queue.get(), timeout=2)
        except asyncio.TimeoutError:
            continue
        try:
            result = await check_username(session, username)
            hunt_stats["checked"] += 1
            if result == "available":
                hunt_stats["found"] += 1
                found_usernames.append(username)
                msg = f"FOUND: @{username}\nTotal found: {hunt_stats['found']}"
                try:
                    await context.bot.send_message(chat_id=OWNER_ID, text=msg)
                except Exception:
                    pass
            elif result == "taken":
                hunt_stats["taken"] += 1
            await asyncio.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
        except Exception:
            hunt_stats["errors"] += 1
        finally:
            queue.task_done()


async def progress_reporter(update, context):
    global hunting
    last_checked = 0
    while hunting:
        await asyncio.sleep(30)
        if not hunting:
            break
        elapsed = time.time() - hunt_stats["start_time"]
        if elapsed < 1:
            continue
        speed = hunt_stats["checked"] / elapsed
        delta = hunt_stats["checked"] - last_checked
        last_checked = hunt_stats["checked"]
        remaining = max(0, hunt_stats["total"] - hunt_stats["checked"])
        eta_sec = remaining / speed if speed > 0 else 0
        eta_h = int(eta_sec // 3600)
        eta_m = int((eta_sec % 3600) // 60)
        msg = (
            f"PROGRESS\n"
            f"Checked: {hunt_stats['checked']}/{hunt_stats['total']}\n"
            f"Found: {hunt_stats['found']} | Taken: {hunt_stats['taken']}\n"
            f"Errors: {hunt_stats['errors']}\n"
            f"Speed: {speed:.1f}/sec\n"
            f"ETA: {eta_h}h {eta_m}m"
        )
        try:
            await context.bot.send_message(chat_id=OWNER_ID, text=msg)
        except Exception:
            pass


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "SYRIA HUB TikTok Username Hunter v3.4\n\n"
        "Commands:\n"
        "/hunt3 [len] - Hunt 3+ char usernames\n"
        "/hunt4 [len] - Hunt 4+ char usernames\n"
        "/test [name] - Quick test one username\n"
        "/debug [name] - Debug detection for one username\n"
        "/status - Show stats\n"
        "/stop - Stop hunting\n"
        "/found - List found usernames\n"
    )
    await update.message.reply_text(msg)


async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /test username")
        return
    username = context.args[0].replace("@", "")
    await update.message.reply_text(f"Checking @{username} ...")
    async with aiohttp.ClientSession() as session:
        result = await check_username(session, username)
    await update.message.reply_text(f"@{username} = {result}")


async def cmd_debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /debug username")
        return
    username = context.args[0].replace("@", "")
    url = f"https://www.tiktok.com/@{username}"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=get_header(), timeout=aiohttp.ClientTimeout(total=15),
                                   ssl=False) as resp:
                chunks = []
                total = 0
                async for chunk in resp.content.iter_chunked(8192):
                    chunks.append(chunk)
                    total += len(chunk)
                    if total >= READ_LIMIT:
                        break
                raw = b"".join(chunks)
                html = decompress_data(raw, resp.headers.get("Content-Encoding", ""))
                try:
                    html = html.decode("utf-8", errors="ignore")
                except Exception:
                    html = str(html)
                detect = detect_username(html)
                snippet = html[:500] if html else "EMPTY"
                msg = (
                    f"DEBUG @{username}\n"
                    f"Status: {resp.status}\n"
                    f"Bytes: {total}\n"
                    f"Detect: {detect}\n"
                    f"Snippet:\n{snippet}"
                )
                await update.message.reply_text(msg[:4000])
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    elapsed = time.time() - hunt_stats["start_time"] if hunt_stats["start_time"] else 0
    speed = hunt_stats["checked"] / elapsed if elapsed > 0 else 0
    msg = (
        f"Status: {'RUNNING' if hunt_stats['running'] else 'IDLE'}\n"
        f"Checked: {hunt_stats['checked']}\n"
        f"Found: {hunt_stats['found']}\n"
        f"Taken: {hunt_stats['taken']}\n"
        f"Errors: {hunt_stats['errors']}\n"
        f"Speed: {speed:.1f}/sec\n"
    )
    await update.message.reply_text(msg)


async def cmd_found(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not found_usernames:
        await update.message.reply_text("No usernames found yet.")
        return
    lines = [f"@{u}" for u in found_usernames[:100]]
    await update.message.reply_text("\n".join(lines))


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global hunting
    hunting = False
    hunt_stats["running"] = False
    await update.message.reply_text("Hunting stopped.")


async def cmd_hunt(update: Update, context: ContextTypes.DEFAULT_TYPE, min_len=3):
    global hunting
    if hunting:
        await update.message.reply_text("Already hunting! Use /stop first.")
        return
    length = int(context.args[0]) if context.args else min_len
    if length < min_len:
        length = min_len
    chars = string.ascii_lowercase + string.digits
    total = len(chars) ** length
    hunt_stats["checked"] = 0
    hunt_stats["found"] = 0
    hunt_stats["taken"] = 0
    hunt_stats["errors"] = 0
    hunt_stats["total"] = total
    hunt_stats["start_time"] = time.time()
    hunt_stats["running"] = True
    hunting = True
    found_usernames.clear()
    msg = (
        f"HUNTING STARTED\n"
        f"Length: {length}\n"
        f"Total combos: {total}\n"
        f"Workers: {WORKERS}\n"
        f"Batch size: {BATCH_SIZE}"
    )
    await update.message.reply_text(msg)
    queue = asyncio.Queue(maxsize=500)
    async with aiohttp.ClientSession() as session:
        workers = [asyncio.create_task(hunt_worker(session, queue, update, context)) for _ in range(WORKERS)]
        reporter = asyncio.create_task(progress_reporter(update, context))
        count = 0
        for combo in generate_combos(length):
            if not hunting:
                break
            await queue.put(combo)
            count += 1
            if count % 500 == 0:
                await asyncio.sleep(0.01)
        await queue.join()
        hunting = False
        for w in workers:
            w.cancel()
        reporter.cancel()
    elapsed = time.time() - hunt_stats["start_time"]
    msg = (
        f"HUNT COMPLETE\n"
        f"Checked: {hunt_stats['checked']}\n"
        f"Found: {hunt_stats['found']}\n"
        f"Taken: {hunt_stats['taken']}\n"
        f"Errors: {hunt_stats['errors']}\n"
        f"Time: {int(elapsed // 60)}m {int(elapsed % 60)}s"
    )
    await update.message.reply_text(msg)


async def cmd_hunt3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_hunt(update, context, min_len=3)


async def cmd_hunt4(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_hunt(update, context, min_len=4)


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("test", cmd_test))
    app.add_handler(CommandHandler("debug", cmd_debug))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("found", cmd_found))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("hunt3", cmd_hunt3))
    app.add_handler(CommandHandler("hunt4", cmd_hunt4))
    logger.info("Bot is running!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
