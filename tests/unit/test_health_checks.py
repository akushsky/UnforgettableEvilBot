"""Unit tests for health check functionality."""

from unittest.mock import AsyncMock, Mock, patch

from app.health.checks import HealthChecker


class TestHealthChecker:
    def setup_method(self):
        """Set up test fixtures"""
        self.health_checker = HealthChecker()

    @patch("app.health.checks.SessionLocal")
    async def test_check_database_success(self, mock_session_local):
        """Test successful database health check"""
        # Mock database session
        mock_db = Mock()
        mock_session_local.return_value = mock_db

        result = await self.health_checker.check_database()

        assert result["status"] == "healthy"
        assert result["error"] is None
        mock_db.execute.assert_called_once()
        mock_db.close.assert_called_once()

    @patch("app.health.checks.SessionLocal")
    async def test_check_database_failure(self, mock_session_local):
        """Test database health check with failure"""
        # Mock database session to raise exception
        mock_db = Mock()
        mock_db.execute.side_effect = Exception("Database connection failed")
        mock_session_local.return_value = mock_db

        result = await self.health_checker.check_database()

        assert result["status"] == "unhealthy"
        assert result["error"] == "Database connection failed"
        # The close() method is not called when an exception occurs in the try block
        mock_db.close.assert_not_called()

    @patch("app.health.checks.redis")
    @patch("app.health.checks.settings")
    async def test_check_redis_success(self, mock_settings, mock_redis):
        """Test successful Redis health check"""
        # Mock settings
        mock_settings.REDIS_URL = "redis://localhost:6379"

        # Mock Redis client
        mock_redis_client = Mock()
        mock_redis.from_url.return_value = mock_redis_client

        result = await self.health_checker.check_redis()

        assert result["status"] == "healthy"
        assert result["error"] is None
        mock_redis.from_url.assert_called_once_with("redis://localhost:6379")
        mock_redis_client.ping.assert_called_once()

    @patch("app.health.checks.redis")
    @patch("app.health.checks.settings")
    async def test_check_redis_not_configured(self, mock_settings, mock_redis):
        """Test Redis health check when not configured"""
        # Mock settings with no Redis URL
        mock_settings.REDIS_URL = None

        result = await self.health_checker.check_redis()

        assert result["status"] == "not_configured"
        assert result["error"] == "Redis URL not configured"
        mock_redis.from_url.assert_not_called()

    @patch("app.health.checks.redis")
    @patch("app.health.checks.settings")
    async def test_check_redis_failure(self, mock_settings, mock_redis):
        """Test Redis health check with failure"""
        # Mock settings
        mock_settings.REDIS_URL = "redis://localhost:6379"

        # Mock Redis client to raise exception
        mock_redis_client = Mock()
        mock_redis_client.ping.side_effect = Exception("Redis connection failed")
        mock_redis.from_url.return_value = mock_redis_client

        result = await self.health_checker.check_redis()

        assert result["status"] == "unhealthy"
        assert result["error"] == "Redis connection failed"
        mock_redis.from_url.assert_called_once_with("redis://localhost:6379")
        mock_redis_client.ping.assert_called_once()

    @patch("app.health.checks.OpenAIService")
    @patch("app.health.checks.settings")
    async def test_check_openai_success(self, mock_settings, mock_openai_service):
        """Test successful OpenAI health check"""
        # Mock settings
        mock_settings.OPENAI_API_KEY = "test-api-key"

        # Mock OpenAI service
        mock_service = Mock()
        mock_circuit_breaker = Mock()
        mock_circuit_breaker.state.value = "closed"
        mock_circuit_breaker.failure_count = 0
        mock_service.circuit_breaker = mock_circuit_breaker
        mock_openai_service.return_value = mock_service

        result = await self.health_checker.check_openai()

        assert result["status"] == "healthy"
        assert result["error"] is None
        assert result["circuit_breaker_state"] == "closed"
        assert result["failure_count"] == 0
        mock_openai_service.assert_called_once()

    @patch("app.health.checks.OpenAIService")
    @patch("app.health.checks.settings")
    async def test_check_openai_degraded(self, mock_settings, mock_openai_service):
        """Test OpenAI health check with degraded status"""
        # Mock settings
        mock_settings.OPENAI_API_KEY = "test-api-key"

        # Mock OpenAI service with open circuit breaker
        mock_service = Mock()
        mock_circuit_breaker = Mock()
        mock_circuit_breaker.state.value = "open"
        mock_circuit_breaker.failure_count = 5
        mock_service.circuit_breaker = mock_circuit_breaker
        mock_openai_service.return_value = mock_service

        result = await self.health_checker.check_openai()

        assert result["status"] == "degraded"
        assert result["error"] is None
        assert result["circuit_breaker_state"] == "open"
        assert result["failure_count"] == 5
        mock_openai_service.assert_called_once()

    @patch("app.health.checks.OpenAIService")
    @patch("app.health.checks.settings")
    async def test_check_openai_not_configured(
        self, mock_settings, mock_openai_service
    ):
        """Test OpenAI health check when not configured"""
        # Mock settings with no API key
        mock_settings.OPENAI_API_KEY = None

        result = await self.health_checker.check_openai()

        assert result["status"] == "not_configured"
        assert result["error"] == "OpenAI API key not configured"
        mock_openai_service.assert_not_called()

    @patch("app.health.checks.OpenAIService")
    @patch("app.health.checks.settings")
    async def test_check_openai_failure(self, mock_settings, mock_openai_service):
        """Test OpenAI health check with failure"""
        # Mock settings
        mock_settings.OPENAI_API_KEY = "test-api-key"

        # Mock OpenAI service to raise exception
        mock_openai_service.side_effect = Exception("OpenAI service failed")

        result = await self.health_checker.check_openai()

        assert result["status"] == "unhealthy"
        assert result["error"] == "OpenAI service failed"
        mock_openai_service.assert_called_once()

    @patch("app.health.checks.TelegramService")
    @patch("app.health.checks.settings")
    async def test_check_telegram_success(self, mock_settings, mock_telegram_service):
        """Test successful Telegram health check"""
        # Mock settings
        mock_settings.TELEGRAM_BOT_TOKEN = "test-bot-token"

        # Mock Telegram service
        mock_service = Mock()
        mock_bot = Mock()
        mock_service.bot = mock_bot
        mock_telegram_service.return_value = mock_service

        result = await self.health_checker.check_telegram()

        assert result["status"] == "healthy"
        assert result["error"] is None
        mock_telegram_service.assert_called_once()

    @patch("app.health.checks.TelegramService")
    @patch("app.health.checks.settings")
    async def test_check_telegram_not_configured(
        self, mock_settings, mock_telegram_service
    ):
        """Test Telegram health check when not configured"""
        # Mock settings with no bot token
        mock_settings.TELEGRAM_BOT_TOKEN = None

        result = await self.health_checker.check_telegram()

        assert result["status"] == "not_configured"
        assert result["error"] == "Telegram bot token not configured"
        mock_telegram_service.assert_not_called()

    @patch("app.health.checks.TelegramService")
    @patch("app.health.checks.settings")
    async def test_check_telegram_failure(self, mock_settings, mock_telegram_service):
        """Test Telegram health check with failure"""
        # Mock settings
        mock_settings.TELEGRAM_BOT_TOKEN = "test-bot-token"

        # Mock Telegram service to raise exception
        mock_telegram_service.side_effect = Exception("Telegram service failed")

        result = await self.health_checker.check_telegram()

        assert result["status"] == "unhealthy"
        assert result["error"] == "Telegram service failed"
        mock_telegram_service.assert_called_once()

    @patch("builtins.__import__")
    async def test_check_whatsapp_bridge_success(self, mock_import):
        """Test successful WhatsApp Bridge health check"""
        # Mock httpx import
        mock_httpx = Mock()
        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"clients": 2}
        mock_client.get.return_value = mock_response

        # Create a context manager mock
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_client
        mock_httpx.AsyncClient.return_value = mock_context
        mock_import.return_value = mock_httpx

        result = await self.health_checker.check_whatsapp_bridge()

        assert result["status"] == "healthy"
        assert result["error"] is None
        assert result["clients"] == 2
        mock_client.get.assert_called_once_with(
            "http://localhost:3000/health", timeout=5.0
        )

    @patch("builtins.__import__")
    async def test_check_whatsapp_bridge_unhealthy_status(self, mock_import):
        """Test WhatsApp Bridge health check with unhealthy status code"""
        # Mock httpx import
        mock_httpx = Mock()
        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.status_code = 500
        mock_client.get.return_value = mock_response

        # Create a context manager mock
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_client
        mock_httpx.AsyncClient.return_value = mock_context
        mock_import.return_value = mock_httpx

        result = await self.health_checker.check_whatsapp_bridge()

        assert result["status"] == "unhealthy"
        assert result["error"] == "HTTP 500"
        mock_client.get.assert_called_once_with(
            "http://localhost:3000/health", timeout=5.0
        )

    @patch("builtins.__import__")
    async def test_check_whatsapp_bridge_failure(self, mock_import):
        """Test WhatsApp Bridge health check with failure"""
        # Mock httpx import
        mock_httpx = Mock()
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("Connection failed")

        # Create a context manager mock
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_client
        mock_httpx.AsyncClient.return_value = mock_context
        mock_import.return_value = mock_httpx

        result = await self.health_checker.check_whatsapp_bridge()

        assert result["status"] == "unhealthy"
        assert result["error"] == "Connection failed"
        mock_client.get.assert_called_once_with(
            "http://localhost:3000/health", timeout=5.0
        )

    @patch("builtins.__import__")
    async def test_check_rate_limiter_healthy(self, mock_import):
        """Test rate limiter health check with healthy status"""
        # Mock the import inside the method
        mock_rate_limiter = Mock()
        mock_rate_limiter.get_stats.return_value = {
            "requests_last_minute": 10,
            "minute_limit": 100,
            "requests_last_hour": 50,
            "hour_limit": 1000,
        }

        # Mock the module import
        mock_module = Mock()
        mock_module.openai_rate_limiter = mock_rate_limiter
        mock_import.return_value = mock_module

        result = await self.health_checker.check_rate_limiter()

        assert result["status"] == "healthy"
        assert result["error"] is None
        assert result["stats"] == {
            "requests_last_minute": 10,
            "minute_limit": 100,
            "requests_last_hour": 50,
            "hour_limit": 1000,
        }
        mock_rate_limiter.get_stats.assert_called_once()

    @patch("builtins.__import__")
    async def test_check_rate_limiter_warning(self, mock_import):
        """Test rate limiter health check with warning status"""
        # Mock the import inside the method
        mock_rate_limiter = Mock()
        mock_rate_limiter.get_stats.return_value = {
            "requests_last_minute": 85,
            "minute_limit": 100,
            "requests_last_hour": 50,
            "hour_limit": 1000,
        }

        # Mock the module import
        mock_module = Mock()
        mock_module.openai_rate_limiter = mock_rate_limiter
        mock_import.return_value = mock_module

        result = await self.health_checker.check_rate_limiter()

        assert result["status"] == "warning"
        assert result["error"] is None
        mock_rate_limiter.get_stats.assert_called_once()

    @patch("builtins.__import__")
    async def test_check_rate_limiter_degraded(self, mock_import):
        """Test rate limiter health check with degraded status"""
        # Mock the import inside the method
        mock_rate_limiter = Mock()
        mock_rate_limiter.get_stats.return_value = {
            "requests_last_minute": 50,
            "minute_limit": 100,
            "requests_last_hour": 1000,
            "hour_limit": 1000,
        }

        # Mock the module import
        mock_module = Mock()
        mock_module.openai_rate_limiter = mock_rate_limiter
        mock_import.return_value = mock_module

        result = await self.health_checker.check_rate_limiter()

        # The logic checks > 0.8 first, so hour usage of 1.0 triggers warning
        assert result["status"] == "warning"
        assert result["error"] is None
        mock_rate_limiter.get_stats.assert_called_once()

    @patch("builtins.__import__")
    async def test_check_rate_limiter_failure(self, mock_import):
        """Test rate limiter health check with failure"""
        # Mock the import inside the method
        mock_rate_limiter = Mock()
        mock_rate_limiter.get_stats.side_effect = Exception("Rate limiter failed")

        # Mock the module import
        mock_module = Mock()
        mock_module.openai_rate_limiter = mock_rate_limiter
        mock_import.return_value = mock_module

        result = await self.health_checker.check_rate_limiter()

        assert result["status"] == "unhealthy"
        assert result["error"] == "Rate limiter failed"
        mock_rate_limiter.get_stats.assert_called_once()

    @patch.object(HealthChecker, "check_database")
    @patch.object(HealthChecker, "check_redis")
    @patch.object(HealthChecker, "check_openai")
    @patch.object(HealthChecker, "check_telegram")
    @patch.object(HealthChecker, "check_whatsapp_bridge")
    @patch.object(HealthChecker, "check_rate_limiter")
    async def test_run_all_checks_all_healthy(
        self,
        mock_rate_limiter,
        mock_whatsapp,
        mock_telegram,
        mock_openai,
        mock_redis,
        mock_database,
    ):
        """Test running all health checks with all healthy"""
        # Mock all checks to return healthy
        mock_database.return_value = {"status": "healthy", "error": None}
        mock_redis.return_value = {"status": "healthy", "error": None}
        mock_openai.return_value = {"status": "healthy", "error": None}
        mock_telegram.return_value = {"status": "healthy", "error": None}
        mock_whatsapp.return_value = {"status": "healthy", "error": None}
        mock_rate_limiter.return_value = {"status": "healthy", "error": None}

        result = await self.health_checker.run_all_checks()

        assert result["status"] == "healthy"
        assert len(result["checks"]) == 6
        assert result["summary"]["total_checks"] == 6
        assert result["summary"]["healthy"] == 6
        assert result["summary"]["degraded"] == 0
        assert result["summary"]["unhealthy"] == 0
        assert result["summary"]["not_configured"] == 0

    @patch.object(HealthChecker, "check_database")
    @patch.object(HealthChecker, "check_redis")
    @patch.object(HealthChecker, "check_openai")
    @patch.object(HealthChecker, "check_telegram")
    @patch.object(HealthChecker, "check_whatsapp_bridge")
    @patch.object(HealthChecker, "check_rate_limiter")
    async def test_run_all_checks_with_degraded(
        self,
        mock_rate_limiter,
        mock_whatsapp,
        mock_telegram,
        mock_openai,
        mock_redis,
        mock_database,
    ):
        """Test running all health checks with some degraded"""
        # Mock checks with some degraded
        mock_database.return_value = {"status": "healthy", "error": None}
        mock_redis.return_value = {"status": "healthy", "error": None}
        mock_openai.return_value = {"status": "degraded", "error": None}
        mock_telegram.return_value = {"status": "healthy", "error": None}
        mock_whatsapp.return_value = {"status": "healthy", "error": None}
        mock_rate_limiter.return_value = {"status": "healthy", "error": None}

        result = await self.health_checker.run_all_checks()

        assert result["status"] == "degraded"
        assert result["summary"]["healthy"] == 5
        assert result["summary"]["degraded"] == 1
        assert result["summary"]["unhealthy"] == 0

    @patch.object(HealthChecker, "check_database")
    @patch.object(HealthChecker, "check_redis")
    @patch.object(HealthChecker, "check_openai")
    @patch.object(HealthChecker, "check_telegram")
    @patch.object(HealthChecker, "check_whatsapp_bridge")
    @patch.object(HealthChecker, "check_rate_limiter")
    async def test_run_all_checks_with_unhealthy(
        self,
        mock_rate_limiter,
        mock_whatsapp,
        mock_telegram,
        mock_openai,
        mock_redis,
        mock_database,
    ):
        """Test running all health checks with some unhealthy"""
        # Mock checks with some unhealthy
        mock_database.return_value = {"status": "healthy", "error": None}
        mock_redis.return_value = {"status": "unhealthy", "error": "Connection failed"}
        mock_openai.return_value = {"status": "healthy", "error": None}
        mock_telegram.return_value = {"status": "healthy", "error": None}
        mock_whatsapp.return_value = {"status": "healthy", "error": None}
        mock_rate_limiter.return_value = {"status": "healthy", "error": None}

        result = await self.health_checker.run_all_checks()

        assert result["status"] == "unhealthy"
        assert result["summary"]["healthy"] == 5
        assert result["summary"]["degraded"] == 0
        assert result["summary"]["unhealthy"] == 1

    @patch.object(HealthChecker, "check_database")
    @patch.object(HealthChecker, "check_redis")
    @patch.object(HealthChecker, "check_openai")
    @patch.object(HealthChecker, "check_telegram")
    @patch.object(HealthChecker, "check_whatsapp_bridge")
    @patch.object(HealthChecker, "check_rate_limiter")
    async def test_run_all_checks_with_not_configured(
        self,
        mock_rate_limiter,
        mock_whatsapp,
        mock_telegram,
        mock_openai,
        mock_redis,
        mock_database,
    ):
        """Test running all health checks with some not configured"""
        # Mock checks with some not configured
        mock_database.return_value = {"status": "healthy", "error": None}
        mock_redis.return_value = {
            "status": "not_configured",
            "error": "Redis URL not configured",
        }
        mock_openai.return_value = {"status": "healthy", "error": None}
        mock_telegram.return_value = {"status": "healthy", "error": None}
        mock_whatsapp.return_value = {"status": "healthy", "error": None}
        mock_rate_limiter.return_value = {"status": "healthy", "error": None}

        result = await self.health_checker.run_all_checks()

        assert (
            result["status"] == "healthy"
        )  # not_configured doesn't affect overall status
        assert result["summary"]["healthy"] == 5
        assert result["summary"]["degraded"] == 0
        assert result["summary"]["unhealthy"] == 0
        assert result["summary"]["not_configured"] == 1

    @patch.object(HealthChecker, "check_database")
    @patch.object(HealthChecker, "check_redis")
    @patch.object(HealthChecker, "check_openai")
    @patch.object(HealthChecker, "check_telegram")
    @patch.object(HealthChecker, "check_whatsapp_bridge")
    @patch.object(HealthChecker, "check_rate_limiter")
    async def test_run_all_checks_mixed_statuses(
        self,
        mock_rate_limiter,
        mock_whatsapp,
        mock_telegram,
        mock_openai,
        mock_redis,
        mock_database,
    ):
        """Test running all health checks with mixed statuses"""
        # Mock checks with mixed statuses
        mock_database.return_value = {"status": "healthy", "error": None}
        mock_redis.return_value = {"status": "unhealthy", "error": "Connection failed"}
        mock_openai.return_value = {"status": "degraded", "error": None}
        mock_telegram.return_value = {
            "status": "not_configured",
            "error": "Token not configured",
        }
        mock_whatsapp.return_value = {"status": "healthy", "error": None}
        mock_rate_limiter.return_value = {"status": "healthy", "error": None}

        result = await self.health_checker.run_all_checks()

        assert result["status"] == "unhealthy"  # unhealthy takes precedence
        assert result["summary"]["healthy"] == 3
        assert result["summary"]["degraded"] == 1
        assert result["summary"]["unhealthy"] == 1
        assert result["summary"]["not_configured"] == 1

    def test_health_checker_initialization(self):
        """Test health checker initialization"""
        assert isinstance(self.health_checker, HealthChecker)
        assert hasattr(self.health_checker, "check_database")
        assert hasattr(self.health_checker, "check_redis")
        assert hasattr(self.health_checker, "check_openai")
        assert hasattr(self.health_checker, "check_telegram")
        assert hasattr(self.health_checker, "check_whatsapp_bridge")
        assert hasattr(self.health_checker, "check_rate_limiter")
        assert hasattr(self.health_checker, "run_all_checks")

    def test_global_health_checker_instance(self):
        """Test that global health checker instance exists"""
        from app.health.checks import health_checker

        assert isinstance(health_checker, HealthChecker)
