"""Tests for the production container entrypoint (`docker/start.sh`).

These assert against the real script on disk, so drift between the script and
the documented startup contract fails the suite instead of passing against a
stale copy embedded in the test.
"""

from pathlib import Path

import pytest

START_SCRIPT = Path(__file__).resolve().parents[2] / "docker" / "start.sh"


@pytest.fixture(scope="module")
def content() -> str:
    return START_SCRIPT.read_text(encoding="utf-8")


class TestStartupScript:
    def test_script_exists_and_is_executable(self):
        assert START_SCRIPT.is_file(), f"{START_SCRIPT} is missing"
        assert START_SCRIPT.stat().st_mode & 0o111, "start.sh must be executable"

    def test_structure(self, content):
        assert content.startswith("#!/bin/bash")
        assert "set -e" in content
        assert "cleanup()" in content
        assert "trap cleanup SIGTERM SIGINT" in content
        assert "Starting WhatsApp Bridge" in content
        assert "Starting FastAPI application" in content
        assert "Waiting for services to fully initialize" in content
        assert "Initiating auto-reconnection" in content

    def test_schema_is_applied_by_alembic_only(self, content):
        assert "alembic upgrade head" in content
        assert "create_all" not in content

    def test_startup_sequence_order(self, content):
        lines = content.split("\n")
        bridge_start_idx = api_start_idx = restore_all_idx = None

        for i, line in enumerate(lines):
            if "Starting WhatsApp Bridge" in line:
                bridge_start_idx = i
            elif "Starting FastAPI application" in line:
                api_start_idx = i
            elif "Initiating auto-reconnection" in line:
                restore_all_idx = i

        assert bridge_start_idx is not None
        assert api_start_idx is not None
        assert restore_all_idx is not None
        assert bridge_start_idx < api_start_idx < restore_all_idx

    def test_migrations_run_before_services_start(self, content):
        assert content.index("alembic upgrade head") < content.index("node bridge.js")

    def test_initialization_delay(self, content):
        assert "sleep 5" in content
        assert "Waiting for services to fully initialize" in content

    def test_health_checks(self, content):
        assert "curl -sf http://localhost:3000/health" in content
        assert "curl -sf http://localhost:${PORT:-9876}/health" in content
        assert "for i in {1..30}" in content

    def test_error_handling(self, content):
        assert "exit 1" in content
        assert "2>/dev/null || true" in content
        assert "cleanup()" in content

    def test_environment_variables(self, content):
        assert "${DEBUG}" in content
        assert "${PORT:-9876}" in content
        assert "export PYTHONPATH=/app:$PYTHONPATH" in content

    def test_session_path_is_configurable_and_defaults_to_volume(self, content):
        assert (
            'export WHATSAPP_SESSION_PATH="${WHATSAPP_SESSION_PATH:-/app/whatsapp_sessions}"'
            in content
        )
        assert 'mkdir -p "${WHATSAPP_SESSION_PATH}"' in content
        assert "mkdir -p /app/logs" in content

    def test_restore_is_triggered_by_supervisor_not_bridge_startup(self, content):
        assert 'export RESTORE_ON_START="${RESTORE_ON_START:-0}"' in content
        assert "curl -X POST http://localhost:3000/restore-all" in content

    def test_process_monitoring(self, content):
        assert 'kill -0 "$BRIDGE_PID"' in content
        assert 'kill -0 "$API_PID"' in content
        assert "while true; do" in content
        assert "sleep 30" in content

    def test_restart_logic(self, content):
        assert "WhatsApp Bridge died, restarting" in content
        assert "FastAPI died, restarting" in content
        assert "BRIDGE_PID=$!" in content
        assert "API_PID=$!" in content

    def test_logging(self, content):
        assert "log() {" in content
        assert 'echo "[$(date' in content

        for message in (
            "Checking database connection",
            "Running database migrations",
            "Starting WhatsApp Bridge",
            "Starting FastAPI application",
            "All services are running",
            "Initiating auto-reconnection",
        ):
            assert message in content, f"Log message '{message}' not found"

    def test_signal_handling(self, content):
        assert "trap cleanup SIGTERM SIGINT" in content
        assert 'kill -TERM "$BRIDGE_PID"' in content
        assert 'kill -TERM "$API_PID"' in content

    def test_debug_mode_handling(self, content):
        assert 'if [ "${DEBUG}" = "true" ]; then' in content
        assert "--reload" in content
        assert "python debug_imports.py" in content

    def test_port_handling(self, content):
        assert "http://localhost:${PORT:-9876}/health" in content
        assert "--port ${PORT:-9876}" in content

    def test_restore_all_runs_after_api_is_ready(self, content):
        lines = content.split("\n")
        api_ready_idx = restore_all_idx = None

        for i, line in enumerate(lines):
            if "FastAPI is ready!" in line:
                api_ready_idx = i
            elif "curl -X POST http://localhost:3000/restore-all" in line:
                restore_all_idx = i

        assert api_ready_idx is not None
        assert restore_all_idx is not None
        assert api_ready_idx < restore_all_idx
