import asyncio, os, sqlite3, time
from datetime import datetime, timezone
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

load_dotenv()
TOKEN=os.getenv("BOT_TOKEN","").strip()
ADMIN_ID=int(os.getenv("ADMIN_ID","0"))
DB=os.getenv("DB_PATH","bot.db")
if not TOKEN or not ADMIN_ID:
    raise RuntimeError("Set BOT_TOKEN and ADMIN_ID in .env")

bot=Bot(TOKEN); dp=Dispatcher()
JOIN_TEXT="🔐 JOIN OUR CHANNELS\n\nTo use this bot, join all the\nrequired channels and groups below."
JOIN_KB=ReplyKeyboardMarkup(keyboard=[
 [KeyboardButton(text="📢 Join Channel"), KeyboardButton(text="👥 Join Group")],
 [KeyboardButton(text="✅ I've Joined")]], resize_keyboard=True)
MAIN_KB=ReplyKeyboardMarkup(keyboard=[
 [KeyboardButton(text="📲 Get Number"), KeyboardButton(text="📩 Receive OTP")],
 [KeyboardButton(text="🌍 Available Countries"), KeyboardButton(text="🆘 Support")]], resize_keyboard=True)

def db():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def init():
 with db() as c:
  c.executescript("""
  CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, created_at INTEGER);
  CREATE TABLE IF NOT EXISTS targets(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, chat_id TEXT, url TEXT, label TEXT);
  CREATE TABLE IF NOT EXISTS owners(user_id INTEGER PRIMARY KEY, expires_at INTEGER, added_by INTEGER);
  """)
def save_user(u):
 with db() as c:
  c.execute("INSERT INTO users VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name",
   (u.id,u.username,u.first_name,int(time.time())))
def owner(uid):
 if uid==ADMIN_ID: return True
 with db() as c:
  r=c.execute("SELECT expires_at FROM owners WHERE user_id=?",(uid,)).fetchone()
  if r and r["expires_at"]>int(time.time()): return True
  if r: c.execute("DELETE FROM owners WHERE user_id=?",(uid,))
 return False
def targets(kind=None):
 with db() as c:
  q="SELECT * FROM targets"; args=()
  if kind: q+=" WHERE kind=?"; args=(kind,)
  return [dict(r) for r in c.execute(q+" ORDER BY id",args).fetchall()]
async def joined_all(uid):
 for t in targets():
  try:
   m=await bot.get_chat_member(t["chat_id"],uid)
   if m.status in ("left","kicked"): return False
  except Exception: return False
 return True
async def gate(m):
 if await joined_all(m.from_user.id): return True
 await m.answer(JOIN_TEXT,reply_markup=JOIN_KB); return False

@dp.message(CommandStart())
async def start(m):
 save_user(m.from_user)
 if await gate(m): await m.answer("📱 Welcome to Number Service!\n\nChoose a service below.",reply_markup=MAIN_KB)
@dp.message(F.text=="📢 Join Channel")
async def channels(m):
 ts=targets("channel")
 await m.answer("📢 Required channels:\n\n" + ("\n\n".join(f"{t['label']}\n{t['url']}" for t in ts) if ts else "No channels configured yet."),disable_web_page_preview=True)
@dp.message(F.text=="👥 Join Group")
async def groups(m):
 ts=targets("group")
 await m.answer("👥 Required groups:\n\n" + ("\n\n".join(f"{t['label']}\n{t['url']}" for t in ts) if ts else "No groups configured yet."),disable_web_page_preview=True)
@dp.message(F.text=="✅ I've Joined")
async def verify(m):
 if await joined_all(m.from_user.id): await m.answer("✅ Membership verified!",reply_markup=MAIN_KB)
 else: await m.answer("❌ Join every required channel/group first, then tap again.",reply_markup=JOIN_KB)
@dp.message(F.text.in_({"📲 Get Number","📩 Receive OTP","🌍 Available Countries","🆘 Support"}))
async def services(m):
 if not await gate(m): return
 answers={
 "📲 Get Number":"📲 Get Number\n\nNumber-provider API not connected yet. Choose a provider and we can integrate it.",
 "📩 Receive OTP":"📩 Receive OTP\n\nOTP retrieval becomes available after connecting your provider's API.",
 "🌍 Available Countries":"🌍 Available Countries\n\nConnect a number-provider API to display its supported countries.",
 "🆘 Support":"🆘 Support\n\nPlease contact the bot administrator for help."
 }
 await m.answer(answers[m.text],reply_markup=MAIN_KB)

@dp.message(Command("addforcechannel"))
async def add_channel(m):
 if not owner(m.from_user.id): return await m.answer("⛔ Owner only.")
 p=(m.text or "").split(maxsplit=3)
 if len(p)<4: return await m.answer("Usage: /addforcechannel @channel https://t.me/channel Channel Name")
 with db() as c: c.execute("INSERT INTO targets(kind,chat_id,url,label) VALUES('channel',?,?,?)",(p[1],p[2],p[3]))
 await m.answer("✅ Channel added. Make the bot an admin there so membership checks work.")
@dp.message(Command("addforcegroup"))
async def add_group(m):
 if not owner(m.from_user.id): return await m.answer("⛔ Owner only.")
 p=(m.text or "").split(maxsplit=3)
 if len(p)<4: return await m.answer("Usage: /addforcegroup @group https://t.me/group Group Name")
 with db() as c: c.execute("INSERT INTO targets(kind,chat_id,url,label) VALUES('group',?,?,?)",(p[1],p[2],p[3]))
 await m.answer("✅ Group added. Ensure the bot has permission to check membership.")
@dp.message(Command("listforce"))
async def list_force(m):
 if not owner(m.from_user.id): return await m.answer("⛔ Owner only.")
 ts=targets()
 await m.answer("\n".join([f"#{t['id']} [{t['kind']}] {t['label']} — {t['chat_id']}" for t in ts]) or "No targets configured.")
@dp.message(Command("removeforce"))
async def remove_force(m):
 if not owner(m.from_user.id): return await m.answer("⛔ Owner only.")
 p=(m.text or "").split()
 if len(p)!=2 or not p[1].isdigit(): return await m.answer("Usage: /removeforce <id>")
 with db() as c: cur=c.execute("DELETE FROM targets WHERE id=?",(int(p[1]),))
 await m.answer("✅ Removed." if cur.rowcount else "Target not found.")
@dp.message(Command("addowner"))
async def add_owner(m):
 if m.from_user.id!=ADMIN_ID: return await m.answer("⛔ Only the primary owner can add owners.")
 try:
  uid_s,days_s=(m.text or "").partition(" ")[2].split(",",1)
  uid,days=int(uid_s.strip()),int(days_s.strip())
  if uid<=0 or not 1<=days<=3650: raise ValueError
 except ValueError: return await m.answer("Usage: /addowner <id>,<days>\nExample: /addowner 123456789,30")
 exp=int(time.time())+days*86400
 with db() as c: c.execute("INSERT INTO owners VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET expires_at=excluded.expires_at,added_by=excluded.added_by",(uid,exp,m.from_user.id))
 await m.answer(f"✅ Owner {uid} added for {days} day(s), until {datetime.fromtimestamp(exp,timezone.utc):%Y-%m-%d %H:%M UTC}.")
@dp.message(Command("removeowner"))
async def remove_owner(m):
 if m.from_user.id!=ADMIN_ID: return await m.answer("⛔ Primary owner only.")
 p=(m.text or "").split()
 if len(p)!=2 or not p[1].isdigit(): return await m.answer("Usage: /removeowner <id>")
 with db() as c: cur=c.execute("DELETE FROM owners WHERE user_id=?",(int(p[1]),))
 await m.answer("✅ Removed." if cur.rowcount else "Owner not found.")
@dp.message(Command("owners"))
async def owners(m):
 if m.from_user.id!=ADMIN_ID: return await m.answer("⛔ Primary owner only.")
 with db() as c: rs=c.execute("SELECT user_id,expires_at FROM owners ORDER BY user_id").fetchall()
 await m.answer("\n".join(f"{r['user_id']} — {'active' if r['expires_at']>int(time.time()) else 'expired'} — {datetime.fromtimestamp(r['expires_at'],timezone.utc):%Y-%m-%d %H:%M UTC}" for r in rs) or "No temporary owners.")
@dp.message(Command("stats"))
async def stats(m):
 if not owner(m.from_user.id): return await m.answer("⛔ Owner only.")
 with db() as c:
  u=c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
 await m.answer(f"📊 Registered users: {u}\nForce-join targets: {len(targets())}")
@dp.message()
async def fallback(m):
 if await gate(m): await m.answer("Please choose a service from the menu.",reply_markup=MAIN_KB)

async def main():
 init()
 await dp.start_polling(bot)
if __name__=="__main__": asyncio.run(main())
