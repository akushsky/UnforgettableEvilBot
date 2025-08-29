# Multi-stage build for optimized image size
FROM node:18-alpine AS node-builder

# Install Node.js dependencies with Puppeteer skip
WORKDIR /app/bridge
COPY whatsapp_bridge/package*.json ./
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
RUN npm ci --only=production

# Main Python image - explicitly for AMD64
FROM --platform=linux/amd64 python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    ca-certificates \
    procps \
    curl \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Chrome for Puppeteer (AMD64 optimized)
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs

# Create user for security
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

# Set working directory
WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy Node.js dependencies from builder stage
COPY --from=node-builder /app/bridge/node_modules /app/whatsapp_bridge/node_modules

# Copy application code
COPY . .

# Copy logging configuration
COPY logging.conf /app/logging.conf

# Create necessary directories with proper permissions
RUN mkdir -p /app/whatsapp_sessions /app/logs /app/data \
    && chown -R appuser:appuser /app

# Switch to non-privileged user
USER appuser

# Environment variables for Chrome and Puppeteer
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/google-chrome-stable \
    DISPLAY=:99

# Copy startup script
COPY --chown=appuser:appuser docker/start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Copy debug scripts
COPY --chown=appuser:appuser debug_db.py /app/debug_db.py
COPY --chown=appuser:appuser debug_imports.py /app/debug_imports.py
RUN chmod +x /app/debug_db.py /app/debug_imports.py

# Expose ports
EXPOSE 9876

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:9876/health || exit 1

# Entry point
CMD ["/app/start.sh"]
