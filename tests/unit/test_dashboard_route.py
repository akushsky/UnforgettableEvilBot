"""Unit tests for dashboard route in app/api/dashboard.py."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    """Create TestClient for the main app."""
    return TestClient(app)


def _mock_db_session(mock_db):
    """Helper: return a context manager that yields mock_db."""

    @contextmanager
    def _cm():
        yield mock_db

    return _cm


class TestMainDashboard:
    """Tests for GET / dashboard route."""

    @patch("app.database.connection.health_check_database")
    @patch("app.api.dashboard.trace_manager")
    @patch("app.api.dashboard.get_db_session")
    def test_dashboard_returns_html(
        self, mock_get_db_session, mock_trace_manager, mock_health_check, client
    ):
        """Test dashboard returns HTML with mocked DB calls."""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.fetchall.return_value = []

        mock_db = MagicMock()
        mock_db.execute.return_value = mock_result

        mock_get_db_session.side_effect = [
            _mock_db_session(mock_db)(),
            _mock_db_session(mock_db)(),
        ]

        mock_trace_manager.create_trace.return_value = MagicMock(trace_id="trace-1")
        mock_trace_manager.create_span.return_value = MagicMock(span_id="span-1")
        mock_health_check.return_value = {
            "status": "healthy",
            "pool_info": {},
            "response_time_ms": 1,
        }

        response = client.get("/")

        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        mock_get_db_session.assert_called()
        mock_health_check.assert_called_once()

    @patch("app.api.dashboard.get_db_session")
    def test_dashboard_handles_db_error(self, mock_get_db_session, client):
        """Test dashboard handles DB error and returns error template."""

        class _RaiseContext:
            def __enter__(self):
                raise Exception("Database connection failed")

            def __exit__(self, *args):
                pass

        mock_get_db_session.return_value = _RaiseContext()

        response = client.get("/")

        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        assert "Database connection failed" in response.text

    @patch("app.database.connection.health_check_database")
    @patch("app.api.dashboard.trace_manager")
    @patch("app.api.dashboard.get_db_session")
    def test_dashboard_includes_stats_in_response(
        self, mock_get_db_session, mock_trace_manager, mock_health_check, client
    ):
        """Test dashboard includes stats from database in rendered template."""
        mock_result = MagicMock()
        mock_result.scalar.side_effect = [10, 5, 3, 100, 2]
        mock_result.fetchall.return_value = []

        mock_db = MagicMock()
        mock_db.execute.return_value = mock_result

        mock_get_db_session.side_effect = [
            _mock_db_session(mock_db)(),
            _mock_db_session(mock_db)(),
        ]
        mock_trace_manager.create_trace.return_value = MagicMock(trace_id="t1")
        mock_trace_manager.create_span.return_value = MagicMock(span_id="s1")
        mock_health_check.return_value = {"status": "healthy", "pool_info": {}}

        response = client.get("/")

        assert response.status_code == 200
        assert "10" in response.text
