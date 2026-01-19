FROM python:3.11-slim-bullseye

WORKDIR /app

# Install system dependencies for Playwright (use bullseye specific packages)
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    ca-certificates \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libasound2 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libxss1 \
    libgtk-3.0-0 \
    libgbm1 \
    libpango-1.0-0 \
    libdrm2 \
    libxinerama1 \
    libglib2.0-0 \
    libfontconfig1 \
    libxext6 \
    fonts-liberation \
    fonts-unifont \
    fonts-freefont-ttf \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (better for caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install Playwright without system dependencies (we installed them manually)
RUN playwright install chromium --with-deps

# Copy application code
COPY bot.py .

# Run the bot
CMD ["python", "bot.py"]


