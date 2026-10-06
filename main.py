import os
import re
import requests
import threading
import asyncio
import sqlite3
from datetime import datetime, timezone, timedelta
from flask import Flask, request
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# =========================================================
# ⚠️ Configs & IDs
# =========================================================
TOKEN = os.getenv("BOT_TOKEN", "8653645989:AAE2qWZvj0SO8dIG07edcIW9fO3E-1lioT0")
TELEBIRR_NO = "0925358925"
ADMIN_USERNAMES = "@mst10m ወይም @ATCITYZEN"
ADMIN_PRIMARY_URL = "https://t.me/mst10m"
CHANNEL_LINK = "https://t.me/ETHIO_FANTASY_1"
GROUP_CHAT_ID = -1002391954418

PHOTO_PATH_1 = "photo_2026-09-06_22-09-38.jpg"
PHOTO_PATH_2 = "photo_2026-09-08_03-50-53.jpg"

FPL_LEAGUE_ID = os.getenv("FPL_LEAGUE_ID", "2309527")
FPL_CODE = os.getenv("FPL_CODE", "v8v7fu")
ENTRY_FEE = "50"

DB_NAME = "bot_data.db"

DAYS_AMHARIC = {
    "Monday": "ሰኞ", "Tuesday": "ማክሰኞ", "Wednesday": "ረቡዕ",
    "Thursday": "ሐሙስ", "Friday": "አርብ", "Saturday": "ቅዳሜ", "Sunday": "እሁድ"
}

MONTHS_AMHARIC = {
    "January": "ጥር", "February": "የካቲት", "March": "መጋቢት", "April": "ሚያዝያ",
    "May": "ግንቦት", "June": "ሰኔ", "July": "ሐምሌ", "August": "ነሐሴ",
    "September": "መስከረም", "October": "ጥቅምት", "November": "ሕዳር", "December": "ታኅሣሥ"
}

# =========================================================
# 🗄️ DATABASE SETUP (SQLite)
# =========================================================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # 1. ከስልክ የደረሱ የTelebirr SMSዎች ማከማቻ (status: 'PENDING' ወይም 'USED')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS telebirr_sms (
            tx_id TEXT PRIMARY KEY,
            status TEXT DEFAULT 'PENDING',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 2. የተጠቃሚዎች የFPL ቡድን ስም ማከማቻ
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_teams (
            user_id INTEGER PRIMARY KEY,
            team_name TEXT,
            photo_id TEXT
        )
    ''')

    # 3. TG ላይ Tx ID ልከው SMS የሚጠብቁ ተጠቃሚዎች
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_users (
            tx_id TEXT PRIMARY KEY,
            user_id INTEGER
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

# DB Helper Functions
def save_telebirr_sms(tx_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO telebirr_sms (tx_id, status) VALUES (?, 'PENDING')", (tx_id,))
    conn.commit()
    conn.close()

def get_sms_status(tx_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM telebirr_sms WHERE tx_id = ?", (tx_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def mark_sms_used(tx_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE telebirr_sms SET status = 'USED' WHERE tx_id = ?", (tx_id,))
    conn.commit()
    conn.close()

def save_user_team(user_id, team_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO user_teams (user_id, team_name, photo_id) VALUES (?, ?, (SELECT photo_id FROM user_teams WHERE user_id = ?))", (user_id, team_name, user_id))
    conn.commit()
    conn.close()

def save_user_photo(user_id, photo_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO user_teams (user_id, team_name, photo_id) VALUES (?, (SELECT team_name FROM user_teams WHERE user_id = ?), ?)", (user_id, user_id, photo_id))
    conn.commit()
    conn.close()

def get_user_data(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT team_name, photo_id FROM user_teams WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"team_name": row[0] or "አልተጠቀሰም", "photo_id": row[1]}
    return {"team_name": "አልተጠቀሰም", "photo_id": None}

def save_pending_user(tx_id, user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO pending_users (tx_id, user_id) VALUES (?, ?)", (tx_id, user_id))
    conn.commit()
    conn.close()

def get_and_clear_pending_user(tx_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM pending_users WHERE tx_id = ?", (tx_id,))
    row = cursor.fetchone()
    if row:
        cursor.execute("DELETE FROM pending_users WHERE tx_id = ?", (tx_id,))
        conn.commit()
        conn.close()
        return row[0]
    conn.close()
    return None

# =========================================================
# ⚙️ GENERAL HELPERS & FLASK
# =========================================================
app = Flask(__name__)

def main_keyboard():
    keyboard = [
        ["💳 ለመክፈል", "⚽ የመግቢያ ኮድ ለመቀበል"],
        ["👥 ጓደኛን መጋበዝ (Invite)", "🎁 ነፃ እድል"],
        ["📊 የሊግ ደረጃዎች (Rank)", "ℹ️ መመሪያ"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def gregorian_to_ethiopian(dt):
    year, month, day = dt.year, dt.month, dt.day
    is_leap = (year % 4 == 3)
    new_year_day = 12 if is_leap else 11

    if month == 9 and day < new_year_day:
        eth_month = "ጳጉሜ"
        eth_day = day + (6 if is_leap else 5)
        eth_year = year - 8
    elif month == 9:
        eth_month = "መስከረም"
        eth_day = day - (new_year_day - 1)
        eth_year = year - 7
    elif month == 10:
        eth_month = "ጥቅምት" if day >= 11 else "መስከረም"
        eth_day = (day - 10) if day >= 11 else (day + 20)
        eth_year = year - 7
    else:
        eth_month = MONTHS_AMHARIC.get(dt.strftime("%B"), "")
        eth_day = day
        eth_year = year - 7

    return eth_month, eth_day, eth_year

def get_current_gameweek_info():
    try:
        url = "https://fantasy.premierleague.com/api/bootstrap-static/"
        res = requests.get(url, timeout=10).json()
        events = res.get('events', [])
        now_utc = datetime.now(timezone.utc)
        
        for event in events:
            deadline_str = event.get('deadline_time')
            if deadline_str:
                deadline_dt = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))
                close_time = deadline_dt - timedelta(minutes=30)
                
                if now_utc < close_time:
                    eat_time = deadline_dt + timedelta(hours=3)
                    day_amharic = DAYS_AMHARIC.get(eat_time.strftime("%A"), eat_time.strftime("%A"))
                    eth_month, eth_day, eth_year = gregorian_to_ethiopian(eat_time)
                    
                    day_english = eat_time.strftime("%A")
                    greg_month_short = eat_time.strftime("%b")
                    greg_day = eat_time.strftime("%d")
                    greg_year = eat_time.strftime("%Y")
                    time_ampm = eat_time.strftime("%I:%M %p")
                    
                    formatted_deadline = (
                        f"ከዛሬ ጀምሮ እስከ {day_amharic}፣ {eth_month} {eth_day}/{eth_year} "
                        f"({day_english}, {greg_month_short} {greg_day}/{greg_year}) - {time_ampm}"
                    )
                    return {
                        "gw_name": event.get('name'),
                        "deadline_str": formatted_deadline,
                        "is_open": True
                    }
        return {"gw_name": "Gameweek", "deadline_str": "አልታወቀም", "is_open": False}
    except Exception as e:
        print(f"FPL API Error: {e}")
        return {"gw_name": "Gameweek", "deadline_str": "N/A", "is_open": True}

async def delete_message_after_delay(chat_id, message_id, delay_seconds=600):
    await asyncio.sleep(delay_seconds)
    try:
        await bot_app.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        print(f"Error deleting message: {e}")

def process_successful_payment(user_id, tx_id):
    gw_info = get_current_gameweek_info()
    user_data = get_user_data(user_id)
    team_name = user_data["team_name"]
    photo_id = user_data["photo_id"]

    # 1. Tx IDውን USED ብሎ መቀየር (እንደገና እንዳይሰራ ማድረግ)
    mark_sms_used(tx_id)

    # 2. ለተጠቃሚው ኮዱን መላክ
    try:
        sent_msg = asyncio.run_coroutine_threadsafe(
            bot_app.bot.send_message(
                chat_id=user_id,
                text=(
                    f"✅ **ክፍያህ በትክክል ተረጋግጧል!**\n\n"
                    f"🏆 **የተመዘገቡበት፡** {gw_info['gw_name']}\n\n"
                    f"🔑 **የመግቢያ ኮድ (Code)፦**\n`{FPL_CODE}`\n\n"
                    f"🔗 **በሊንክ ቀጥታ ለመቀላቀል፦**\n"
                    f"https://fantasy.premierleague.com/leagues/auto-join/{FPL_CODE}\n\n"
                    f"⏱ ይህ መልእክት ከ 10 ደቂቃ በኋላ በራስ-ሰር ይፊቃል!"
                ),
                parse_mode="Markdown",
                protect_content=True
            ),
            bot_loop
        ).result()

        asyncio.run_coroutine_threadsafe(
            delete_message_after_delay(user_id, sent_msg.message_id, 600),
            bot_loop
        )
    except Exception as e:
        print(f"Error sending code to user: {e}")

    # 3. ለአድሚን ግሩፕ መላክ
    try:
        user_info = asyncio.run_coroutine_threadsafe(
            bot_app.bot.get_chat(user_id),
            bot_loop
        ).result()
        
        full_name = user_info.full_name if user_info else "ተጠቃሚ"
        username = f"@{user_info.username}" if user_info and user_info.username else "የለውም"

        admin_msg = (
            f"✅ **አዲስ የተረጋገጠ ክፍያ!**\n\n"
            f"👤 **ተጠቃሚ፦** {full_name} ({username})\n"
            f"🆔 **User ID፦** `{user_id}`\n"
            f"🔢 **Tx ID፦** `{tx_id}`\n"
            f"⚽ **የ FPL ቡድን ስም፦** `{team_name}`"
        )

        if photo_id:
            asyncio.run_coroutine_threadsafe(
                bot_app.bot.send_photo(chat_id=GROUP_CHAT_ID, photo=photo_id, caption=admin_msg, parse_mode="Markdown"),
                bot_loop
            )
        else:
            asyncio.run_coroutine_threadsafe(
                bot_app.bot.send_message(chat_id=GROUP_CHAT_ID, text=admin_msg, parse_mode="Markdown"),
                bot_loop
            )
    except Exception as e:
        print(f"Error sending to group: {e}")

# =========================================================
# 📩 SMS WEBHOOK (ከስልክ የሚመጣበት)
# =========================================================
@app.route('/')
def home():
    return "FPL Bot with Database is running!", 200

@app.route('/sms_webhook', methods=['GET', 'POST'], strict_slashes=False)
@app.route('/sms_webhook/', methods=['GET', 'POST'], strict_slashes=False)
def sms_webhook():
    if request.method == 'GET':
        return "SMS Webhook Active!", 200

    try:
        data = request.get_json(force=True, silent=True) or {}
        if not data and request.form:
            data = request.form.to_dict()
            
        full_message = str(data.get('message', '') or data.get('text', '') or request.get_data(as_text=True))
        print(f"--> Webhook SMS Received: {full_message}")

        found_ids = re.findall(r'[A-Za-z0-9]{8,}', full_message)
        
        for tx in found_ids:
            tx_upper = tx.upper()
            
            # 1. ዳታቤዝ ውስጥ አስቀምጥ
            save_telebirr_sms(tx_upper)

            # 2. ተጠቃሚው አስቀድሞ TG ላይ ልኮት የሚጠብቅ ከሆነ አስገባው
            waiting_user_id = get_and_clear_pending_user(tx_upper)
            if waiting_user_id:
                print(f"✅ MATCH FOUND! Pending User {waiting_user_id} matched with Tx {tx_upper}")
                process_successful_payment(waiting_user_id, tx_upper)

        return "OK", 200
    except Exception as e:
        print(f"Error in SMS Webhook: {e}")
        return "OK", 200

# =========================================================
# 🤖 TELEGRAM BOT HANDLERS
# =========================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gw_info = get_current_gameweek_info()
    welcome_text = (
        f"👋 **እንኳን ወደ FPL ውድድር ቦት በደህና መጡ!**\n\n"
        f"⚽ **የአሁኑ ውድድር፦** {gw_info['gw_name']}\n"
        f"⏰ **የምዝገባ ጊዜ፦**\n`{gw_info['deadline_str']}`\n\n"
        f"💵 **የመግቢያ ክፍያ፦** {ENTRY_FEE} ብር\n\n"
        f"👉 ለመክፈል **«💳 ለመክፈል»** የሚለውን ቁልፍ ይጫኑ።"
    )
    await update.message.reply_text(welcome_text, reply_markup=main_keyboard(), parse_mode="Markdown")

async def pay_instruction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    instruction_text = (
        f"💳 **የክፍያና ምዝገባ መመሪያ፦**\n\n"
        f"1️⃣ በ Telebirr ወደሚከተለው ቁጥር **{ENTRY_FEE} ብር** ይላኩ፦\n"
        f"📲 **Telebirr ቁጥር፦** `{TELEBIRR_NO}`\n\n"
        f"2️⃣ **መጀመሪያ** የ FPL የቡድን ስምዎን በጽሁፍ ይላኩ።\n"
        f"3️⃣ **ከዚያም** የ Telebirr Transaction ID (Tx ID) ይላኩ።"
    )

    if os.path.exists(PHOTO_PATH_1):
        with open(PHOTO_PATH_1, 'rb') as photo:
            await update.message.reply_photo(photo=photo, caption=instruction_text, reply_markup=main_keyboard(), parse_mode="Markdown")
    else:
        await update.message.reply_text(instruction_text, reply_markup=main_keyboard(), parse_mode="Markdown")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    photo_id = update.message.photo[-1].file_id
    save_user_photo(user_id, photo_id)
    await update.message.reply_text("📸 ስክሪንሾቱ ተመዝግቧል! አሁን Transaction ID ይላኩ።", reply_markup=main_keyboard())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.message.chat_id

    # አዝራሮች
    if text in ["💳 ለመክፈል", "⚽ የመግቢያ ኮድ ለመቀበል"]:
        await pay_instruction(update, context)
        return
    elif text == "ℹ️ መመሪያ":
        await update.message.reply_text(f"ℹ️ **መመሪያ**\n\n• ክፍያ በ Telebirr `{TELEBIRR_NO}` ፈጽመው Tx ID ይላኩ።\n• አድሚን፦ {ADMIN_USERNAMES}", reply_markup=main_keyboard(), parse_mode="Markdown")
        return

    # Tx ID መሆኑን ማረጋገጥ (8-15 ፊደል/ቁጥር ያለው እና Space የሌለው)
    is_tx_format = bool(re.match(r'^[A-Za-z0-9]{8,15}$', text))

    if is_tx_format:
        tx_id = text.upper()
        status = get_sms_status(tx_id)

        # 🚨 1. Tx IDው ከዚህ ቀደም ጥቅም ላይ ውሎ ከሆነ (ደግመው እንዳይገቡ መከላከል)
        if status == 'USED':
            await update.message.reply_text(
                "❌ **ይህ Transaction ID ቀደም ሲል ጥቅም ላይ ውሏል!**\n"
                "እባክዎን አዲስ ያልተጠቀሙበትን ክፍያ Tx ID ይላኩ።",
                reply_markup=main_keyboard()
            )
            return

        # ✅ 2. ኤስኤምኤሱ ቀድሞ ደርሶ ከነበረ እና ያልተጠቀሙበት ከሆነ (PENDING)
        elif status == 'PENDING':
            process_successful_payment(user_id, tx_id)
            return

        # ⏳ 3. ኤስኤምኤሱ ገና ካልደረሰ (ወደ pending_users አስገባው)
        else:
            save_pending_user(tx_id, user_id)
            admin_btn = InlineKeyboardMarkup([[InlineKeyboardButton("💬 አድሚንን ለማናገር", url=ADMIN_PRIMARY_URL)]])
            await update.message.reply_text(
                f"📥 **Transaction ID ({tx_id}) ደርሶናል!**\n\n"
                f"የ Telebirr SMS ማረጋገጫ እንደደረሰን የመግቢያ ኮዱ በራስ-ሰር ይላክሎታል።",
                reply_markup=admin_btn,
                parse_mode="Markdown"
            )
            return

    else:
        # Tx ID ካልሆነ የ FPL የቡድን ስም አድርጎ ዳታቤዝ ላይ መመዝገብ
        save_user_team(user_id, text)
        await update.message.reply_text(
            f"✅ **የ FPL ቡድን ስምዎ «{text}» ተብሎ ተመዝግቧል!**\n\n"
            f"አሁን ደግሞ የ Telebirr **Transaction ID (Tx ID)** ይላኩልን።",
            reply_markup=main_keyboard(),
            parse_mode="Markdown"
        )

# =========================================================
# 🚀 STARTUP
# =========================================================
bot_app = Application.builder().token(TOKEN).build()
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

bot_loop = asyncio.new_event_loop()

def run_telegram_bot():
    asyncio.set_event_loop(bot_loop)
    bot_loop.run_until_complete(bot_app.initialize())
    bot_loop.run_until_complete(bot_app.start())
    bot_loop.run_until_complete(bot_app.updater.start_polling(drop_pending_updates=True))
    bot_loop.run_forever()

if __name__ == '__main__':
    t = threading.Thread(target=run_telegram_bot, daemon=True)
    t.start()
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
