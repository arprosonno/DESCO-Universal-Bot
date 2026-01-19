import asyncio
import os
import re
import sys
from datetime import time
from typing import Dict
import time as ttime

import pytz
from playwright.async_api import async_playwright, TimeoutError as PWTimeout
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

FETCH_TIMEOUT = 45
RETRY_ATTEMPTS = 3
RETRY_DELAY = 15

USER_DATA: Dict[int, Dict[str, str]] = {}
FETCH_SEMAPHORE = asyncio.Semaphore(3)

# =================================================
# DESCO SCRAPER
# =================================================

async def fetch_desco_balance(account: str) -> float:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        page = await browser.new_page()

        try:
            await page.goto(DESCO_URL, timeout=30000)
            await page.wait_for_selector("input", timeout=20000)
            await page.fill("input", account)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(6000)
            content = await page.inner_text("body")
        finally:
            await browser.close()

    match = re.search(r"Remaining Balance:\s*([\d,]+\.\d+)\s*BDT", content)
    if not match:
        raise RuntimeError("Balance not found")
    return float(match.group(1).replace(",", ""))

async def fetch_with_retry(account: str) -> float:
    last_error = None
    async with FETCH_SEMAPHORE:
        for _ in range(RETRY_ATTEMPTS):
            try:
                return await asyncio.wait_for(
                    fetch_desco_balance(account),
                    timeout=FETCH_TIMEOUT,
                )
            except (PWTimeout, asyncio.TimeoutError):
                last_error = "Timeout while fetching DESCO"
            except Exception as e:
                last_error = str(e)
            await asyncio.sleep(RETRY_DELAY)
    raise RuntimeError("DESCO unreachable repeatedly")

# =================================================
# COMMANDS
# =================================================

HELP_TEXT = (
    "📌 *DESCO Balance Bot*\n\n"
    "/start — Start the bot\n"
    "/balance — Check balance now\n"
    "/help — Show help menu\n\n"
    "*Automatic alerts:*\n"
    "• 🌅 10:00 AM\n"
    "• 🌙 10:00 PM\n"
    "• 🔔 Every 10 minutes\n"
    "• 🚨 Low balance alert\n"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    USER_DATA.setdefault(chat_id, {})
    await update.message.reply_text(
        "👋 Welcome!\n\nSend your *DESCO account number*.",
        parse_mode="Markdown",
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")

async def receive_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    msg = update.message.text.strip()

    if msg.lower() in {"hi", "hello", "hey"}:
        await update.message.reply_text("👋 Hello! Use /help to see options.")
        return

    if not msg.isdigit():
        await update.message.reply_text("❌ Digits only. Send your account number.")
        return

    USER_DATA.setdefault(chat_id, {})["account"] = msg
    await update.message.reply_text(
        f"✅ Account saved: *{msg}*\n\nAutomatic alerts enabled.\nUse /balance anytime.",
        parse_mode="Markdown",
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = USER_DATA.get(chat_id)

    if not data or "account" not in data:
        await update.message.reply_text("❗ Send your account number first.")
        return

    await update.message.reply_text("🔄 Checking balance...")
    try:
        bal = await fetch_with_retry(data["account"])
        await update.message.reply_text(
            f"💡 Remaining Balance: *{bal:.2f} BDT*",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"⚠️ {e}")

# =================================================
# SCHEDULED JOBS
# =================================================

async def broadcast(context: ContextTypes.DEFAULT_TYPE, title: str):
    for chat_id, data in list(USER_DATA.items()):
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
            continue

async def morning_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        await broadcast(context, "🌅 Good Morning!")
    except Exception:
        pass

async def evening_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        await broadcast(context, "🌙 Good Evening!")
    except Exception:
        pass

async def ten_min_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        await broadcast(context, "🔔 10-Minute Update")
    except Exception:
        pass

async def low_balance_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        for chat_id, data in list(USER_DATA.items()):
            account = data.get("account")
            if not account:
                continue
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
# MAIN FUNCTION - SIMPLIFIED
# =================================================

def main():
    print("🚀 Starting DESCO Balance Bot...")
    
    # Initialize application
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .connection_pool_size(1)
        .pool_timeout(30)
        .build()
    )
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_account))
    
    # Setup job queue
    jq = app.job_queue
    if jq:
        jq.run_daily(morning_job, time=time(10, 0, tzinfo=BD_TZ))
        jq.run_daily(evening_job, time=time(22, 0, tzinfo=BD_TZ))
        jq.run_repeating(ten_min_job, interval=600, first=600)
        jq.run_repeating(low_balance_job, interval=300, first=300)
        print("✅ Job scheduler initialized")
    
    # Run the bot
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
        close_loop=False
    )

if __name__ == "__main__":
    # Simple restart logic
    max_restarts = 5
    restart_delay = 30
    
    for attempt in range(max_restarts):
        try:
            print(f"📡 Attempt {attempt + 1}/{max_restarts}")
            main()
        except KeyboardInterrupt:
            print("🛑 Bot stopped by user")
            sys.exit(0)
        except Exception as e:
            print(f"💥 Bot crashed: {type(e).__name__}: {e}")
            if attempt < max_restarts - 1:
                print(f"🔄 Restarting in {restart_delay} seconds...")
                ttime.sleep(restart_delay)
            else:
                print("❌ Max restart attempts reached")
                sys.exit(1)
