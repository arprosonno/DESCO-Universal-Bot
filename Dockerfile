# Use official Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \
    curl \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libasound2 \
    libatk1.0-0 \
    libcups2 \
    libxss1 \
    libgtk-3-0 \
    libgbm1 \
    libpango-1.0-0 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxinerama1 \
    libglib2.0-0 \
    libfontconfig1 \
    libxext6 \
    unzip \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Copy files
COPY . .

# Upgrade pip and install Python dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Install Playwright browsers
RUN python -m playwright install --with-deps

# Expose port if needed (for web apps, optional)
EXPOSE 8080

# Set environment variable (can override in Railway dashboard)
ENV BOT_TOKEN=""

# Start the bot using polling
CMD ["python", "bot.py"]





