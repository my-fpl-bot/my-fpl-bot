import os
import re
import requests
import threading
import asyncio
from datetime import datetime, timezone, timedelta
from flask import Flask, request
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# =========================================================
# ⚠️ Configs & IDs
# =========================================================
TOKEN = os.getenv("BOT_TOKEN", "8653645989:AAE2qWZvj0SO8dIG07edcIW9fO3E-1lioT0")
TELEBIRR_NO = "0925358925"
ADMIN_USERNAME = "mst10m"  # ያለ @ ምልክት አድሚን ዩዘርኔም
ADMIN_USERNAMES = "@mst10m ወይም @ATCITYZEN"
CHANNEL_LINK = "https://t.me/ETHIO_FANTASY_1"
GROUP_CHAT_ID = -1002391954418  # የግሩፕ ID

# የፎቶዎች ስም በ GitHub ላይ
PHOTO_PATH_1 = "photo_2026-09-06_22-09-38.jpg"
PHOTO_PATH_2 = "photo_2026-09-08_03-50-53.jpg"

# የ FPL ሊግ መረጃዎች
FPL_LEAGUE_ID = "2276766"
FPL_CODE = os.getenv("FPL_CODE", "v8v7fu")
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
pending_payments = {}  # {tx_id: {"user_id": user_id, "user_name": name, "username": username}}
user_fpl_names = {}    # {user_id: fpl_team_name}
user_referrals = {}    # {user_id: [referred_user_ids]}
user_invited_by = {}   # {user_id: referrer_user_id}

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
        h2h_url = f"https://fantasy.premierleague.com/api/leagues-h2h/{FPL_LEAGUE_ID}/standings/"
        res = requests.get(h2h_url, timeout=10)
        
        if res.status_code == 200:
            data = res.json()
            standings = data.get('standings', {}).get('results', [])
            league_name = data.get('league', {}).get('name', 'ETHIO FANTASY')
            is_h2h = True
        else:
            classic_url = f"https://fantasy.premierleague.com/api/leagues-classic/{FPL_LEAGUE_ID}/standings/"
            res = requests.get(classic_url, timeout=10)
            data = res.json()
            standings = data.get('standings', {}).get('results', [])
            league_name = data.get('league', {}).get('name', 'ETHIO FANTASY')
            is_h2h = False
        
        escaped_link = CHANNEL_LINK.replace("_", r"\_")

        if not standings:
            return (
                f"🏆 **{league_name} - የደረጃ ሰንጠረዥ**\n\n"
                f"📊 እስካሁን ምንም የተመዘገበ ደረጃ የለም። Game Week ሲያልቅ ደረጃዎች እዚህ ይዘምናሉ።\n\n"
                f"🎁 **ስለ ሽልማቱ ለማወቅና ሽልማቱን ለመቀበል የቴሌግራም ቻናላችንን ይቀላቀሉ፦**\n{escaped_link}"
            )
        
        text = f"🏆 **{league_name} - የደረጃ ሰንጠረዥ**\n\n"
        for player in standings[:15]:
            rank = player.get('rank')
            entry_name = player.get('entry_name')
            player_name = player.get('player_name')
            
            if is_h2h:
                points = player.get('total', 0)
                win = player.get('matches_won', 0)
                draw = player.get('matches_drawn', 0)
                loss = player.get('matches_lost', 0)
                text += f"**{rank}. {entry_name}** ({player_name})\n └ `{points} pts` | (W:{win} D:{draw} L:{loss})\n"
            else:
                total = player.get('total', 0)
                text += f"**{rank}. {entry_name}** ({player_name}) - `{total} pts`\n"
            
        text += f"\n🎁 **ስለ ሽልማቱ ለማወቅ እና ሽልማቱን ለመቀበል የቴሌግራም ቻናላችንን ይቀላቀሉ፦**\n{escaped_link}"
        return text
    except Exception as e:
        print(f"Rank Error: {e}")
        return "⚠️ የደረጃ መረጃውን ማምጣት አልተቻለም። እባክዎን ቆየት ብለው ይሞክሩ።"

# --- 10 ደቂቃ (600 ሰከንድ) ሲሞላ መልእክት የሚያጠፋ Function ---
async def delete_message_after_delay(chat_id, message_id, delay_seconds=600):
    await asyncio.sleep(delay_seconds)
    try:
        await bot_app.bot.delete_message(chat_id=chat_id, message_id=message_id)
        print(f"Message {message_id} deleted for user {chat_id}")
    except Exception as e:
        print(f"Error deleting message: {e}")

# --- Flask Routes ---
@app.route('/')
def home():
    return "FPL Bot is running successfully!", 200

# --- Telebirr SMS Webhook ---
@app.route('/sms_webhook', methods=['POST'])
def sms_webhook():
    try:
        gw_info = get_current_gameweek_info()
        
        data = request.get_json(force=True, silent=True) or request.form.to_dict() or {}
        message = str(data.get('message', '') or data.get('text', '') or request.get_data(as_text=True))
        
        print(f"--> Received SMS Webhook: {message}")

        tx_match = re.search(r'([A-Z0-9]{10,})', message)
        if tx_match:
            tx_id = tx_match.group(1).upper()
            print(f"Extracted Tx ID: {tx_id}")

            if tx_id in pending_payments:
                user_info = pending_payments.pop(tx_id)
                user_id = user_info["user_id"]
                full_name = user_info["user_name"]
                username = user_info["username"]
                fpl_team = user_fpl_names.get(user_id, "አልተጠቀሰም")

                # የ ቻናል ቁልፍ + የአድሚን ማናገሪያ ቁልፍ
                success_keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎁 ቻናላችንን ይቀላቀሉ & ሽልማት ይውሰዱ", url=CHANNEL_LINK)],
                    [InlineKeyboardButton("💬 አድሚንን ለማናገር ይጫኑ", url=f"https://t.me/{ADMIN_USERNAME}")]
                ])

                sent_msg = asyncio.run_coroutine_threadsafe(
                    bot_app.bot.send_message(
                        chat_id=user_id,
                        text=(
                            f"🎉 **ምዝገባዎ በስኬት ተጠናቋል!**\n\n"
                            f"✅ **ክፍያህ በትክክል ተረጋግጧል!**\n\n"
                            f"🏆 **የተመዘገቡበት፡** {gw_info['gw_name']}\n\n"
                            f"🔑 **የመግቢያ ኮድ (Code)፦**\n`{FPL_CODE}`\n"
                            f"*(ከላይ ያለውን ኮድ በመንካት/በመጫን በቀላሉ Copy ማድረግ ይችላሉ)*\n\n"
                            f"🔗 **ወይም በሊንክ ቀጥታ ለመቀላቀል፦**\n"
                            f"https://fantasy.premierleague.com/leagues/auto-join/{FPL_CODE}\n\n"
                            f"📌 **ሊንኩን ከተቀላቀሉ በኋላ፦**\n"
                            f"1️⃣ **ደረጃ ለማወቅ፦** በቦቱ ሜኑ ላይ **«📊 የሊግ ደረጃዎች (Rank)»** የሚለውን በመጫን አጠቃላይ ደረጃዎትን ማየት ይችላሉ።\n"
                            f"2️⃣ **ሽልማት ለመቀበል፦** ከታች ያለውን ቁልፍ ተጭነው **የቴሌግራም ቻናላችንን ይቀላቀሉ!** የጨዋታ ሳምንት ሲጠናቀቅ አሸናፊዎች የሚገለጹበት እና ሽልማት የሚላክበት በቻናሉ ነው።\n\n"
                            f"❓ **ማሳሰቢያ፦** የመግቢያ ሊንኩ/ኮዱ እምቢ ካለዎት፣ ካልሰራዎት ወይም ምንም ዓይነት ችግር ካጋጠመዎት ከታች ያለውን **«💬 አድሚንን ለማናገር»** የሚለውን ቁልፍ ተጭነው ማናገር ይችላሉ።\n\n"
                            f"⏱ **ደህንነት፦** ይህ የመግቢያ ኮድ ያለበት መልእክት **ከ 10 ደቂቃ በኋላ በራስ-ሰር ይፊቃል!** እባክዎን አሁኑኑ ተጭነው ይቀላቀሉ።"
                        ),
                        reply_markup=success_keyboard,
                        parse_mode="Markdown",
                        protect_content=True
                    ),
                    bot_loop
                ).result()

                # ከ 10 ደቂቃ በኋላ ማጥፋት
                asyncio.run_coroutine_threadsafe(
                    delete_message_after_delay(user_id, sent_msg.message_id, 600),
                    bot_loop
                )

                # ወደ አድሚን ግሩፕ መላክ
                asyncio.run_coroutine_threadsafe(
                    bot_app.bot.send_message(
                        chat_id=GROUP_CHAT_ID,
                        text=(
                            f"🎉 **አዲስ የተሳካ ምዝገባ እና ክፍያ!**\n\n"
                            f"👤 **ተወዳዳሪ፦** {full_name} (@{username if username else 'የለውም'})\n"
                            f"🆔 **User ID፦** `{user_id}`\n"
                            f"⚽ **FPL Team Name፦** `{fpl_team}`\n"
                            f"🔢 **Tx ID፦** `{tx_id}`\n"
                            f"✅ **ሁኔታ፦** ክፍያው ተረጋግጦ የሊጉ መግቢያ ሊንክ ተልኮለታል።"
                        ),
                        parse_mode="Markdown"
                    ),
                    bot_loop
                )

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
        f"💳 **የክፍያና ምዝገባ ደረጃዎች (ተከተሉ)፦**\n\n"
        f"1️⃣ **መጀመሪያ፦** በ Telebirr መተግበሪያ ወይም በ `*127#` ወደሚከተለው ቁጥር **{ENTRY_FEE} ብር** ይላኩ፦\n"
        f"📲 **Telebirr ቁጥር፦** `{TELEBIRR_NO}`\n\n"
        f"2️⃣ **ሁለተኛ፦** **የ FPL የቡድን ስምዎን (Team Name)** በጽሁፍ ይላኩልን ወይም በምስል (Screenshot) አያይዘው ይላኩ።\n\n"
        f"3️⃣ **ሦስተኛ፦** ክፍያ እንደፈጸሙ ከ Telebirr የደረሰዎትን **Transaction ID (Code)** በጽሁፍ ይላኩ።\n\n"
        f"🚨 **ዋና ማሳሰቢያ፦**\n"
        f"• **በመጀመሪያ የ FPL ቡድን ስምዎን በመቀጠል Transaction ID መላክዎን ያረጋግጡ!**\n"
        f"• ከአንድ በላይ ቡድን ማስመዝገብ ከፈለጉ ለእያንዳንዱ ቡድን በተለየ ክፍያና የቡድን ስም/ስክሪንሾት መላክ አለብዎት።\n\n"
        f"🖼 **Transaction ID የት እንደሚገኝ በምስሎቹ ላይ ማየት ይችላሉ☝️**"
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
    await update.message.reply_text(
        "📸 **የ FPL የቡድን ስምዎ ስክሪንሾት ደርሶናል!**\n\n"
        "አሁን ደግሞ በመቀጠል የ Telebirr **Transaction ID** በጽሁፍ ይላኩ።",
        reply_markup=main_keyboard(),
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.message.chat_id
    user = update.message.from_user
    
    if text in ["💳 ለመክፈል", "⚽ የመግቢያ ኮድ ለመቀበል"]:
        await pay_instruction(update, context)
        return
    elif text == "📊 የሊግ ደረጃዎች (Rank)":
        await rank_command(update, context)
        return
    elif text == "ℹ️ መመሪያ":
        await update.message.reply_text(
            f"ℹ️ **መመሪያ**\n\n"
            f"1️⃣ ክፍያ በ Telebirr `{TELEBIRR_NO}` ይፈጽሙ።\n"
            f"2️⃣ በመጀመሪያ የ FPL የቡድን ስምዎን (Team Name) ይላኩ።\n"
            f"3️⃣ በመቀጠል የ Telebirr Transaction ID በጽሁፍ ይላኩ።\n\n"
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

    # 1. Transaction ID መሆኑን ማረጋገጥ
    tx_match = re.search(r'([A-Z0-9]{10,})', text, re.IGNORECASE)
    if tx_match:
        tx_id = tx_match.group(1).upper()
        
        pending_payments[tx_id] = {
            "user_id": user_id,
            "user_name": user.full_name,
            "username": user.username
        }

        admin_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 አድሚንን ለማናገር ይጫኑ", url=f"https://t.me/{ADMIN_USERNAME}")]
        ])

        await update.message.reply_text(
            f"📥 **Transaction ID `{tx_id}` ተመዝግቧል!**\n\n"
            f"⏳ **ክፍያዎ በመረጋገጥ ላይ ነው...**\n"
            f"የ Telebirr መልእክት እንደደረሰን የሊጉ መግቢያ ኮድ እና ሊንክ በራስ-ሰር ይላክልዎታል።\n\n"
            f"📌 የ FPL የቡድን ስምዎን (Team Name) ካልላኩ እባክዎን አሁኑኑ በጽሁፍ ወይም በስክሪንሾት ይላኩ።\n\n"
            f"⚠️ **ማሳሰቢያ፦** ክፍያ ፈጽመው የሊጉ ሊንክ ካልደረስዎት ወይም መዘግየት ካጋጠመዎት ከታች ያለውን ቁልፍ ተጭነው አድሚኑን ማናገር ይችላሉ።",
            reply_markup=admin_keyboard,
            parse_mode="Markdown"
        )

    else:
        # 2. የተላከው ጽሁፍ Transaction ID ካልሆነ (የ FPL Team Name ከሆነ)
        fail_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 አድሚንን ለማናገር ይጫኑ", url=f"https://t.me/{ADMIN_USERNAME}")]
        ])

        user_fpl_names[user_id] = text
        await update.message.reply_text(
            f"✅ **የ FPL የቡድን ስምዎት `{text}` ተብሎ በጊዜያዊነት ተይዟል!**\n\n"
            f"👉 **አሁን ደግሞ በመቀጠል፦** ክፍያ የፈጸሙበትን **የ Telebirr Transaction ID** በጽሁፍ ይላኩ።\n\n"
            f"❓ **ጥያቄ ካለዎት፣ የመግቢያ ሊንክ እምቢ ካለዎት ወይም ችግር ካጋጠመዎት** ከታች ያለውን ቁልፍ ተጭነው አድሚንን ማናገር ይችላሉ።",
            reply_markup=fail_keyboard,
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
    # Start Telegram Bot in Thread
    t = threading.Thread(target=run_telegram_bot, daemon=True)
    t.start()
    
    # Start Flask Web Server
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
