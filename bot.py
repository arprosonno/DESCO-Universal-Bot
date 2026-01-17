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

# =================================================
# ENVIRONMENT & CONSTANTS
# =================================================

ENV_FILE = ".env"

if not os.path.exists(ENV_FILE):
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


# =================================================
# DESCO BALANCE FETCHING
# =================================================

async def fetch_desco_balance(account: str | None = None) -> float:
    """Fetch DESCO prepaid balance using Playwright."""
    account_number = account or DESCO_ACCOUNT
    if not account_number:
        raise RuntimeError("DESCO account number not set")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto(DESCO_URL, timeout=60_000)
        await page.wait_for_selector("input", timeout=30_000)
        await page.fill("input", account_number)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(6_000)

        content = await page.inner_text("body")
        await browser.close()

    match = re.search(
        r"Remaining Balance:\s*([\d,]+\.\d+)\s*BDT",
        content,
    )

    if not match:
        raise RuntimeError("Balance not found")

    return float(match.group(1).replace(",", ""))


async def fetch_balance_with_retry(account: str | None = None) -> float:
    """Retry wrapper for DESCO balance fetching."""
    last_error = None

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return await fetch_desco_balance(account)
        except Exception as exc:
            last_error = exc
            print(f"[Retry {attempt}/{RETRY_ATTEMPTS}] {exc}")
            await asyncio.sleep(RETRY_DELAY)

    raise RuntimeError("All retries failed") from last_error


# =================================================
# BOT COMMANDS
# =================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler."""
    global CHAT_ID

    CHAT_ID = str(update.effective_chat.id)
    set_key(ENV_FILE, "CHAT_ID", CHAT_ID)

    if not DESCO_ACCOUNT:
        await update.message.reply_text(
            "👋 Welcome!\nPlease send your DESCO account number."
        )
        return

    await show_menu(update)


async def receive_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive and save DESCO account number."""
    global DESCO_ACCOUNT

    account_input = update.message.text.strip()

    if not account_input.isdigit():
        await update.message.reply_text(
            "❌ Invalid account number.\nDigits only, please."
        )
        return

    DESCO_ACCOUNT = account_input
    set_key(ENV_FILE, "DESCO_ACCOUNT_NUMBER", DESCO_ACCOUNT)

    await update.message.reply_text(
        f"✅ Account saved: {DESCO_ACCOUNT}\n\n"
        "You can now use /balance or wait for notifications."
    )
    await show_menu(update)


async def show_menu(update: Update):
    """Display help/menu."""
    await update.message.reply_text(
        "📌 *Commands & Info*\n\n"
        "/balance — Check balance manually\n"
        "/help — Show this menu\n\n"
        "*Automatic updates:*\n"
        "• 10:00 AM — Morning update\n"
        "• 10:00 PM — Evening update\n"
        "• Every 10 min — Regular update\n"
        "• Low balance (<100 BDT) — Alerts\n",
        parse_mode="Markdown",
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_menu(update)


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual balance check."""
    await update.message.reply_text("🔄 Fetching DESCO balance...")

    try:
        balance_value = await fetch_balance_with_retry()
        await update.message.reply_text(
            f"💡 Remaining Balance:\n{balance_value:.2f} BDT"
        )
    except Exception:
        await update.message.reply_text(
            "⚠️ Unable to fetch DESCO balance."
        )


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Simple greeting handler."""
    msg = update.message.text.lower()
    if any(word in msg for word in ("hi", "hello")):
        await update.message.reply_text(
            "👋 Hello! Use /help to see commands."
        )


# =================================================
# SCHEDULED JOBS
# =================================================

async def scheduled_balance(context: ContextTypes.DEFAULT_TYPE):
    if not CHAT_ID or not DESCO_ACCOUNT:
        return

    try:
        balance_value = await fetch_balance_with_retry()
        await context.bot.send_message(
            CHAT_ID,
            f"⏰ Scheduled Update\n"
            f"💡 Remaining Balance: {balance_value:.2f} BDT",
        )
    except Exception:
        await context.bot.send_message(
            CHAT_ID,
            "⚠️ Scheduled DESCO check failed."
        )


async def regular_10min_update(context: ContextTypes.DEFAULT_TYPE):
    if not CHAT_ID or not DESCO_ACCOUNT:
        return

    try:
        balance_value = await fetch_balance_with_retry()
        await context.bot.send_message(
            CHAT_ID,
            f"🔔 10-Minute Update\n"
            f"💡 Remaining Balance: {balance_value:.2f} BDT",
        )
    except Exception:
        pass


async def low_balance_monitor(context: ContextTypes.DEFAULT_TYPE):
    if not CHAT_ID or not DESCO_ACCOUNT:
        return

    try:
        balance_value = await fetch_balance_with_retry()
        if balance_value < LOW_BALANCE_THRESHOLD:
            await context.bot.send_message(
                CHAT_ID,
                f"🚨 *LOW BALANCE ALERT!*\n"
                f"Remaining Balance: {balance_value:.2f} BDT",
                parse_mode="Markdown",
            )
    except Exception:
        pass


# =================================================
# MAIN ENTRY POINT
# =================================================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_account))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    job_queue = app.job_queue

    job_queue.run_daily(
        scheduled_balance,
        time=time(10, 0, tzinfo=BD_TZ),
        name="morning_update",
    )
    job_queue.run_daily(
        scheduled_balance,
        time=time(22, 0, tzinfo=BD_TZ),
        name="evening_update",
    )

    job_queue.run_repeating(
        regular_10min_update,
        interval=600,
        first=600,
        name="10min_update",
    )
    job_queue.run_repeating(
        low_balance_monitor,
        interval=300,
        first=300,
        name="low_balance_monitor",
    )

    print("✅ DESCO Universal Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
