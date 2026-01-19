# Official Playwright Python image (stable)
FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy

WORKDIR /app

# Copy project files
COPY . .

# Install Python dependencies
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

# Railway runs containers continuously
CMD ["python", "bot.py"]







