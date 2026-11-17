import datetime as dt
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument
import config

client = AsyncIOMotorClient(config.MONGO_URL)
db = client[config.DB_NAME]
users, downloads, joined, settings = db.users, db.downloads, db.joined, db.settings

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

def now():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)

def today():
    return dt.datetime.now(IST).strftime("%Y-%m-%d")

async def get_cfg():
    d = await settings.find_one({"_id": "cfg"}) or {}
    return d.get("daily_limit", config.DAILY_LIMIT), d.get("premium_limit", config.PREMIUM_LIMIT)

async def set_cfg(daily=None, premium=None):
    s = {}
    if daily is not None: s["daily_limit"] = daily
    if premium is not None: s["premium_limit"] = premium
    if s:
        await settings.update_one({"_id": "cfg"}, {"$set": s}, upsert=True)

async def upsert_user(u):
    return await users.find_one_and_update(
        {"_id": u.id},
        {"$set": {"name": u.first_name or "", "username": u.username or ""},
         "$setOnInsert": {"joined": now(), "banned": False, "premium_until": None,
                          "unlimited": False, "used": 0, "used_date": today(), "total": 0}},
        upsert=True, return_document=ReturnDocument.AFTER)

async def get_user(uid):
    return await users.find_one({"_id": uid})

def is_premium(doc):
    if not doc: return False
    pu = doc.get("premium_until")
    return bool(pu and pu > now())

def is_priority(doc):
    return bool(doc and (doc.get("unlimited") or is_premium(doc)))

async def limit_for(doc):
    """None = unlimited"""
    if doc.get("unlimited"): return None
    daily, prem = await get_cfg()
    return prem if is_premium(doc) else daily

async def try_consume(uid):
    doc = await get_user(uid)
    if not doc: return False
    await users.update_one({"_id": uid, "used_date": {"$ne": today()}},
                           {"$set": {"used": 0, "used_date": today()}})
    lim = await limit_for(doc)
    flt = {"_id": uid, "used_date": today()}
    if lim is not None:
        flt["used"] = {"$lt": lim}
    r = await users.update_one(flt, {"$inc": {"used": 1, "total": 1}})
    return r.modified_count == 1

async def refund(uid):
    await users.update_one({"_id": uid, "used": {"$gt": 0}}, {"$inc": {"used": -1, "total": -1}})

async def is_verified(uid):
    return await joined.find_one({"_id": uid}) is not None

async def mark_joined(uid, how):
    await joined.update_one({"_id": uid}, {"$set": {"how": how, "ts": now()}}, upsert=True)
