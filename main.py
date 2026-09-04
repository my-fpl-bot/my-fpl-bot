from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# --- የውቅር መረጃዎች (Configuration) ---
TELEBIRR_NUMBER = "0935657570"  # የእንተ የTelebirr ስልክ ቁጥር
ENTRY_FEE = "50 ብር"             # የመግቢያ ክፍያ
FPL_LEAGUE_CODE = "abc123xy"     # የ FPL Private League Code

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    keyboard = [
        [InlineKeyboardButton("💳 በ Telebirr ለመክፈል", callback_data='pay')],
        [InlineKeyboardButton("ℹ️ የውድድር ህጎች", callback_data='rules')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_msg = (
        f"ሰላም {user_name}! ወደ FPL ውድድር ቦት እንኳን ደህና መጣህ።\n\n"
        f"🏆 **የመግቢያ ክፍያ:** {ENTRY_FEE}\n"
        f"ቁልፉን በመጫን ክፍያ ፈጽመህ የሊጉን ኮድ ማግኘት ትችላለህ።"
    )
    await update.message.reply_text(welcome_msg, parse_mode='Markdown', reply_markup=reply_markup)

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == 'pay':
        pay_msg = (
            f"📲 **የ Telebirr ክፍያ መመሪያ:**\n\n"
            f"1. ወደ Telebirr አፕሊኬሽንህ/USSD ሂድ።\n"
            f"2. ወደ **{TELEBIRR_NUMBER}** የ **{ENTRY_FEE}** ክፍያ ፈጽም።\n"
            f"3. ክፍያ ከፈጸምክ በኋላ የትራንዛክሽን ቁጥሩን (Transaction ID) ወይም ደረሰኙን እዚህ ቻት ላይ ላክ።"
        )
        await query.message.reply_text(pay_msg, parse_mode='Markdown')
    elif query.data == 'rules':
        rules_msg = "📜 **ህጎች:**\n- ከDeadline በፊት መግባት አለብህ።\n- ክፍያ ያልፈጸመ ሰው ከሊጉ ይወገዳል።"
        await query.message.reply_text(rules_msg)

# ተጠቃሚው የትራንዛክሽን ቁጥር ሲልክ አውቶማቲክ ኮድ መላክ
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    # እዚህ ላይ የክፍያ ማረጋገጫ ከተላከ በኋላ ለተወዳዳሪው ኮዱ ይላካል
    success_msg = (
        f"✅ የክፍያ መረጃህ ደርሶናል!\n\n"
        f"🔗 **የ FPL League Code:** `{FPL_LEAGUE_CODE}`\n\n"
        f"እባክህ ወዲያውኑ FPL አፕ ላይ ገብተህ የተቀላቀል! ኮዱ በቅርቡ ይቀየራል።"
    )
    await update.message.reply_text(success_msg, parse_mode='Markdown')

if __name__ == '__main__':
    app = ApplicationBuilder().token("8653645989:AAE2qWZvj0SO8dIG07edcIW9fO3E-1lioT0").build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_click))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("ቦቱ በአዲስ አሰራር መስራት ጀምሯል...")
    app.run_polling()
