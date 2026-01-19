# Use Playwright official base image (with browsers pre-installed)
FROM mcr.microsoft.com/playwright:focal

# Set working directory
WORKDIR /app

# Copy project files
COPY . .

# Upgrade pip and install Python dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Expose port if needed (optional)
EXPOSE 8080

# Set environment variable placeholder
ENV BOT_TOKEN=""

# Start bot
CMD ["python", "bot.py"]






