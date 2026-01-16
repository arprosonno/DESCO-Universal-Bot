# Use Python slim image
FROM python:3.11-slim

# Set environment variables for non-interactive installs
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies required by Playwright
RUN apt-get update && apt-get install -y \
    curl wget gnupg ca-certificates \
    fonts-liberation libnss3 libx11-xcb1 libxcomposite1 \
    libxc
