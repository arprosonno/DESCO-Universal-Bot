# Use Playwright's official Python image (with all dependencies)
FROM mcr.microsoft.com/playwright/python:v1.49.0-focal

# Set working directory
WORKDIR /app

# Copy project files
COPY . .

# Upgrade pip & install Python dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Expose default port (needed for Railway health checks)
EXPOSE 8080

# Start the bot
CMD ["python", "bot.py"]

