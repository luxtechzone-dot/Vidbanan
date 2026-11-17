import asyncio, os, re, json, time, uuid, shutil, logging, itertools, html
from urllib.parse import quote, urlparse
import aiohttp
from pyrogram import Client, filters, idle
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import datetime as dt

import config
import database as dbm
from webpanel import start_web

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

app = Client("vidbot", api_id=config.API_ID, api_hash=config.API_HASH,
             bot_token=config.BOT_TOKEN, in_memory=True, parse_mode=ParseMode.HTML)

Q = asyncio.PriorityQueue()
counter = itertools.count()
URL_RE = re.compile(r"https?://[^\s]+")
INVITE = {"link": config.INVITE_LINK}
ADMIN = filters.user(config.OWNER_IDS)

# ---------------------------------------------------------------- helpers
def hsize(n):
    n = float(n)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024: return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"

def bar(done, total):
    if not total: return f"{hsize(done)}"
    p = min(done / total, 1)
    f = int(p * 12)
    return f"[{'█' * f}{'░' * (12 - f)}] {p * 100:.0f}%  {hsize(done)}/{hsize(total)}"

def allowed(url):
    if not config.ALLOWED_DOMAINS: return True
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in config.ALLOWED_DOMAINS)

async def run(*args):
    p = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, _ = await p.communicate()
    return p.returncode, out.decode(errors="ignore")

async def probe(path):
    rc, out = await run("ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height:format=duration", "-of", "json", path)
    try:
        j = json.loads(out)
        return int(float(j["format"]["duration"])), int(j["streams"][0]["width"]), int(j["streams"][0]["height"])
    except Exception:
        return 0, 0, 0

async def make_thumb(path, dur, out):
    await run("ffmpeg", "-y", "-ss", str(max(dur // 2, 0)), "-i", path, "-frames:v", "1",
              "-vf", "scale=320:-2", "-q:v", "5", out)
    return out if os.path.exists(out) and os.path.getsize(out) > 0 else None

# ---------------------------------------------------------------- fetching
VID_RE = re.compile(r'https?://[^\s"\'<>\\]+', re.I)
EXT_RE = re.compile(r"\.(mp4|m3u8|mkv|webm)(\?|$)", re.I)

def find_link(body):
    try: data = json.loads(body)
    except Exception: data = None
    cands = []
    def walk(o, k=""):
        if isinstance(o, dict):
            for kk, v in o.items(): walk(v, kk)
        elif isinstance(o, list):
            for v in o: walk(v, k)
        elif isinstance(o, str) and o.startswith("http"):
            cands.append((k.lower(), o))
    if data is not None: walk(data)
    else: cands = [("", x) for x in VID_RE.findall(body.replace("\\/", "/"))]
    for _, u in cands:
        if EXT_RE.search(u): return u
    for k, u in cands:
        if k in ("url", "download", "download_url", "video", "video_url", "link", "src", "direct"): return u
    return cands[0][1] if cands else None

async def stream(r, dest, cb):
    total = int(r.headers.get("Content-Length", 0) or 0)
    limit = config.MAX_MB * 1048576
    if total > limit: raise RuntimeError(f"File badi hai ({hsize(total)}), limit {config.MAX_MB} MB")
    done = 0
    with open(dest, "wb") as f:
        async for chunk in r.content.iter_chunked(1 << 20):
            done += len(chunk)
            if done > limit: raise RuntimeError(f"File {config.MAX_MB} MB se badi hai")
            f.write(chunk)
            await cb(done, total)
    if done < 1024: raise RuntimeError("File khali/chhoti mili")
    return done

async def hls(link, dest):
    rc, _ = await run("ffmpeg", "-y", "-i", link, "-c", "copy", "-bsf:a", "aac_adtstoasc", dest)
    if rc != 0 or not os.path.exists(dest): raise RuntimeError("m3u8 download fail")
    return os.path.getsize(dest)

async def fetch_video(url, dest, cb):
    api = config.API_BASE + quote(url, safe="")
    timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=120)
    async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}) as s:
        async with s.get(api) as r:
            if r.status != 200: raise RuntimeError(f"API error {r.status}")
            ct = r.headers.get("Content-Type", "").lower()
            if not any(x in ct for x in ("json", "text", "mpegurl")):
                return await stream(r, dest, cb)
            body = await r.text()
        if body.lstrip().startswith("#EXTM3U"): return await hls(api, dest)
        link = find_link(body)
        if not link: raise RuntimeError("API se video link nahi mila")
        if ".m3u8" in link.lower(): return await hls(link, dest)
        async with s.get(link) as r2:
            if r2.status != 200: raise RuntimeError(f"Video server error {r2.status}")
            return await stream(r2, dest, cb)

# ---------------------------------------------------------------- access control
async def check_access(c, user, send=None):
    doc = await dbm.upsert_user(user)
    if doc.get("banned"):
        if send: await send("🚫 Aapko is bot se ban kiya gaya hai.")
        return False
    if not config.FORCE_CHANNEL or await dbm.is_verified(user.id): return True
    try:
        mem = await c.get_chat_member(config.FORCE_CHANNEL, user.id)
        if mem.status.name in ("MEMBER", "ADMINISTRATOR", "OWNER"):
            await dbm.mark_joined(user.id, "member")
            return True
    except Exception:
        pass
    if send:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Join Channel (Request bhejo)", url=INVITE["link"] or "https://t.me")],
            [InlineKeyboardButton("✅ Maine request bhej di", callback_data="check")]])
        await send("⚠️ Bot use karne ke liye pehle hamare channel ko <b>join request</b> bhejo, phir niche wala button dabao.",
                   reply_markup=kb)
    return False

@app.on_chat_join_request(filters.chat(config.FORCE_CHANNEL or 0))
async def on_join_request(c, req):
    uid = req.from_user.id
    await dbm.mark_joined(uid, "request")
    if config.AUTO_APPROVE:
        try: await c.approve_chat_join_request(req.chat.id, uid)
        except Exception as e: log.warning("approve fail %s", e)
    try: await c.send_message(uid, "✅ Request mil gayi! Ab bot use kar sakte ho. Video link bhejo.")
    except Exception: pass

@app.on_callback_query(filters.regex("^check$"))
async def cb_check(c, q):
    if await check_access(c, q.from_user):
        await q.answer("✅ Verified! Ab link bhejo.", show_alert=True)
    else:
        await q.answer("Pehle channel ko join request bhejo.", show_alert=True)

# ---------------------------------------------------------------- user commands
@app.on_message(filters.command("start") & filters.private)
async def start_cmd(c, m):
    if not await check_access(c, m.from_user, m.reply): return
    await m.reply("👋 <b>Welcome!</b>\n\nMujhe video link bhejo (ek saath kai links bhi chalenge, har link alag line me). "
                  "Main video thumbnail ke saath bhej dunga.\n\n/stats - aapki limit\n/premium - premium info\n/help - madad")

@app.on_message(filters.command("help") & filters.private)
async def help_cmd(c, m):
    await m.reply("📖 Link bhejo, bot video download karke bhejega.\n• Free users: roz limited downloads\n• Premium: zyada limit + priority queue\n• Ek message me multiple links bhej sakte ho")

@app.on_message(filters.command("stats") & filters.private)
async def stats_cmd(c, m):
    if not await check_access(c, m.from_user, m.reply): return
    doc = await dbm.get_user(m.from_user.id)
    if doc.get("used_date") != dbm.today(): doc["used"] = 0
    lim = await dbm.limit_for(doc)
    pu = doc.get("premium_until")
    plan = "♾ Unlimited" if doc.get("unlimited") else (f"💎 Premium ({pu:%d-%m-%Y} tak)" if dbm.is_premium(doc) else "🆓 Free")
    left = "∞" if lim is None else max(lim - doc.get("used", 0), 0)
    await m.reply(f"👤 <b>{html.escape(m.from_user.first_name or '')}</b>\n🆔 <code>{m.from_user.id}</code>\n"
                  f"📦 Plan: {plan}\n📥 Aaj bache: <b>{left}</b>\n📊 Total downloads: {doc.get('total', 0)}")

@app.on_message(filters.command("premium") & filters.private)
async def premium_cmd(c, m):
    daily, prem = await dbm.get_cfg()
    await m.reply(f"💎 <b>Premium</b>\n\n🆓 Free: {daily} video/din\n💎 Premium: {prem} video/din + priority queue\n"
                  f"♾ Unlimited: koi limit nahi\n\nPremium ke liye admin se sampark karo. Aapki ID: <code>{m.from_user.id}</code>")

# ---------------------------------------------------------------- link handler
@app.on_message(filters.private & filters.text & ~filters.regex(r"^/"))
async def on_text(c, m):
    if not await check_access(c, m.from_user, m.reply): return
    urls = [u for u in dict.fromkeys(URL_RE.findall(m.text)) if allowed(u)]
    if not urls:
        return await m.reply("❌ Sahi video link bhejo.")
    uid = m.from_user.id
    doc = await dbm.get_user(uid)
    prio = dbm.is_priority(doc)
    urls = urls[: 20 if prio else 5]
    queued = skipped = 0
    for u in urls:
        if not await dbm.try_consume(uid):
            skipped += 1
            continue
        queued += 1
        st = await m.reply(f"⏳ Queue me add ho gaya (#{queued})")
        user = {"id": uid, "name": m.from_user.first_name or "", "username": m.from_user.username or ""}
        await Q.put((0 if prio else 1, next(counter),
                     {"chat_id": m.chat.id, "url": u, "user": user, "status": st}))
    if skipped:
        await m.reply(f"⚠️ Daily limit khatam. {skipped} link skip hue. /premium dekho.")

# ---------------------------------------------------------------- worker
async def process(job):
    chat, url, u, st = job["chat_id"], job["url"], job["user"], job["status"]
    last = [0.0]
    async def edit(text, force=False):
        if not force and time.time() - last[0] < 4: return
        last[0] = time.time()
        try: await st.edit_text(text)
        except Exception: pass

    workdir = os.path.join(config.DOWNLOAD_DIR, uuid.uuid4().hex)
    os.makedirs(workdir, exist_ok=True)
    sent, size = None, 0
    try:
        cached = await dbm.downloads.find_one({"url": url, "status": "ok", "file_id": {"$exists": True}})
        if cached:
            try:
                sent = await app.send_video(chat, cached["file_id"], caption=config.CAPTION)
                size = cached.get("size", 0)
            except Exception:
                sent = None
        if sent is None:
            path = os.path.join(workdir, "video.mp4")
            await edit("⬇️ Download ho raha hai...", True)
            async def dl_prog(d, t): await edit(f"⬇️ <b>Downloading</b>\n{bar(d, t)}")
            size = await fetch_video(url, path, dl_prog)
            dur, w, h = await probe(path)
            thumb = await make_thumb(path, dur, os.path.join(workdir, "thumb.jpg"))
            await edit("⬆️ Upload ho raha hai...", True)
            async def up_prog(cur, tot): await edit(f"⬆️ <b>Uploading</b>\n{bar(cur, tot)}")
            sent = await app.send_video(chat, path, caption=config.CAPTION, duration=dur, width=w, height=h,
                                        thumb=thumb, supports_streaming=True, progress=up_prog)
        try: await st.delete()
        except Exception: pass

        fid = sent.video.file_id if sent.video else None
        if config.LOG_GROUP:
            try:
                cap = (f"👤 {html.escape(u['name'])} (@{u['username'] or '-'})\n🆔 <code>{u['id']}</code>\n"
                       f"🔗 {html.escape(url)}\n📦 {hsize(size)}")
                await sent.copy(config.LOG_GROUP, caption=cap)
            except Exception as e:
                log.warning("log copy fail: %s", e)
        await dbm.downloads.insert_one({"user_id": u["id"], "name": u["name"], "username": u["username"], "url": url,
                                        "status": "ok", "size": size, "file_id": fid,
                                        "ts": dbm.now(), "day": dbm.today()})
    except Exception as e:
        log.exception("job fail")
        await dbm.refund(u["id"])
        await edit(f"❌ Download fail: {html.escape(str(e)[:150])}\nAapki limit wapas kar di gayi.", True)
        await dbm.downloads.insert_one({"user_id": u["id"], "name": u["name"], "username": u["username"], "url": url,
                                        "status": "failed", "error": str(e)[:300], "ts": dbm.now(), "day": dbm.today()})
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

async def worker():
    while True:
        _, _, job = await Q.get()
        try: await process(job)
        except Exception: log.exception("worker error")
        finally: Q.task_done()

# ---------------------------------------------------------------- admin commands
def _args(m): return m.command[1:]

@app.on_message(filters.command("addpremium") & ADMIN)
async def addpremium(c, m):
    a = _args(m)
    if len(a) < 2 or not a[0].isdigit() or not a[1].isdigit(): return await m.reply("Use: /addpremium user_id days")
    uid, days = int(a[0]), int(a[1])
    doc = await dbm.get_user(uid)
    if not doc: return await m.reply("User DB me nahi hai (usne bot start nahi kiya).")
    base = max(doc.get("premium_until") or dbm.now(), dbm.now())
    until = base + dt.timedelta(days=days)
    await dbm.users.update_one({"_id": uid}, {"$set": {"premium_until": until}})
    await m.reply(f"✅ {uid} premium {until:%d-%m-%Y} tak")
    try: await c.send_message(uid, f"💎 Aapko premium mila! Valid: {until:%d-%m-%Y} tak")
    except Exception: pass

@app.on_message(filters.command("removepremium") & ADMIN)
async def removepremium(c, m):
    a = _args(m)
    if not a or not a[0].isdigit(): return await m.reply("Use: /removepremium user_id")
    await dbm.users.update_one({"_id": int(a[0])}, {"$set": {"premium_until": None}})
    await m.reply("✅ Premium hata diya")

@app.on_message(filters.command(["unlimited", "removeunlimited"]) & ADMIN)
async def unlimited(c, m):
    a = _args(m)
    if not a or not a[0].isdigit(): return await m.reply("Use: /unlimited user_id  ya  /removeunlimited user_id")
    on = m.command[0] == "unlimited"
    await dbm.users.update_one({"_id": int(a[0])}, {"$set": {"unlimited": on}})
    await m.reply("✅ Unlimited ON" if on else "✅ Unlimited OFF")
    if on:
        try: await c.send_message(int(a[0]), "♾ Aapko unlimited access mil gaya!")
        except Exception: pass

@app.on_message(filters.command(["ban", "unban"]) & ADMIN)
async def ban(c, m):
    a = _args(m)
    if not a or not a[0].isdigit(): return await m.reply("Use: /ban user_id  ya  /unban user_id")
    await dbm.users.update_one({"_id": int(a[0])}, {"$set": {"banned": m.command[0] == "ban"}})
    await m.reply("✅ Done")

@app.on_message(filters.command("setlimit") & ADMIN)
async def setlimit(c, m):
    a = _args(m)
    if not a or not a[0].isdigit(): return await m.reply("Use: /setlimit 5 [premium_limit]")
    await dbm.set_cfg(int(a[0]), int(a[1]) if len(a) > 1 and a[1].isdigit() else None)
    await m.reply("✅ Limit update ho gayi")

@app.on_message(filters.command("botstats") & ADMIN)
async def botstats(c, m):
    tu = await dbm.users.count_documents({})
    pr = await dbm.users.count_documents({"premium_until": {"$gt": dbm.now()}})
    un = await dbm.users.count_documents({"unlimited": True})
    td = await dbm.downloads.count_documents({"day": dbm.today(), "status": "ok"})
    await m.reply(f"📊 Users: {tu}\n💎 Premium: {pr}\n♾ Unlimited: {un}\n📥 Aaj ke downloads: {td}\n🕒 Queue: {Q.qsize()}")

@app.on_message(filters.command("broadcast") & ADMIN)
async def broadcast(c, m):
    if not m.reply_to_message: return await m.reply("Kisi message ko reply karke /broadcast likho.")
    ok = fail = 0
    st = await m.reply("📢 Broadcast shuru...")
    async for u in dbm.users.find({}, {"_id": 1}):
        try:
            await m.reply_to_message.copy(u["_id"]); ok += 1
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    await st.edit_text(f"✅ Sent: {ok}\n❌ Failed: {fail}")

# ---------------------------------------------------------------- main
async def keepalive():
    url = os.getenv("RENDER_EXTERNAL_URL")
    if not url: return
    while True:
        await asyncio.sleep(600)
        try:
            async with aiohttp.ClientSession() as s:
                await s.get(url.rstrip("/") + "/health")
        except Exception:
            pass

async def main():
    os.makedirs(config.DOWNLOAD_DIR, exist_ok=True)
    await app.start()
    for chat in (config.FORCE_CHANNEL, config.LOG_GROUP):
        if chat:
            try: await app.get_chat(chat)
            except Exception as e: log.warning("chat %s resolve fail: %s", chat, e)
    if config.FORCE_CHANNEL and not INVITE["link"]:
        try:
            INVITE["link"] = (await app.create_chat_invite_link(config.FORCE_CHANNEL, creates_join_request=True)).invite_link
        except Exception as e:
            log.warning("invite link fail (bot ko channel me admin banao): %s", e)
    await start_web()
    for _ in range(config.WORKERS):
        asyncio.create_task(worker())
    asyncio.create_task(keepalive())
    log.info("Bot started")
    await idle()
    await app.stop()

if __name__ == "__main__":
    app.run(main())
