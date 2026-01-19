import asyncio
import os
import re
from datetime import time

import pytz
from aiohttp import web
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from telegram import Update
from telegram.ext import (
    Application,
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
PUBLIC_URL = os.getenv("PUBLIC_URL")

if not BOT_TOKEN or not PUBLIC_URL:
    raise RuntimeError("TELEGRAM_BOT_TOKEN or PUBLIC_URL not set")

DESCO_URL = "https://prepaid.desco.org.bd/customer/#/customer-info"
BD_TZ = pytz.timezone("Asia/Dhaka")

LOW_BALANCE_THRESHOLD = 100

USER_DATA: dict[int, dict] = {}

# =================================================
# PLAYWRIGHT GLOBALS (CRITICAL FIX)
# =================================================

playwright = None
browser = None
desco_lock = asyncio.Lock()

# =================================================
# PLAYWRIGHT INIT / CLEANUP
# =================================================

async def start_browser():
    global playwright, browser
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    print("✅ Playwright browser started")

async def stop_browser():
    global playwright, browser
    if browser:
        await browser.close()
    if playwright:
        await playwright.stop()

# =================================================
# DESCO SCRAPER (SAFE)
# =================================================

async def fetch_desco_balance(account: str) -> float:
    async with desco_lock:
        context = await browser.new_context()
        page = await context.new_page()

        try:
            await page.goto(DESCO_URL, timeout=30_000)
            await page.wait_for_selector("input", timeout=15_000)
            await page.fill("input", account)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(5_000)

            content = await page.inner_text("body")
        except PlaywrightTimeout:
            raise RuntimeError("DESCO timeout")
        finally:
            await context.close()

    match = re.search(r"Remaining Balance:\s*([\d,]+\.\d+)\s*BDT", content)
    if not match:
        raise RuntimeError("Balance not found")

    return float(match.group(1).replace(",", ""))

# =================================================
# HELP
# =================================================

HELP_TEXT = (
    "📌 *DESCO Balance Bot*\n\n"
    "/start — Start bot\n"
    "/balance — Check balance\n"
    "/help — Help menu\n\n"
    "⏰ Notifications:\n"
    "• 10:00 AM\n"
    "• 10:00 PM\n"
    "• Every 10 minutes\n"
    "• Low balance alert\n"
)

# =================================================
# COMMANDS
# =================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER_DATA.setdefault(update.effective_chat.id, {})
    await update.message.reply_text(
        "👋 Welcome!\nSend your *DESCO account number*.",
        parse_mode="Markdown",
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")

async def receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    msg = update.message.text.strip()

    if msg.lower() in ("hi", "hello", "hey"):
        await update.message.reply_text("👋 Hi! Use /help")
        return

    if not msg.isdigit():
        await update.message.reply_text("❌ Send digits only.")
        return

    USER_DATA.setdefault(chat_id, {})["account"] = msg
    await update.message.reply_text(
        f"✅ Account saved: *{msg}*\nUse /balance anytime.",
        parse_mode="Markdown",
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    account = USER_DATA.get(chat_id, {}).get("account")

    if not account:
        await update.message.reply_text("❗ Send account number first.")
        return

    await update.message.reply_text("🔄 Checking...")
    try:
        bal = await fetch_desco_balance(account)
        await update.message.reply_text(
            f"💡 Balance: *{bal:.2f} BDT*",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"⚠️ {e}")

# =================================================
# JOBS (NON-BLOCKING)
# =================================================

async def broadcast(context: ContextTypes.DEFAULT_TYPE, title: str):
    for chat_id, data in USER_DATA.items():
        account = data.get("account")
        if not account:
            continue
        try:
            bal = await fetch_desco_balance(account)
            await context.bot.send_message(
                chat_id,
                f"{title}\n💡 Balance: *{bal:.2f} BDT*",
                parse_mode="Markdown",
            )
        except Exception:
            pass

async def morning_job(ctx): await broadcast(ctx, "🌅 Good Morning")
async def evening_job(ctx): await broadcast(ctx, "🌙 Good Evening")
async def ten_min_job(ctx): await broadcast(ctx, "🔔 10-Min Update")

async def low_balance_job(ctx):
    for chat_id, data in USER_DATA.items():
        account = data.get("account")
        if not account:
            continue
        try:
            bal = await fetch_desco_balance(account)
            if bal < LOW_BALANCE_THRESHOLD:
                await ctx.bot.send_message(
                    chat_id,
                    f"🚨 *LOW BALANCE*\n{bal:.2f} BDT",
                    parse_mode="Markdown",
                )
        except Exception:
            pass

# =================================================
# WEBHOOK SERVER
# =================================================

async def run_webhook(app: Application):
    await app.bot.set_webhook(f"{PUBLIC_URL}/webhook")

    web_app = web.Application()
    web_app.router.add_post(
        "/webhook",
        lambda request: app.update_queue.put(
            Update.de_json(await request.json(), app.bot)
        ),
    )

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()

# =================================================
# MAIN
# =================================================

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text))

    await start_browser()

    jq = app.job_queue
    jq.run_daily(morning_job, time=time(10, 0, tzinfo=BD_TZ))
    jq.run_daily(evening_job, time=time(22, 0, tzinfo=BD_TZ))
    jq.run_repeating(ten_min_job, interval=600)
    jq.run_repeating(low_balance_job, interval=300)

    await app.initialize()
    await app.start()
    await run_webhook(app)

    print("💓 BOT STABLE & PRODUCTION READY")

    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
