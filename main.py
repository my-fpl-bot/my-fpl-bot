import os
import re
import requests
import threading
import asyncio
from datetime import datetime, timezone, timedelta
from flask import Flask, request
from telegram import Update, ReplyKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# =========================================================
# ⚠️ Configs & IDs
# =========================================================
TOKEN = os.getenv("BOT_TOKEN", "8653645989:AAG4dvmb5p6baKZBiA1Mzcd_wfvZxPvgO74")
TELEBIRR_NO = "0925358925"
ADMIN_USERNAMES = "@mst10m ወይም @ATCITYZEN"
CHANNEL_LINK = "https://t.me/ETHIO_FANTASY_1"
CONFIRMATION_GROUP_ID = -1002391954418  # ክፍያ ሲረጋገጥ መረጃ የሚላክበት Group ID

# የፎቶዎች ስም በ GitHub ላይ
PHOTO_PATH_1 = "photo_2026-09-06_22-09-38.jpg"
PHOTO_PATH_2 = "photo_2026-09-08_03-50-53.jpg"

# የ FPL ሊግ መረጃዎች
FPL_LEAGUE_ID = "2309527"
FPL_CODE = os.getenv("FPL_CODE", "w90c98")
ENTRY_FEE = "50"

# የሳምንታት ስም በኢትዮጵያ አቆጣጠር
DAYS_AMHARIC = {
    "Monday": "ሰኞ", "Tuesday": "ማክሰኞ", "Wednesday": "ረቡዕ",
    "Thursday": "ሐሙስ", "Friday": "አርብ", "Saturday": "ቅዳሜ", "Sunday": "እሁድ"
}

# የፈረንጆች ወራት በኢትዮጵያ ስም
MONTHS_AMHARIC = {
    "January": "ጥር", "February": "የካቲት", "March": "መጋቢት", "April": "ሚያዝያ",
    "May": "ግንቦት", "June": "ሰኔ", "July": "ሐምሌ", "August": "ነሐሴ",
    "September": "መስከረም", "October": "ጥቅምት", "November": "ሕዳር", "December": "ታኅሣሥ"
}

# ዳታዎችን ጊዜያዊ ማከማቻ
pending_payments = {}    # {tx_id: user_id}
user_fpl_names = {}      # {user_id: fpl_team_name}
user_screenshots = {}    # {user_id: photo_file_id}
user_referrals = {}      # {user_id: [referred_user_ids]}

app = Flask(__name__)

# Main Keyboard Menu
def main_keyboard():
    keyboard = [
        ["💳 ለመክፈል", "⚽ የመግቢያ ኮድ ለመቀበል"],
        ["👥 ጓደኛን መጋበዝ (Invite)", "🎁 ነፃ እድል"],
        ["📊 የሊግ ደረጃዎች (Rank)", "ℹ️ መመሪያ"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- የፈረንጅ ቀንን ወደ ኢትዮጵያ ዘመን አቆጣጠር መቀየሪያ Function ---
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

# --- FPL Gameweek እና Deadline መረጃ ማግኛ ---
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

# --- FPL Standings / Rank ማግኛ ---
def get_league_standings():
    try:
        url = f"https://fantasy.premierleague.com/api/leagues-classic/{FPL_LEAGUE_ID}/standings/"
        res = requests.get(url, timeout=10).json()
        standings = res.get('standings', {}).get('results', [])
        league_name = res.get('league', {}).get('name', 'ETHIO FANTASY')
        
        escaped_link = CHANNEL_LINK.replace("_", r"\_")

        if not standings:
            return (
                f"🏆 **{league_name} - የደረጃ ሰንጠረዥ**\n\n"
                f"📊 እስካሁን ምንም የተመዘገበ ደረጃ የለም።\n\n"
                f"🎁 **ስለ ሽልማቱ ለማወቅና ሽልማቱን ለመቀበል የቴሌግራም ቻናላችንን ይቀላቀሉ፦**\n{escaped_link}"
            )
        
        text = f"🏆 **{league_name} - የደረጃ ሰንጠረዥ**\n\n"
        for player in standings[:10]:
            rank = player.get('rank')
            entry_name = player.get('entry_name')
            player_name = player.get('player_name')
            total = player.get('total')
            text += f"**{rank}. {entry_name}** ({player_name}) - `{total} pts`\n"
            
        text += f"\n🎁 **ስለ ሽልማቱ ለማወቅ እና ሽልማቱን ለመቀበል የቴሌግራም ቻናላችንን ይቀላቀሉ፦**\n{escaped_link}"
        return text
    except Exception as e:
        print(f"Rank Error: {e}")
        return "⚠️ የደረጃ መረጃውን ማምጣት አልተቻለም። እባክዎን ቆየት ብለው ይሞክሩ።"

# --- Async Helper: መልእክት መላክ እና ከ 7 ደቂቃ በኋላ ማጥፋት ---
async def send_and_auto_delete(user_id, text, delay=420):
    try:
        sent_msg = await bot_app.bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode="Markdown",
            protect_content=True
        )
        await asyncio.sleep(delay)
        await bot_app.bot.delete_message(chat_id=user_id, message_id=sent_msg.message_id)
        print(f"Deleted link message for user {user_id}")
    except Exception as e:
        print(f"Auto delete error: {e}")

# --- Async Helper: ክፍያን ለ Admin/Group ማሳወቅ ---
async def notify_admin_group(user_id, tx_id, team_name, photo_id):
    try:
        user_info = await bot_app.bot.get_chat(user_id)
        full_name = user_info.full_name if user_info else "ተጠቃሚ"
        username = f"@{user_info.username}" if user_info and user_info.username else "የለውም"

        admin_msg = (
            f"✅ **አዲስ የተረጋገጠ ክፍያ ደርሷል!**\n\n"
            f"👤 **ተጠቃሚ፦** {full_name} ({username})\n"
            f"🆔 **User ID፦** `{user_id}`\n"
            f"🔢 **Tx ID፦** `{tx_id}`\n"
            f"⚽ **የ FPL ቡድን ስም፦** `{team_name}`"
        )

        if photo_id:
            await bot_app.bot.send_photo(
                chat_id=CONFIRMATION_GROUP_ID,
                photo=photo_id,
                caption=admin_msg,
                parse_mode="Markdown"
            )
        else:
            await bot_app.bot.send_message(
                chat_id=CONFIRMATION_GROUP_ID,
                text=admin_msg,
                parse_mode="Markdown"
            )
    except Exception as e:
        print(f"Error notifying admin group: {e}")

# --- Flask Routes ---
@app.route('/')
def home():
    return "FPL Bot is running successfully!", 200

# --- Telebirr SMS Webhook ---
@app.route('/sms_webhook', methods=['GET', 'POST'], strict_slashes=False)
@app.route('/sms_webhook/', methods=['GET', 'POST'], strict_slashes=False)
def sms_webhook():
    if request.method == 'GET':
        return "SMS Webhook Endpoint is Active!", 200

    try:
        gw_info = get_current_gameweek_info()
        
        # 1. MacroDroid የሚልከውን ዳታ በሙሉ ማውጣት
        raw_data = request.get_data(as_text=True)
        data = request.get_json(force=True, silent=True) or {}
        if not data and request.form:
            data = request.form.to_dict()
            
        message = str(data.get('message', '') or data.get('text', '') or raw_data)
        print(f"--> Received Webhook Data: {message}")

        # 2. Transaction ID መፈለግ (10+ Upper Alpha-Numeric)
        tx_match = re.search(r'\b([A-Z0-9]{10,})\b', message)
        if tx_match:
            tx_id = tx_match.group(1).upper()
            print(f"Matched Tx ID from SMS: {tx_id}")

            if tx_id in pending_payments:
                user_id = pending_payments.pop(tx_id)
                team_name = user_fpl_names.pop(user_id, "አልተጠቀሰም")
                photo_id = user_screenshots.pop(user_id, None)

                join_text = (
                    f"✅ **ክፍያህ በትክክል ተረጋግጧል!**\n\n"
                    f"🏆 **የተመዘገቡበት፡** {gw_info['gw_name']}\n\n"
                    f"🔗 **ቀጥታ ለመቀላቀል ከታች ያለውን ሊንክ ይጫኑ፦**\n"
                    f"https://fantasy.premierleague.com/leagues/auto-join/{FPL_CODE}\n\n"
                    f"⏱ **ማሳሰቢያ፦** ይህ መልእክትና ሊንክ ለደህንነት ሲባል **ከ 7 ደቂቃ በኋላ በራስ-ሰር ይፊቃል!** እባክዎን አሁኑኑ ተጭነው ይቀላቀሉ።"
                )

                # Async Task ወደ Telegram Loop በደህና መላክ
                asyncio.run_coroutine_threadsafe(
                    send_and_auto_delete(user_id, join_text, 420),
                    bot_loop
                )

                asyncio.run_coroutine_threadsafe(
                    notify_admin_group(user_id, tx_id, team_name, photo_id),
                    bot_loop
                )

                print(f"Successfully processed Tx ID: {tx_id} for User: {user_id}")
                return "OK", 200

        return "OK", 200
    except Exception as e:
        print(f"Error handling SMS Webhook: {e}")
        return "OK", 200

# --- Telegram Bot Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gw_info = get_current_gameweek_info()
    welcome_text = (
        f"👋 **እንኳን ወደ FPL ውድድር ቦት በደህና መጡ!**\n\n"
        f"⚽ **የአሁኑ ውድድር፦** {gw_info['gw_name']}\n"
        f"⏰ **የምዝገባ ጊዜ፦**\n`{gw_info['deadline_str']}`\n\n"
        f"💵 **የመግቢያ ክፍያ፦** {ENTRY_FEE} ብር (ለአንድ ቡድን)\n\n"
        f"👉 ለመክፈል ከታች ያለውን **«💳 ለመክፈል»** የሚለውን ቁልፍ ይጫኑ።"
    )
    await update.message.reply_text(welcome_text, reply_markup=main_keyboard(), parse_mode="Markdown")

async def pay_instruction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gw_info = get_current_gameweek_info()
    if not gw_info["is_open"]:
        await update.message.reply_text("⚠️ የዚህ Gameweek የመመዝገቢያ ሰዓት አልፏል።", reply_markup=main_keyboard())
        return

    instruction_text = (
        f"💳 **የክፍያና ምዝገባ መመሪያ፦**\n\n"
        f"1️⃣ በ Telebirr መተግበሪያ ወይም በ `*127#` ወደሚከተለው ቁጥር **ትክክለኛውን {ENTRY_FEE} ብር ብቻ** ይላኩ፦\n"
        f"📲 **Telebirr ቁጥር፦** `{TELEBIRR_NO}`\n\n"
        f"⚠️ **ማሳሰቢያ፦** የመግቢያ ክፍያው **በትክክል {ENTRY_FEE} ብር ብቻ** መሆን አለበት። ከ {ENTRY_FEE} ብር በታች ከተላከ ክፍያው አይቀበለውም።\n\n"
        f"🚨 **መረጃዎችን በሚከተለው ቅደም-ተከተል ብቻ ይላኩ፦**\n\n"
        f"1️⃣ **መጀመሪያ፦** የ FPL የቡድን ስምዎን (Team Name) በጽሁፍ ይላኩ።\n"
        f"2️⃣ **በመቀጠል፦** ከ Telebirr የደረሶትን **Transaction ID** በጽሁፍ ይላኩ።\n"
        f"3️⃣ **በመጨረሻም፦** የ FPL የቡድን ስምዎን **ስክሪንሾት (Screenshot)** ይላኩ።\n\n"
        f"⏱ **ማሳሰቢያ፦** የ Telebirr SMS ማረጋገጫ እንደደረሰን የሊጉ መግቢያ ሊንክ በግል ይላክሎታል። ሊንኩ በደረሰዎት **በ 7 ደቂቃ ውስጥ** ተጭነው መቀላቀል አለብዎት!"
    )

    if os.path.exists(PHOTO_PATH_1) and os.path.exists(PHOTO_PATH_2):
        media = [
            InputMediaPhoto(open(PHOTO_PATH_1, 'rb'), caption=instruction_text, parse_mode="Markdown"),
            InputMediaPhoto(open(PHOTO_PATH_2, 'rb'))
        ]
        await update.message.reply_media_group(media=media)
    elif os.path.exists(PHOTO_PATH_1):
        with open(PHOTO_PATH_1, 'rb') as photo:
            await update.message.reply_photo(photo=photo, caption=instruction_text, reply_markup=main_keyboard(), parse_mode="Markdown")
    else:
        await update.message.reply_text(instruction_text, reply_markup=main_keyboard(), parse_mode="Markdown")

async def rank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ የደረጃ ሰንጠረዡ በመጫን ላይ ነው...", parse_mode="Markdown")
    standings_text = get_league_standings()
    await update.message.reply_text(standings_text, reply_markup=main_keyboard(), parse_mode="Markdown")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    photo_file_id = update.message.photo[-1].file_id
    user_screenshots[user_id] = photo_file_id
    
    await update.message.reply_text(
        "📸 **የ FPL የቡድን ስምዎ ስክሪንሾት ተመዝግቧል!**\n\n"
        "የ Telebirr SMS ማረጋገጫ እንደደረሰን የመግቢያ ሊንኩ ይላክልዎታል።",
        reply_markup=main_keyboard(),
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.message.chat_id
    
    if text in ["💳 ለመክፈል", "⚽ የመግቢያ ኮድ ለመቀበል"]:
        await pay_instruction(update, context)
        return
    elif text == "📊 የሊግ ደረጃዎች (Rank)":
        await rank_command(update, context)
        return
    elif text == "ℹ️ መመሪያ":
        await update.message.reply_text(
            f"ℹ️ **መመሪያ**\n\n"
            f"• ክፍያ በ Telebirr `{TELEBIRR_NO}` ፈጽመው (በትክክል {ENTRY_FEE} ብር) ደረጃዎቹን ተከትለው መረጃዎችን ይላኩ።\n"
            f"• ጥያቄ ካለዎት አድሚኖችን ለማናገር፦ {ADMIN_USERNAMES}",
            reply_markup=main_keyboard(),
            parse_mode="Markdown"
        )
        return
    elif text == "👥 ጓደኛን መጋበዝ (Invite)":
        bot_username = (await context.bot.get_me()).username
        referral_link = f"https://t.me/{bot_username}?start={user_id}"
        count = len(user_referrals.get(user_id, []))
        
        invite_text = (
            f"👥 **ጓደኛዎን ይጋብዙ!**\n\n"
            f"እነዚህን ደረጃዎች በመከተል ነፃ እድል ያግኙ፦\n"
            f"1️⃣ ከታች ያለውን **የመጋበዣ ሊንክ Copy አድርገው** ለጓደኛዎ ይላኩ።\n"
            f"2️⃣ ጓደኛዎ በሊንክዎ ገብቶ ሲመዘገብ የነፃ እድል ቁጥርዎ ይጨምራል!\n\n"
            f"🔗 **የእርስዎ መጋበዣ ሊንክ፦**\n`{referral_link}`\n\n"
            f"📊 **በእርስዎ ሊንክ የተመዘገቡ፦** {count}/10"
        )
        await update.message.reply_text(invite_text, reply_markup=main_keyboard(), parse_mode="Markdown")
        return
    elif text == "🎁 ነፃ እድል":
        count = len(user_referrals.get(user_id, []))
        await update.message.reply_text(f"🎁 የተመዘገቡልዎት ጓደኞች፦ **{count}/10**", reply_markup=main_keyboard())
        return

    gw_info = get_current_gameweek_info()
    if not gw_info["is_open"]:
        await update.message.reply_text("⚠️ የዚህ Gameweek የመመዝገቢያ ሰዓት አልፏል።", reply_markup=main_keyboard())
        return

    tx_match = re.search(r'\b([A-Z0-9]{10,})\b', text)
    if tx_match:
        tx_id = tx_match.group(1).upper()
        pending_payments[tx_id] = user_id

        await update.message.reply_text(
            f"📥 **Transaction ID `{tx_id}` ተመዝግቧል!**\n\n"
            f"📌 አሁን ደግሞ የ FPL የቡድንዎን **ስክሪንሾት (Screenshot)** ይላኩ።\n\n"
            f"⏳ **የክፍያ ማረጋገጫ፦** የ Telebirr SMS ማረጋገጫ እንደደረሰን የሊጉ መግቢያ ሊንክ ይላክሎታል። ሊንኩ እንደደረሰዎት **በ 7 ደቂቃ ውስጥ** ተጭነው መቀላቀል አለብዎት!",
            reply_markup=main_keyboard(),
            parse_mode="Markdown"
        )
    else:
        user_fpl_names[user_id] = text
        await update.message.reply_text(
            f"✅ **የ FPL የቡድን ስምዎት `{text}` ተብሎ ተመዝግቧል!**\n\n"
            f"አሁን በመቀጠል ከ Telebirr የደረሶትን **Transaction ID** በጽሁፍ ይላኩ።",
            reply_markup=main_keyboard(),
            parse_mode="Markdown"
        )

# --- Application setup & Background Runner ---
bot_app = Application.builder().token(TOKEN).build()
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("rank", rank_command))
bot_app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

bot_loop = asyncio.new_event_loop()

def run_telegram_bot():
    asyncio.set_event_loop(bot_loop)
    bot_loop.run_until_complete(bot_app.initialize())
    bot_loop.run_until_complete(bot_app.start())
    bot_loop.run_until_complete(bot_app.updater.start_polling())
    bot_loop.run_forever()

if __name__ == '__main__':
    t = threading.Thread(target=run_telegram_bot, daemon=True)
    t.start()
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
