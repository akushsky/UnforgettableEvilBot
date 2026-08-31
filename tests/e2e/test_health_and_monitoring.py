"""E2E tests for health and monitoring endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.e2e
def test_health_endpoint(client):
    """GET /health returns JSON with status and checks."""
    with patch("app.api.health.get_telegram_service") as mock_get_telegram:
        mock_telegram = MagicMock()
        mock_telegram.check_bot_health = AsyncMock(return_value=True)
        mock_get_telegram.return_value = mock_telegram

        response = client.get("/health")
    assert response.status_code in (200, 503)
    data = response.json()
    assert "status" in data
    assert "checks" in data
    assert data["status"] in ("healthy", "degraded", "unhealthy")


@pytest.mark.e2e
def test_metrics_endpoint(authenticated_client):
    """GET /metrics returns JSON with system metrics (admin-auth required)."""
    with patch("app.api.monitoring.get_telegram_service") as mock_get_telegram:
        mock_telegram = MagicMock()
        mock_telegram.check_bot_health = AsyncMock(return_value=True)
        mock_get_telegram.return_value = mock_telegram

        response = authenticated_client.get("/metrics")
    assert response.status_code == 200
    data = response.json()
    assert "metrics" in data
    assert "timestamp" in data
    assert "users" in data["metrics"] or "performance" in data["metrics"]
