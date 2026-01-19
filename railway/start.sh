#!/bin/bash
# Startup script for Railway

echo "🚀 Starting DESCO Bot..."

# Set environment variables
export PYTHONUNBUFFERED=1
export PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Run the bot
exec python bot.py
