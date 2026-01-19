FROM python:3.11-bullseye

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libnss3 libx11-xcb1 libxcomposite1 libxdamage1 \
    libxrandr2 libasound2 libatk1.0-0 libcups2 \
    libxss1 libgtk-3-0 libgbm1 libpango-1.0-0 \
    libatk-bridge2.0-0 libdrm2 libxinerama1 \
    libglib2.0-0 libfontconfig1 libxext6 \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN pip install --upgrade pip
RUN pip install -r requirements.txt
RUN playwright install --with-deps

EXPOSE 8080
CMD ["python", "bot.py"]



