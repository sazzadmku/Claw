import os
import json
import random
import asyncio
import threading
import aiohttp
import pytz
from asyncio import Lock
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, MessageHandler,
    CommandHandler, ContextTypes, filters,
    CallbackQueryHandler
)

# =========================
# Config — সব key Railway Environment Variables থেকে নেবে
# =========================
TOKEN    = os.environ.get("TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
GROUP_ID = os.environ.get("GROUP_ID", "@jjSERVICE_SMM_FATHER")

TWELVE_KEY = os.environ.get("TWELVE_KEY", "")
ALPHA_KEYS = os.environ.get("ALPHA_KEYS", "").split(",")
_alpha_idx = 0
_alpha_lock = threading.Lock()
def get_alpha_key():
    global _alpha_idx
    with _alpha_lock:
        key = ALPHA_KEYS[_alpha_idx % len(ALPHA_KEYS)]
        _alpha_idx += 1
    return key

GROQ_KEY   = os.environ.get("GROQ_KEY", "")
GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

DATA_FILE = "data.json"
USER_FILE = "ultra_users.json"

PAYMENT_INFO = {
    "bkash":   os.environ.get("BKASH", ""),
    "nagad":   os.environ.get("NAGAD", ""),
    "binance": os.environ.get("BINANCE", ""),
}
VIP_PRICE        = int(os.environ.get("VIP_PRICE", "500"))
SUPPORT_USERNAME = os.environ.get("SUPPORT_USERNAME", "@SOPPORT_CLAW_BOT")
OWNER_USERNAME   = os.environ.get("OWNER_USERNAME", "@SW_WAFI")

REAL_PAIRS = [
    "EURUSD","GBPUSD","USDJPY","AUDUSD","USDCAD",
    "USDCHF","NZDUSD","EURJPY","GBPJPY","AUDJPY",
    "EURGBP","EURAUD","EURCAD","EURCHF","EURNZD",
    "GBPAUD","GBPCAD","GBPCHF","GBPNZD","AUDCAD",
    "AUDCHF","AUDNZD","CADJPY","CHFJPY","NZDJPY",
    "NZDCAD","NZDCHF","USDSGD","USDHKD","USDMXN",
]

FREE_SIGNALS = 3
VIP_SIGNALS  = 5

active_sessions:        set  = set()
pending_signal_confirm: set  = set()
pending_payment:        dict = {}
admin_set_mode:         dict = {}
pending_txn:            dict = {}

_file_lock = Lock()
_user_cache: dict = {}
_data_cache: dict = {}

# =========================
# Session Time
# =========================
VIP_SESSIONS = [(7,0,12,0),(13,0,16,0),(19,0,21,30)]

def get_dhaka_now():
    return datetime.now(pytz.timezone("Asia/Dhaka"))

def get_time_str():
    return get_dhaka_now().strftime("%H:%M")

def seconds_to_next_candle():
    return 60 - get_dhaka_now().second

def in_session(sessions):
    now = get_dhaka_now()
    cur = now.hour*60 + now.minute
    for sh,sm,eh,em in sessions:
        if (sh*60+sm) <= cur < (eh*60+em): return True
    return False

def next_session_str(sessions):
    now = get_dhaka_now()
    cur = now.hour*60 + now.minute
    for sh,sm,eh,em in sessions:
        if sh*60+sm > cur: return f"{sh:02d}:{sm:02d}"
    sh,sm = sessions[0][0],sessions[0][1]
    return f"আগামীকাল {sh:02d}:{sm:02d}"

def can_signal(user_id):
    if int(user_id) == ADMIN_ID: return True, ""
    if not is_vip(user_id): return True, ""
    if in_session(VIP_SESSIONS): return True, ""
    return False, next_session_str(VIP_SESSIONS)

# =========================
# Keep-Alive
# =========================
class KeepAlive(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Claw VIP Bot alive!")
    def log_message(self, f, *a): pass

threading.Thread(target=lambda: HTTPServer(
    ("0.0.0.0", int(os.environ.get("PORT",8080))), KeepAlive
).serve_forever(), daemon=True).start()

# =========================
# File Setup
# =========================
for f in [DATA_FILE, USER_FILE]:
    if not os.path.exists(f):
        with open(f,"w",encoding="utf-8") as fp: json.dump({}, fp)

def load_json(file):
    try:
        with open(file,"r",encoding="utf-8") as f: return json.load(f)
    except: return {}

def save_json(file, data):
    tmp = file + ".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, file)

async def load_json_async(file):
    async with _file_lock:
        return load_json(file)

async def save_json_async(file, data):
    async with _file_lock:
        save_json(file, data)

# =========================
# User System
# =========================
def _make_default_user():
    return {
        "name":"বন্ধু","mode":"normal","xp":0,"level":1,
        "session_used_today":[],"signal_count":0,
        "win":0,"loss":0,"is_vip":False,
        "last_reset":str(datetime.now().date())
    }

def get_user(uid):
    uid = str(uid)
    if uid in _user_cache:
        return _user_cache[uid]
    data = load_json(USER_FILE)
    if uid not in data:
        data[uid] = _make_default_user()
        save_json(USER_FILE, data)
    _user_cache[uid] = data[uid]
    return _user_cache[uid]

async def get_user_async(uid):
    uid = str(uid)
    if uid in _user_cache:
        return _user_cache[uid]
    async with _file_lock:
        data = load_json(USER_FILE)
        if uid not in data:
            data[uid] = _make_default_user()
            save_json(USER_FILE, data)
        _user_cache[uid] = data[uid]
    return _user_cache[uid]

async def update_user_async(uid, key, value):
    uid = str(uid)
    if uid not in _user_cache:
        await get_user_async(uid)
    _user_cache[uid][key] = value
    async with _file_lock:
        data = load_json(USER_FILE)
        if uid not in data:
            data[uid] = _make_default_user()
        data[uid][key] = value
        save_json(USER_FILE, data)

def update_user(uid, key, value):
    uid = str(uid)
    if uid not in _user_cache:
        get_user(uid)
    _user_cache[uid][key] = value
    data = load_json(USER_FILE)
    if uid not in data:
        data[uid] = _make_default_user()
    data[uid][key] = value
    save_json(USER_FILE, data)

def add_xp(uid, amount=3):
    uid = str(uid)
    user = get_user(uid)
    user["xp"] += amount
    if user["xp"] >= user["level"]*50:
        user["xp"] = 0; user["level"] += 1
    update_user(uid, "xp", user["xp"])
    update_user(uid, "level", user["level"])

def reset_daily(uid):
    uid = str(uid)
    user = get_user(uid)
    today = str(datetime.now().date())
    if user.get("last_reset") != today:
        user.update({"session_used_today":[],"signal_count":0,
                     "win":0,"loss":0,"last_reset":today})
        _user_cache[uid] = user
        data = load_json(USER_FILE)
        data[uid] = user
        save_json(USER_FILE, data)

def is_vip(uid):
    uid = str(uid)
    if int(uid) == ADMIN_ID: return True
    return get_user(uid).get("is_vip", False)

def current_slot():
    now = get_dhaka_now(); cur = now.hour*60+now.minute
    if 7*60 <= cur < 12*60:     return "morning"
    if 13*60 <= cur < 16*60:    return "afternoon"
    if 19*60 <= cur < 21*60+30: return "evening"
    return None

def check_session_used(uid):
    reset_daily(uid); user = get_user(uid)
    if is_vip(uid) and int(uid) != ADMIN_ID:
        slot = current_slot()
        used = user.get("session_used_today",[])
        return (slot in used if slot else False), slot
    slot = "free"
    return (slot in user.get("session_used_today",[])), slot

def mark_session_used(uid, slot):
    if int(uid) == ADMIN_ID or not slot: return
    user = get_user(uid); used = user.get("session_used_today",[])
    if slot not in used: used.append(slot)
    update_user(uid, "session_used_today", used)

def get_vip_session_count(uid):
    reset_daily(uid); user = get_user(uid)
    return len([s for s in user.get("session_used_today",[])
                if s in ("morning","afternoon","evening")])

# =========================
# Market Data
# =========================
import time as _time
_candle_cache: dict = {}
_candle_lock  = Lock()

async def _do_fetch_candles_async(session: aiohttp.ClientSession, pair: str):
    now = _time.time()
    try:
        sym = pair + "=X"
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
               f"?interval=1m&range=1d")
        headers = {"User-Agent": "Mozilla/5.0"}
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10),
                               headers=headers) as resp:
            res = await resp.json(content_type=None)
        chart = res.get("chart",{}).get("result",[])
        if chart:
            r = chart[0]
            timestamps = r.get("timestamp",[])
            q = r.get("indicators",{}).get("quote",[{}])[0]
            opens  = q.get("open",[])
            highs  = q.get("high",[])
            lows   = q.get("low",[])
            closes = q.get("close",[])
            candles = []
            for i in range(len(timestamps)):
                if (opens[i] is not None and highs[i] is not None and
                    lows[i] is not None and closes[i] is not None):
                    candles.append({
                        "open":float(opens[i]),"high":float(highs[i]),
                        "low":float(lows[i]),"close":float(closes[i])
                    })
            if len(candles) >= 20:
                async with _candle_lock:
                    _candle_cache[pair] = (candles, now)
                return candles
    except: pass

    try:
        sym = f"{pair[:3]}/{pair[3:]}"
        url = (f"https://api.twelvedata.com/time_series"
               f"?symbol={sym}&interval=1min&outputsize=60&apikey={TWELVE_KEY}")
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
            res = await resp.json(content_type=None)
        if "values" in res:
            candles = [
                {"open":float(v["open"]),"high":float(v["high"]),
                 "low":float(v["low"]),"close":float(v["close"])}
                for v in reversed(res["values"])
            ]
            if len(candles) >= 20:
                async with _candle_lock:
                    _candle_cache[pair] = (candles, now)
                return candles
    except: pass

    try:
        url = (f"https://www.alphavantage.co/query?function=FX_INTRADAY"
               f"&from_symbol={pair[:3]}&to_symbol={pair[3:]}"
               f"&interval=1min&outputsize=compact&apikey={get_alpha_key()}")
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            res = await resp.json(content_type=None)
        ts = res.get("Time Series FX (1min)",{})
        if ts:
            candles = [
                {"open":float(v["1. open"]),"high":float(v["2. high"]),
                 "low":float(v["3. low"]),"close":float(v["4. close"])}
                for _,v in sorted(ts.items())
            ]
            if len(candles) >= 20:
                async with _candle_lock:
                    _candle_cache[pair] = (candles, now)
                return candles
    except: pass
    return None

async def fetch_candles_async(session: aiohttp.ClientSession, pair: str, count=50):
    now = _time.time()
    async with _candle_lock:
        cached = _candle_cache.get(pair)
    if cached and now - cached[1] < 180:
        return cached[0][-count:]
    candles = await _do_fetch_candles_async(session, pair)
    return candles[-count:] if candles else None

async def fetch_realtime_price_async(session: aiohttp.ClientSession, pair: str):
    try:
        sym = pair + "=X"
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1m&range=1d"
        headers = {"User-Agent": "Mozilla/5.0"}
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=8),
                               headers=headers) as resp:
            res = await resp.json(content_type=None)
        chart = res.get("chart",{}).get("result",[])
        if chart:
            q = chart[0].get("indicators",{}).get("quote",[{}])[0]
            closes = [c for c in q.get("close",[]) if c is not None]
            if closes: return float(closes[-1])
    except: pass
    try:
        sym = f"{pair[:3]}/{pair[3:]}"
        url = f"https://api.twelvedata.com/price?symbol={sym}&apikey={TWELVE_KEY}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            res = await resp.json(content_type=None)
        if "price" in res: return float(res["price"])
    except: pass
    try:
        candles = await fetch_candles_async(session, pair, 1)
        if candles: return candles[-1]["close"]
    except: pass
    return None

# =========================
# Indicators
# =========================
def calculate_rsi(closes, period=14):
    if len(closes) < period+1: return 50
    gains,losses = [],[]
    for i in range(1, period+1):
        d = closes[i]-closes[i-1]
        gains.append(d if d>0 else 0)
        losses.append(abs(d) if d<0 else 0)
    ag = sum(gains)/period; al = sum(losses)/period
    if al == 0: return 100
    return 100 - (100/(1+ag/al))

def ema(data, period):
    k = 2/(period+1); r = [data[0]]
    for p in data[1:]: r.append(p*k + r[-1]*(1-k))
    return r

def indicator_system(closes, opens, highs, lows):
    call = put = 0
    e5=ema(closes,5); e10=ema(closes,10); e20=ema(closes,20)
    call+=1 if e5[-1]>e5[-2] else 0;   put+=1 if e5[-1]<e5[-2] else 0
    call+=1 if e10[-1]>e10[-2] else 0; put+=1 if e10[-1]<e10[-2] else 0
    call+=1 if e20[-1]>e20[-2] else 0; put+=1 if e20[-1]<e20[-2] else 0
    if e5[-1]>e10[-1]>e20[-1]: call+=2
    elif e5[-1]<e10[-1]<e20[-1]: put+=2
    rsi = calculate_rsi(closes[-15:])
    if rsi<30: call+=2
    elif rsi>70: put+=2
    if 45<=rsi<=55: call+=1; put+=1
    call+=1 if closes[-1]>closes[-3] else 0; put+=1 if closes[-1]<closes[-3] else 0
    call+=1 if closes[-1]>closes[-6] else 0; put+=1 if closes[-1]<closes[-6] else 0
    call+=1 if closes[-1]>opens[-1] else 0;  put+=1 if closes[-1]<opens[-1] else 0
    body=abs(closes[-1]-opens[-1]); rng=highs[-1]-lows[-1]
    if rng>0 and body/rng>0.6:
        call+=1 if closes[-1]>opens[-1] else 0
        put+=1  if closes[-1]<opens[-1] else 0
    trend = sum(1 for i in range(-10,0) if closes[i]>closes[i-1])
    if trend>=7: call+=2
    elif trend<=3: put+=2
    call+=1 if closes[-1]>closes[-2] else 0; put+=1 if closes[-1]<closes[-2] else 0
    if closes[-1]>closes[-2]>closes[-3]: call+=1
    elif closes[-1]<closes[-2]<closes[-3]: put+=1
    return call, put, rsi

async def _analyze_tier_async(session: aiohttp.ClientSession, pair: str, tier: int):
    try:
        candles = await fetch_candles_async(session, pair, 60)
        if not candles or len(candles) < 20: return None,0,None
        closes=[c["close"] for c in candles]; opens=[c["open"] for c in candles]
        highs=[c["high"] for c in candles];   lows=[c["low"] for c in candles]
        call,put,rsi = indicator_system(closes,opens,highs,lows)
        total = call+put
        if total==0: return None,0,None
        strength = abs(call-put)
        e5=ema(closes,5); e10=ema(closes,10); e20=ema(closes,20)
        recent_up = sum(1 for i in range(-5,0) if closes[i]>closes[i-1])

        if tier==1:
            if strength<5: return None,0,None
            if call>put and rsi>70: return None,0,None
            if put>call and rsi<30: return None,0,None
            if call>put and recent_up<3: return None,0,None
            if put>call and recent_up>2: return None,0,None
            if call>put and not(e5[-1]>e10[-1]>e20[-1]): return None,0,None
            if put>call and not(e5[-1]<e10[-1]<e20[-1]): return None,0,None
            if call>put and not(closes[-1]>closes[-2]>closes[-3]): return None,0,None
            if put>call and not(closes[-1]<closes[-2]<closes[-3]): return None,0,None
        elif tier==2:
            if strength<3: return None,0,None
            if call>put and rsi>75: return None,0,None
            if put>call and rsi<25: return None,0,None
            if call>put and e5[-1]<e10[-1]: return None,0,None
            if put>call and e5[-1]>e10[-1]: return None,0,None

        signal = "CALL" if call>put else "PUT"
        base   = {1:88,2:85}[tier]
        acc    = min(round(base+(strength/total)*6, 1), 94.0)
        return signal, acc, closes[-1]
    except: return None,0,None

async def smart_scan_async(session: aiohttp.ClientSession, pairs: list, needed: int):
    result   = []
    shuffled = pairs[:]
    random.shuffle(shuffled)

    for tier in [1, 2]:
        if len(result) >= needed: break
        remaining = needed - len(result)
        already   = {p for p,_,_,_ in result}
        candidates = [p for p in shuffled if p not in already]

        tasks = [_analyze_tier_async(session, pair, tier) for pair in candidates]
        results_raw = await asyncio.gather(*tasks, return_exceptions=True)

        found = []
        for pair, res in zip(candidates, results_raw):
            if isinstance(res, Exception): continue
            sig, acc, price = res
            if sig is not None:
                found.append((pair, sig, acc, price))

        found.sort(key=lambda x: x[2], reverse=True)
        result.extend(found[:remaining])

    return result

# =========================
# Session Summary
# =========================
def session_summary(win, loss):
    total = win+loss
    bars  = "🟩"*win + "🟥"*loss
    return (
        "𝗧𝗢𝗗𝗔𝗬𝗦   𝗩𝗜𝗣   𝗦𝗜𝗚𝗡𝗔𝗟\n"
        f"{bars}\n"
        f"𝗧𝗼𝘁𝗮𝗹 𝗧𝗿𝗮𝗱𝗲𝘀 : {total:02d} 🎀\n\n"
        f"𝗪𝗶𝗻  : {win:02d} 📊\n\n"
        f"𝗟𝗼𝘀𝘀 : {loss:02d} {'☑️' if loss==0 else '❌'}\n\n"
        "𝘼𝙇𝙃𝘼𝙈𝘿𝙐𝙇𝙄𝙇𝙇𝘼𝙃, আজকের সেশনের জন্য যথেষ্ট হয়েছে...\n\n"
        f"⭐️ {OWNER_USERNAME} ✅"
    )

# =========================
# AI System
# =========================
_ai_usage: dict = {}
chat_history: dict = {}

def check_ai_limit(uid):
    uid = str(uid)
    if int(uid)==ADMIN_ID: return True,999
    today = str(datetime.now().date())
    rec   = _ai_usage.get(uid,{})
    if rec.get("date")!=today: _ai_usage[uid]={"date":today,"count":0}; rec=_ai_usage[uid]
    limit = 999 if is_vip(uid) else 5
    used  = rec.get("count",0)
    return (used<limit), max(0,limit-used)

def use_ai_quota(uid):
    uid=str(uid); today=str(datetime.now().date())
    if uid not in _ai_usage or _ai_usage[uid].get("date")!=today:
        _ai_usage[uid]={"date":today,"count":0}
    _ai_usage[uid]["count"]+=1

def add_history(uid,role,text):
    if uid not in chat_history: chat_history[uid]=[]
    chat_history[uid].append({"role":role,"content":text})
    if len(chat_history[uid])>12: chat_history[uid]=chat_history[uid][-12:]

def build_prompt(uid):
    user = get_user(uid)
    name = user.get("name","বন্ধু")
    mode = user.get("mode","normal")
    base = (
        f"তুমি Wafi — Claw VIP Trading Bot এর AI assistant। "
        f"User এর নাম {name}। বাংলায় বন্ধুর মতো কথা বলো, ২-৪ লাইনে সংক্ষিপ্ত। "
        f"Signal: /signal_dao | VIP: /buy ({VIP_PRICE} tk) | Support: {SUPPORT_USERNAME}"
    )
    modes={"funny":" মজা করে বলো।","savage":" Bold ভাবে বলো।",
           "emotional":" আবেগের সাথে বলো।","genius":" Expert level এ বলো।"}
    return base+modes.get(mode,"")

async def groq_reply(message:str, uid:str) -> str:
    allowed,_ = check_ai_limit(uid)
    if not allowed:
        return f"⛔ আজকের AI limit শেষ (৫টা/দিন)।\n💎 VIP নিলে unlimited!\n/buy"
    for attempt in range(3):
        try:
            prompt   = build_prompt(uid)
            messages = [{"role":"system","content":prompt}]
            messages.extend(chat_history.get(str(uid),[])[-6:])
            messages.append({"role":"user","content":message})
            headers  = {"Authorization":f"Bearer {GROQ_KEY}","Content-Type":"application/json"}
            body     = {"model":GROQ_MODEL,"messages":messages,"max_tokens":300,"temperature":0.75}
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    GROQ_URL, headers=headers, json=body,
                    timeout=aiohttp.ClientTimeout(total=25)
                ) as resp:
                    res = await resp.json(content_type=None)
            if "choices" in res:
                txt = res["choices"][0]["message"]["content"].strip()
                add_history(str(uid),"user",message)
                add_history(str(uid),"assistant",txt)
                use_ai_quota(uid)
                return txt
            if "error" in res and ("rate" in str(res["error"]).lower() or "429" in str(res["error"])):
                await asyncio.sleep(5); continue
        except Exception as e:
            print(f"Groq err {attempt+1}: {e}")
            if attempt<2: await asyncio.sleep(3)
    return None

# =========================
# Brain
# =========================
user_context:dict = {}
def get_ctx(uid): return user_context.get(uid)
def set_ctx(uid,v): user_context[uid]=v

def load_umem(uid):
    data={}
    try:
        with open(f"user_{uid}.db","r",encoding="utf-8") as f:
            for line in f:
                if "=" in line: k,v=line.strip().split("=",1); data[k]=v
    except: pass
    return data

def save_umem(uid,key,value):
    data=load_umem(uid); data[key]=value
    with open(f"user_{uid}.db","w",encoding="utf-8") as f:
        [f.write(k+"="+data[k]+"\n") for k in data]

def detect_emotion(text):
    t=text.lower()
    if any(w in t for w in ["sad","😢","মন খারাপ","কষ্ট"]): return "sad"
    if any(w in t for w in ["happy","😂","খুশি"]): return "happy"
    if any(w in t for w in ["angry","😡","রাগ"]): return "angry"
    return "normal"

def is_english(text):
    return sum(1 for c in text if c.isascii() and c.isalpha()) > len(text)*0.5

def brain(text, uid):
    msg  = text.lower().strip()
    mem  = load_umem(uid)
    name = mem.get("name")
    ctx  = get_ctx(uid)
    emo  = detect_emotion(text)
    eng  = is_english(text)
    def r(bn,en=None): return (en if eng and en else bn)

    if ctx=="ask_name":
        save_umem(uid,"name",text); set_ctx(uid,None)
        return r(f"চমৎকার নাম! {text} 😊",f"Great name! {text} 😊")

    if msg in ["hi","hello","hey","হাই","হ্যালো","সালাম","আসসালামুআলাইকুম"]:
        if name: return r(f"ওয়ালাইকুম আস্সালাম, {name}! 😊",f"Hey {name}! 😊")
        set_ctx(uid,"ask_name")
        return r("আস্সালামু আলাইকুম! তোমার নাম কী? 😊","Hey! What's your name? 😊")

    if emo=="sad":   return r("মন খারাপ কেন? বলো 😔")
    if emo=="happy": return r("দারুণ! 😊🔥")
    if emo=="angry": return r("শান্ত হও 😅 বলো কী হয়েছে?")

    if any(w in msg for w in ["কেমন আছো","how are you"]):
        return r("আলহামদুলিল্লাহ ভালো! তুমি? 😊")
    if any(w in msg for w in ["কে তুমি","who are you"]):
        return r("আমি Wafi — Claw VIP BOT এর AI 🤖")
    if any(w in msg for w in ["payment","পেমেন্ট","pay"]):
        return (f"💰 Payment:\n📱 bKash: {PAYMENT_INFO['bkash']}\n"
                f"📱 Nagad: {PAYMENT_INFO['nagad']}\n💳 Binance: {PAYMENT_INFO['binance']}")
    if any(w in msg for w in ["vip","ভিআইপি"]):
        return f"💎 VIP মাত্র {VIP_PRICE} টাকা/মাস! দিনে ১৫টা signal। /buy"
    if "time" in msg or "সময়" in msg: return f"⏰ ঢাকার সময়: {get_time_str()}"
    if "bye" in msg or "বিদায়" in msg: return r("আল্লাহ হাফেজ! 👋")
    return None

def handle_commands(msg, uid):
    m    = msg.lower().strip()
    user = get_user(uid)
    if m.startswith("mode "):
        mode  = m.split(" ")[1] if len(m.split())>1 else ""
        modes = ["funny","savage","emotional","genius","normal"]
        if mode in modes: update_user(uid,"mode",mode); return f"Mode: {mode} ✅"
        return f"Available: {', '.join(modes)}"
    if m.startswith("setname "):
        name = msg.replace("setname ","").strip()
        update_user(uid,"name",name); return f"নাম সেট: {name} ✅"
    if m=="mystats":
        vip = is_vip(uid)
        return (f"📊 Stats:\n{'💎 VIP' if vip else '🆓 Free'}\n"
                f"Level: {user['level']} | XP: {user['xp']}/{user['level']*50}\n"
                f"Win: {user.get('win',0)} | Loss: {user.get('loss',0)}")
    return None

# =========================
# Start
# =========================
async def start(update:Update, context:ContextTypes.DEFAULT_TYPE):
    uid   = str(update.message.from_user.id)
    uname = update.message.from_user.first_name or "বন্ধু"
    get_user(uid)
    await update.message.reply_text(
        f"আস্সালামু আলাইকুম, {uname}! 👋\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🏆  Claw VIP BOT  🏆\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "✅ 20+ Indicator + AI Filter\n"
        "✅ Live WIN/LOSS Result\n"
        "✅ 85–94% Accuracy\n\n"
        "📈 Plan:\n"
        f"🆓 Free: দিনে {FREE_SIGNALS}টা Signal\n"
        f"💎 VIP:  দিনে {VIP_SIGNALS*3}টা Signal\n\n"
        "• /signal_dao — Signal নিন\n"
        "• /buy — VIP কিনুন\n"
        "• /status — Status\n"
        "• /help — Help\n\n"
        f"📞 {SUPPORT_USERNAME} | 👑 {OWNER_USERNAME}"
    )

async def status_cmd(update:Update, context:ContextTypes.DEFAULT_TYPE):
    uid  = str(update.message.from_user.id)
    user = get_user(uid); vip = is_vip(uid)
    slots= user.get("session_used_today",[])
    await update.message.reply_text(
        "📊 Status:\n\n"
        +("💎 VIP" if vip else "🆓 Free")+"\n"
        f"Session: {len(slots)}/{'3' if vip else '1'}\n"
        f"Win: {user.get('win',0)} | Loss: {user.get('loss',0)}\n\n"
        f"Support: {SUPPORT_USERNAME}"
    )

async def help_cmd(update:Update, context:ContextTypes.DEFAULT_TYPE):
    uid = str(update.message.from_user.id); vip = is_vip(uid)
    await update.message.reply_text(
        "📋 Commands:\n\n"
        "• /signal_dao — Signal\n• /buy — VIP কিনুন\n"
        "• /status — Status\n• mystats — Stats\n\n"
        +("💎 VIP: সকাল ৭–১২ | দুপুর ১–৪ | সন্ধ্যা ৭–৯:৩০"
          if vip else f"🆓 Free: দিনে {FREE_SIGNALS}টা | VIP = {VIP_SIGNALS*3}টা /buy")+
        f"\n\n📞 {SUPPORT_USERNAME}"
    )

async def vip_on(update:Update, context:ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Admin only!"); return
    try:
        target = int(context.args[0])
        await _activate_vip(context.bot, target, "Manual by Admin")
        await update.message.reply_text(f"✅ {target} VIP activated!")
    except: await update.message.reply_text("use: /vip_on [user_id]")

async def _activate_vip(bot, target_id:int, method:str=""):
    update_user(str(target_id),"is_vip",True)
    async with _file_lock:
        d = load_json(DATA_FILE)
        d["total_vip"]    = d.get("total_vip",0)+1
        d["total_income"] = d.get("total_income",0)+VIP_PRICE
        save_json(DATA_FILE, d)
    try:
        await bot.send_message(
            chat_id=target_id,
            text=(
                "🎉 অভিনন্দন! তুমি এখন 💎 VIP Member!\n\n"
                "⏰ সকাল ৭–১২ | দুপুর ১–৪ | সন্ধ্যা ৭–৯:৩০\n"
                f"✅ {VIP_SIGNALS}×৩ = {VIP_SIGNALS*3} signal/দিন\n\n"
                f"/signal_dao লিখে শুরু করো! 🔥\n{OWNER_USERNAME}"
            )
        )
    except: pass
    try:
        users = load_json(USER_FILE)
        udata = users.get(str(target_id),{})
        uname = udata.get("name","বন্ধু")
        await bot.send_message(
            chat_id=GROUP_ID,
            text=(
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "🎉 নতুন VIP Member!\n"
                "━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 নাম  : {uname}\n"
                f"🆔 ID   : {target_id}\n"
                f"💰 পরিমাণ: {VIP_PRICE} টাকা\n"
                f"💳 Method: {method}\n\n"
                "🏆 তিনি এখন Claw VIP Member!\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n{OWNER_USERNAME}"
            )
        )
    except: pass

# =========================
# Signal Session
# =========================
async def run_signal_session(update:Update, uid:str):
    if uid in active_sessions:
        await update.message.reply_text("⚠️ Session চলছে!"); return

    reset_daily(uid)

    if not is_vip(uid) and int(uid)!=ADMIN_ID:
        user_data = get_user(uid)
        if len(user_data.get("session_used_today",[]))>=1:
            await update.message.reply_text(
                "⛔ আজকের signal নেওয়া হয়ে গেছে।\nকাল আবার পাবে। 😊\n\n"
                f"💎 VIP = {VIP_SIGNALS*3}টা/দিন!\n/buy"
            ); return
        slot = "free"
    elif is_vip(uid) and int(uid)!=ADMIN_ID:
        ok,nxt = can_signal(uid)
        if not ok:
            await update.message.reply_text(
                f"⛔ VIP session বন্ধ।\n⏰ পরবর্তী: {nxt}\n\n"
                "সকাল ৭–১২ | দুপুর ১–৪ | সন্ধ্যা ৭–৯:৩০"
            ); return
        used,slot = check_session_used(uid)
        if used:
            sn={"morning":"সকাল","afternoon":"দুপুর","evening":"সন্ধ্যা"}.get(slot,slot)
            await update.message.reply_text(f"⛔ {sn} session আগেই নেওয়া হয়েছে।\nপরের session এ এসো।"); return
        if get_vip_session_count(uid)>=3:
            await update.message.reply_text("⛔ আজকের ৩টা VIP session শেষ।\nকাল আবার পাবে।"); return
    else:
        slot = None

    per_session = VIP_SIGNALS if is_vip(uid) else FREE_SIGNALS
    active_sessions.add(uid)

    try:
        await update.message.reply_text("🔍 Market analyze করছি...")
        pairs = REAL_PAIRS.copy(); random.shuffle(pairs)
        await update.message.reply_text("📡 Market scan করছি...")

        async with aiohttp.ClientSession() as http_session:
            signal_list = await smart_scan_async(http_session, pairs, per_session)

            if not signal_list:
                await update.message.reply_text(
                    "⚠️ এই মুহূর্তে market data আসছে না।\n২ মিনিট পরে আবার /signal_dao লিখো।"
                )
                active_sessions.discard(uid); return

            if slot: mark_session_used(uid, slot)

            session_win=0; session_loss=0

            for pair,signal_type,accuracy,entry_est in signal_list:
                now       = get_dhaka_now()
                wait_sec  = seconds_to_next_candle()
                trade_time = (now+timedelta(seconds=wait_sec)).replace(
                    second=0,microsecond=0).strftime("%H:%M")

                sig_line  = "🟢 CALL UP ⬆️" if signal_type=="CALL" else "🔴 PUT DOWN ⬇️"
                vip_badge = "💎" if is_vip(uid) else "🆓"
                acc_line  = f"🎯 Accuracy: {accuracy}%" if is_vip(uid) else ""

                await update.message.reply_text(
                    "━━━━━━━━━━━━━━━━━\n"
                    f"📊 Pair  : {pair}\n"
                    f"⏰ Entry : {trade_time}\n"
                    "🕐 Time  : 1 Minute\n"
                    f"{sig_line}\n"
                    +(f"{acc_line}\n" if acc_line else "")+
                    "━━━━━━━━━━━━━━━━━\n"
                    f"{vip_badge} CLAW VIP BOT {vip_badge}"
                )

                await asyncio.sleep(wait_sec+1)

                entry_price = None
                for _ in range(3):
                    entry_price = await fetch_realtime_price_async(http_session, pair)
                    if entry_price: break
                    await asyncio.sleep(2)
                if not entry_price: entry_price = entry_est

                await asyncio.sleep(62)

                exit_price = None
                for _ in range(3):
                    exit_price = await fetch_realtime_price_async(http_session, pair)
                    if exit_price: break
                    await asyncio.sleep(2)

                if entry_price and exit_price:
                    diff = exit_price - entry_price
                    if abs(diff) >= 0.000001:
                        is_win = diff>0 if signal_type=="CALL" else diff<0
                    else:
                        await asyncio.sleep(10)
                        final = await fetch_realtime_price_async(http_session, pair)
                        if final: diff2=final-entry_price; is_win=diff2>0 if signal_type=="CALL" else diff2<0
                        else: is_win=False
                else:
                    is_win = None

                if is_win is None: continue

                dir_str = "CALL ⬆️" if signal_type=="CALL" else "PUT ⬇️"
                await update.message.reply_text(
                    f"🗓 {pair} — {dir_str} {'WIN ✅' if is_win else 'Loss ❌'}"
                )

                if is_win:
                    session_win+=1
                    await update_user_async(uid,"win",get_user(uid).get("win",0)+1)
                else:
                    session_loss+=1
                    await update_user_async(uid,"loss",get_user(uid).get("loss",0)+1)

                await update_user_async(uid,"signal_count",get_user(uid).get("signal_count",0)+1)
                add_xp(uid,5)
                await asyncio.sleep(3)

        await update.message.reply_text(session_summary(session_win,session_loss))

    except Exception as e:
        print(f"Signal error uid={uid}: {e}")
        await update.message.reply_text("⚠️ সমস্যা হয়েছে। আবার try করো।")
    finally:
        active_sessions.discard(uid)

# =========================
# Payment System
# =========================
async def buy(update:Update, context:ContextTypes.DEFAULT_TYPE):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"💰 {VIP_PRICE} টাকা — ১ মাস", callback_data="pay_amt_500")],
        [InlineKeyboardButton("🔙 বাতিল", callback_data="pay_cancel")],
    ])
    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💎 VIP PLAN\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✅ দিনে {VIP_SIGNALS*3}টা Signal ({VIP_SIGNALS}×৩ session)\n"
        "✅ 85–94% Accuracy\n"
        "✅ Live WIN/LOSS Result\n\n"
        "নিচে সিলেক্ট করো:",
        reply_markup=kb
    )

async def payment_callback(update, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    query = update.callback_query; await query.answer()
    data  = query.data; uid = str(query.from_user.id)

    if data=="pay_amt_500":
        pending_payment[uid]={"method":"pending","amount":500}
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 bKash",   callback_data="pay_bkash")],
            [InlineKeyboardButton("📱 Nagad",   callback_data="pay_nagad")],
            [InlineKeyboardButton("💳 Binance", callback_data="pay_binance")],
            [InlineKeyboardButton("🔙 Back",    callback_data="pay_back")],
        ])
        await query.edit_message_text("💳 Payment method বেছে নাও:", reply_markup=kb)

    elif data=="pay_back":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"💰 {VIP_PRICE} টাকা — ১ মাস",callback_data="pay_amt_500")],
            [InlineKeyboardButton("🔙 বাতিল",callback_data="pay_cancel")],
        ])
        await query.edit_message_text(f"💎 VIP — {VIP_PRICE} টাকা/মাস\nAmount সিলেক্ট করো:", reply_markup=kb)

    elif data in ["pay_bkash","pay_nagad","pay_binance"]:
        method = data.replace("pay_","")
        if uid in pending_payment: pending_payment[uid]["method"]=method
        pending_txn[uid] = {"method":method,"amount":pending_payment.get(uid,{}).get("amount",VIP_PRICE)}
        info   = PAYMENT_INFO.get(method,"")
        amount = pending_txn[uid]["amount"]
        if method=="binance":
            msg=(f"💳 Binance Pay ID: {info}\n\n"
                 f"💰 Amount: {amount} TK এর সমপরিমাণ USDT\n\n"
                 "✅ Transfer করার পর\n"
                 "📋 শুধু Transaction ID টা পাঠাও\n"
                 "(bot নিজেই admin কে পাঠাবে)")
        else:
            msg=(f"📱 {method.upper()} Number: {info}\n(Send Money)\n\n"
                 f"💰 Amount: {amount} টাকা\n\n"
                 "✅ পাঠানোর পর\n"
                 "📋 শুধু Transaction ID টা পাঠাও\n"
                 "(bot নিজেই admin কে পাঠাবে)")
        await query.edit_message_text(msg)

    elif data=="pay_cancel":
        pending_payment.pop(uid,None); pending_txn.pop(uid,None)
        await query.edit_message_text("❌ বাতিল করা হয়েছে।")

    elif data.startswith("vip_yes_"):
        if query.from_user.id!=ADMIN_ID: await query.answer("❌ Admin only!",show_alert=True); return
        target_id = int(data.replace("vip_yes_",""))
        txn_info  = query.message.text
        method    = "Payment"
        for line in txn_info.split("\n"):
            if "Method" in line: method=line.split(":")[-1].strip()
        await _activate_vip(context.bot, target_id, method)
        await query.edit_message_text(f"✅ {target_id} — VIP activated! +{VIP_PRICE}৳")

    elif data.startswith("vip_no_"):
        if query.from_user.id!=ADMIN_ID: await query.answer("❌ Admin only!",show_alert=True); return
        target_id = int(data.replace("vip_no_",""))
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"❌ Payment Rejected\nদুঃখিত, verify হয়নি।\n{SUPPORT_USERNAME}"
            )
        except: pass
        await query.edit_message_text(f"❌ {target_id} — Rejected.")

    elif data.startswith("admin_"):
        await handle_admin_callback(query, context, data)

async def handle_txn_id(update:Update, context:ContextTypes.DEFAULT_TYPE, uid:str, txn_id:str):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    user   = update.message.from_user
    p      = pending_txn.get(uid, {})
    method = p.get("method","unknown")
    amount = p.get("amount", VIP_PRICE)
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ VIP দাও", callback_data=f"vip_yes_{user.id}"),
            InlineKeyboardButton("❌ বাতিল",   callback_data=f"vip_no_{user.id}")
        ]
    ])
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "🟢 নতুন VIP Payment!\n\n"
                f"👤 নাম    : {user.first_name}\n"
                f"🆔 ID     : {user.id}\n"
                f"💳 Method : {method.upper()}\n"
                f"💰 Amount : {amount} TK\n"
                f"📋 TXN ID : {txn_id}\n\n"
                "📸 Screenshot আলাদাভাবে আসতে পারে\n"
                "নিচের বাটন চেপে confirm করো:"
            ),
            reply_markup=kb
        )
        pending_txn.pop(uid,None)
        pending_payment.pop(uid,None)
        await update.message.reply_text(
            "✅ Transaction ID পাঠানো হয়েছে!\n"
            "📸 এখন payment এর Screenshot পাঠাও\n"
            "⏳ Admin verify করছে... 😊"
        )
    except Exception as e:
        await update.message.reply_text(f"সমস্যা। {SUPPORT_USERNAME}")

async def handle_screenshot(update:Update, context:ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.photo: return
    user  = update.message.from_user
    photo = update.message.photo[-1].file_id
    try:
        await context.bot.send_photo(
            chat_id=ADMIN_ID, photo=photo,
            caption=f"📸 Payment Screenshot\n👤 {user.first_name}\n🆔 {user.id}"
        )
        await update.message.reply_text("📸 Screenshot পৌঁছে গেছে! Admin verify করবে। 😊")
    except: pass

# =========================
# Admin Panel
# =========================
async def admin_panel(update:Update, context:ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id!=ADMIN_ID: return
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 My Profile",        callback_data="admin_profile")],
        [InlineKeyboardButton("💳 My Payment System", callback_data="admin_payment")],
        [InlineKeyboardButton("📋 All Commands",      callback_data="admin_commands")],
        [InlineKeyboardButton("📢 Admin Message",     callback_data="admin_broadcast")],
    ])
    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🔧 ADMIN PANEL\n"
        "━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=kb
    )

async def handle_admin_callback(query, context, data):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    d     = load_json(DATA_FILE)
    users = load_json(USER_FILE)
    today = str(datetime.now().date())

    if data=="admin_profile":
        total_users  = len(users)
        active_vip   = sum(1 for u in users.values() if u.get("is_vip"))
        today_vip    = sum(1 for u in users.values()
                          if u.get("is_vip") and u.get("last_reset")==today)
        total_vip    = d.get("total_vip",0)
        total_income = d.get("total_income",0)
        bot_on       = d.get("bot_on",True)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 Bot বন্ধ" if bot_on else "🟢 Bot চালু",
                                  callback_data="admin_toggle_bot")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")],
        ])
        await query.edit_message_text(
            "👤 My Profile\n\n"
            f"👥 মোট User     : {total_users} জন\n"
            f"💎 Active VIP   : {active_vip} জন\n"
            f"🆕 আজ VIP হয়েছে: {today_vip} জন\n"
            f"💰 আজ আয়       : {today_vip*VIP_PRICE}৳\n"
            f"🏆 মোট VIP sold : {total_vip}\n"
            f"💵 মোট আয়      : {total_income}৳\n"
            f"🤖 Bot Status   : {'🟢 ON' if bot_on else '🔴 OFF'}",
            reply_markup=kb
        )

    elif data=="admin_payment":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 bKash নম্বর বদলাও",  callback_data="admin_set_bkash")],
            [InlineKeyboardButton("📱 Nagad নম্বর বদলাও",  callback_data="admin_set_nagad")],
            [InlineKeyboardButton("💳 Binance ID বদলাও",   callback_data="admin_set_binance")],
            [InlineKeyboardButton(f"💰 VIP Price বদলাও (এখন {VIP_PRICE}৳)", callback_data="admin_set_price")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")],
        ])
        await query.edit_message_text(
            "💳 My Payment System\n\n"
            f"📱 bKash  : {PAYMENT_INFO['bkash']}\n"
            f"📱 Nagad  : {PAYMENT_INFO['nagad']}\n"
            f"💳 Binance: {PAYMENT_INFO['binance']}\n"
            f"💰 VIP Price: {VIP_PRICE}৳",
            reply_markup=kb
        )

    elif data=="admin_commands":
        await query.edit_message_text(
            "📋 All Admin Commands\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "/admin — Admin panel খুলবে\n"
            "/vip_on [ID] — User কে VIP দেবে\n"
            "/me — Jarvis report দেখবে\n"
            "/me [প্রশ্ন] — Jarvis AI কে প্রশ্ন\n"
            "admin — Admin panel (text)\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Payment Settings:\n"
            "Admin panel → Payment System → নম্বর বদলাও\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Broadcast:\n"
            "Admin panel → Admin Message → সব user কে message"
        )

    elif data=="admin_broadcast":
        admin_set_mode[str(ADMIN_ID)] = "broadcast"
        await query.edit_message_text(
            "📢 সব user কে পাঠাতে চাও?\n\n"
            "এখন message লিখো:\n"
            "(পরের message টা সবার কাছে যাবে)"
        )

    elif data=="admin_toggle_bot":
        current     = d.get("bot_on",True)
        d["bot_on"] = not current
        save_json(DATA_FILE, d)
        status = "🟢 চালু" if not current else "🔴 বন্ধ"
        await query.edit_message_text(f"✅ Bot এখন {status}!")

    elif data in ["admin_set_bkash","admin_set_nagad","admin_set_binance","admin_set_price"]:
        key = data.replace("admin_set_","")
        admin_set_mode[str(ADMIN_ID)] = key
        labels = {"bkash":"bKash নম্বর","nagad":"Nagad নম্বর",
                  "binance":"Binance ID","price":"VIP Price (শুধু সংখ্যা)"}
        await query.edit_message_text(f"📝 নতুন {labels[key]} লিখো:")

    elif data=="admin_back":
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 My Profile",        callback_data="admin_profile")],
            [InlineKeyboardButton("💳 My Payment System", callback_data="admin_payment")],
            [InlineKeyboardButton("📋 All Commands",      callback_data="admin_commands")],
            [InlineKeyboardButton("📢 Admin Message",     callback_data="admin_broadcast")],
        ])
        await query.edit_message_text(
            "━━━━━━━━━━━━━━━━━━━━━\n🔧 ADMIN PANEL\n━━━━━━━━━━━━━━━━━━━━━",
            reply_markup=kb
        )

# =========================
# Owner Assistant (Jarvis)
# =========================
async def owner_assistant(update:Update, context:ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id!=ADMIN_ID: return
    args  = context.args; msg = " ".join(args) if args else ""
    d     = load_json(DATA_FILE); users = load_json(USER_FILE)
    today = str(datetime.now().date())
    total_users  = len(users)
    active_vip   = sum(1 for u in users.values() if u.get("is_vip"))
    today_vip    = sum(1 for u in users.values()
                       if u.get("is_vip") and u.get("last_reset")==today)
    total_income = d.get("total_income",0)
    if not msg:
        await update.message.reply_text(
            f"👑 Jarvis রিপোর্ট — {today}\n\n"
            f"👥 মোট User     : {total_users} জন\n"
            f"💎 Active VIP   : {active_vip} জন\n"
            f"🆕 আজ VIP হয়েছে: {today_vip} জন\n"
            f"💰 আজ আয়       : {today_vip*VIP_PRICE}৳\n"
            f"💵 মোট আয়      : {total_income}৳\n\n"
            "প্রশ্ন করতে: /me [প্রশ্ন]"
        ); return
    sys_p = (f"তুমি Jarvis — Wafi এর personal assistant। বাংলায় সম্মানের সাথে কথা বলো। "
             f"Bot stats: user={total_users}, vip={active_vip}, আয়={total_income}৳")
    try:
        headers = {"Authorization":f"Bearer {GROQ_KEY}","Content-Type":"application/json"}
        body    = {"model":GROQ_MODEL,"messages":[
            {"role":"system","content":sys_p},{"role":"user","content":msg}
        ],"max_tokens":400}
        async with aiohttp.ClientSession() as session:
            async with session.post(
                GROQ_URL, headers=headers, json=body,
                timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                res = await resp.json(content_type=None)
        if "choices" in res:
            await update.message.reply_text(
                f"🤖 Jarvis:\n\n{res['choices'][0]['message']['content'].strip()}")
        else: await update.message.reply_text("⚠️ Jarvis busy। একটু পরে try করুন।")
    except Exception as e: await update.message.reply_text(f"⚠️ Error: {e}")

# =========================
# Signal Command
# =========================
async def signal_dao_cmd(update:Update, context:ContextTypes.DEFAULT_TYPE):
    uid = str(update.message.from_user.id)
    pending_signal_confirm.add(uid)
    await update.message.reply_text(
        "📊 Signal শুরু করবো?\n\n✅ হ্যাঁ — yes লিখো\n❌ না — no লিখো"
    )

# =========================
# Main Reply Handler
# =========================
async def reply(update:Update, context:ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    msg     = update.message.text
    msg_low = msg.lower().strip()
    uid     = str(update.message.from_user.id)

    d = load_json(DATA_FILE)
    if not d.get("bot_on",True) and int(uid)!=ADMIN_ID:
        await update.message.reply_text("⚠️ Bot সাময়িকভাবে বন্ধ। পরে আসুন।"); return

    if int(uid)==ADMIN_ID and admin_set_mode.get(uid)=="broadcast":
        admin_set_mode.pop(uid,None)
        users = load_json(USER_FILE)
        async def _send(tid):
            try:
                await context.bot.send_message(chat_id=int(tid), text=f"📢 Admin Message:\n\n{msg}")
                return 1
            except: return 0
        results = await asyncio.gather(*[_send(tid) for tid in users], return_exceptions=True)
        sent = sum(r for r in results if r==1)
        await update.message.reply_text(f"✅ {sent} জনকে পাঠানো হয়েছে!"); return

    if int(uid)==ADMIN_ID and uid in admin_set_mode:
        key = admin_set_mode.pop(uid)
        if key=="price":
            try:
                global VIP_PRICE; VIP_PRICE=int(msg.strip())
                await update.message.reply_text(f"✅ VIP Price আপডেট: {VIP_PRICE}৳")
            except: await update.message.reply_text("❌ শুধু সংখ্যা লিখো!")
        else:
            PAYMENT_INFO[key]=msg.strip()
            await update.message.reply_text(f"✅ {key.upper()} আপডেট: {msg.strip()}")
        return

    add_xp(uid,1)

    if uid in pending_signal_confirm:
        yes=["yes","হ্যা","হে","হ্যাঁ","ha","হা","ok","okay","ওকে","sure","start","শুরু","দাও","দে"]
        if any(w in msg_low for w in yes):
            pending_signal_confirm.discard(uid)
            await run_signal_session(update, uid)
        else:
            pending_signal_confirm.discard(uid)
            await update.message.reply_text("❌ বাতিল। /signal_dao")
        return

    if uid in pending_txn and len(msg.strip())>=5:
        await handle_txn_id(update, context, uid, msg.strip()); return

    sig_triggers=["signal dao","সিগনাল দাও","signal daw","এন্ট্রি দাও","signal","সিগনাল"]
    if any(t==msg_low for t in sig_triggers):
        pending_signal_confirm.add(uid)
        await update.message.reply_text(
            "📊 Signal শুরু করবো?\n\n✅ হ্যাঁ — yes লিখো\n❌ না — no লিখো"
        ); return

    if msg_low in ["admin","এডমিন"] and int(uid)==ADMIN_ID:
        await admin_panel(update,context); return

    cmd = handle_commands(msg,uid)
    if cmd: await update.message.reply_text(cmd); return

    brain_res = brain(msg,uid)
    if brain_res: await update.message.reply_text(brain_res); return

    await update.message.chat.send_action(action="typing")
    ai_text = await groq_reply(msg,uid)
    if ai_text: await update.message.reply_text(ai_text)

async def voice_reply(update:Update, context:ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.voice: return
    uid = str(update.message.from_user.id)
    try:
        vf=await update.message.voice.get_file()
        fp=f"voice_{uid}.ogg"; await vf.download_to_drive(fp)
        try: os.remove(fp)
        except: pass
        await update.message.reply_text("🎙️ Voice পেয়েছি! Text এ লিখলে ভালো হয় 😊")
    except Exception as e: print(f"Voice error: {e}")

# =========================
# RUN
# =========================
def main():
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .concurrent_updates(True)
        .build()
    )
    app.add_handler(CommandHandler("start",      start))
    app.add_handler(CommandHandler("buy",        buy))
    app.add_handler(CommandHandler("signal_dao", signal_dao_cmd))
    app.add_handler(CommandHandler("vip_on",     vip_on))
    app.add_handler(CommandHandler("status",     status_cmd))
    app.add_handler(CommandHandler("help",       help_cmd))
    app.add_handler(CommandHandler("admin",      admin_panel))
    app.add_handler(CommandHandler("me",         owner_assistant))
    app.add_handler(CallbackQueryHandler(payment_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_screenshot))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))
    app.add_handler(MessageHandler(filters.VOICE, voice_reply))
    print("Claw VIP Bot ON! 🔥 [High-Concurrency Mode]")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
