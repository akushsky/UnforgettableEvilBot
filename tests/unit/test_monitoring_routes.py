"""Unit tests for monitoring routes in app/api/monitoring.py."""

from contextlib import contextmanager
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    """Create TestClient for monitoring routes."""
    with TestClient(app) as test_client:
        yield test_client


@patch("app.api.monitoring.process_start_time", 0)
@patch("app.core.resource_savings.resource_savings_service")
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
    mock_rs_service,
    client,
):
    """Test GET /metrics returns JSON with system metrics."""
    mock_db = Mock()
    mock_db.execute.return_value.scalar.side_effect = [5, 3, 10, 100, 2]

    @contextmanager
    def _cm():
        yield mock_db

    mock_get_db_session.side_effect = [_cm(), _cm()]

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

    mock_rs_service.get_total_savings.return_value = {
        "total_whatsapp_connections_saved": 0,
        "total_messages_processed_saved": 0,
        "total_openai_requests_saved": 0,
        "total_memory_mb_saved": 0.0,
        "total_cpu_seconds_saved": 0.0,
        "total_openai_cost_saved_usd": 0.0,
        "period_days": 30,
        "records_count": 0,
    }
    mock_rs_service.get_current_system_savings.return_value = {
        "current_memory_usage_mb": 0.0,
        "current_cpu_usage_percent": 0.0,
        "estimated_memory_saved_mb": 0.0,
        "estimated_cpu_saved_percent": 0.0,
        "timestamp": "2024-01-01T00:00:00",
    }

    response = client.get("/metrics")

    assert response.status_code == 200
    data = response.json()
    assert "metrics" in data
    assert "timestamp" in data
    assert "users" in data["metrics"]
    assert "performance" in data["metrics"]


@patch("app.api.monitoring.trace_manager")
def test_get_traces_returns_list(mock_trace, client):
    """Test GET /monitoring/traces returns trace list."""
    mock_trace.get_recent_traces.return_value = [{"trace_id": "t1", "spans": []}]
    mock_trace.active_traces = {}
    mock_trace.completed_traces = []

    response = client.get("/monitoring/traces")

    assert response.status_code == 200
    data = response.json()
    assert "traces" in data
    assert isinstance(data["traces"], list)


@patch("app.api.monitoring.get_system_alerts")
def test_get_alerts_returns_alerts(mock_get_alerts, client):
    """Test GET /monitoring/alerts returns alerts."""
    mock_get_alerts.return_value = {
        "total_alerts": 2,
        "active_alerts": 1,
        "alerts_by_severity": {"info": 0, "warning": 1, "error": 0, "critical": 0},
        "recent_alerts": [{"id": "a1", "title": "Test", "severity": "warning"}],
    }

    response = client.get("/monitoring/alerts")

    assert response.status_code == 200
    data = response.json()
    assert data["total_alerts"] == 2
    assert "recent_alerts" in data


@patch("app.api.monitoring.clear_all_alerts")
def test_clear_alerts(mock_clear, client):
    """Test POST /monitoring/alerts/clear clears all alerts."""
    response = client.post("/monitoring/alerts/clear")

    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "cleared" in data["message"].lower()
    mock_clear.assert_called_once()


@patch("app.api.monitoring.alert_manager")
def test_acknowledge_alert(mock_alert_mgr, client):
    """Test POST /monitoring/alerts/{alert_id}/acknowledge acknowledges alert."""
    response = client.post(
        "/monitoring/alerts/alert-123/acknowledge",
        params={"user": "admin"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "acknowledged" in data["message"].lower()
    mock_alert_mgr.acknowledge_alert.assert_called_once_with("alert-123", "admin")


@patch("app.api.monitoring.alert_manager")
def test_resolve_alert(mock_alert_mgr, client):
    """Test POST /monitoring/alerts/{alert_id}/resolve resolves alert."""
    response = client.post("/monitoring/alerts/alert-123/resolve")

    assert response.status_code == 200
    data = response.json()
    assert "resolved" in data["message"].lower()
    mock_alert_mgr.resolve_alert.assert_called_once_with("alert-123")


@patch("app.api.monitoring.check_system_health")
def test_trigger_health_check(mock_check_health, client):
    """Test POST /monitoring/health-check triggers health check."""
    mock_check_health.return_value = []

    response = client.post("/monitoring/health-check")

    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "Health check completed" in data["message"]
    mock_check_health.assert_called_once()


def test_monitoring_dashboard_returns_html(client):
    """Test GET /monitoring/dashboard returns HTML."""
    response = client.get("/monitoring/dashboard")

    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


@patch("app.api.monitoring.openai_monitor")
def test_get_openai_stats(mock_openai, client):
    """Test GET /monitoring/openai returns OpenAI stats."""
    mock_openai.get_stats.return_value = {
        "total_requests": 100,
        "total_cost_usd": 2.5,
        "success_rate": 0.98,
    }

    response = client.get("/monitoring/openai")

    assert response.status_code == 200
    data = response.json()
    assert "openai" in data
    assert data["openai"]["total_requests"] == 100
    assert "timestamp" in data


@patch("app.api.monitoring.trace_manager")
def test_export_trace(mock_trace, client):
    """Test GET /monitoring/traces/{trace_id}/export exports trace as JSON."""
    mock_trace.export_trace.return_value = '{"trace_id": "t1", "spans": []}'

    response = client.get("/monitoring/traces/trace-123/export")

    assert response.status_code == 200
    assert response.headers.get("content-disposition", "").startswith("attachment")
    assert "application/json" in response.headers.get("content-type", "")
    mock_trace.export_trace.assert_called_once_with("trace-123")


@patch("app.api.monitoring.trace_manager")
def test_get_trace_detail(mock_trace, client):
    """Test GET /monitoring/traces/{trace_id} returns trace detail."""
    mock_trace.get_trace_summary.return_value = {
        "trace_id": "t1",
        "spans": [],
        "duration_ms": 100,
    }

    response = client.get("/monitoring/traces/trace-123")

    assert response.status_code == 200
    data = response.json()
    assert data["trace_id"] == "t1"


@patch("app.api.monitoring.optimize_database")
def test_optimize_performance(mock_optimize, client):
    """Test GET /performance/optimize runs database optimization."""
    response = client.get("/performance/optimize")

    assert response.status_code == 200
    data = response.json()
    assert (
        "optimization" in data["message"].lower()
        or "optimize" in data["message"].lower()
    )
    mock_optimize.assert_called_once()
