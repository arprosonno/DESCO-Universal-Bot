import asyncio
import os
import re
from datetime import time

import pytz
from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =================================================
# CONFIG
# =================================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN not set")

DESCO_URL = "https://prepaid.desco.org.bd/customer/#/customer-info"
BD_TZ = pytz.timezone("Asia/Dhaka")

LOW_BALANCE_THRESHOLD = 100
RETRY_ATTEMPTS = 5
RETRY_DELAY = 20  # seconds

# In-memory multi-user store
# { chat_id: { "account": "xxxx" } }
USER_DATA = {}

# =================================================
# PLAYWRIGHT SCRAPER
# =================================================

async def fetch_desco_balance(account: str) -> float:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await browser.new_page()

        try:
            await page.goto(DESCO_URL, timeout=60_000)
            await page.wait_for_selector("input", timeout=30_000)
            await page.fill("input", account)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(6_000)

            content = await page.inner_text("body")
        finally:
            await browser.close()

    match = re.search(
        r"Remaining Balance:\s*([\d,]+\.\d+)\s*BDT", content
    )

    if not match:
        raise RuntimeError("Balance not found")

    return float(match.group(1).replace(",", ""))


async def fetch_with_retry(account: str) -> float:
    last_error = None
    for _ in range(RETRY_ATTEMPTS):
        try:
            return await fetch_desco_balance(account)
        except Exception as e:
            last_error = e
            await asyncio.sleep(RETRY_DELAY)
    raise RuntimeError("DESCO unreachable repeatedly") from last_error

# =================================================
# HELP / MENU
# =================================================

HELP_TEXT = (
    "📌 *DESCO Balance Bot*\n\n"
    "/start — Start the bot\n"
    "/balance — Check balance now\n"
    "/help — Show this menu\n\n"
    "*Automatic alerts:*\n"
    "• 🌅 10:00 AM\n"
    "• 🌙 10:00 PM\n"
    "• 🔔 Every 10 minutes\n"
    "• 🚨 Low balance alert\n"
)

# =================================================
# COMMANDS
# =================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    USER_DATA.setdefault(chat_id, {})

    await update.message.reply_text(
        "👋 Welcome!\n\n"
        "Please send your *DESCO account number*.",
        parse_mode="Markdown",
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def receive_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    msg = update.message.text.strip()

    # Greeting response
    if msg.lower() in ("hi", "hello", "hey"):
        await update.message.reply_text("👋 Hello! Use /help to see options.")
        return

    if not msg.isdigit():
        await update.message.reply_text("❌ Digits only. Please send account number.")
        return

    USER_DATA.setdefault(chat_id, {})["account"] = msg

    await update.message.reply_text(
        f"✅ Account saved: *{msg}*\n\n"
        "You will now receive automatic updates.\n"
        "Use /balance anytime.",
        parse_mode="Markdown",
    )


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = USER_DATA.get(chat_id)

    if not data or "account" not in data:
        await update.message.reply_text("❗ Please send your account number first.")
        return

    await update.message.reply_text("🔄 Checking balance...")
    try:
        bal = await fetch_with_retry(data["account"])
        await update.message.reply_text(f"💡 Remaining Balance: *{bal:.2f} BDT*", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"⚠️ {e}")

# =================================================
# SCHEDULED JOBS
# =================================================

async def broadcast(context: ContextTypes.DEFAULT_TYPE, title: str):
    for chat_id, data in USER_DATA.items():
        account = data.get("account")
        if not account:
            continue
        try:
            bal = await fetch_with_retry(account)
            await context.bot.send_message(
                chat_id,
                f"{title}\n💡 Remaining Balance: *{bal:.2f} BDT*",
                parse_mode="Markdown",
            )
        except Exception:
            pass


async def morning_job(context: ContextTypes.DEFAULT_TYPE):
    await broadcast(context, "🌅 Good Morning!")


async def evening_job(context: ContextTypes.DEFAULT_TYPE):
    await broadcast(context, "🌙 Good Evening!")


async def ten_min_job(context: ContextTypes.DEFAULT_TYPE):
    await broadcast(context, "🔔 10-Minute Update")


async def low_balance_job(context: ContextTypes.DEFAULT_TYPE):
    for chat_id, data in USER_DATA.items():
        account = data.get("account")
        if not account:
            continue
        try:
            bal = await fetch_with_retry(account)
            if bal < LOW_BALANCE_THRESHOLD:
                await context.bot.send_message(
                    chat_id,
                    f"🚨 *LOW BALANCE ALERT!*\nRemaining: {bal:.2f} BDT",
                    parse_mode="Markdown",
                )
        except Exception:
            pass

# =================================================
# TELEGRAM CONFLICT FIX
# =================================================

async def post_init(app):
    await app.bot.delete_webhook(drop_pending_updates=True)
    print("✅ Telegram session cleaned")

# =================================================
# MAIN
# =================================================

def main():
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_account))

    jq = app.job_queue
    jq.run_daily(morning_job, time=time(10, 0, tzinfo=BD_TZ))
    jq.run_daily(evening_job, time=time(22, 0, tzinfo=BD_TZ))
    jq.run_repeating(ten_min_job, interval=600, first=600)
    jq.run_repeating(low_balance_job, interval=300, first=300)

    print("💓 Bot alive & scheduler running normally")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()


