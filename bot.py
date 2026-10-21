import asyncio
import os
import sqlite3
import time
from datetime import datetime, timezone

from aiohttp import web
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, Update
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "bot.db")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "change-this-secret")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
PORT = int(os.getenv("PORT", "10000"))

if not TOKEN or not ADMIN_ID:
    raise RuntimeError("Set BOT_TOKEN and ADMIN_ID environment variables.")

bot = Bot(TOKEN)
dp = Dispatcher()

JOIN_TEXT = "🔐 JOIN OUR CHANNELS\n\nTo use this bot, join all the\nrequired channels and groups below."
JOIN_KB = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="📢 Join Channel"), KeyboardButton(text="👥 Join Group")],
    [KeyboardButton(text="✅ I've Joined")],
], resize_keyboard=True)
MAIN_KB = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="📲 Get Number"), KeyboardButton(text="📩 Receive OTP")],
    [KeyboardButton(text="🌍 Available Countries"), KeyboardButton(text="🆘 Support")],
], resize_keyboard=True)

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    parent = os.path.dirname(DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, created_at INTEGER);
        CREATE TABLE IF NOT EXISTS targets(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, chat_id TEXT, url TEXT, label TEXT);
        CREATE TABLE IF NOT EXISTS owners(user_id INTEGER PRIMARY KEY, expires_at INTEGER, added_by INTEGER);
        """)

def save_user(u):
    with db() as con:
        con.execute(
            "INSERT INTO users VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name",
            (u.id, u.username, u.first_name, int(time.time()))
        )

def is_primary(uid):
    return uid == ADMIN_ID

def is_owner(uid):
    if is_primary(uid):
        return True
    with db() as con:
        row = con.execute("SELECT expires_at FROM owners WHERE user_id=?", (uid,)).fetchone()
        if row and row["expires_at"] > int(time.time()):
            return True
        if row:
            con.execute("DELETE FROM owners WHERE user_id=?", (uid,))
    return False

def targets(kind=None):
    with db() as con:
        if kind:
            rows = con.execute("SELECT * FROM targets WHERE kind=? ORDER BY id", (kind,)).fetchall()
        else:
            rows = con.execute("SELECT * FROM targets ORDER BY id").fetchall()
        return [dict(r) for r in rows]

async def joined_all(uid):
    for target in targets():
        try:
            member = await bot.get_chat_member(target["chat_id"], uid)
            if member.status in ("left", "kicked"):
                return False
        except Exception:
            return False
    return True

async def gate(message):
    if await joined_all(message.from_user.id):
        return True
    await message.answer(JOIN_TEXT, reply_markup=JOIN_KB)
    return False

@dp.message(CommandStart())
async def start(message: Message):
    save_user(message.from_user)
    if await gate(message):
        await message.answer("📱 Welcome to Number Service!\n\nChoose a service below.", reply_markup=MAIN_KB)

@dp.message(F.text == "📢 Join Channel")
async def show_channels(message: Message):
    ts = targets("channel")
    body = "\n\n".join(f"{t['label']}\n{t['url']}" for t in ts) or "No channels configured yet."
    await message.answer("📢 Required channels:\n\n" + body, disable_web_page_preview=True)

@dp.message(F.text == "👥 Join Group")
async def show_groups(message: Message):
    ts = targets("group")
    body = "\n\n".join(f"{t['label']}\n{t['url']}" for t in ts) or "No groups configured yet."
    await message.answer("👥 Required groups:\n\n" + body, disable_web_page_preview=True)

@dp.message(F.text == "✅ I've Joined")
async def verify_join(message: Message):
    if await joined_all(message.from_user.id):
        await message.answer("✅ Membership verified! You can now use the bot.", reply_markup=MAIN_KB)
    else:
        await message.answer("❌ Join every required channel/group first, then tap again.", reply_markup=JOIN_KB)

@dp.message(F.text.in_({"📲 Get Number", "📩 Receive OTP", "🌍 Available Countries", "🆘 Support"}))
async def services(message: Message):
    if not await gate(message):
        return
    replies = {
        "📲 Get Number": "📲 Get Number\n\nA legitimate number-provider API must be connected before this feature can supply numbers.",
        "📩 Receive OTP": "📩 Receive OTP\n\nConnect your provider's API to retrieve OTPs for numbers you are authorized to use.",
        "🌍 Available Countries": "🌍 Available Countries\n\nConnect a number-provider API to list its supported countries.",
        "🆘 Support": "🆘 Support\n\nPlease contact the bot administrator for help.",
    }
    await message.answer(replies[message.text], reply_markup=MAIN_KB)

@dp.message(Command("addforcechannel"))
async def add_channel(message: Message):
    if not is_owner(message.from_user.id):
        return await message.answer("⛔ Owner only.")
    p = (message.text or "").split(maxsplit=3)
    if len(p) < 4:
        return await message.answer("Usage: /addforcechannel @channel https://t.me/channel Channel Name")
    with db() as con:
        con.execute("INSERT INTO targets(kind,chat_id,url,label) VALUES('channel',?,?,?)", (p[1], p[2], p[3]))
    await message.answer("✅ Channel added. Make the bot an administrator there so it can check membership.")

@dp.message(Command("addforcegroup"))
async def add_group(message: Message):
    if not is_owner(message.from_user.id):
        return await message.answer("⛔ Owner only.")
    p = (message.text or "").split(maxsplit=3)
    if len(p) < 4:
        return await message.answer("Usage: /addforcegroup @group https://t.me/group Group Name")
    with db() as con:
        con.execute("INSERT INTO targets(kind,chat_id,url,label) VALUES('group',?,?,?)", (p[1], p[2], p[3]))
    await message.answer("✅ Group added.")

@dp.message(Command("listforce"))
async def list_force(message: Message):
    if not is_owner(message.from_user.id):
        return await message.answer("⛔ Owner only.")
    ts = targets()
    await message.answer("\n".join(f"#{t['id']} [{t['kind']}] {t['label']} — {t['chat_id']}" for t in ts) or "No targets configured.")

@dp.message(Command("removeforce"))
async def remove_force(message: Message):
    if not is_owner(message.from_user.id):
        return await message.answer("⛔ Owner only.")
    p = (message.text or "").split()
    if len(p) != 2 or not p[1].isdigit():
        return await message.answer("Usage: /removeforce <id>")
    with db() as con:
        cur = con.execute("DELETE FROM targets WHERE id=?", (int(p[1]),))
    await message.answer("✅ Removed." if cur.rowcount else "Target not found.")

@dp.message(Command("addowner"))
async def add_owner(message: Message):
    if not is_primary(message.from_user.id):
        return await message.answer("⛔ Only the primary owner can add owners.")
    try:
        user_s, days_s = (message.text or "").partition(" ")[2].split(",", 1)
        uid, days = int(user_s.strip()), int(days_s.strip())
        if uid <= 0 or not 1 <= days <= 3650:
            raise ValueError
    except ValueError:
        return await message.answer("Usage: /addowner <id>,<days>\nExample: /addowner 123456789,30")
    expires = int(time.time()) + days * 86400
    with db() as con:
        con.execute("INSERT INTO owners VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET expires_at=excluded.expires_at, added_by=excluded.added_by",
                    (uid, expires, message.from_user.id))
    await message.answer(f"✅ Owner {uid} added for {days} day(s), until {datetime.fromtimestamp(expires, timezone.utc):%Y-%m-%d %H:%M UTC}.")

@dp.message(Command("removeowner"))
async def remove_owner(message: Message):
    if not is_primary(message.from_user.id):
        return await message.answer("⛔ Primary owner only.")
    p = (message.text or "").split()
    if len(p) != 2 or not p[1].isdigit():
        return await message.answer("Usage: /removeowner <id>")
    with db() as con:
        cur = con.execute("DELETE FROM owners WHERE user_id=?", (int(p[1]),))
    await message.answer("✅ Removed." if cur.rowcount else "Owner not found.")

@dp.message(Command("owners"))
async def owners(message: Message):
    if not is_primary(message.from_user.id):
        return await message.answer("⛔ Primary owner only.")
    with db() as con:
        rows = con.execute("SELECT user_id,expires_at FROM owners ORDER BY user_id").fetchall()
    await message.answer("\n".join(
        f"{r['user_id']} — {'active' if r['expires_at'] > int(time.time()) else 'expired'} — {datetime.fromtimestamp(r['expires_at'], timezone.utc):%Y-%m-%d %H:%M UTC}"
        for r in rows
    ) or "No temporary owners.")

@dp.message(Command("stats"))
async def stats(message: Message):
    if not is_owner(message.from_user.id):
        return await message.answer("⛔ Owner only.")
    with db() as con:
        count = con.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
    await message.answer(f"📊 Registered users: {count}\nForce-join targets: {len(targets())}")

@dp.message()
async def fallback(message: Message):
    if await gate(message):
        await message.answer("Please choose a service from the menu.", reply_markup=MAIN_KB)

async def on_startup(app):
    if not RENDER_EXTERNAL_URL:
        raise RuntimeError("Set RENDER_EXTERNAL_URL to your Render service URL.")
    webhook_url = f"{RENDER_EXTERNAL_URL}/telegram/{WEBHOOK_SECRET}"
    await bot.set_webhook(webhook_url, secret_token=WEBHOOK_SECRET, drop_pending_updates=True)

async def on_shutdown(app):
    await bot.delete_webhook()
    await bot.session.close()

def create_app():
    init_db()
    app = web.Application()
    app["bot"] = bot
    app["dispatcher"] = dp
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET).register(app, path=f"/telegram/{WEBHOOK_SECRET}")
    setup_application(app, dp, bot=bot)
    async def health(request):
        return web.Response(text="Telegram bot is running.")
    app.router.add_get("/", health)
    return app

if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=PORT)
