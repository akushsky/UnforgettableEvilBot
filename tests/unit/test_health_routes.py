"""Unit tests for health routes in app/api/health.py."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    """Create TestClient for the main app."""
    return TestClient(app)


def _mock_db_cm(mock_db):
    """Helper: return a context manager that yields mock_db."""

    @contextmanager
    def _cm():
        yield mock_db

    return _cm


class TestHealthCheck:
    """Tests for GET /health route."""

    @patch("app.api.health.openai_monitor")
    @patch("app.api.health.settings")
    @patch("app.api.health.cache_manager")
    @patch("app.api.health.psutil")
    @patch("app.api.health.health_check_database")
    def test_health_returns_200_when_healthy(
        self,
        mock_health_db,
        mock_psutil,
        mock_cache,
        mock_settings,
        mock_openai_monitor,
        client,
    ):
        """Test health endpoint returns 200 when all checks pass."""
        mock_settings.TESTING = True
        mock_settings.USE_OPTIMIZED_REPOSITORIES = False

        mock_health_db.return_value = {
            "status": "healthy",
            "pool_info": {},
            "response_time_ms": 5,
        }

        mock_psutil.cpu_percent.return_value = 50
        mock_psutil.virtual_memory.return_value = MagicMock(percent=60)
        mock_psutil.disk_usage.return_value = MagicMock(percent=40)
        mock_process = MagicMock()
        mock_process.memory_info.return_value = MagicMock(rss=1000000)
        mock_process.cpu_percent.return_value = 1.0
        mock_psutil.Process.return_value = mock_process
        mock_psutil.getloadavg = lambda: (1.0, 1.0, 1.0)

        mock_cache.get_stats.return_value = {
            "redis_available": True,
            "memory_hit_ratio": 0.8,
            "memory_cache_size": 100,
            "redis_hit_ratio": 0.7,
        }

        mock_openai_monitor.get_stats.return_value = {
            "success_rate": 1.0,
            "recent_errors": 0,
            "total_requests": 0,
        }

        with patch("app.api.health.get_db_session") as mock_get_db:
            mock_db = MagicMock()
            mock_db.execute.return_value.scalar.side_effect = [10, 5, 3]
            mock_get_db.side_effect = [_mock_db_cm(mock_db)(), _mock_db_cm(mock_db)()]

            response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "checks" in data
        assert "database" in data["checks"]

    @patch("app.api.health.settings")
    @patch("app.api.health.cache_manager")
    @patch("app.api.health.psutil")
    @patch("app.api.health.health_check_database")
    def test_health_includes_database_check(
        self, mock_health_db, mock_psutil, mock_cache, mock_settings, client
    ):
        """Test health response includes database check."""
        mock_settings.TESTING = True
        mock_settings.USE_OPTIMIZED_REPOSITORIES = False

        mock_health_db.return_value = {
            "status": "healthy",
            "pool_info": {"pool_size": 20},
            "response_time_ms": 2,
        }

        mock_psutil.cpu_percent.return_value = 10
        mock_psutil.virtual_memory.return_value = MagicMock(percent=50)
        mock_psutil.disk_usage.return_value = MagicMock(percent=30)
        mock_process = MagicMock()
        mock_process.memory_info.return_value = MagicMock(rss=500000)
        mock_process.cpu_percent.return_value = 0.5
        mock_psutil.Process.return_value = mock_process
        mock_psutil.getloadavg = lambda: (0.5, 0.5, 0.5)

        mock_cache.get_stats.return_value = {
            "redis_available": False,
            "memory_hit_ratio": 0.9,
            "memory_cache_size": 50,
        }

        with patch("app.api.health.get_db_session") as mock_get_db:
            mock_db = MagicMock()
            mock_db.execute.return_value.scalar.side_effect = [0, 0, 0]
            mock_get_db.side_effect = [_mock_db_cm(mock_db)(), _mock_db_cm(mock_db)()]

            response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["checks"]["database"]["status"] == "healthy"
        assert data["checks"]["database"]["pool_info"] == {"pool_size": 20}
        assert data["checks"]["database"]["response_time_ms"] == 2

    @patch("app.api.health.settings")
    @patch("app.api.health.cache_manager")
    @patch("app.api.health.psutil")
    @patch("app.api.health.health_check_database")
    def test_health_includes_system_info(
        self, mock_health_db, mock_psutil, mock_cache, mock_settings, client
    ):
        """Test health response includes system info (CPU, memory, disk)."""
        mock_settings.TESTING = True
        mock_settings.USE_OPTIMIZED_REPOSITORIES = False

        mock_health_db.return_value = {
            "status": "healthy",
            "pool_info": {},
            "response_time_ms": 0,
        }

        mock_psutil.cpu_percent.return_value = 25
        mock_psutil.virtual_memory.return_value = MagicMock(percent=45)
        mock_psutil.disk_usage.return_value = MagicMock(percent=55)
        mock_process = MagicMock()
        mock_process.memory_info.return_value = MagicMock(rss=2 * 1024 * 1024)
        mock_process.cpu_percent.return_value = 2.0
        mock_psutil.Process.return_value = mock_process
        mock_psutil.getloadavg = lambda: (1.5, 1.2, 1.0)

        mock_cache.get_stats.return_value = {
            "redis_available": True,
            "memory_hit_ratio": 0.75,
            "memory_cache_size": 80,
        }

        with patch("app.api.health.get_db_session") as mock_get_db:
            mock_db = MagicMock()
            mock_db.execute.return_value.scalar.side_effect = [0, 0, 0]
            mock_get_db.side_effect = [_mock_db_cm(mock_db)(), _mock_db_cm(mock_db)()]

            response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert "system" in data["checks"]
        sys_check = data["checks"]["system"]
        assert sys_check["cpu_usage_percent"] == 25
        assert sys_check["memory_usage_percent"] == 45
        assert sys_check["disk_usage_percent"] == 55
        assert "process_memory_mb" in sys_check

    @patch("app.api.health.settings")
    @patch("app.api.health.cache_manager")
    @patch("app.api.health.psutil")
    @patch("app.api.health.health_check_database")
    def test_health_returns_503_when_database_unhealthy(
        self, mock_health_db, mock_psutil, mock_cache, mock_settings, client
    ):
        """Test health returns 503 when database is unhealthy."""
        mock_settings.TESTING = True
        mock_settings.USE_OPTIMIZED_REPOSITORIES = False

        mock_health_db.return_value = {
            "status": "unhealthy",
            "pool_info": {},
            "error": "Connection refused",
        }

        mock_psutil.cpu_percent.return_value = 10
        mock_psutil.virtual_memory.return_value = MagicMock(percent=50)
        mock_psutil.disk_usage.return_value = MagicMock(percent=30)
        mock_process = MagicMock()
        mock_process.memory_info.return_value = MagicMock(rss=500000)
        mock_process.cpu_percent.return_value = 0.5
        mock_psutil.Process.return_value = mock_process
        mock_psutil.getloadavg = lambda: (0.5, 0.5, 0.5)

        mock_cache.get_stats.return_value = {
            "redis_available": False,
            "memory_hit_ratio": 0.9,
        }

        with patch("app.api.health.get_db_session") as mock_get_db:
            mock_db = MagicMock()
            mock_db.execute.return_value.scalar.side_effect = [0, 0, 0]
            mock_get_db.side_effect = [_mock_db_cm(mock_db)(), _mock_db_cm(mock_db)()]

            response = client.get("/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert "Connection refused" in str(data.get("summary", {}).get("errors", []))

    @patch("app.api.health.settings")
    @patch("app.api.health.cache_manager")
    @patch("app.api.health.psutil")
    @patch("app.api.health.health_check_database")
    def test_health_includes_cache_check(
        self, mock_health_db, mock_psutil, mock_cache, mock_settings, client
    ):
        """Test health response includes cache/redis check."""
        mock_settings.TESTING = True
        mock_settings.USE_OPTIMIZED_REPOSITORIES = False

        mock_health_db.return_value = {
            "status": "healthy",
            "pool_info": {},
            "response_time_ms": 0,
        }

        mock_psutil.cpu_percent.return_value = 10
        mock_psutil.virtual_memory.return_value = MagicMock(percent=50)
        mock_psutil.disk_usage.return_value = MagicMock(percent=30)
        mock_process = MagicMock()
        mock_process.memory_info.return_value = MagicMock(rss=500000)
        mock_process.cpu_percent.return_value = 0.5
        mock_psutil.Process.return_value = mock_process
        mock_psutil.getloadavg = lambda: (0.5, 0.5, 0.5)

        mock_cache.get_stats.return_value = {
            "redis_available": True,
            "memory_hit_ratio": 0.85,
            "memory_cache_size": 200,
            "redis_hit_ratio": 0.9,
        }

        with patch("app.api.health.get_db_session") as mock_get_db:
            mock_db = MagicMock()
            mock_db.execute.return_value.scalar.side_effect = [0, 0, 0]
            mock_get_db.side_effect = [_mock_db_cm(mock_db)(), _mock_db_cm(mock_db)()]

            response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert "cache" in data["checks"]
        cache_check = data["checks"]["cache"]
        assert cache_check["redis_available"] is True
        assert cache_check["memory_hit_ratio"] == 0.85
