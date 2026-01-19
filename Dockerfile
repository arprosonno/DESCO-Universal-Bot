FROM python:3.11-slim-bullseye

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl wget gnupg ca-certificates \
    fonts-liberation libnss3 libx11-xcb1 libxcomposite1 \
    libxdamage1 libxrandr2 libasound2 libatk1.0-0 libcups2 \
    libxss1 libgtk-3-0 libgbm1 libpango-1.0-0 libatk-bridge2.0-0 \
    libdrm2 libxinerama1 libglib2.0-0 libfontconfig1 libxext6 \
    && rm -rf /var/lib/apt/lists/*

# Copy application files
COPY requirements.txt .
COPY bot.py .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install Playwright browser
RUN playwright install --with-deps chromium

# Expose port for health checks
EXPOSE 8080

# Run the bot
CMD ["python", "bot.py"]


