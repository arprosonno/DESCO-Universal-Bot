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

# =====================
# CONFIG
# =====================

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
DESCO_URL = "https://prepaid.desco.org.bd/customer/#/customer-info"

BD_TZ = pytz.timezone("Asia/Dhaka")
LOW_BALANCE_THRESHOLD = 100

USER_DATA = {}

# =====================
# PLAYWRIGHT (SAFE SINGLETON)
# =====================

_playwright = None
_browser = None
_browser_lock = asyncio.Lock()


async def get_browser():
    global _playwright, _browser

    async with _browser_lock:
        if _browser is None:
            _playwright = await async_playwright().start()
            _browser = await _playwright.chromium.launch(headless=True)
        return _browser


async def fetch_desco_balance(account: str):
    try:
        browser = await get_browser()
        page = await browser.new_page()

        await page.goto(DESCO_URL, timeout=60000)
        await page.wait_for_selector("input", timeout=30000)
        await page.fill("input", account)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(6000)

        text = await page.inner_text("body")
        match = re.search(r"Remaining Balance:\s*([\d,]+\.\d+)", text)

        await page.close()

        if not match:
            return None

        return float(match.group(1).replace(",", ""))

    except Exception:
        return None


# =====================
# COMMANDS
# =====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome!\nSend your *DESCO account number*.",
        parse_mode="Markdown",
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start – Start\n"
        "/balance – Check balance\n\n"
        "⏰ Alerts:\n"
        "• Morning & Evening\n"
        "• Every 10 minutes\n"
        "• Low balance warning",
        parse_mode="Markdown",
    )


async def receive_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.strip()
    chat_id = update.effective_chat.id

    if not msg.isdigit():
        await update.message.reply_text("❌ Digits only.")
        return

    USER_DATA[chat_id] = {"account": msg}
    await update.message.reply_text(
        f"✅ Account saved: *{msg}*",
        parse_mode="Markdown",
    )


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = USER_DATA.get(chat_id)

    if not data:
        await update.message.reply_text("❗ Send account number first.")
        return

    await update.message.reply_text("🔄 Checking balance...")
    bal = await fetch_desco_balance(data["account"])

    if bal is None:
        await update.message.reply_text("⚠️ DESCO unavailable.")
    else:
        await update.message.reply_text(
            f"💡 Balance: *{bal:.2f} BDT*",
            parse_mode="Markdown",
        )


# =====================
# SCHEDULED JOBS
# =====================

async def broadcast(context, title):
    for chat_id, data in USER_DATA.items():
        bal = await fetch_desco_balance(data["account"])
        if bal is not None:
            await context.bot.send_message(
                chat_id,
                f"{title}\n💡 *{bal:.2f} BDT*",
                parse_mode="Markdown",
            )


async def morning(context):
    await broadcast(context, "🌅 Good Morning")


async def evening(context):
    await broadcast(context, "🌙 Good Evening")


async def ten_min(context):
    await broadcast(context, "🔔 10-Min Update")


async def low_balance(context):
    for chat_id, data in USER_DATA.items():
        bal = await fetch_desco_balance(data["account"])
        if bal is not None and bal < LOW_BALANCE_THRESHOLD:
            await context.bot.send_message(
                chat_id,
                f"🚨 LOW BALANCE: *{bal:.2f} BDT*",
                parse_mode="Markdown",
            )


# =====================
# MAIN
# =====================

def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN missing (set in Railway variables)")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_account))

    jq = app.job_queue
    jq.run_daily(morning, time=time(10, 0, tzinfo=BD_TZ))
    jq.run_daily(evening, time=time(22, 0, tzinfo=BD_TZ))
    jq.run_repeating(ten_min, interval=600, first=600)
    jq.run_repeating(low_balance, interval=300, first=300)

    print("💓 Bot running safely (polling)")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()



