#!/bin/bash
set -e

echo "🚀 Starting WhatsApp Digest System..."

# Function for logging
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1"
}

# Function for graceful shutdown
cleanup() {
    log "📛 Shutting down services..."
    kill -TERM "$BRIDGE_PID" 2>/dev/null || true
    kill -TERM "$API_PID" 2>/dev/null || true
    wait "$BRIDGE_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
    log "✅ Services stopped"
    exit 0
}

# Signal handler
trap cleanup SIGTERM SIGINT

# Test imports first
log "🔍 Testing imports..."
export PYTHONPATH=/app:$PYTHONPATH
python debug_imports.py

# Wait for database readiness
log "🔍 Checking database connection..."
export PYTHONPATH=/app:$PYTHONPATH
python -c "
import time
import sys
from app.database.connection import engine
from sqlalchemy import text

for i in range(30):
    try:
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        print('Database is ready!')
        break
    except Exception as e:
        print(f'Waiting for database... ({i+1}/30)')
        time.sleep(2)
else:
    print('Database connection failed!')
    sys.exit(1)
"

# Run migrations
log "🔄 Running database migrations..."
export PYTHONPATH=/app:$PYTHONPATH
alembic upgrade head

# Create directories if they don't exist
mkdir -p /app/whatsapp_sessions
mkdir -p /app/logs

# Start WhatsApp Bridge in background
log "🌉 Starting WhatsApp Bridge..."
cd /app/whatsapp_bridge
node persistent_bridge.js > /app/logs/bridge.log 2>&1 &
BRIDGE_PID=$!
cd /app

# Wait for Bridge readiness
log "⏳ Waiting for WhatsApp Bridge to be ready..."
for i in {1..30}; do
    if curl -sf http://localhost:3000/health > /dev/null 2>&1; then
        log "✅ WhatsApp Bridge is ready!"
        break
    fi
    sleep 2
    if [ $i -eq 30 ]; then
        log "❌ WhatsApp Bridge failed to start"
        exit 1
    fi
done

# Start auto-reconnection recovery
log "🔄 Initiating auto-reconnection..."
curl -X POST http://localhost:3000/restore-all > /dev/null 2>&1 || true

# Start FastAPI application
log "🐍 Starting FastAPI application..."
export PYTHONPATH=/app:$PYTHONPATH
uvicorn main:app --host 0.0.0.0 --port ${PORT:-9876} --reload --log-config /app/logging.conf > /app/logs/api.log 2>&1 &
API_PID=$!

# Wait for API readiness
log "⏳ Waiting for FastAPI to be ready..."
for i in {1..30}; do
    if curl -sf http://localhost:${PORT:-9876}/health > /dev/null 2>&1; then
        log "✅ FastAPI is ready!"
        break
    fi
    sleep 2
    if [ $i -eq 30 ]; then
        log "❌ FastAPI failed to start"
        exit 1
    fi
done

log "🎉 All services are running!"
log "📊 FastAPI: http://localhost:${PORT:-9876}"
log "🌉 Bridge: http://localhost:3000"
log "📋 Admin Panel: http://localhost:${PORT:-9876}/admin"

# Monitor processes
while true; do
    # Check if processes are alive
    if ! kill -0 "$BRIDGE_PID" 2>/dev/null; then
        log "❌ WhatsApp Bridge died, restarting..."
        cd /app/whatsapp_bridge
        node persistent_bridge.js > /app/logs/bridge.log 2>&1 &
        BRIDGE_PID=$!
        cd /app
        sleep 10
        curl -X POST http://localhost:3000/restore-all > /dev/null 2>&1 || true
    fi

    if ! kill -0 "$API_PID" 2>/dev/null; then
        log "❌ FastAPI died, restarting..."
        export PYTHONPATH=/app:$PYTHONPATH
        uvicorn main:app --host 0.0.0.0 --port ${PORT:-9876} --reload --log-config /app/logging.conf > /app/logs/api.log 2>&1 &
        API_PID=$!
    fi

    sleep 30
done
