import asyncio
import os
import sqlite3
import time
from datetime import datetime, timezone

from aiohttp import web
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, Update, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ChatMemberUpdated
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
support_waiting = set()  # user IDs currently composing a support message

JOIN_TEXT = "🔐 JOIN OUR REQUIRED CHANNELS TO USE THIS BOT\n\nJoin every channel/group below, then tap ✅ I've Joined."

def join_keyboard():
    rows = []
    for target in targets():
        style = "primary" if target["kind"] == "channel" else "primary"
        rows.append([InlineKeyboardButton(
            text=f"📢 Join {target['label']}", url=target["url"], style=style
        )])
    rows.append([InlineKeyboardButton(
        text="✅ I've Joined", callback_data="verify_join", style="success"
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)
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
        CREATE TABLE IF NOT EXISTS demo_orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            country TEXT NOT NULL,
            service TEXT NOT NULL,
            demo_number TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'waiting',
            created_at INTEGER NOT NULL
        );
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
    await message.answer(JOIN_TEXT, reply_markup=join_keyboard())
    return False

@dp.message(CommandStart())
async def start(message: Message):
    save_user(message.from_user)
    if await gate(message):
        await message.answer("📱 Welcome to Number Service!\n\nChoose a service below.", reply_markup=MAIN_KB)

@dp.chat_member()
async def membership_changed(event: ChatMemberUpdated):
    """Notify users when they leave a required target; every later message is gated too."""
    target_ids = {str(t["chat_id"]).lstrip("@") for t in targets()}
    chat_username = (event.chat.username or "").lstrip("@")
    chat_id = str(event.chat.id)
    if chat_id not in target_ids and chat_username not in target_ids:
        return
    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    was_member = old_status in ("member", "administrator", "creator", "restricted")
    is_member = new_status in ("member", "administrator", "creator", "restricted")
    if was_member and not is_member:
        try:
            await bot.send_message(
                event.new_chat_member.user.id,
                "⛔ You left a required channel or group. Join all required targets again to use this bot.",
                reply_markup=join_keyboard(),
            )
        except Exception:
            pass

@dp.callback_query(F.data == "verify_join")
async def verify_join_callback(callback: CallbackQuery):
    if await joined_all(callback.from_user.id):
        await callback.answer("Membership verified!")
        await callback.message.answer("✅ Membership verified! You can now use the bot.", reply_markup=MAIN_KB)
    else:
        await callback.answer("Please join every required channel/group first, then tap again.", show_alert=True)

@dp.message(F.text == "💬 Contact Support")
async def begin_support(message: Message):
    if not await gate(message):
        return
    support_waiting.add(message.from_user.id)
    await message.answer("💬 Send your message now. Our support team will receive it and reply here. Send /cancel to stop.")

@dp.message(Command("cancel"))
async def cancel_support(message: Message):
    if message.from_user.id in support_waiting:
        support_waiting.discard(message.from_user.id)
        await message.answer("Support message cancelled.", reply_markup=MAIN_KB)
    else:
        await message.answer("Nothing to cancel.", reply_markup=MAIN_KB)

@dp.message(Command("reply"))
async def admin_reply(message: Message):
    if not is_owner(message.from_user.id):
        return await message.answer("⛔ Owner only.")
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        return await message.answer("Usage: /reply <user_id> <message>\nExample: /reply 123456789 Hello, how can we help?")
    try:
        await bot.send_message(int(parts[1]), "🆘 Support team reply:\n\n" + parts[2])
        await message.answer("✅ Reply sent.")
    except Exception as exc:
        await message.answer(f"❌ Could not send reply. Check the user ID and whether the user has started the bot. ({type(exc).__name__})")

@dp.message(F.text == "🔙 Back to Menu")
async def back_to_menu(message: Message):
    support_waiting.discard(message.from_user.id)
    if await gate(message):
        await message.answer("Main menu:", reply_markup=MAIN_KB)

COUNTRIES = ["🇳🇬 Nigeria", "🇺🇸 United States", "🇬🇧 United Kingdom", "🇨🇦 Canada", "🇮🇳 India", "🇿🇦 South Africa", "🇬🇭 Ghana", "🇰🇪 Kenya"]
SERVICES = ["Telegram", "WhatsApp", "Instagram", "Other"]

@dp.message(F.text.in_({"📲 Get Number", "📩 Receive OTP", "🌍 Available Countries", "🆘 Support"}))
async def services(message: Message):
    if not await gate(message):
        return
    if message.text == "📲 Get Number":
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=c, callback_data=f"demo_country:{i}", style="primary")] for i, c in enumerate(COUNTRIES)])
        return await message.answer("📲 DEMO NUMBER SERVICE\n\nChoose a country. Demo numbers are fictional and cannot receive real SMS.", reply_markup=kb)
    if message.text == "📩 Receive OTP":
        with db() as con:
            rows = con.execute("SELECT id,country,service,demo_number,status FROM demo_orders WHERE user_id=? ORDER BY id DESC LIMIT 10", (message.from_user.id,)).fetchall()
        if not rows:
            return await message.answer("📩 You have no demo orders yet. Tap 📲 Get Number to create one.", reply_markup=MAIN_KB)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"🧪 {r['service']} · {r['status'].upper()}", callback_data=f"demo_otp:{r['id']}", style="primary" if r['status']=='waiting' else "success")] for r in rows])
        return await message.answer("📩 YOUR DEMO ORDERS\nTap an order to view its simulated OTP. No real SMS is received.", reply_markup=kb)
    if message.text == "🌍 Available Countries":
        return await message.answer("🌍 Demo countries available:\n" + "\n".join(COUNTRIES) + "\n\nThese are demo options, not live number inventory.", reply_markup=MAIN_KB)
    support_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="💬 Contact Support")],[KeyboardButton(text="🔙 Back to Menu")]], resize_keyboard=True)
    await message.answer("🆘 CUSTOMER SUPPORT\n\nTap 💬 Contact Support to message the support team.", reply_markup=support_kb)

@dp.callback_query(F.data.startswith("demo_country:"))
async def demo_country(callback: CallbackQuery):
    if not await joined_all(callback.from_user.id):
        await callback.answer("Join the required channels first.", show_alert=True); return
    try: country = COUNTRIES[int(callback.data.split(":",1)[1])]
    except (ValueError, IndexError):
        await callback.answer("Invalid country.", show_alert=True); return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"📱 {svc}", callback_data=f"demo_service:{COUNTRIES.index(country)}:{i}", style="primary")] for i, svc in enumerate(SERVICES)])
    await callback.answer()
    await callback.message.answer(f"🌍 {country} selected. Choose a demo service:", reply_markup=kb)

@dp.callback_query(F.data.startswith("demo_service:"))
async def demo_service(callback: CallbackQuery):
    if not await joined_all(callback.from_user.id):
        await callback.answer("Join the required channels first.", show_alert=True); return
    try:
        _, ci, si = callback.data.split(":"); country, service = COUNTRIES[int(ci)], SERVICES[int(si)]
    except (ValueError, IndexError):
        await callback.answer("Invalid selection.", show_alert=True); return
    demo_number = f"DEMO-{secrets.randbelow(900000) + 100000}"
    with db() as con:
        cur = con.execute("INSERT INTO demo_orders(user_id,country,service,demo_number,status,created_at) VALUES(?,?,?,?,?,?)", (callback.from_user.id,country,service,demo_number,"waiting",int(time.time())))
        order_id = cur.lastrowid
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🟡 WAITING FOR DEMO OTP", callback_data=f"demo_otp:{order_id}", style="primary")]])
    await callback.answer("Demo order created")
    await callback.message.answer(f"🧪 DEMO ORDER #{order_id}\nCountry: {country}\nService: {service}\nDemo ID: `{demo_number}`\nStatus: 🟡 Waiting\n\nThis is not a real phone number and cannot receive real SMS.", reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("demo_otp:"))
async def demo_otp(callback: CallbackQuery):
    try: order_id = int(callback.data.split(":",1)[1])
    except ValueError:
        await callback.answer("Invalid order.", show_alert=True); return
    with db() as con:
        row = con.execute("SELECT * FROM demo_orders WHERE id=? AND user_id=?", (order_id,callback.from_user.id)).fetchone()
    if not row:
        await callback.answer("Order not found.", show_alert=True); return
    # Fixed clearly-labelled sample code; it is not received from an external service.
    await callback.answer("Demo OTP generated")
    await callback.message.answer(f"🧪 SIMULATED OTP\nOrder: #{row['id']}\nService: {row['service']}\nDemo ID: {row['demo_number']}\n\n🔐 Sample code: 123456\n\n⚠️ Test code only — no real SMS was received.")

@dp.message(F.text & ~F.text.startswith("/"))
async def support_message_or_fallback(message: Message):
    uid = message.from_user.id
    if uid in support_waiting and uid != ADMIN_ID:
        if not await gate(message):
            support_waiting.discard(uid)
            return
        text_content = message.text or message.caption or "[Non-text message]"
        username = f"@{message.from_user.username}" if message.from_user.username else "No username"
        try:
            await bot.send_message(ADMIN_ID, f"🆘 SUPPORT MESSAGE\nFrom: {message.from_user.full_name} ({username})\nUser ID: {uid}\n\n{text_content}\n\nReply with: /reply {uid} <your message>")
            # Forward attachments as well as the readable summary when possible.
            if message.photo:
                await bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=f"Attachment from support user {uid}")
            elif message.document:
                await bot.send_document(ADMIN_ID, message.document.file_id, caption=f"Attachment from support user {uid}")
            elif message.voice:
                await bot.send_voice(ADMIN_ID, message.voice.file_id, caption=f"Voice message from support user {uid}")
            await message.answer("✅ Your message has been sent to support. You can send another message or /cancel to finish.")
        except Exception:
            await message.answer("❌ Sorry, your message could not be delivered. Please try again later.")
        return
    if await gate(message):
        await message.answer("Please choose a service from the menu.", reply_markup=MAIN_KB)

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

@dp.message(Command("adminhelp"))
async def admin_help(message: Message):
    if not is_owner(message.from_user.id):
        return await message.answer("⛔ Owner only.")
    text = (
        "🛠 ADMIN COMMANDS\n\n"
        "📊 /stats — user and demo-order statistics\n"
        "📢 /broadcast <message> — send an announcement to registered users (primary owner only)\n"
        "💬 /reply <user_id> <message> — reply to a support message\n"
        "➕ /addforcechannel <@channel> <t.me URL> <name> — add required channel\n"
        "➕ /addforcegroup <@group> <t.me URL> <name> — add required group\n"
        "📋 /listforce — list required channels/groups\n"
        "➖ /removeforce <id> — remove a required target\n"
        "👑 /owners — list temporary owners (primary owner only)\n"
        "➕ /addowner <user_id>,<days> — add temporary owner (primary owner only)\n"
        "➖ /removeowner <user_id> — remove owner (primary owner only)\n"
        "🆔 /myid — show your Telegram user ID"
    )
    await message.answer(text)

@dp.message(Command("myid"))
async def my_id(message: Message):
    await message.answer(f"Your Telegram user ID: {message.from_user.id}")

@dp.message(Command("stats"))
async def stats(message: Message):
    if not is_owner(message.from_user.id):
        return await message.answer("⛔ Owner only.")
    with db() as con:
        count = con.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        orders = con.execute("SELECT COUNT(*) n FROM demo_orders").fetchone()["n"]
        waiting = con.execute("SELECT COUNT(*) n FROM demo_orders WHERE status='waiting'").fetchone()["n"]
    await message.answer(
        "📊 BOT STATISTICS\n\n"
        f"👥 Registered users: {count}\n"
        f"🧪 Demo orders: {orders}\n"
        f"🟡 Waiting demo orders: {waiting}\n"
        f"📢 Force-join targets: {len(targets())}"
    )

@dp.message(Command("broadcast"))
async def broadcast(message: Message):
    if not is_primary(message.from_user.id):
        return await message.answer("⛔ Primary owner only.")
    announcement = (message.text or "").partition(" ")[2].strip()
    if not announcement:
        return await message.answer("Usage: /broadcast Your announcement text")
    with db() as con:
        rows = con.execute("SELECT user_id FROM users").fetchall()
    sent = failed = 0
    status = await message.answer(f"📢 Sending announcement to {len(rows)} registered users…")
    for row in rows:
        try:
            await bot.send_message(row["user_id"], "📢 ANNOUNCEMENT\n\n" + announcement)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.04)
    await status.edit_text(f"📢 Broadcast complete.\n✅ Sent: {sent}\n❌ Failed: {failed}\n👥 Total: {len(rows)}")

async def on_startup(app):
    if not RENDER_EXTERNAL_URL:
        raise RuntimeError("Set RENDER_EXTERNAL_URL to your Render service URL.")
    webhook_url = f"{RENDER_EXTERNAL_URL.rstrip('/')}/telegram/{WEBHOOK_SECRET}"
    info = await bot.get_webhook_info()
    if info.url != webhook_url:
        await bot.set_webhook(
            url=webhook_url,
            secret_token=WEBHOOK_SECRET,
            allowed_updates=dp.resolve_used_update_types(),
        )
    print("Telegram webhook registered successfully.")

async def on_shutdown(app):
    # Do not delete the webhook on normal Render restarts.
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
