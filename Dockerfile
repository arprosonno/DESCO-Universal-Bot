# Base Python image
FROM python:3.11-slim

# Non-interactive install
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \
    curl wget gnupg ca-certificates \
    fonts-liberation libnss3 libx11-xcb1 libxcomposite1 \
    libxdamage1 libxrandr2 libasound2 libatk1.0-0 libcups2 \
    libxss1 libgtk-3-0 libgbm1 libpango1.0-0 libatk-bridge2.0-0 \
    libdrm2 libxinerama1 libglib2.0-0 libfontconfig1 libxext6 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy all project files
COPY . .

# Install Python dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Install Playwright browsers
RUN playwright install --with-deps

# Expose a port (needed by Railway, but bot doesn't actually use it)
EXPOSE 8080

# Run the bot
CMD ["python", "bot.py"]
