import asyncio
import os
import re
from datetime import time

import pytz
from dotenv import load_dotenv, set_key
from playwright.async_api import async_playwright

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# -------------------------------------------------
# ENV & CONSTANTS
# -------------------------------------------------
ENV_FILE = ".env"
if not os.path.exists(ENV_FILE):
    # Create .env if missing
    with open(ENV_FILE, "w") as f:
        f.write("TELEGRAM_BOT_TOKEN=\n")
        f.write("DESCO_ACCOUNT_NUMBER=\n")
        f.write("CHAT_ID=\n")

load_dotenv(ENV_FILE)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DESCO_ACCOUNT = os.getenv("DESCO_ACCOUNT_NUMBER")
CHAT_ID = os.getenv("CHAT_ID")

DESCO_URL = "https://prepaid.desco.org.bd/customer/#/customer-info"
BD_TZ = pytz.timezone("Asia/Dhaka")

LOW_BALANCE_THRESHOLD = 100
RETRY_ATTEMPTS = 5
RETRY_DELAY = 20  # seconds

# -------------------------------------------------
# DESCO BALANCE FETCH
# -------------------------------------------------
async def fetch_desco_balance(account=None):
    account_to_use = account or DESCO_ACCOUNT
    if not account_to_use:
        raise RuntimeError("DESCO account not set")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto(DESCO_URL, timeout=60000)
        await page.wait_for_selector("input", timeout=30000)

        await page.fill("input", account_to_use)
        await page.keyboard.press("Enter")

        await page.wait_for_timeout(6000)

        content = await page.inner_text("body")
        await browser.close()

        match = re.search(r"Remaining Balance:\s*([\d,]+\.\d+)\s*BDT", content)
        if not match:
            raise RuntimeError("Balance not found")

        return float(match.group(1).replace(",", ""))


# -------------------------------------------------
# RETRY WRAPPER
# -------------------------------------------------
async def fetch_balance_with_retry(account=None):
    last_error = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return await fetch_desco_balance(account)
        except Exception as e:
            last_error = e
            print(f"[Retry {attempt}/{RETRY_ATTEMPTS}] {e}")
            await asyncio.sleep(RETRY_DELAY)
    raise RuntimeError("All retries failed") from last_error


# -------------------------------------------------
# COMMANDS
# -------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global DESCO_ACCOUNT, CHAT_ID

    chat_id = update.effective_chat.id
    CHAT_ID = str(chat_id)

    # Save chat id to .env
    set_key(ENV_FILE, "CHAT_ID", CHAT_ID)

    if not DESCO_ACCOUNT:
        await update.message.reply_text(
            "👋 Welcome! Please enter your DESCO account number:"
        )
        # Wait for user to send account in next message
        return

    # If account exists, show menu
    await show_menu(update)


async def receive_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global DESCO_ACCOUNT

    account_input = update.message.text.strip()
    if not account_input.isdigit():
        await update.message.reply_text("❌ Invalid account number. Please enter digits only.")
        return

    DESCO_ACCOUNT = account_input
    # Save to .env
    set_key(ENV_FILE, "DESCO_ACCOUNT_NUMBER", DESCO_ACCOUNT)

    await update.message.reply_text(
        f"✅ Account set: {DESCO_ACCOUNT}\n\n"
        "You will now receive notifications and can use /balance or /help."
    )
    await show_menu(update)


async def show_menu(update: Update):
    await update.message.reply_text(
        "📌 Commands & Info:\n\n"
        "/balance — Check balance manually\n"
        "/help — Show this help menu\n\n"
        "Automatic notifications:\n"
        "• 10:00 AM — Good Morning balance\n"
        "• 10:00 PM — Good Evening balance\n"
        "• Every 10 min — Regular update\n"
        "• Low balance (<100 BDT) — Alerts every 5 min\n\n"
        "Say hi / hello for greetings"
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_menu(update)


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Fetching DESCO balance...")
    try:
        balance_val = await fetch_balance_with_retry()
        await update.message.reply_text(f"💡 Remaining Balance:\n{balance_val:.2f} BDT")
    except Exception:
        await update.message.reply_text("⚠️ Unable to fetch DESCO balance.")


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.lower()
    if "hi" in msg or "hello" in msg:
        await update.message.reply_text("👋 Hello! Use /help to know all commands.")


# -------------------------------------------------
# SCHEDULED JOBS
# -------------------------------------------------
async def scheduled_balance(context: ContextTypes.DEFAULT_TYPE):
    if not CHAT_ID or not DESCO_ACCOUNT:
        return

    try:
        balance_val = await fetch_balance_with_retry()
        await context.bot.send_message(
            CHAT_ID,
            f"⏰ Scheduled Update 💡\nRemaining Balance: {balance_val:.2f} BDT"
        )
    except Exception:
        await context.bot.send_message(CHAT_ID, "⚠️ Scheduled DESCO check failed.")


async def regular_10min_update(context: ContextTypes.DEFAULT_TYPE):
    if not CHAT_ID or not DESCO_ACCOUNT:
        return

    try:
        balance_val = await fetch_balance_with_retry()
        await context.bot.send_message(
            CHAT_ID,
            f"🔔 10 min update 💡 Remaining Balance: {balance_val:.2f} BDT"
        )
    except Exception:
        pass  # silent retry


async def low_balance_monitor(context: ContextTypes.DEFAULT_TYPE):
    if not CHAT_ID or not DESCO_ACCOUNT:
        return

    try:
        balance_val = await fetch_balance_with_retry()
        if balance_val < LOW_BALANCE_THRESHOLD:
            await context.bot.send_message(
                CHAT_ID,
                f"🚨 LOW BALANCE ALERT!\nRemaining Balance: {balance_val:.2f} BDT"
            )
    except Exception:
        pass


# -------------------------------------------------
# MAIN
# -------------------------------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_account))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    job_queue = app.job_queue

    # 10 AM and 10 PM notifications
    job_queue.run_daily(scheduled_balance, time=time(10, 0, tzinfo=BD_TZ), name="10am")
    job_queue.run_daily(scheduled_balance, time=time(22, 0, tzinfo=BD_TZ), name="10pm")

    # Regular 10 min update
    job_queue.run_repeating(regular_10min_update, interval=600, first=600, name="10min_update")

    # Low balance monitor every 5 min
    job_queue.run_repeating(low_balance_monitor, interval=300, first=300, name="low_balance_monitor")

    print("✅ DESCO Universal Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()

