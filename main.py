import os
import time
import random
import string
import qrcode
from io import BytesIO
from flask import Flask
from threading import Thread
from pyrogram import Client, filters
from pyrogram.errors import UserNotParticipant
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient

# --- KEEP-ALIVE ---
web = Flask('')
@web.route('/')
def home(): return "Bot is Running!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    web.run(host='0.0.0.0', port=port)

def keep_alive():
    Thread(target=run_web).start()

# --- CONFIG ---
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME") 
OWNER_ID = int(os.getenv("OWNER_ID", "1853401283"))
UPI_ID = os.getenv("UPI_ID")
BOT_USERNAME = "Memestorehubbot"

app = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo = AsyncIOMotorClient(MONGO_URI)
db = mongo["bot_db"]
videos, premium_users, payments = db["videos"], db["premium_users"], db["payments"]

app.batch_data = {}

# --- FORCE JOIN ---
async def check_join(client, user_id):
    try:
        await client.get_chat_member(CHANNEL_USERNAME, user_id)
        return True
    except UserNotParticipant: return False
    except: return False

# --- START COMMAND ---
@app.on_message(filters.command("start"))
async def start(client, message):
    if not await check_join(client, message.from_user.id):
        await message.reply_text(f"🚫 पहले channel join करो:\n\nhttps://t.me/{CHANNEL_USERNAME.replace('@','')}")
        return

    if len(message.command) < 2:
        await message.reply_text("Welcome!") 
        return

    name = message.command[1].lower()
    data = await videos.find_one({"name": name})
    if not data:
        await message.reply_text("❌ Video not found!")
        return

    user_p = await premium_users.find_one({"user_id": message.from_user.id})
    if user_p and user_p["expiry"] > int(time.time()):
        if data.get("type") == "batch":
            for f_id in data["file_ids"]: await message.reply_video(f_id)
        else: await message.reply_video(data["file_id"])
    else:
        await message.reply_text(
            "⚠️ **Premium Required!**\n\nBhai, ye file sirf Premium users ke liye hai.\n\n"
            "✅ After buying a plan you can watch all content unlimited time.\n"
            "✅ Plan lene ke baad aap saara content unlimited baar dekh sakte hain.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 SUBSCRIBE 💎", callback_data="premium")]])
        )

# --- CALLBACKS ---
@app.on_callback_query()
async def cb(client, query):
    if query.data == "premium":
        btns = [[InlineKeyboardButton(f"7 Days - ₹19", callback_data="buy_7d")],
                [InlineKeyboardButton(f"15 Days - ₹29", callback_data="buy_15d")],
                [InlineKeyboardButton(f"30 Days - ₹39", callback_data="buy_30d")],
                [InlineKeyboardButton(f"100 Days - ₹99", callback_data="buy_100d")]]
        await query.message.reply_text("💎 **Choose Plan:**", reply_markup=InlineKeyboardMarkup(btns))
    elif query.data.startswith("buy_"):
        days = query.data.split("_")[1]
        price = {"7d":"19", "15d":"29", "30d":"39", "100d":"99"}[days]
        pid = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        qr = qrcode.make(f"upi://pay?pa={UPI_ID}&pn=Premium&am={price}&cu=INR&tn={pid}")
        bio = BytesIO(); bio.name = "p.png"; qr.save(bio, "PNG"); bio.seek(0)
        await payments.insert_one({"user_id": query.from_user.id, "payment_id": pid, "days": int(days[:-1])})
        
        await query.message.reply_photo(
            photo=bio, 
            caption=(
                f"💎 Premium Plan Request\n\n"
                f"Plan: {days.replace('d', ' Days')}\n"
                f"Amount: ₹{price}\n"
                f"Payment ID: {pid}\n\n"
                f"QR scan करके payment करो\n\n"
                f"Payment के बाद यह भेजो:\n"
                f"`/verify {pid} YOUR_UTR`"
            )
        )
    await query.answer()

# --- ADMIN NOTIFICATION ---
@app.on_message(filters.command("verify"))
async def verify(client, message):
    if len(message.command) < 3: return
    pid, utr = message.command[1], message.command[2]
    pay = await payments.find_one({"payment_id": pid})
    if pay:
        await client.send_message(OWNER_ID, f"💰 **New Premium Request**\n\nUser ID: `{message.from_user.id}`\nPlan: {pay['days']} Days\nPayment ID: {pid}\nUTR: {utr}\n\n`/approve {message.from_user.id} {pay['days']}`")
        await message.reply_text("✅ Sent to admin for approval!")

@app.on_message(filters.command("approve"))
async def approve(client, message):
    if message.from_user.id != OWNER_ID: return
    uid, days = int(message.command[1]), int(message.command[2])
    exp = int(time.time()) + (days * 86400)
    await premium_users.update_one({"user_id": uid}, {"$set": {"expiry": exp}}, upsert=True)
    await client.send_message(uid, "🎉 Activated!")
    await message.reply_text("✅ Done!")

# --- OWNER: VIDEO ADDING ---
@app.on_message((filters.video | filters.document) & filters.private)
async def handle_video(client, message):
    if message.from_user.id != OWNER_ID: return
    fid = message.video.file_id if message.video else message.document.file_id
    
    if OWNER_ID not in app.batch_data: app.batch_data[OWNER_ID] = []
    app.batch_data[OWNER_ID].append(fid)
    app.last_fid = fid

    await message.reply_text(
        f"✅ **Video added**\n\n"
        f"Batch size: {len(app.batch_data[OWNER_ID])}\n\n"
        f"Single save:\n`/add movie1`\n\n"
        f"Batch save:\n`/addbatch series1`"
    )

@app.on_message(filters.command("add"))
async def add_single(client, message):
    if message.from_user.id != OWNER_ID or len(message.command) < 2: return
    name = message.command[1].lower()
    await videos.update_one({"name": name}, {"$set": {"file_id": app.last_fid, "type": "single"}}, upsert=True)
    
    # CLICK AND WATCH LINE ADDED
    await message.reply_text(
        f"Videos: 1\n\n"
        f"Click and Watch 👇\n"
        f"https://t.me/{BOT_USERNAME}?start={name}",
        disable_web_page_preview=True
    )

@app.on_message(filters.command("addbatch"))
async def add_batch(client, message):
    if message.from_user.id != OWNER_ID or len(message.command) < 2: return
    name = message.command[1].lower()
    f_list = list(app.batch_data.get(OWNER_ID, []))
    if not f_list: return
    
    await videos.update_one({"name": name}, {"$set": {"file_ids": f_list, "type": "batch"}}, upsert=True)
    size = len(f_list)
    app.batch_data[OWNER_ID] = [] 
    
    # CLICK AND WATCH LINE ADDED
    await message.reply_text(
        f"✅ **Batch Saved**\n\n"
        f"Videos: {size}\n\n"
        f"Click and Watch 👇\n"
        f"https://t.me/{BOT_USERNAME}?start={name}",
        disable_web_page_preview=True
    )

if __name__ == "__main__":
    keep_alive()
    app.run()
