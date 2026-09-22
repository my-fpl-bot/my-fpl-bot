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
ADMIN_USERNAMES = "@mst10m ወይም @ATCITYZEN"
ADMIN_PRIMARY_URL = "https://t.me/mst10m"  # በአዝራሩ (Button) የሚከፈተው የአድሚን አካውንት
CHANNEL_LINK = "https://t.me/ETHIO_FANTASY_1"
GROUP_CHAT_ID = -1002391954418  # ክፍያ ሲረጋገጥ ብቻ መረጃ የሚላክበት ግሩፕ ID

# የፎቶዎች ስም በ GitHub ላይ
PHOTO_PATH_1 = "photo_2026-09-06_22-09-38.jpg"
PHOTO_PATH_2 = "photo_2026-09-08_03-50-53.jpg"

# የ FPL ሊግ መረጃዎች
FPL_LEAGUE_ID = os.getenv("FPL_LEAGUE_ID", "2309527")
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

# ዳታዎችን ማከማቻ
pending_payments = {}         # {tx_id: user_id}
received_telebirr_smes = set() # {tx_id1, tx_id2, ...}
user_fpl_names = {}           # {user_id: fpl_team_name}
user_screenshots = {}         # {user_id: photo_file_id}
user_referrals = {}           # {user_id: [referred_user_ids]}

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
        classic_url = f"https://fantasy.premierleague.com/api/leagues-classic/{FPL_LEAGUE_ID}/standings/"
        res = requests.get(classic_url, timeout=10)
        
        if res.status_code == 200:
            data = res.json()
            standings = data.get('standings', {}).get('results', [])
            league_name = data.get('league', {}).get('name', 'ETHIO FANTASY')
            is_h2h = False
        else:
            h2h_url = f"https://fantasy.premierleague.com/api/leagues-h2h/{FPL_LEAGUE_ID}/standings/"
            res = requests.get(h2h_url, timeout=10)
            data = res.json()
            standings = data.get('standings', {}).get('results', [])
            league_name = data.get('league', {}).get('name', 'ETHIO FANTASY')
            is_h2h = True

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

# --- የመግቢያ ሊንክ ለተጠቃሚ የመላክ እና ወደ ግሩፕ የማስተላለፍ ስራ ---
def process_successful_payment(user_id, tx_id):
    gw_info = get_current_gameweek_info()
    team_name = user_fpl_names.pop(user_id, "አልተጠቀሰም")
    photo_id = user_screenshots.pop(user_id, None)

    # 1. የመግቢያ ሊንክና ኮድ ለተጠቃሚው በግል መላክ
    sent_msg = asyncio.run_coroutine_threadsafe(
        bot_app.bot.send_message(
            chat_id=user_id,
            text=(
                f"✅ **ክፍያህ በትክክል ተረጋግጧል!**\n\n"
                f"🏆 **የተመዘገቡበት፡** {gw_info['gw_name']}\n\n"
                f"🔑 **የመግቢያ ኮድ (Code)፦**\n`{FPL_CODE}`\n"
                f"*(ከላይ ያለውን ኮድ በመንካት በቀላሉ Copy ማድረግ ይችላሉ)*\n\n"
                f"🔗 **በሊንክ ቀጥታ ለመቀላቀል፦**\n"
                f"https://fantasy.premierleague.com/leagues/auto-join/{FPL_CODE}\n\n"
                f"⏱ **ማሳሰቢያ፦** ይህ መልእክትና ሊንክ ለደህንነት ሲባል **ከ 10 ደቂቃ በኋላ በራስ-ሰር ይፊቃል!** እባክዎን አሁኑኑ ተጭነው ይቀላቀሉ።"
            ),
            parse_mode="Markdown",
            protect_content=True
        ),
        bot_loop
    ).result()

    # ከ 10 ደቂቃ በኋላ መልእክቱን ማጥፋት
    asyncio.run_coroutine_threadsafe(
        delete_message_after_delay(user_id, sent_msg.message_id, 600),
        bot_loop
    )

    # 2. የተረጋገጠውን መረጃ ወደ አድሚን ግሩፕ መላክ
    try:
        user_info = asyncio.run_coroutine_threadsafe(
            bot_app.bot.get_chat(user_id),
            bot_loop
        ).result()
        
        full_name = user_info.full_name if user_info else "ተጠቃሚ"
        username = f"@{user_info.username}" if user_info and user_info.username else "የለውም"

        admin_msg = (
            f"✅ **አዲስ የተረጋገጠ ክፍያና ምዝገባ!**\n\n"
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
        data = request.get_json(force=True, silent=True) or {}
        if not data and request.form:
            data = request.form.to_dict()
            
        full_message = str(data.get('message', '') or data.get('text', '') or request.get_data(as_text=True))
        print(f"--> Received Full Webhook Content: {full_message}")

        # SMS ውስጥ ያሉትን Tx IDዎች መፈለግ
        found_ids = re.findall(r'[A-Za-z0-9]{8,}', full_message)
        
        for tx in found_ids:
            tx_upper = tx.upper()
            received_telebirr_smes.add(tx_upper)

            if tx_upper in pending_payments:
                matched_user_id = pending_payments.pop(tx_upper)
                print(f"✅ MATCH FOUND VIA SMS! Tx ID: {tx_upper} for User: {matched_user_id}")
                process_successful_payment(matched_user_id, tx_upper)

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
        f"2️⃣ ክፍያ ከፈጸሙ በኋላ የሚደርስዎትን **Transaction ID (Tx ID)** እና **የ FPL የቡድን ስምዎን** ለቦቱ ይላኩ።\n\n"
        f"📌 **ማሳሰቢያ፦** ክፍያዎ ሲረጋገጥ የሊጉ መግቢያ ኮድ በራስ-ሰር ይላክሎታል።"
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

# ፎቶ ሲላክ የሚስተናገድበት
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    photo_file_id = update.message.photo[-1].file_id
    user_screenshots[user_id] = photo_file_id
    
    await update.message.reply_text(
        "📸 **የ FPL የቡድን ስምዎ ስክሪንሾት ተመዝግቧል!**\n\n"
        "አሁን ደግሞ የ Telebirr **Transaction ID (Tx ID)** በጽሁፍ ይላኩ። ክፍያዎ ሲረጋገጥ የመግቢያ ኮዱ ይላክልዎታል።",
        reply_markup=main_keyboard(),
        parse_mode="Markdown"
    )

# ጽሁፎች ሲላኩ የሚስተናገድበት
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
            f"• ክፍያ በ Telebirr `{TELEBIRR_NO}` ፈጽመው Transaction ID እና የ FPL የቡድን ስም መላክ አለብዎት።\n"
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
    tx_match = re.search(r'([A-Za-z0-9]{8,})', text)
    if tx_match and not text.startswith('/'):
        tx_id = tx_match.group(1).upper()

        # ሀ) Telebirr SMS አስቀድሞ ቀድሞ ደርሶ ከሆነ፦
        if tx_id in received_telebirr_smes:
            print(f"✅ IMMEDIATE MATCH! Tx ID: {tx_id} was already received via SMS.")
            process_successful_payment(user_id, tx_id)
        # ለ) SMS ገና ካልደረሰ ወደ pending አስገባው፦
        else:
            pending_payments[tx_id] = user_id
            
            # 🔘 የቀጥታ አድሚን አዝራር (Inline Button)
            admin_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 አድሚንን ለማናገር (Contact Admin)", url=ADMIN_PRIMARY_URL)]
            ])

            await update.message.reply_text(
                f"📥 **Transaction ID ደርሶናል!**\n\n"
                f"የ Telebirr ክፍያ ማረጋገጫ SMS እንደደረሰን የሊጉ መግቢያ ኮድ እና ሊንክ ይላክሎታል።\n\n"
                f"🚨 **ማሳሰቢያ፦** ክፍያ ካልፈጸሙ ኮዱ አይላክም። ክፍያ ፈጽመው SMS ከዘገየ ወይም ካልተሳካ ከታች ያለውን አዝራር ተጭነው አድሚንን መጠየቅ ይችላሉ።",
                reply_markup=admin_keyboard,
                parse_mode="Markdown"
            )
    else:
        # የ FPL የቡድን ስም በጽሁፍ ከተላከ
        user_fpl_names[user_id] = text
        await update.message.reply_text(
            f"✅ **የ FPL የቡድን ስምዎ ተመዝግቧል!**\n\n"
            f"አሁን ክፍያ ፈጽመው የ Telebirr **Transaction ID (Tx ID)** ይላኩ።\n"
            f"*(የ Telebirr SMS ማረጋገጫ እንደደረሰን የሊጉ መግቢያ ኮድ በራስ-ሰር ይላክሎታል።)*",
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
