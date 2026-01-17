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
    raise RuntimeError("TELEGRAM_BOT_TOKEN not set in Railway")

DESCO_URL = "https://prepaid.desco.org.bd/customer/#/customer-info"
BD_TZ = pytz.timezone("Asia/Dhaka")

LOW_BALANCE_THRESHOLD = 100
RETRY_ATTEMPTS = 5
RETRY_DELAY = 20  # seconds

# { chat_id: { "account": "xxxx" } }
USER_DATA = {}

# =================================================
# DESCO SCRAPER
# =================================================

async def fetch_desco_balance(account: str) -> float:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await browser.new_page()

        await page.goto(DESCO_URL, timeout=60_000)
        await page.wait_for_selector("input", timeout=30_000)
        await page.fill("input", account)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(6_000)

        content = await page.inner_text("body")
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
    raise RuntimeError("All retries failed") from last_error

# =================================================
# COMMANDS
# =================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    USER_DATA.setdefault(chat_id, {})

    await update.message.reply_text(
        "👋 Welcome!\n\n"
        "Please send your DESCO account number.\n\n"
        "ℹ️ Type /help for commands."
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Help Menu*\n\n"
        "➡️ Send DESCO account number (digits only)\n"
        "➡️ /balance – Check balance\n\n"
        "⏱ Automatic updates:\n"
        "• 10 AM\n"
        "• 10 PM\n"
        "• Every 10 minutes\n"
        "• Low balance alerts",
        parse_mode="Markdown",
    )


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = USER_DATA.get(chat_id)

    if not data or "account" not in data:
        await update.message.reply_text("❗ Send account number first.")
        return

    await update.message.reply_text("🔄 Checking balance...")
    try:
        bal = await fetch_with_retry(data["account"])
        await update.message.reply_text(f"💡 Remaining Balance: {bal:.2f} BDT")
    except Exception:
        await update.message.reply_text("⚠️ Failed to fetch balance.")

# =================================================
# MESSAGE HANDLERS (RESPONSIVE, SAFE)
# =================================================

async def greetings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower().strip()

    if any(w in text for w in ["hi", "hello", "hey", "ho"]):
        await update.message.reply_text(
            "👋 Hello!\nSend your account number or type /help 🙂"
        )


async def receive_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    account = update.message.text.strip()

    # IMPORTANT: ignore non-digit silently
    if not account.isdigit():
        return

    USER_DATA.setdefault(chat_id, {})["account"] = account

    await update.message.reply_text(
        f"✅ Account saved: {account}\n\n"
        "You will now receive:\n"
        "• 10 AM update\n"
        "• 10 PM update\n"
        "• Every 10 min update\n"
        "• Low balance alerts\n\n"
        "Use /balance anytime."
    )

# =================================================
# SCHEDULED JOBS (UNCHANGED)
# =================================================

async def scheduled_updates(context: ContextTypes.DEFAULT_TYPE, label: str):
    for chat_id, data in USER_DATA.items():
        account = data.get("account")
        if not account:
            continue
        try:
            bal = await fetch_with_retry(account)
            await context.bot.send_message(
                chat_id,
                f"{label}\n💡 Remaining Balance: {bal:.2f} BDT",
            )
        except Exception:
            pass


async def morning_job(context: ContextTypes.DEFAULT_TYPE):
    await scheduled_updates(context, "🌅 Good Morning!")


async def evening_job(context: ContextTypes.DEFAULT_TYPE):
    await scheduled_updates(context, "🌙 Good Evening!")


async def ten_min_job(context: ContextTypes.DEFAULT_TYPE):
    await scheduled_updates(context, "🔔 10-Min Update")


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
                    f"🚨 LOW BALANCE ALERT!\nRemaining: {bal:.2f} BDT",
                )
        except Exception:
            pass

# =================================================
# MAIN
# =================================================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("balance", balance))

    # ORDER MATTERS
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, greetings))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_account))

    jq = app.job_queue
    jq.run_daily(morning_job, time=time(10, 0, tzinfo=BD_TZ))
    jq.run_daily(evening_job, time=time(22, 0, tzinfo=BD_TZ))
    jq.run_repeating(ten_min_job, interval=600, first=600)
    jq.run_repeating(low_balance_job, interval=300, first=300)

    print("✅ DESCO Universal Bot RUNNING")
    app.run_polling()


if __name__ == "__main__":
    main()

