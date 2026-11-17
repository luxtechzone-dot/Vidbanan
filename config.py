import os, re

def _i(k, d=0):
    v = os.getenv(k, "").strip()
    return int(v) if v.lstrip("-").isdigit() else d

API_ID = _i("API_ID")
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MONGO_URL = os.getenv("MONGO_URL", "")
DB_NAME = os.getenv("DB_NAME", "vidbot")
OWNER_IDS = [int(x) for x in re.split(r"[ ,]+", os.getenv("OWNER_IDS", "")) if x.lstrip("-").isdigit()]

FORCE_CHANNEL = _i("FORCE_CHANNEL")
INVITE_LINK = os.getenv("INVITE_LINK", "")
AUTO_APPROVE = os.getenv("AUTO_APPROVE", "false").lower() == "true"
LOG_GROUP = _i("LOG_GROUP")

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
PORT = _i("PORT", 8080)

API_BASE = os.getenv("API_BASE", "https://vidbunker-backend.dailyweb577.workers.dev/api/download/?url=")
ALLOWED_DOMAINS = [d.strip().lower() for d in os.getenv("ALLOWED_DOMAINS", "vidbunker.in").split(",") if d.strip()]
DAILY_LIMIT = _i("DAILY_LIMIT", 5)
PREMIUM_LIMIT = _i("PREMIUM_LIMIT", 50)
MAX_MB = _i("MAX_MB", 500)
WORKERS = _i("WORKERS", 2)
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/tmp/downloads")
CAPTION = os.getenv("CAPTION", "✅ Download complete")
