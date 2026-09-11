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
TOKEN = os.getenv("BOT_TOKEN", "8653645989:AAE2qWZvj0SO8dIG07edcIW9fO3E-1lioT0")
TELEBIRR_NO = "0925358925"
ADMIN_USERNAMES = "@mst10m ወይም @ATCITYZEN"
CHANNEL_LINK = "https://t.me/ETHIO_FANTASY_1"
GROUP_CHAT_ID = -1002391954418  # የግሩፕ ID

# የፎቶዎች ስም በ GitHub ላይ
PHOTO_PATH_1 = "photo_2026-09-06_22-09-38.jpg"
PHOTO_PATH_2 = "photo_2026-09-08_03-50-53.jpg"

# የ FPL ሊግ መረጃዎች
FPL_LEAGUE_ID = "2309527"
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
pending_payments = {}  # {tx_id: user_id}
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
                    
                    # 1. የአማርኛ/ኢትዮጵያ ቀን
                    day_amharic = DAYS_AMHARIC.get(eat_time.strftime("%A"), eat_time.strftime("%A"))
                    eth_month, eth_day, eth_year = gregorian_to_ethiopian(eat_time)
                    
                    # 2. የEnglish/Gregorian ቀን
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

# --- 7 ደቂቃ (420 ሰከንድ) ሲሞላ መልእክት የሚያጠፋ Function ---
async def delete_message_after_delay(chat_id, message_id, delay_seconds=420):
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

# --- Telebirr SMS Webhook (የተስተካከለ) ---
@app.route('/sms_webhook', methods=['POST'])
def sms_webhook():
    try:
        gw_info = get_current_gameweek_info()
        
        # ከ SMS Forwarder አፕ የሚመጣውን JSON/Form ዳታ ማስተናገድ
        data = request.get_json(force=True, silent=True) or request.form.to_dict() or {}
        message = str(data.get('message', '') or data.get('text', '') or request.get_data(as_text=True))
        
        print(f"--> Received SMS Webhook: {message}")

        tx_match = re.search(r'([A-Z0-9]{10,})', message)
        if tx_match:
            tx_id = tx_match.group(1).upper()
            print(f"Extracted Tx ID: {tx_id}")

            if tx_id in pending_payments:
                user_id = pending_payments.pop(tx_id)
                
                # 1. የመግቢያ ሊንክ መልእክት መላክ
                sent_msg = asyncio.run_coroutine_threadsafe(
                    bot_app.bot.send_message(
                        chat_id=user_id,
                        text=(
                            f"✅ **ክፍያህ በትክክል ተረጋግጧል!**\n\n"
                            f"🏆 **የተመዘገቡበት፡** {gw_info['gw_name']}\n\n"
                            f"🔗 **ቀጥታ ለመቀላቀል ከታች ያለውን ሊንክ ይጫኑ፦**\n"
                            f"https://fantasy.premierleague.com/leagues/auto-join/{FPL_CODE}\n\n"
                            f"⏱ **ማሳሰቢያ፦** ይህ መልእክትና ሊንክ ለደህንነት ሲባል **ከ 7 ደቂቃ በኋላ በራስ-ሰር ይፊቃል!** እባክዎን አሁኑኑ ተጭነው ይቀላቀሉ።"
                        ),
                        parse_mode="Markdown",
                        protect_content=True
                    ),
                    bot_loop
                ).result()

                # 2. ከ 7 ደቂቃ በኋላ መልእክቱን ማጥፋት
                asyncio.run_coroutine_threadsafe(
                    delete_message_after_delay(user_id, sent_msg.message_id, 420),
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
        f"💳 **የክፍያና ምዝገባ መመሪያ፦**\n\n"
        f"1️⃣ በ Telebirr መተግበሪያ ወይም በ `*127#` ወደሚከተለው ቁጥር **{ENTRY_FEE} ብር** ይላኩ፦\n"
        f"📲 **Telebirr ቁጥር፦** `{TELEBIRR_NO}`\n\n"
        f"2️⃣ ክፍያ ከፈጸሙ በኋላ በምስሉ ላይ **በቀይ ሳጥን የተከበበውን የ Telebirr Transaction ID (Code)** Copy አድርገው በጽሁፍ ይላኩ።\n\n"
        f"🚨 **ዋና ማሳሰቢያ፦**\n"
        f"• እንዳይሳሳቱ **የ FPL የቡድን ስምዎን (Team Name)** በጽሁፍ ወይም **ስክሪንሾት (Screenshot)** አያይዘው መላክ አለብዎት!\n"
        f"• ከአንድ በላይ ቡድን (በተለየ Email) ማስመዝገብ ከፈለጉ ለእያንዳንዱ ቡድን የተለየ ክፍያና የቡድን ስም/ስክሪንሾት መላክ አለብዎት።\n\n"
        f"🖼 **እንዴት እንደሚላክ በምስሎቹ ላይ ማየት ይችላሉ☝️**"
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

# ፎቶ ሲላክ የሚስተናገድበት (ወደ ግሩፕ ይላካል)
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    photo_file_id = update.message.photo[-1].file_id
    
    await update.message.reply_text(
        "📸 **የ FPL የቡድን ስምዎ ስክሪንሾት ደርሶናል!**\n\n"
        "አሁን ደግሞ እባክዎን የ Telebirr **Transaction ID** በጽሁፍ ይላኩ።",
        reply_markup=main_keyboard(),
        parse_mode="Markdown"
    )

    caption_text = (
        f"📥 **አዲስ የ FPL Team Screenshot ደርሷል!**\n\n"
        f"👤 **ላኪ፦** {user.full_name} (@{user.username if user.username else 'የለውም'})\n"
        f"🆔 **User ID፦** `{user.id}`"
    )
    
    try:
        await context.bot.send_photo(
            chat_id=GROUP_CHAT_ID,
            photo=photo_file_id,
            caption=caption_text,
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Error sending photo to group: {e}")

# ጽሁፎች ሲላኩ የሚስተናገድበት
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
            f"• ክፍያ በ Telebirr `{TELEBIRR_NO}` ፈጽመው Transaction ID እና የ FPL የቡድን ስም (በጽሁፍ ወይም በስክሪንሾት) መላክ አለብዎት።\n"
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

    # Transaction ID ከተላከ
    tx_match = re.search(r'([A-Z0-9]{10,})', text)
    if tx_match:
        tx_id = tx_match.group(1).upper()
        pending_payments[tx_id] = user_id

        await update.message.reply_text(
            f"📥 **Transaction ID `{tx_id}` ተመዝግቧል!**\n\n"
            f"📌 የ FPL የቡድን ስምዎን በጽሁፍ ወይም በስክሪንሾት ካልላኩ እባክዎን አሁኑኑ ይላኩ።\n\n"
            f"🚨 **ዋና ማሳሰቢያ፦** የ Telebirr SMS እንደደረሰን የሊጉ መግቢያ ሊንክ ይላክሎታል። ሊንኩ እንደደረሰዎት **በ 7 ደቂቃ ውስጥ** ተጭነው መቀላቀል አለብዎት! ከ 7 ደቂቃ በኋላ መልእክቱ ለደህንነት ሲባል በራስ-ሰር ይፊቃል።",
            reply_markup=main_keyboard(),
            parse_mode="Markdown"
        )
        # Transaction ID ወደ ግሩፕ መላክ
        try:
            await context.bot.send_message(
                chat_id=GROUP_CHAT_ID,
                text=(
                    f"💳 **አዲስ Transaction ID ደርሷል!**\n\n"
                    f"🔢 **Tx ID፦** `{tx_id}`\n"
                    f"👤 **ላኪ፦** {user.full_name} (@{user.username if user.username else 'የለውም'})\n"
                    f"🆔 **User ID፦** `{user.id}`"
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Error sending Tx ID to group: {e}")

    else:
        # የ FPL የቡድን ስም በጽሁፍ ከተላከ
        user_fpl_names[user_id] = text
        await update.message.reply_text(
            f"✅ **የ FPL የቡድን ስምዎት `{text}` ተብሎ ተመዝግቧል!**\n\n"
            f"አሁን ደግሞ ክፍያ ፈጽመው የ Telebirr **Transaction ID** በጽሁፍ ይላኩ።",
            reply_markup=main_keyboard(),
            parse_mode="Markdown"
        )
        # ወደ ግሩፑ መረጃውን መላክ
        try:
            await context.bot.send_message(
                chat_id=GROUP_CHAT_ID,
                text=(
                    f"📝 **አዲስ የ FPL Team Name (በጽሁፍ) ደርሷል!**\n\n"
                    f"⚽ **የቡድን ስም፦** `{text}`\n"
                    f"👤 **ላኪ፦** {user.full_name} (@{user.username if user.username else 'የለውም'})\n"
                    f"🆔 **User ID፦** `{user.id}`"
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Error sending text to group: {e}")

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
