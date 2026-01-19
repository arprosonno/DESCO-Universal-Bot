import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ---------- ENV ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "8080"))

# ---------- LOGGING ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


# ---------- HANDLERS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🟢 Bot alive & stable (webhook mode)")


async def health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Health OK")


# ---------- MAIN ----------
def main():
    if not BOT_TOKEN or not WEBHOOK_URL:
        logger.critical("Missing BOT_TOKEN or WEBHOOK_URL")
        raise RuntimeError("BOT_TOKEN or WEBHOOK_URL missing")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("health", health))

    logger.info("Starting webhook server")

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
        url_path=BOT_TOKEN,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()



