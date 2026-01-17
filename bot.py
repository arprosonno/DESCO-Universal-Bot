import asyncio
import re
import sqlite3
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

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
DESCO_URL = "https://prepaid.desco.org.bd/customer/#/customer-info"
BD_TZ = pytz.timezone("Asia/Dhaka")

LOW_BALANCE_THRESHOLD = 100
RETRY_ATTEMPTS = 5
RETRY_DELAY = 15

# ---------------- DB ----------------
conn = sqlite3.connect("users.db", check_same_thread=False)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    chat_id INTEGER PRIMARY KEY,
    account TEXT NOT NULL
)
""")
conn.commit()

# ---------------- DESCO FETCH ----------------
async def fetch_desco_balance(account):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(DESCO_URL, timeout=60000)
        await page.fill("input", account)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(6000)

        body = await page.inner_text("body")
        await browser.close()

        match = re.search(r"Remaining Balance:\s*([\d,]+\.\d+)\s*BDT", body)
        if not match:
            raise RuntimeError("Balance not found")

        return float(match.group(1).replace(",", ""))

async def fetch_with_retry(account):
    for _ in range(RETRY_ATTEMPTS):
        try:
            return await fetch_desco_balance(account)
        except:
            await asyncio.sleep(RETRY_DELAY)
    raise RuntimeError("All retries failed")

# ---------------- HELPERS ----------------
def get_account(chat_id):
    cur.execute("SELECT account FROM users WHERE chat_id=?", (chat_id,))
    row = cur.fetchone()
    return row[0] if row else None

# ---------------- COMMANDS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome!\n\n"
        "Please send your DESCO prepaid meter account number."
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    account = get_account(chat_id)

    if not account:
        await update.message.reply_text("❌ No account set. Send account number first.")
        return

    await update.message.reply_text("🔄 Checking balance...")
    try:
        bal = await fetch_with_retry(account)
        await update.message.reply_text(f"💡 Remaining Balance: {bal:.2f} BDT")
    except:
        await update.message.reply_text("⚠️ Failed to fetch balance")

# ---------------- MESSAGE HANDLER ----------------
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    if text.isdigit():
        cur.execute(
            "INSERT OR REPLACE INTO users (chat_id, account) VALUES (?,?)",
            (chat_id, text),
        )
        conn.commit()
        await update.message.reply_text(
            f"✅ Account saved!\n\n"
            f"Automatic updates enabled:\n"
            f"• Every 10 minutes\n"
            f"• 10 AM & 10 PM\n"
            f"• Low balance alerts"
        )
    else:
        await update.message.reply_text("❌ Please send a valid account number.")

# ---------------- JOBS ----------------
async def ten_min_job(context: ContextTypes.DEFAULT_TYPE):
    cur.execute("SELECT chat_id, account FROM users")
    for chat_id, account in cur.fetchall():
        try:
            bal = await fetch_with_retry(account)
            await context.bot.send_message(
                chat_id,
                f"⏰ 10-Min Update\nBalance: {bal:.2f} BDT"
            )
        except:
            pass

async def daily_job(context: ContextTypes.DEFAULT_TYPE):
    cur.execute("SELECT chat_id, account FROM users")
    for chat_id, account in cur.fetchall():
        try:
            bal = await fetch_with_retry(account)
            await context.bot.send_message(
                chat_id,
                f"🌞 Daily Update\nBalance: {bal:.2f} BDT"
            )
        except:
            pass

async def low_balance_job(context: ContextTypes.DEFAULT_TYPE):
    cur.execute("SELECT chat_id, account FROM users")
    for chat_id, account in cur.fetchall():
        try:
            bal = await fetch_with_retry(account)
            if bal < LOW_BALANCE_THRESHOLD:
                await context.bot.send_message(
                    chat_id,
                    f"🚨 LOW BALANCE ALERT!\nBalance: {bal:.2f} BDT"
                )
        except:
            pass

# ---------------- MAIN ----------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    jq = app.job_queue
    jq.run_repeating(ten_min_job, interval=600, first=60)
    jq.run_daily(daily_job, time=time(10, 0, tzinfo=BD_TZ))
    jq.run_daily(daily_job, time=time(22, 0, tzinfo=BD_TZ))
    jq.run_repeating(low_balance_job, interval=300, first=120)

    print("✅ DESCO BOT ONLINE (MULTI-USER)")
    app.run_polling()

if __name__ == "__main__":
    main()
