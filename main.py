import os
import re
import requests
import threading
import asyncio
from datetime import datetime, timezone, timedelta
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# =========================================================
# ⚠️ እነዚህን 3 መረጃዎች ብቻ የራስህን አስተካክል
# =========================================================
TOKEN = "8653645989:AAE2qWZvj0SO8dIG07edcIW9fO3E-1lioT0"  # ከ BotFather ያገኘኸውን Token እዚህ ተካ
TELEBIRR_NO = "0935657570"                       # የ Telebirr ስልክ ቁጥርህ
ADMIN_USERNAME = "@mst10man"                # የቴሌግራም username ህ

# የ FPL ሊግ መረጃዎች
FPL_LEAGUE_ID = "2309527"          
FPL_CODE = "v8v7fu"                
ENTRY_FEE = "100"                  

pending_payments = {}

app = Flask(__name__)

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
            
            # Message ለመላክ
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
    gw_info = get_current_gameweek_info()
    
    if not gw_info["is_open"]:
        await update.message.reply_text(
            f"⚠️ **ይቅርታ! የ {gw_info['gw_name']} የመመዝገቢያ ሰዓት (Deadline) አብቅቷል።**\n\n"
            f"ጨዋታዎቹ ሲጠናቀቁ ለቀጣዩ Gameweek ምዝገባው በራስ-ሰር ይከፈታል።",
            parse_mode="Markdown"
        )
        return

    welcome_text = (
        f"👋 **እንኳን ወደ FPL ውድድር ቦት በደህና መጡ!**\n\n"
        f"⚽ **የአሁኑ ውድድር፦** {gw_info['gw_name']}\n"
        f"⏰ **የምዝገባ ማጠቃለያ ሰዓት፦** {gw_info['deadline_str']}\n\n"
        f"💵 **የመግቢያ ክፍያ፦** {ENTRY_FEE} ብር\n"
        f"📲 **Telebirr ቁጥር፦** `{TELEBIRR_NO}`\n\n"
        f"👉 ክፍያ ከፈጸሙ በኋላ የተቀበሉትን **Transaction ID** እዚህ ይላኩ።\n\n"
        f"ℹ️ ስለ ደንቦችና መመሪያዎች ለማወቅ `/info` የሚለውን ይጫኑ።"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gw_info = get_current_gameweek_info()
    info_text = (
        f"ℹ️ **ስለ FPL ውድድር ቦትና አስፈላጊ ማሳሰቢያዎች**\n\n"
        f"📌 **አሁን ክፍት የሆነው፡** {gw_info['gw_name']}\n"
        f"⏳ **የመመዝገቢያ ገደብ፡** {gw_info['deadline_str']}\n\n"
        "1️⃣ **ክፍያን በተመለከተ፦**\n"
        f"• የመግቢያ ክፍያ **{ENTRY_FEE} ብር** ብቻ ነው።\n"
        f"• ክፍያ መፈጸም ያለበት በ Telebirr ቁጥር `{TELEBIRR_NO}` ነው::\n"
        "• ክፍያ ከፈጸሙ በኋላ የሚደርስዎትን **Transaction ID** ብቻ ወደ ቦቱ ይላኩ።\n\n"
        "2️⃣ **የሊግ መግቢያ ኮድ፦**\n"
        "• ክፍያው በሲስተሙ እንደተረጋገጠ የ FPL ሊግ መግቢያ ኮድ በራስ-ሰር ይላክልዎታል።\n"
        "• ኮዱ የተላከለት ተወዳዳሪ ለአንድ የ FPL አካውንት ብቻ መጠቀም አለበት።\n\n"
        "3️⃣ **የሰዓት ገደብ (Deadline)፦**\n"
        "• ከ Deadline 30 ደቂቃ በፊት ክፍያ መቀበል ይዘጋል።\n\n"
        f"4️⃣ **እርዳታና አቤቱታ፦**\n"
        f"• ማንኛውም ችግር ካጋጠመዎት ለአድሚን ያውሩ፦ {ADMIN_USERNAME}"
    )
    await update.message.reply_text(info_text, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gw_info = get_current_gameweek_info()
    
    if not gw_info["is_open"]:
        await update.message.reply_text(
            f"⚠️ **የ {gw_info['gw_name']} የመመዝገቢያ ሰዓት አልፏል።**\nለቀጣዩ Gameweek ምዝገባ ሲከፈት እንደገና ይሞክሩ።",
            parse_mode="Markdown"
        )
        return

    text = update.message.text.strip()
    user_id = update.message.chat_id
    
    if len(text) >= 8 and text.isalnum():
        pending_payments[text] = user_id
        await update.message.reply_text(
            f"📥 Transaction ID `{text}` ተመዝግቧል።\n"
            f"የ Telebirr SMS እንደደረሰን የሊጉ ኮድ በራስ-ሰር ይላክልሃል!",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("እባክዎን ትክክለኛ የ Telebirr Transaction ID ያስገቡ።")

# --- Application setup ---
bot_app = Application.builder().token(TOKEN).build()
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("info", info))
bot_app.add_handler(CommandHandler("help", info))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

bot_loop = asyncio.new_event_loop()

def run_telegram_bot():
    asyncio.set_event_loop(bot_loop)
    bot_loop.run_until_complete(bot_app.initialize())
    bot_loop.run_until_complete(bot_app.start())
    bot_loop.run_until_complete(bot_app.updater.start_polling())
    bot_loop.run_forever()

if __name__ == '__main__':
    # ቴሌግራም ቦቱን ለብቻው በ Thread ማስኬድ
    t = threading.Thread(target=run_telegram_bot, daemon=True)
    t.start()
    
    # Flask Web Server
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
