import hmac, hashlib, html, re, time, datetime as dt
from aiohttp import web
from bson import ObjectId
import config
import database as dbm

routes = web.RouteTableDef()
PER = 25
FLASH = []
FAILS = {}

CSS = """
:root{--bg:#0f1115;--card:#181b22;--bd:#2a2f3a;--tx:#e6e8ee;--mu:#8b93a5;--ac:#4f8cff;--rd:#e5484d;--gn:#30a46c;--yl:#f5a524}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.5 system-ui,sans-serif}
header{display:flex;gap:6px;align-items:center;flex-wrap:wrap;padding:10px 16px;background:var(--card);border-bottom:1px solid var(--bd)}
header a{color:var(--tx);text-decoration:none;padding:6px 12px;border-radius:8px}header a:hover{background:var(--bd)}
header .sp{flex:1}main{padding:16px;max-width:1200px;margin:auto}
h1{font-size:20px;margin:0 0 14px}h2{font-size:16px;margin:22px 0 10px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:14px}
.card b{display:block;font-size:24px}.card span{color:var(--mu)}
.tw{overflow-x:auto;background:var(--card);border:1px solid var(--bd);border-radius:12px}
table{border-collapse:collapse;width:100%}th,td{padding:8px 10px;border-bottom:1px solid var(--bd);text-align:left;vertical-align:middle;white-space:nowrap}
th{color:var(--mu);font-weight:600}td.w{white-space:normal;word-break:break-all;max-width:360px}
button,.btn{background:var(--bd);color:var(--tx);border:0;border-radius:8px;padding:5px 10px;cursor:pointer;font-size:12px;text-decoration:none;display:inline-block}
button:hover{filter:brightness(1.3)}button.r{background:var(--rd)}button.g{background:var(--gn)}button.b{background:var(--ac)}button.y{background:var(--yl);color:#000}
input{background:var(--bg);color:var(--tx);border:1px solid var(--bd);border-radius:8px;padding:6px 9px;font-size:13px}
form.inl{display:inline-flex;gap:4px;margin:2px;align-items:center}
.flash{background:#1d3b2c;border:1px solid var(--gn);padding:8px 12px;border-radius:8px;margin-bottom:12px}
.tag{padding:2px 7px;border-radius:6px;font-size:11px;background:var(--bd)}.tag.r{background:var(--rd)}.tag.g{background:var(--gn)}.tag.y{background:var(--yl);color:#000}
.pager{margin:12px 0;display:flex;gap:8px;align-items:center}.danger{border-color:var(--rd)}
.login{max-width:320px;margin:15vh auto}
"""

def e(x): return html.escape(str(x), quote=True)

# ------------------------------------------------------------ auth
def _sig(s): return hmac.new(config.SECRET_KEY.encode(), s.encode(), hashlib.sha256).hexdigest()

def make_cookie():
    ts = str(int(time.time()))
    return f"{ts}.{_sig(ts)}"

def valid_cookie(v):
    try:
        ts, sig = (v or "").split(".")
        return time.time() - int(ts) < 43200 and hmac.compare_digest(sig, _sig(ts))
    except Exception:
        return False

def csrf(request): return _sig("csrf" + request.cookies.get("s", ""))[:32]

@web.middleware
async def auth_mw(request, handler):
    if request.path in ("/login", "/health"): return await handler(request)
    if not valid_cookie(request.cookies.get("s")): raise web.HTTPFound("/login")
    return await handler(request)

# ------------------------------------------------------------ html helpers
def page(request, title, body):
    flash = "".join(f'<div class="flash">{e(f)}</div>' for f in FLASH); FLASH.clear()
    nav = "".join(f'<a href="{h}">{t}</a>' for h, t in
                  [("/", "📊 Dashboard"), ("/users", "👥 Users"), ("/downloads", "📥 Downloads"), ("/joined", "🔗 Join Requests")])
    html_ = (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
             f'<title>{e(title)}</title><style>{CSS}</style></head><body><header>{nav}<span class="sp"></span>'
             f'<a href="/logout">Logout</a></header><main>{flash}<h1>{e(title)}</h1>{body}</main></body></html>')
    return web.Response(text=html_, content_type="text/html")

def form(request, action, label, id="", cls="", confirm=True, extra=""):
    c = ' onsubmit="return confirm(\'Pakka karna hai?\')"' if confirm else ""
    return (f'<form method="post" action="/do" class="inl"{c}><input type="hidden" name="csrf" value="{csrf(request)}">'
            f'<input type="hidden" name="action" value="{action}"><input type="hidden" name="id" value="{e(id)}">'
            f'<input type="hidden" name="next" value="{e(request.path_qs)}">{extra}<button class="{cls}">{label}</button></form>')

def pager(request, pg, total):
    pages = max((total + PER - 1) // PER, 1)
    q = request.query.get("q", "")
    def link(p, t): return f'<a class="btn" href="{request.path}?p={p}&q={e(q)}">{t}</a>'
    return (f'<div class="pager">{link(pg - 1, "← Prev") if pg > 1 else ""}<span>Page {pg}/{pages} · {total} records</span>'
            f'{link(pg + 1, "Next →") if pg < pages else ""}</div>')

def pnum(request):
    p = request.query.get("p", "1")
    return int(p) if p.isdigit() and int(p) > 0 else 1

def fmt(d): return d.strftime("%d-%m-%y %H:%M") if d else "-"

# ------------------------------------------------------------ auth routes
@routes.get("/health")
async def health(request): return web.Response(text="ok")

def login_page(msg=""):
    note = f'<p style="color:#e5484d">{e(msg)}</p>' if msg else ""
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<style>{CSS}</style></head><body><div class="login card"><h1>🔐 Admin Login</h1>{note}'
            '<form method="post"><input type="password" name="password" placeholder="Password" style="width:100%;margin-bottom:10px" autofocus>'
            '<button class="b" style="width:100%;padding:9px">Login</button></form></div></body></html>')

@routes.get("/login")
async def login_get(request): return web.Response(text=login_page(), content_type="text/html")

@routes.post("/login")
async def login_post(request):
    ip = (request.headers.get("X-Forwarded-For") or request.remote or "").split(",")[0].strip()
    fails = [t for t in FAILS.get(ip, []) if time.time() - t < 600]
    if len(fails) >= 5:
        return web.Response(text=login_page("Bahut attempts. 10 min baad try karo."), content_type="text/html", status=429)
    data = await request.post()
    pw = data.get("password", "")
    if config.ADMIN_PASSWORD and hmac.compare_digest(pw.encode(), config.ADMIN_PASSWORD.encode()):
        resp = web.HTTPFound("/")
        resp.set_cookie("s", make_cookie(), httponly=True, samesite="Strict", max_age=43200,
                        secure=request.headers.get("X-Forwarded-Proto") == "https")
        raise resp
    fails.append(time.time()); FAILS[ip] = fails
    return web.Response(text=login_page("Galat password"), content_type="text/html", status=401)

@routes.get("/logout")
async def logout(request):
    resp = web.HTTPFound("/login"); resp.del_cookie("s"); raise resp

# ------------------------------------------------------------ pages
@routes.get("/")
async def dashboard(request):
    U, D = dbm.users, dbm.downloads
    now = dbm.now()
    stats = [
        ("Total Users", await U.count_documents({})),
        ("Premium", await U.count_documents({"premium_until": {"$gt": now}})),
        ("Unlimited", await U.count_documents({"unlimited": True})),
        ("Banned", await U.count_documents({"banned": True})),
        ("Verified (Join)", await dbm.joined.count_documents({})),
        ("Total Downloads", await D.count_documents({"status": "ok"})),
        ("Aaj ke Downloads", await D.count_documents({"status": "ok", "day": dbm.today()})),
        ("Failed", await D.count_documents({"status": "failed"})),
    ]
    cards = "".join(f'<div class="card"><b>{v}</b><span>{k}</span></div>' for k, v in stats)
    daily, prem = await dbm.get_cfg()
    set_form = form(request, "set_limit", "Save", confirm=False,
                    extra=f'Free/din <input name="daily" value="{daily}" size="4"> Premium/din <input name="premium" value="{prem}" size="4">')
    old = form(request, "dl_old", "Purane downloads delete", cls="r", extra='<input name="days" value="30" size="3"> din se purane')
    users_del = form(request, "users_all", "Saare users delete", cls="r", extra='<input name="confirm" placeholder="DELETE likho" size="12">')
    body = (f'<div class="grid">{cards}</div><h2>⚙️ Limits</h2><div class="card">{set_form}</div>'
            f'<h2>🧹 Database Cleanup</h2><div class="card danger">'
            f'<p>{old}</p>'
            f'<p>{form(request, "dl_failed", "Failed records delete", cls="y")} '
            f'{form(request, "dl_all", "Saare download records delete (cache bhi)", cls="r")}</p>'
            f'<p>{form(request, "joined_all", "Saari join-request records delete", cls="r")} '
            f'{form(request, "reset_usage", "Sabka aaj ka usage reset", cls="b")}</p>'
            f'<p>{users_del}</p>'
            f'<span style="color:var(--mu)">Note: download records delete karne se cache bhi saaf hota hai, '
            f'to wahi link dobara aaye to fresh download hoga.</span></div>')
    return page(request, "Dashboard", body)

@routes.get("/users")
async def users_page(request):
    q = request.query.get("q", "").strip(); pg = pnum(request)
    flt = {}
    if q:
        r = re.escape(q)
        cond = [{"name": {"$regex": r, "$options": "i"}}, {"username": {"$regex": r, "$options": "i"}}]
        if q.isdigit(): cond.append({"_id": int(q)})
        flt = {"$or": cond}
    total = await dbm.users.count_documents(flt)
    rows = ""
    async for u in dbm.users.find(flt).sort("joined", -1).skip((pg - 1) * PER).limit(PER):
        uid = u["_id"]
        tags = ""
        if u.get("banned"): tags += '<span class="tag r">BANNED</span> '
        if u.get("unlimited"): tags += '<span class="tag g">UNLIMITED</span> '
        if dbm.is_premium(u): tags += f'<span class="tag y">PREMIUM {u["premium_until"]:%d-%m-%y}</span> '
        act = (form(request, "user_unban" if u.get("banned") else "user_ban", "Unban" if u.get("banned") else "Ban", uid, "y", confirm=False)
               + form(request, "user_unlimited_off" if u.get("unlimited") else "user_unlimited_on", "Unlimited OFF" if u.get("unlimited") else "Unlimited ON", uid, "g", confirm=False)
               + form(request, "user_premium", "+Premium", uid, "b", confirm=False, extra='<input name="days" value="30" size="3">')
               + form(request, "user_unpremium", "−Premium", uid, "", confirm=False)
               + form(request, "user_reset", "Reset", uid, "", confirm=False)
               + form(request, "user_delete", "🗑 Delete", uid, "r"))
        rows += (f'<tr><td>{uid}</td><td>{e(u.get("name"))}<br><span style="color:var(--mu)">@{e(u.get("username") or "-")}</span></td>'
                 f'<td>{tags}</td><td>{u.get("used", 0)} aaj / {u.get("total", 0)} total</td><td>{fmt(u.get("joined"))}</td><td>{act}</td></tr>')
    search = f'<form method="get" style="margin-bottom:10px"><input name="q" value="{e(q)}" placeholder="ID / naam / username"> <button class="b">Search</button></form>'
    body = (f'{search}<div class="tw"><table><tr><th>ID</th><th>User</th><th>Status</th><th>Usage</th><th>Joined</th><th>Actions</th></tr>{rows}</table></div>'
            f'{pager(request, pg, total)}')
    return page(request, "Users", body)

@routes.get("/downloads")
async def downloads_page(request):
    q = request.query.get("q", "").strip(); pg = pnum(request)
    flt = {}
    if q:
        flt = {"$or": [{"url": {"$regex": re.escape(q), "$options": "i"}}] + ([{"user_id": int(q)}] if q.isdigit() else [])}
    total = await dbm.downloads.count_documents(flt)
    rows = ""
    async for d in dbm.downloads.find(flt).sort("ts", -1).skip((pg - 1) * PER).limit(PER):
        ok = d.get("status") == "ok"
        st = '<span class="tag g">OK</span>' if ok else f'<span class="tag r" title="{e(d.get("error", ""))}">FAILED</span>'
        size = f'{d.get("size", 0) / 1048576:.1f} MB' if ok else "-"
        rows += (f'<tr><td>{fmt(d.get("ts"))}</td><td>{d.get("user_id")}<br><span style="color:var(--mu)">{e(d.get("name", ""))}</span></td>'
                 f'<td class="w">{e(d.get("url"))}</td><td>{st}</td><td>{size}</td>'
                 f'<td>{form(request, "dl_delete", "🗑", d["_id"], "r")}{form(request, "dl_user", "Is user ke sab", d.get("user_id"), "")}</td></tr>')
    search = f'<form method="get" style="margin-bottom:10px"><input name="q" value="{e(q)}" placeholder="URL ya user ID"> <button class="b">Search</button></form>'
    body = (f'{search}<div class="tw"><table><tr><th>Time</th><th>User</th><th>URL</th><th>Status</th><th>Size</th><th>Action</th></tr>{rows}</table></div>'
            f'{pager(request, pg, total)}')
    return page(request, "Downloads", body)

@routes.get("/joined")
async def joined_page(request):
    pg = pnum(request)
    total = await dbm.joined.count_documents({})
    rows = ""
    async for j in dbm.joined.find({}).sort("ts", -1).skip((pg - 1) * PER).limit(PER):
        u = await dbm.get_user(j["_id"]) or {}
        rows += (f'<tr><td>{j["_id"]}</td><td>{e(u.get("name", "-"))}</td><td>{e(j.get("how"))}</td><td>{fmt(j.get("ts"))}</td>'
                 f'<td>{form(request, "joined_delete", "🗑 Delete (dobara verify karna padega)", j["_id"], "r")}</td></tr>')
    body = f'<div class="tw"><table><tr><th>User ID</th><th>Name</th><th>Type</th><th>Time</th><th>Action</th></tr>{rows}</table></div>{pager(request, pg, total)}'
    return page(request, "Join Requests", body)

# ------------------------------------------------------------ actions
@routes.post("/do")
async def do(request):
    data = await request.post()
    if not hmac.compare_digest(str(data.get("csrf", "")), csrf(request)):
        return web.Response(text="CSRF error", status=403)
    a, i = data.get("action", ""), str(data.get("id", ""))
    uid = int(i) if i.lstrip("-").isdigit() else None
    U, D = dbm.users, dbm.downloads
    msg = "Done"
    if a == "user_ban":   await U.update_one({"_id": uid}, {"$set": {"banned": True}}); msg = "User ban"
    elif a == "user_unban": await U.update_one({"_id": uid}, {"$set": {"banned": False}}); msg = "User unban"
    elif a == "user_unlimited_on":  await U.update_one({"_id": uid}, {"$set": {"unlimited": True}}); msg = "Unlimited ON"
    elif a == "user_unlimited_off": await U.update_one({"_id": uid}, {"$set": {"unlimited": False}}); msg = "Unlimited OFF"
    elif a == "user_premium":
        days = int(data.get("days", "30")) if str(data.get("days", "30")).isdigit() else 30
        doc = await dbm.get_user(uid)
        if doc:
            until = max(doc.get("premium_until") or dbm.now(), dbm.now()) + dt.timedelta(days=days)
            await U.update_one({"_id": uid}, {"$set": {"premium_until": until}}); msg = f"Premium {until:%d-%m-%Y} tak"
    elif a == "user_unpremium": await U.update_one({"_id": uid}, {"$set": {"premium_until": None}}); msg = "Premium hata diya"
    elif a == "user_reset": await U.update_one({"_id": uid}, {"$set": {"used": 0, "used_date": dbm.today()}}); msg = "Usage reset"
    elif a == "user_delete":
        await U.delete_one({"_id": uid}); await D.delete_many({"user_id": uid}); await dbm.joined.delete_one({"_id": uid})
        msg = "User aur uska data delete"
    elif a == "dl_delete":
        try: await D.delete_one({"_id": ObjectId(i)}); msg = "Download record delete"
        except Exception: msg = "Invalid id"
    elif a == "dl_user": r = await D.delete_many({"user_id": uid}); msg = f"{r.deleted_count} records delete"
    elif a == "dl_all": r = await D.delete_many({}); msg = f"{r.deleted_count} records delete"
    elif a == "dl_failed": r = await D.delete_many({"status": "failed"}); msg = f"{r.deleted_count} failed delete"
    elif a == "dl_old":
        days = int(data.get("days", "30")) if str(data.get("days", "30")).isdigit() else 30
        r = await D.delete_many({"ts": {"$lt": dbm.now() - dt.timedelta(days=days)}}); msg = f"{r.deleted_count} purane records delete"
    elif a == "joined_delete": await dbm.joined.delete_one({"_id": uid}); msg = "Join record delete"
    elif a == "joined_all": r = await dbm.joined.delete_many({}); msg = f"{r.deleted_count} join records delete"
    elif a == "reset_usage": await U.update_many({}, {"$set": {"used": 0, "used_date": dbm.today()}}); msg = "Sabka usage reset"
    elif a == "users_all":
        if data.get("confirm") == "DELETE":
            r = await U.delete_many({}); msg = f"{r.deleted_count} users delete"
        else: msg = "Confirm me DELETE likhna padega"
    elif a == "set_limit":
        d, p = str(data.get("daily", "")), str(data.get("premium", ""))
        await dbm.set_cfg(int(d) if d.isdigit() else None, int(p) if p.isdigit() else None); msg = "Limits save"
    else: msg = "Unknown action"
    FLASH.append(msg)
    nxt = str(data.get("next", "/"))
    if not nxt.startswith("/") or nxt.startswith("//"): nxt = "/"
    raise web.HTTPFound(nxt)

async def start_web():
    wa = web.Application(middlewares=[auth_mw])
    wa.add_routes(routes)
    runner = web.AppRunner(wa)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", config.PORT).start()
