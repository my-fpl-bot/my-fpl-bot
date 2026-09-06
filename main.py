import os
import re
import requests
import threading
import asyncio
from datetime import datetime, timezone, timedelta
from flask import Flask, request
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# =========================================================
# ⚠️ እነዚህን መረጃዎች የራስህን አስተካክል
# =========================================================
TOKEN = "8653645989:AAE2qWZvj0SO8dIG07edcIW9fO3E-1lioT0"  # ከ BotFather ያገኘኸውን Token እዚህ ተካ
TELEBIRR_NO = "0935657570"                       # የ Telebirr ስልክ ቁጥርህ
ADMIN_USERNAME = "@mst10m"                # የቴሌግራም username ህ
PHOTO_PATH = "photo_2026-09-06_22-09-38.jpg"     # በ GitHub ላይ የሰቀልከው የፎቶ ስም

# የ FPL ሊግ መረጃዎች
FPL_LEAGUE_ID = "2309527"          
FPL_CODE = "v8v7fu"                
ENTRY_FEE = "100"                  

# ዳታዎችን ጊዜያዊ ማከማቻ (In-Memory Databases)
pending_payments = {}  # {tx_id: user_id}
user_referrals = {}    # {user_id: [referred_user_ids]}
user_invited_by = {}   # {user_id: referrer_user_id}

app = Flask(__name__)

# Main Keyboard Menu
def main_keyboard():
    keyboard = [
        ["💳 ለመክፈል", "⚽ የመግቢያ ኮድ ለመቀበል"],
        ["👥 ጓደኛን መጋበዝ (Invite)", "🎁 ነፃ እድል"],
        ["ℹ️ መመሪያ"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

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
                    time_str = eat_time.strftime("%d/%m/%Y - %I:%M %p")
                    return {
                        "gw_name": event.get('name'),
                        "deadline_str": time_str,
                        "is_open": True
                    }
        return {"gw_name": "Gameweek", "deadline_str": "Unknown", "is_open": False}
    except Exception as e:
        print(f"FPL API Error: {e}")
        return {"gw_name": "Gameweek", "deadline_str": "N/A", "is_open": True}

# --- Telebirr SMS Webhook ---
@app.route('/sms_webhook', methods=['POST'])
def sms_webhook():
    gw_info = get_current_gameweek_info()
    if not gw_info["is_open"]:
        return "Deadline Passed", 200

    data = request.get_json(silent=True) or request.form
    message = str(data.get('message', '') or data.get('text', ''))
    
    tx_match = re.search(r'([A-Z0-9]{10,})', message)
    if tx_match:
        tx_id = tx_match.group(1)
        if tx_id in pending_payments:
            user_id = pending_payments.pop(tx_id)
            
            # ተጠቃሚው በሰው ተጋብዞ ከሆነ ለጋባዡ ቁጥር መቁጠር
            if user_id in user_invited_by:
                referrer_id = user_invited_by[user_id]
                if referrer_id not in user_referrals:
                    user_referrals[referrer_id] = []
                
                if user_id not in user_referrals[referrer_id]:
                    user_referrals[referrer_id].append(user_id)
                    count = len(user_referrals[referrer_id])
                    
                    if count >= 10:
                        asyncio.run_coroutine_threadsafe(
                            bot_app.bot.send_message(
                                chat_id=referrer_id,
                                text=(
                                    f"🎉 **እንኳን ደስ አለዎት!**\n\n"
                                    f"10 ጓደኞችን በሊንክዎ ጋብዘው አስመዝግበዋል!\n"
                                    f"🎁 **የነፃ መግቢያ ኮድዎ፦** `{FPL_CODE}`\n\n"
                                    f"🔗 **ቀጥታ ለመቀላቀል፦**\nhttps://fantasy.premierleague.com/leagues/auto-join/{FPL_CODE}"
                                ),
                                parse_mode="Markdown"
                            ),
                            bot_loop
                        )
                    else:
                        asyncio.run_coroutine_threadsafe(
                            bot_app.bot.send_message(
                                chat_id=referrer_id,
                                text=f"🔔 የጋበዙት 1 ሰው ክፍያ ፈጽሞ ተመዝግቧል!\n📊 **የተመዘገቡት፦** {count}/10",
                                parse_mode="Markdown"
                            ),
                            bot_loop
                        )

            # ለከፋዩ የሊግ ኮድ መላክ
            asyncio.run_coroutine_threadsafe(
                bot_app.bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"✅ **ክፍያህ በትክክል ተረጋግጧል!**\n\n"
                        f"🏆 **የተመዘገቡበት፡** {gw_info['gw_name']}\n"
                        f"🔑 **የ FPL ሊግ መግቢያ ኮድ፡** `{FPL_CODE}`\n\n"
                        f"🔗 **ቀጥታ ለመቀላቀል ሊንኩን ተጫን፡**\n"
                        f"https://fantasy.premierleague.com/leagues/auto-join/{FPL_CODE}"
                    ),
                    parse_mode="Markdown"
                ),
                bot_loop
            )
            return "OK", 200
            
    return "Ignored", 200

@app.route('/')
def home():
    return "FPL Bot is running successfully!", 200

# --- Telegram Bot Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    
    if context.args:
        try:
            referrer_id = int(context.args[0])
            if referrer_id != user_id and user_id not in user_invited_by:
                user_invited_by[user_id] = referrer_id
        except ValueError:
            pass

    gw_info = get_current_gameweek_info()
    
    welcome_text = (
        f"👋 **እንኳን ወደ FPL ውድድር ቦት በደህና መጡ!**\n\n"
        f"⚽ **የአሁኑ ውድድር፦** {gw_info['gw_name']}\n"
        f"⏰ **የምዝገባ ማጠቃለያ ሰዓት፦** {gw_info['deadline_str']}\n\n"
        f"💵 **የመግቢያ ክፍያ፦** {ENTRY_FEE} ብር\n\n"
        f"👉 ለመክፈል ከታች ያለውን **«💳 ለመክፈል»** የሚለውን ቁልፍ ይጫኑ።"
    )
    await update.message.reply_text(welcome_text, reply_markup=main_keyboard(), parse_mode="Markdown")

async def pay_instruction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gw_info = get_current_gameweek_info()
    if not gw_info["is_open"]:
        await update.message.reply_text("⚠️ የዚህ Gameweek የመመዝገቢያ ሰዓት አልፏል።", reply_markup=main_keyboard())
        return

    instruction_text = (
        f"💳 **የክፍያ መመሪያ፦**\n\n"
        f"1️⃣ በ Telebirr መተግበሪያ ወይም በ `*127#` ወደሚከተለው ቁጥር **{ENTRY_FEE} ብር** ይላኩ፦\n"
        f"📲 **Telebirr ቁጥር፦** `{TELEBIRR_NO}`\n\n"
        f"2️⃣ ክፍያ ከፈጸሙ በኋላ ከ Telebirr የሚደርስዎትን **Transaction ID** ኮፒ በማድረግ እዚህ ቦት ላይ ይላኩ።\n\n"
        f"🖼 **እንዴት መላክ እንዳለብዎት በምስሉ ላይ ማየት ይችላሉ👇**"
    )

    if os.path.exists(PHOTO_PATH):
        with open(PHOTO_PATH, 'rb') as photo:
            await update.message.reply_photo(
                photo=photo,
                caption=instruction_text,
                reply_markup=main_keyboard(),
                parse_mode="Markdown"
            )
    else:
        await update.message.reply_text(
            instruction_text,
            reply_markup=main_keyboard(),
            parse_mode="Markdown"
        )

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gw_info = get_current_gameweek_info()
    info_text = (
        f"ℹ️ **ስለ FPL ውድድር ቦትና መመሪያዎች**\n\n"
        f"📌 **አሁን ክፍት የሆነው፡** {gw_info['gw_name']}\n"
        f"⏳ **የመመዝገቢያ ገደብ፡** {gw_info['deadline_str']}\n\n"
        "1️⃣ **ክፍያን በተመለከተ፦**\n"
        f"• የመግቢያ ክፍያ **{ENTRY_FEE} ብር** ነው።\n"
        f"• ክፍያ መፈጸም ያለበት በ Telebirr ቁጥር `{TELEBIRR_NO}` ነው::\n"
        "• ክፍያ ከፈጸሙ በኋላ የሚደርስዎትን **Transaction ID** ብቻ ለቦቱ ይላኩ።\n\n"
        "2️⃣ **ነፃ ምዝገባ ለማግኘት፦**\n"
        "• 10 ጓደኞችን በጋበዙ ቁጥር 1 ነፃ የሊግ መግቢያ ይሸለማሉ!\n\n"
        f"3️⃣ **አድሚን ለማናገር፦** {ADMIN_USERNAME}"
    )
    await update.message.reply_text(info_text, reply_markup=main_keyboard(), parse_mode="Markdown")

async def invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={user_id}"
    
    count = len(user_referrals.get(user_id, []))
    
    msg = (
        f"👥 **ጓደኞችዎን ይጋብዙና ነፃ እድል ያግኙ!**\n\n"
        f"🔗 **የእርስዎ መጋበዣ ሊንክ፦**\n`{referral_link}`\n\n"
        f"📊 **እስካሁን የከፈሉ ጋባዦች፦** {count}/10\n\n"
        f"💡 ይህንን ሊንክ ለጓደኞችዎ ያጋሩ። 10 ሰው በሊንክዎ ገብቶ ሲመዘገብ **1 ነፃ የሊግ መግቢያ** ያገኛሉ!"
    )
    await update.message.reply_text(msg, reply_markup=main_keyboard(), parse_mode="Markdown")

async def free_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    count = len(user_referrals.get(user_id, []))
    remaining = max(0, 10 - count)
    
    msg = (
        f"🎁 **የነፃ እድል ሁኔታዎት**\n\n"
        f"✅ የተመዘገቡልዎት ጓደኞች፦ **{count}**\n"
        f"⏳ የቀሩዎት ጓደኞች፦ **{remaining}**\n\n"
        f"10 ሰው እንደሞላ የሊጉ ኮድ በራስ-ሰር ይላክልዎታል!"
    )
    await update.message.reply_text(msg, reply_markup=main_keyboard(), parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if text in ["💳 ለመክፈል", "⚽ የመግቢያ ኮድ ለመቀበል"]:
        await pay_instruction(update, context)
        return
    elif text == "ℹ️ መመሪያ":
        await info(update, context)
        return
    elif text == "👥 ጓደኛን መጋበዝ (Invite)":
        await invite(update, context)
        return
    elif text == "🎁 ነፃ እድል":
        await free_status(update, context)
        return

    gw_info = get_current_gameweek_info()
    if not gw_info["is_open"]:
        await update.message.reply_text("⚠️ የዚህ Gameweek የመመዝገቢያ ሰዓት አልፏል።", reply_markup=main_keyboard())
        return

    user_id = update.message.chat_id
    if len(text) >= 8 and text.isalnum():
        pending_payments[text] = user_id
        await update.message.reply_text(
            f"📥 Transaction ID `{text}` ተመዝግቧል።\nየ Telebirr SMS እንደደረሰን የሊጉ ኮድ በራስ-ሰር ይላክላችኋል!",
            reply_markup=main_keyboard(),
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("እባክዎን ከታች ያሉትን ቁልፎች ይጠቀሙ ወይም ትክክለኛ የ Telebirr Transaction ID ያስገቡ።", reply_markup=main_keyboard())

# --- Application setup ---
bot_app = Application.builder().token(TOKEN).build()
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("info", info))
bot_app.add_handler(CommandHandler("invite", invite))
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
