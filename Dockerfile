# Use Python full image from Docker Hub
FROM python:3.11-bullseye

# Set working directory
WORKDIR /app

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \
    curl wget gnupg ca-certificates \
    fonts-liberation libnss3 libx11-xcb1 libxcomposite1 \
    libxdamage1 libxrandr2 libasound2 libatk1.0-0 libcups2 \
    libxss1 libgtk-3-0 libgbm1 libpango-1.0-0 libatk-bridge2.0-0 \
    libdrm2 libxinerama1 libglib2.0-0 libfontconfig1 libxext6 \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY . .

# Upgrade pip & install Python dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Install Playwright browsers
RUN playwright install --with-deps

# Expose default port (needed for Railway)
EXPOSE 8080

# Start the bot
CMD ["python", "bot.py"]

