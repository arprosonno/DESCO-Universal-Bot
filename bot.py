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

# =========================
# CONFIG
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("⚠️ BOT_TOKEN not set! Bot will wait until it's available...")
    while not BOT_TOKEN:
        asyncio.sleep(5)
        BOT_TOKEN = os.getenv("BOT_TOKEN")

DESCO_URL = "https://prepaid.desco.org.bd/customer/#/customer-info"
BD_TZ = pytz.timezone("Asia/Dhaka")
LOW_BALANCE_THRESHOLD = 100
USER_DATA = {}

# =========================
# PLAYWRIGHT
# =========================

_browser = None
_playwright = None

async def get_browser():
    global _browser, _playwright
    if _browser is None:
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(headless=True)
    return _browser

async def fetch_desco_balance(account: str) -> float:
    browser = await get_browser()
    page = await browser.new_page()
    try:
        await page.goto(DESCO_URL, timeout=60_000)
        await page.wait_for_selector("input", timeout=30_000)
        await page.fill("input", account)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(6_000)
        content = await page.inner_text("body")
        match = re.search(r"Remaining Balance:\s*([\d,]+\.\d+)", content)
        if not match:
            raise RuntimeError("Balance not found")
        return float(match.group(1).replace(",", ""))
    finally:
        await page.close()

async def safe_fetch(account: str):
    try:
        return await fetch_desco_balance(account)
    except Exception:
        return None

# =========================
# COMMANDS
# =========================

HELP_TEXT = (
    "📌 *DESCO Balance Bot*\n\n"
    "/start – Start\n"
    "/balance – Check balance\n"
    "/help – Help\n\n"
    "⏰ Auto alerts:\n"
    "• 10:00 AM\n"
    "• 10:00 PM\n"
    "• Every 10 minutes\n"
    "• Low balance warning\n"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome!\nSend your *DESCO account number*.",
        parse_mode="Markdown",
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")

async def receive_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.strip()
    chat_id = update.effective_chat.id
    if msg.lower() in ("hi", "hello", "hey"):
        await update.message.reply_text("👋 Hello! Use /help")
        return
    if not msg.isdigit():
        await update.message.reply_text("❌ Digits only.")
        return
    USER_DATA[chat_id] = {"account": msg}
    await update.message.reply_text(f"✅ Account saved: *{msg}*\nUse /balance anytime.", parse_mode="Markdown")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = USER_DATA.get(chat_id)
    if not data:
        await update.message.reply_text("❗ Send account number first.")
        return
    await update.message.reply_text("🔄 Checking balance...")
    bal = await safe_fetch(data["account"])
    if bal is None:
        await update.message.reply_text("⚠️ DESCO temporarily unavailable.")
    else:
        await update.message.reply_text(f"💡 Balance: *{bal:.2f} BDT*", parse_mode="Markdown")

# =========================
# SCHEDULED JOBS
# =========================

async def broadcast(context, title):
    for chat_id, data in USER_DATA.items():
        bal = await safe_fetch(data["account"])
        if bal is None:
            continue
        await context.bot.send_message(chat_id, f"{title}\n💡 *{bal:.2f} BDT*", parse_mode="Markdown")

async def morning(context):
    await broadcast(context, "🌅 Good Morning!")

async def evening(context):
    await broadcast(context, "🌙 Good Evening!")

async def ten_min(context):
    await broadcast(context, "🔔 10-Minute Update")

async def low_balance(context):
    for chat_id, data in USER_DATA.items():
        bal = await safe_fetch(data["account"])
        if bal is not None and bal < LOW_BALANCE_THRESHOLD:
            await context.bot.send_message(chat_id, f"🚨 LOW BALANCE: *{bal:.2f} BDT*", parse_mode="Markdown")

# =========================
# MAIN
# =========================

def main():
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

    print("💓 Bot running (polling, stable)")
    app.run_polling()

if __name__ == "__main__":
    main()





