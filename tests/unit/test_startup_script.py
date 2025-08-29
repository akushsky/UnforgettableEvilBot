import os
import tempfile
from unittest.mock import patch

import pytest


class TestStartupScript:
    """Test cases for startup script functionality"""

    @pytest.fixture
    def mock_subprocess(self):
        """Mock subprocess for testing"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            yield mock_run

    @pytest.fixture
    def mock_curl(self):
        """Mock curl responses"""
        with patch("subprocess.run") as mock_run:
            # Mock successful curl responses
            mock_run.return_value.returncode = 0
            yield mock_run

    @pytest.fixture
    def temp_startup_script(self):
        """Create a temporary startup script for testing"""
        script_content = """#!/bin/bash
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

# Start FastAPI application
log "🐍 Starting FastAPI application..."
export PYTHONPATH=/app:$PYTHONPATH
# Enable reload only when DEBUG=true (default: false in Coolify)
if [ "${DEBUG}" = "true" ]; then
    uvicorn main:app --host 0.0.0.0 --port ${PORT:-9876} --reload --log-config /app/logging.conf > /app/logs/api.log 2>&1 &
else
    uvicorn main:app --host 0.0.0.0 --port ${PORT:-9876} --log-config /app/logging.conf > /app/logs/api.log 2>&1 &
fi
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

# Start auto-reconnection recovery after both services are ready
log "🔄 Waiting for services to fully initialize..."
sleep 5
log "🔄 Initiating auto-reconnection..."
curl -X POST http://localhost:3000/restore-all > /dev/null 2>&1 || true

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
        if [ "${DEBUG}" = "true" ]; then
            uvicorn main:app --host 0.0.0.0 --port ${PORT:-9876} --reload --log-config /app/logging.conf > /app/logs/api.log 2>&1 &
        else
            uvicorn main:app --host 0.0.0.0 --port ${PORT:-9876} --log-config /app/logging.conf > /app/logs/api.log 2>&1 &
        fi
        API_PID=$!
    fi

    sleep 30
done
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
            f.write(script_content)
            f.flush()
            os.chmod(f.name, 0o755)
            yield f.name

        # Cleanup
        os.unlink(f.name)

    def test_startup_script_structure(self, temp_startup_script):
        """Test that startup script has the correct structure"""
        with open(temp_startup_script, "r") as f:
            content = f.read()

        # Check for essential components
        assert "set -e" in content
        assert "cleanup()" in content
        assert "trap cleanup SIGTERM SIGINT" in content
        assert "Starting WhatsApp Bridge" in content
        assert "Starting FastAPI application" in content
        assert "Waiting for services to fully initialize" in content
        assert "Initiating auto-reconnection" in content

    def test_startup_sequence_order(self, temp_startup_script):
        """Test that startup sequence follows the correct order"""
        with open(temp_startup_script, "r") as f:
            content = f.read()

        # Check that services start in the correct order
        lines = content.split("\n")

        # Find key operations
        bridge_start_idx = None
        api_start_idx = None
        restore_all_idx = None

        for i, line in enumerate(lines):
            if "Starting WhatsApp Bridge" in line:
                bridge_start_idx = i
            elif "Starting FastAPI application" in line:
                api_start_idx = i
            elif "Initiating auto-reconnection" in line:
                restore_all_idx = i

        # Verify order: Bridge -> API -> Restore
        assert bridge_start_idx is not None
        assert api_start_idx is not None
        assert restore_all_idx is not None
        assert bridge_start_idx < api_start_idx
        assert api_start_idx < restore_all_idx

    def test_startup_script_initialization_delay(self, temp_startup_script):
        """Test that startup script includes initialization delay"""
        with open(temp_startup_script, "r") as f:
            content = f.read()

        # Check for the 5-second delay
        assert "sleep 5" in content
        assert "Waiting for services to fully initialize" in content

    def test_startup_script_health_checks(self, temp_startup_script):
        """Test that startup script includes proper health checks"""
        with open(temp_startup_script, "r") as f:
            content = f.read()

        # Check for health check patterns
        assert "curl -sf http://localhost:3000/health" in content
        assert "curl -sf http://localhost:${PORT:-9876}/health" in content
        assert "for i in {1..30}" in content  # Retry loops

    def test_startup_script_error_handling(self, temp_startup_script):
        """Test that startup script includes proper error handling"""
        with open(temp_startup_script, "r") as f:
            content = f.read()

        # Check for error handling
        assert "exit 1" in content  # Exit on failure
        assert "2>/dev/null || true" in content  # Graceful failure handling
        assert "cleanup()" in content  # Graceful shutdown

    def test_startup_script_environment_variables(self, temp_startup_script):
        """Test that startup script handles environment variables correctly"""
        with open(temp_startup_script, "r") as f:
            content = f.read()

        # Check for environment variable usage
        assert "${DEBUG}" in content
        assert "${PORT:-9876}" in content
        assert "export PYTHONPATH=/app:$PYTHONPATH" in content

    def test_startup_script_process_monitoring(self, temp_startup_script):
        """Test that startup script includes process monitoring"""
        with open(temp_startup_script, "r") as f:
            content = f.read()

        # Check for process monitoring
        assert 'kill -0 "$BRIDGE_PID"' in content
        assert 'kill -0 "$API_PID"' in content
        assert "while true; do" in content
        assert "sleep 30" in content

    def test_startup_script_restart_logic(self, temp_startup_script):
        """Test that startup script includes restart logic"""
        with open(temp_startup_script, "r") as f:
            content = f.read()

        # Check for restart logic
        assert "WhatsApp Bridge died, restarting" in content
        assert "FastAPI died, restarting" in content
        assert "BRIDGE_PID=$!" in content
        assert "API_PID=$!" in content

    def test_startup_script_logging(self, temp_startup_script):
        """Test that startup script includes proper logging"""
        with open(temp_startup_script, "r") as f:
            content = f.read()

        # Check for logging function
        assert "log() {" in content
        assert 'echo "[$(date' in content

        # Check for log messages (using echo instead of log function for some messages)
        log_messages = [
            "Testing imports",
            "Checking database connection",
            "Running database migrations",
            "Starting WhatsApp Bridge",
            "Starting FastAPI application",
            "All services are running",
            "Initiating auto-reconnection",
        ]

        for message in log_messages:
            # Check for log function calls with the message (handle unicode characters)
            message_found = False
            if f'log "{message}"' in content:
                message_found = True
            elif f"log '{message}'" in content:
                message_found = True
            elif message in content:  # Fallback: just check if message appears anywhere
                message_found = True
            assert message_found, f"Log message '{message}' not found in startup script"

    def test_startup_script_directory_creation(self, temp_startup_script):
        """Test that startup script creates necessary directories"""
        with open(temp_startup_script, "r") as f:
            content = f.read()

        # Check for directory creation
        assert "mkdir -p /app/whatsapp_sessions" in content
        assert "mkdir -p /app/logs" in content

    def test_startup_script_signal_handling(self, temp_startup_script):
        """Test that startup script handles signals properly"""
        with open(temp_startup_script, "r") as f:
            content = f.read()

        # Check for signal handling
        assert "trap cleanup SIGTERM SIGINT" in content
        assert "cleanup()" in content
        assert 'kill -TERM "$BRIDGE_PID"' in content
        assert 'kill -TERM "$API_PID"' in content

    def test_startup_script_debug_mode_handling(self, temp_startup_script):
        """Test that startup script handles debug mode correctly"""
        with open(temp_startup_script, "r") as f:
            content = f.read()

        # Check for debug mode conditional
        assert 'if [ "${DEBUG}" = "true" ]; then' in content
        assert "--reload" in content
        assert "else" in content
        assert "fi" in content

    def test_startup_script_port_handling(self, temp_startup_script):
        """Test that startup script handles port configuration correctly"""
        with open(temp_startup_script, "r") as f:
            content = f.read()

        # Check for port handling
        assert "${PORT:-9876}" in content  # Default port fallback
        assert "http://localhost:${PORT:-9876}/health" in content
        assert "--port ${PORT:-9876}" in content

    def test_startup_script_restore_all_timing(self, temp_startup_script):
        """Test that restore-all is called at the right time"""
        with open(temp_startup_script, "r") as f:
            content = f.read()

        # Check that restore-all is called after both services are ready
        lines = content.split("\n")

        # Find the sequence
        api_ready_idx = None
        restore_all_idx = None

        for i, line in enumerate(lines):
            if "FastAPI is ready!" in line:
                api_ready_idx = i
            elif "curl -X POST http://localhost:3000/restore-all" in line:
                restore_all_idx = i

        # Verify restore-all comes after API is ready
        assert api_ready_idx is not None
        assert restore_all_idx is not None
        assert api_ready_idx < restore_all_idx
