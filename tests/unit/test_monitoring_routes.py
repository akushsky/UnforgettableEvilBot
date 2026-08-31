"""Unit tests for monitoring routes in app/api/monitoring.py."""

from contextlib import contextmanager
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth.admin_auth import get_admin_auth_dependency
from main import app


@pytest.fixture
def client():
    """Create TestClient for monitoring routes with admin auth satisfied."""
    app.dependency_overrides[get_admin_auth_dependency] = lambda: True
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_metrics_route_requires_authentication():
    """Test that /metrics redirects to login without an admin session."""
    with TestClient(app, follow_redirects=False) as unauthenticated_client:
        response = unauthenticated_client.get("/metrics")

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


@patch("app.api.monitoring.process_start_time", 0)
@patch("app.api.monitoring.psutil")
@patch("app.api.monitoring.openai_monitor")
@patch("app.api.monitoring.metrics_collector")
@patch("app.api.monitoring.cache_manager")
@patch("app.api.monitoring.health_check_database")
@patch("app.api.monitoring.get_db_stats")
@patch("app.api.monitoring.get_db_session")
@patch("app.api.monitoring.trace_manager")
@patch("app.api.monitoring.check_system_health")
@patch("app.api.monitoring.alert_manager")
@patch("app.api.monitoring.check_telegram_availability", new_callable=AsyncMock)
def test_get_metrics_returns_json(
    mock_telegram,
    mock_alert_mgr,
    mock_check_health,
    mock_trace,
    mock_get_db_session,
    mock_db_stats,
    mock_health_db,
    mock_cache,
    mock_metrics,
    mock_openai,
    mock_psutil,
    client,
):
    """Test GET /metrics returns JSON with system metrics."""
    mock_db = Mock()
    mock_db.execute.return_value.scalar.side_effect = [5, 3, 10, 100, 2]

    @contextmanager
    def _cm():
        yield mock_db

    mock_get_db_session.side_effect = [_cm()]

    mock_trace.create_trace.return_value = Mock(trace_id="t1")
    mock_trace.create_span.return_value = Mock(span_id="s1")

    mock_psutil.Process.return_value.create_time.return_value = 0
    mock_psutil.cpu_percent.return_value = 10.0
    mock_psutil.virtual_memory.return_value = Mock(percent=50.0)
    mock_psutil.Process.return_value.memory_info.return_value.rss = 100 * 1024 * 1024

    mock_db_stats.return_value = {
        "avg_query_time": 0.02,
        "total_queries": 10,
        "slow_queries": 0,
    }
    mock_health_db.return_value = {"pool_info": {"pool_size": 5, "checked_out": 2}}
    mock_cache.get_stats.return_value = {
        "memory_cache_size": 100,
        "redis_available": False,
    }
    mock_metrics.get_cache_stats.return_value = {
        "memory_hit_ratio": 0.9,
        "redis_hit_ratio": 0,
    }
    mock_metrics.get_stats.return_value = {"avg_response_time": 0.3}
    mock_openai.get_stats.return_value = {
        "total_requests": 50,
        "total_cost_usd": 1.0,
        "success_rate": 0.95,
        "recent_24h": 10,
        "last_request_time": "2024-01-01T00:00:00",
        "avg_tokens_per_request": 100,
        "cost_24h": 0.1,
        "recent_requests": [],
        "models_usage": {},
        "recent_errors": 0,
    }
    mock_alert_mgr.get_active_alerts.return_value = []
    mock_telegram.return_value = True

    response = client.get("/metrics")

    assert response.status_code == 200
    data = response.json()
    assert "metrics" in data
    assert "timestamp" in data
    assert "users" in data["metrics"]
    assert "performance" in data["metrics"]
    assert "openai" in data["metrics"]
    assert "cache_hit_ratio" not in mock_check_health.call_args[0][0]
    assert data["metrics"]["performance"]["cache"]["memory_hit_ratio"] == 0.9
