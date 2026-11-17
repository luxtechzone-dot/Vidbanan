# VidBot - Telegram Video Downloader + Web Admin Panel

## 1. Zaroori cheezein
1. **API_ID / API_HASH**: https://my.telegram.org -> API development tools
2. **BOT_TOKEN**: @BotFather se bot banao
3. **MONGO_URL**: MongoDB Atlas free cluster (Network Access me 0.0.0.0/0 allow karo)
4. **FORCE_CHANNEL**: channel banao -> Manage channel -> *Approve new members* ON -> bot ko admin banao (Invite Users permission).
   Channel ID `-100...` format me (@userinfobot ya @username_to_id_bot se mil jayegi)
5. **LOG_GROUP**: private group banao, bot ko admin banao, uski `-100...` ID lo
6. **OWNER_IDS**: aapki Telegram user ID

## 2. Render par deploy
1. Project ko GitHub repo me push karo
2. Render -> New -> **Web Service** -> repo select -> Runtime **Docker** -> Plan **Free**
3. `.env.example` ke saare variables Environment me daalo
4. Deploy ke baad panel: `https://<aapka-app>.onrender.com/` (ADMIN_PASSWORD se login)
5. Free plan 15 min idle par sleep hota hai. https://uptimerobot.com par `/health` URL ko 5 min me ping karwao
   (bot khud bhi har 10 min me ping karta hai).

## 3. Bot commands (sirf OWNER_IDS)
/addpremium id days · /removepremium id · /unlimited id · /removeunlimited id
/ban id · /unban id · /setlimit 5 50 · /botstats · /broadcast (reply karke)

## 4. Web panel
Dashboard, Users (search, ban, premium, unlimited, reset, delete), Downloads (search, delete, bulk cleanup),
Join Requests (delete), limits change.

## Note
Render free par disk temporary hai, MAX_MB=500 rakha gaya hai. Agar API ka response format alag nikle to
`bot.py` ka `fetch_video()` / `find_link()` adjust karna padega.
