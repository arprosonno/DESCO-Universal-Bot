import asyncio
import os
import re
from datetime import time, datetime

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
RETRY_DELAY = 20

JOB_TIMEOUT = 120
TG_TIMEOUT = 20

HEARTBEAT_INTERVAL = 3600      # 1 hour
WATCHDOG_INTERVAL = 900        # 15 min
MAX_FAILS = 3

# =================================================
# STATE (IN-MEMORY)
# =================================================

USER_DATA = {}                 # {chat_id: {"account": str}}
OWNER_CHAT_ID = None

FAIL_COUNT = 0
LAST_JOB_RUN = datetime.utcnow()

# =================================================
# UTILITIES
# =================================================

async def safe_send(bot, chat_id, text):
    await asyncio.wait_for(
        bot.send_message(chat_id, text),
        timeout=TG_TIMEOUT,
    )


async def notify_owner(bot, text):
    if OWNER_CHAT_ID is None:
        return
    try:
        await safe_send(bot, OWNER_CHAT_ID, text)
    except Exception:
        pass

# =================================================
# DESCO SCRAPER (HARDENED)
# =================================================

async def fetch_desco_balance(account: str) -> float:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = await browser.new_page()
            await page.goto(DESCO_URL, timeout=60_000)
            await page.wait_for_selector("input", timeout=30_000)
            await page.fill("input", account)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(6_000)
            content = await page.inner_text("body")
        finally:
            await browser.close()

    match = re.search(r"Remaining Balance:\s*([\d,]+\.\d+)\s*BDT", content)
    if not match:
        raise RuntimeError("Balance not found")

    return float(match.group(1).replace(",", ""))


async def fetch_with_retry(account: str) -> float:
    global FAIL_COUNT
    for _ in range(RETRY_ATTEMPTS):
        try:
            bal = await fetch_desco_balance(account)
            FAIL_COUNT = 0
            return bal
        except Exception:
            FAIL_COUNT += 1
            await asyncio.sleep(RETRY_DELAY)

    raise RuntimeError("DESCO unreachable")

# =================================================
# COMMAND HANDLERS
# =================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global OWNER_CHAT_ID

    chat_id = update.effective_chat.id
    USER_DATA.setdefault(chat_id, {})

    if OWNER_CHAT_ID is None:
        OWNER_CHAT_ID = chat_id

    await update.message.reply_text(
        "👋 Welcome!\n\nPlease send your DESCO account number."
    )


async def receive_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    account = update.message.text.strip()

    if not account.isdigit():
        await update.message.reply_text("❌ Digits only. Send again.")
        return

    USER_DATA.setdefault(chat_id, {})["account"] = account

    await update.message.reply_text(
        f"✅ Account saved: {account}\n\n"
        "You will receive:\n"
        "• 10 AM update\n"
        "• 10 PM update\n"
        "• Every 10 minutes\n"
        "• Low balance alerts\n\n"
        "Use /balance anytime."
    )


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = USER_DATA.get(update.effective_chat.id)
    if not data or "account" not in data:
        await update.message.reply_text("❗ Send account first.")
        return

    await update.message.reply_text("🔄 Checking balance...")
    try:
        bal = await asyncio.wait_for(
            fetch_with_retry(data["account"]),
            timeout=JOB_TIMEOUT,
        )
        await update.message.reply_text(f"💡 Remaining Balance: {bal:.2f} BDT")
    except Exception:
        await update.message.reply_text("⚠️ Failed to fetch balance.")

# =================================================
# SCHEDULED JOBS
# =================================================

async def scheduled_updates(context, label):
    global LAST_JOB_RUN
    LAST_JOB_RUN = datetime.utcnow()

    for chat_id, data in USER_DATA.items():
        account = data.get("account")
        if not account:
            continue
        try:
            bal = await fetch_with_retry(account)
            await safe_send(
                context.bot,
                chat_id,
                f"{label}\n💡 Remaining Balance: {bal:.2f} BDT",
            )
        except Exception:
            pass


async def morning_job(context):
    await asyncio.wait_for(
        scheduled_updates(context, "🌅 Good Morning!"),
        timeout=JOB_TIMEOUT,
    )


async def evening_job(context):
    await asyncio.wait_for(
        scheduled_updates(context, "🌙 Good Evening!"),
        timeout=JOB_TIMEOUT,
    )


async def ten_min_job(context):
    await asyncio.wait_for(
        scheduled_updates(context, "🔔 10-Min Update"),
        timeout=JOB_TIMEOUT,
    )


async def low_balance_job(context):
    async def _run():
        for chat_id, data in USER_DATA.items():
            account = data.get("account")
            if not account:
                continue
            try:
                bal = await fetch_with_retry(account)
                if bal < LOW_BALANCE_THRESHOLD:
                    await safe_send(
                        context.bot,
                        chat_id,
                        f"🚨 LOW BALANCE ALERT!\nRemaining: {bal:.2f} BDT",
                    )
            except Exception:
                pass

    await asyncio.wait_for(_run(), timeout=JOB_TIMEOUT)

# =================================================
# MONITORING LAYERS
# =================================================

async def heartbeat_job(context):
    await notify_owner(
        context.bot,
        "💓 Bot alive & scheduler running normally"
    )


async def watchdog_job(context):
    global FAIL_COUNT
    if FAIL_COUNT >= MAX_FAILS:
        await notify_owner(
            context.bot,
            "⚠️ WARNING: DESCO unreachable repeatedly"
        )
        FAIL_COUNT = 0

# =================================================
# GLOBAL ERROR SHIELD
# =================================================

async def error_handler(update, context):
    await notify_owner(
        context.bot,
        f"🔥 Unexpected error:\n{context.error}"
    )

# =================================================
# MAIN
# =================================================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_account))
    app.add_error_handler(error_handler)

    jq = app.job_queue

    jq.run_daily(morning_job, time=time(10, 0, tzinfo=BD_TZ))
    jq.run_daily(evening_job, time=time(22, 0, tzinfo=BD_TZ))
    jq.run_repeating(ten_min_job, interval=600, first=600)
    jq.run_repeating(low_balance_job, interval=300, first=300)

    jq.run_repeating(heartbeat_job, interval=HEARTBEAT_INTERVAL, first=60)
    jq.run_repeating(watchdog_job, interval=WATCHDOG_INTERVAL, first=300)

    print("✅ DESCO Bot FULLY FAIL-SAFE & RUNNING")
    app.run_polling()


if __name__ == "__main__":
    main()

