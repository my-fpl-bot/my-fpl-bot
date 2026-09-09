import os
import re
from flask import Flask, request, jsonify
import telebot

# 1. Environment variables (ከ Render Environment Settings ይመጣሉ)
TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

app = Flask(__name__)

# 2. የቴሌግራም ቦት Start Command
@bot.message_handler(commands=['start'])
def start_message(message):
    bot.reply_to(message, "ሰላም! የ Telebirr ክፍያ የፈጸሙበትን የ Transaction ID ይላኩልኝ ወይም ክፍያው በራስ-ሰር ይረጋገጣል።")

# 3. SMS Webhook Endpoint (ከ SMS Forwarder አፕ መልእክት የሚቀበልበት)
@app.route('/sms_webhook', methods=['POST'])
def sms_webhook():
    try:
        data = request.get_json(force=True, silent=True) or {}
        sms_text = data.get('message', '')
        
        print(f"የደረሰው SMS: {sms_text}")
        
        # ከ SMS ውስጥ የ Transaction ID መፈለጊያ (Regex)
        # ምሳሌ: Telebirr Transaction ID አብዛኛውን ጊዜ DF... ወይም 10-12 አሃዝ ቁጥር ነው
        match = re.search(r'\b([A-Z0-9]{10,12})\b', sms_text)
        
        if match:
            txn_id = match.group(1)
            print(f"የተገኘው Transaction ID: {txn_id}")
            # እዚህ ጋር የክፍያ ማረጋገጫ logic-ህ ይገባል (ለምሳሌ Database ውስጥ መመዝገብ)
        
        return jsonify({"status": "success", "message": "SMS received successfully"}), 200

    except Exception as e:
        print(f"ስህተት ተከሰተ: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# 4. Render ጤንነት መፈተሻ (Health Check Endpoint)
@app.route('/', methods=['GET'])
def home():
    return "Bot is running live!", 200

if __name__ == "__main__":
    # Render Port Setting
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
