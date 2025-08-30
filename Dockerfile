# Optimized Dockerfile for Baileys WhatsApp Bridge
FROM python:3.12-slim

# Install system dependencies (minimal set)
RUN apt-get update && apt-get install -y \
    curl \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20 (required for Baileys)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Create user for security
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

# Set working directory
WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Copy logging configuration
COPY logging.conf /app/logging.conf

# Install Node.js dependencies for WhatsApp Bridge
WORKDIR /app/whatsapp_bridge
RUN npm ci --only=production
WORKDIR /app

# Create necessary directories with proper permissions
RUN mkdir -p /app/whatsapp_sessions /app/logs \
    && chown -R appuser:appuser /app

# Switch to non-privileged user
USER appuser

# Copy startup script
COPY --chown=appuser:appuser docker/start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Expose ports
EXPOSE 9876

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:9876/health || exit 1

# Entry point
CMD ["/app/start.sh"]
