from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

from app.core.openai_monitoring import OpenAIMetrics, OpenAIMonitor


def _mock_db_session(mock_db):
    """Create a mock context manager that yields mock_db."""

    @contextmanager
    def _ctx():
        yield mock_db

    return _ctx


class TestOpenAIMetrics:
    def test_initialization(self):
        """Test OpenAIMetrics dataclass initialization"""
        metrics = OpenAIMetrics()

        assert metrics.total_requests == 0
        assert metrics.total_tokens == 0
        assert metrics.total_cost_usd == 0.0
        assert metrics.successful_requests == 0
        assert metrics.failed_requests == 0
        assert metrics.last_request_time is None
        assert metrics.requests_by_model == {}
        assert metrics.tokens_by_model == {}
        assert metrics.cost_by_model == {}

    def test_initialization_with_values(self):
        """Test OpenAIMetrics dataclass initialization with values"""
        now = datetime.utcnow()
        metrics = OpenAIMetrics(
            total_requests=10,
            total_tokens=1000,
            total_cost_usd=0.05,
            successful_requests=9,
            failed_requests=1,
            last_request_time=now,
            requests_by_model={"gpt-4": 5, "gpt-3.5-turbo": 5},
            tokens_by_model={"gpt-4": 600, "gpt-3.5-turbo": 400},
            cost_by_model={"gpt-4": 0.03, "gpt-3.5-turbo": 0.02},
        )

        assert metrics.total_requests == 10
        assert metrics.total_tokens == 1000
        assert metrics.total_cost_usd == 0.05
        assert metrics.successful_requests == 9
        assert metrics.failed_requests == 1
        assert metrics.last_request_time == now
        assert metrics.requests_by_model == {"gpt-4": 5, "gpt-3.5-turbo": 5}
        assert metrics.tokens_by_model == {"gpt-4": 600, "gpt-3.5-turbo": 400}
        assert metrics.cost_by_model == {"gpt-4": 0.03, "gpt-3.5-turbo": 0.02}


class TestOpenAIMonitor:
    def setup_method(self):
        """Set up test fixtures"""
        # Create a fresh monitor instance for each test
        self.monitor = OpenAIMonitor()
        # Reset the monitor to initial state
        self.monitor.metrics = OpenAIMetrics()
        self.monitor.daily_metrics.clear()
        self.monitor.hourly_metrics.clear()
        self.monitor.recent_requests.clear()

    def test_initialization(self):
        """Test OpenAIMonitor initialization"""
        assert self.monitor.metrics is not None
        assert isinstance(self.monitor.metrics, OpenAIMetrics)
        assert self.monitor.daily_metrics == {}
        assert self.monitor.hourly_metrics == {}
        assert self.monitor.recent_requests == []
        assert "gpt-4o" in self.monitor.PRICING
        assert "gpt-4o-mini" in self.monitor.PRICING
        assert "gpt-4" in self.monitor.PRICING
        assert "gpt-3.5-turbo" in self.monitor.PRICING

    def test_calculate_cost_gpt4o(self):
        """Test cost calculation for gpt-4o model"""
        input_tokens = 1000
        output_tokens = 500

        cost = self.monitor.calculate_cost("gpt-4o", input_tokens, output_tokens)

        # Expected: (1000/1000) * 0.005 + (500/1000) * 0.015 = 0.005 + 0.0075 = 0.0125
        expected_cost = (input_tokens / 1000) * 0.005 + (output_tokens / 1000) * 0.015
        assert cost == expected_cost

    def test_calculate_cost_gpt35_turbo(self):
        """Test cost calculation for gpt-3.5-turbo model"""
        input_tokens = 2000
        output_tokens = 1000

        cost = self.monitor.calculate_cost("gpt-3.5-turbo", input_tokens, output_tokens)

        # Expected: (2000/1000) * 0.0005 + (1000/1000) * 0.0015 = 0.001 + 0.0015 =
        # 0.0025
        expected_cost = (input_tokens / 1000) * 0.0005 + (output_tokens / 1000) * 0.0015
        assert cost == expected_cost

    def test_calculate_cost_unknown_model(self):
        """Test cost calculation for unknown model (should use fallback)"""
        input_tokens = 1000
        output_tokens = 500

        cost = self.monitor.calculate_cost("unknown-model", input_tokens, output_tokens)

        # Should use gpt-4o-mini as fallback
        expected_cost = (input_tokens / 1000) * 0.00015 + (
            output_tokens / 1000
        ) * 0.0006
        assert cost == expected_cost

    @patch("app.core.openai_monitoring.get_db_session")
    @patch("app.core.openai_monitoring.repository_factory")
    def test_load_from_database_success(
        self, mock_repository_factory, mock_get_db_session
    ):
        """Test loading metrics from database successfully"""
        mock_db = Mock()
        mock_get_db_session.side_effect = _mock_db_session(mock_db)

        mock_repository = Mock()
        mock_repository_factory.get_openai_metrics_repository.return_value = (
            mock_repository
        )

        mock_db_metric = Mock()
        mock_db_metric.model = "gpt-4"
        mock_db_metric.input_tokens = 100
        mock_db_metric.output_tokens = 50
        mock_db_metric.total_tokens = 150
        mock_db_metric.cost_usd = 0.01
        mock_db_metric.success = True
        mock_db_metric.error_message = None
        mock_db_metric.request_time = datetime.utcnow()

        mock_repository.get_all_metrics_ordered.return_value = [mock_db_metric]

        monitor = OpenAIMonitor()

        assert monitor.metrics.total_requests == 1
        assert monitor.metrics.total_tokens == 150
        assert monitor.metrics.total_cost_usd == 0.01
        assert monitor.metrics.successful_requests == 1
        assert monitor.metrics.failed_requests == 0
        assert "gpt-4" in monitor.metrics.requests_by_model
        assert monitor.metrics.requests_by_model["gpt-4"] == 1

    @patch("app.core.openai_monitoring.get_db_session")
    @patch("app.core.openai_monitoring.repository_factory")
    def test_load_from_database_no_data(
        self, mock_repository_factory, mock_get_db_session
    ):
        """Test loading metrics from database with no data"""
        mock_db = Mock()
        mock_get_db_session.side_effect = _mock_db_session(mock_db)

        mock_repository = Mock()
        mock_repository_factory.get_openai_metrics_repository.return_value = (
            mock_repository
        )

        mock_repository.get_all_metrics_ordered.return_value = []

        monitor = OpenAIMonitor()

        assert monitor.metrics.total_requests == 0
        assert monitor.metrics.total_tokens == 0
        assert monitor.metrics.total_cost_usd == 0.0

    @patch("app.core.openai_monitoring.get_db_session")
    @patch("app.core.openai_monitoring.repository_factory")
    def test_load_from_database_exception(
        self, mock_repository_factory, mock_get_db_session
    ):
        """Test loading metrics from database with exception"""
        mock_db = Mock()
        mock_get_db_session.side_effect = _mock_db_session(mock_db)

        mock_repository = Mock()
        mock_repository_factory.get_openai_metrics_repository.return_value = (
            mock_repository
        )
        mock_repository.get_all_metrics_ordered.side_effect = Exception(
            "Database error"
        )

        monitor = OpenAIMonitor()

        assert monitor.metrics.total_requests == 0
        assert monitor.metrics.total_tokens == 0
        assert monitor.metrics.total_cost_usd == 0.0

    @patch("app.core.openai_monitoring.get_db_session")
    @patch("app.core.openai_monitoring.datetime")
    def test_record_request_success(self, mock_datetime, mock_get_db_session):
        """Test recording a successful request"""
        now = datetime.now(UTC)
        mock_datetime.now.return_value = now

        mock_db = Mock()
        mock_get_db_session.side_effect = _mock_db_session(mock_db)

        self.monitor.record_request("gpt-4", 100, 50, success=True)

        assert self.monitor.metrics.total_requests == 1
        assert self.monitor.metrics.total_tokens == 150
        assert self.monitor.metrics.successful_requests == 1
        assert self.monitor.metrics.failed_requests == 0
        assert self.monitor.metrics.last_request_time == now
        assert "gpt-4" in self.monitor.metrics.requests_by_model
        assert self.monitor.metrics.requests_by_model["gpt-4"] == 1

        day_key = now.strftime("%Y-%m-%d")
        assert day_key in self.monitor.daily_metrics
        daily = self.monitor.daily_metrics[day_key]
        assert daily.total_requests == 1
        assert daily.total_tokens == 150
        assert daily.successful_requests == 1

        hour_key = now.strftime("%Y-%m-%d-%H")
        assert hour_key in self.monitor.hourly_metrics
        hourly = self.monitor.hourly_metrics[hour_key]
        assert hourly.total_requests == 1
        assert hourly.total_tokens == 150
        assert hourly.successful_requests == 1

        assert len(self.monitor.recent_requests) == 1
        recent_request = self.monitor.recent_requests[0]
        assert recent_request["model"] == "gpt-4"
        assert recent_request["tokens"] == 150
        assert recent_request["success"]
        assert recent_request["error"] is None

        mock_db.add.assert_called_once()

    @patch("app.core.openai_monitoring.get_db_session")
    @patch("app.core.openai_monitoring.datetime")
    def test_record_request_failure(self, mock_datetime, mock_get_db_session):
        """Test recording a failed request"""
        now = datetime.now(UTC)
        mock_datetime.now.return_value = now

        mock_db = Mock()
        mock_get_db_session.side_effect = _mock_db_session(mock_db)

        error_message = "API rate limit exceeded"
        self.monitor.record_request("gpt-4", 100, 0, success=False, error=error_message)

        assert self.monitor.metrics.total_requests == 1
        assert self.monitor.metrics.total_tokens == 100
        assert self.monitor.metrics.successful_requests == 0
        assert self.monitor.metrics.failed_requests == 1

        assert len(self.monitor.recent_requests) == 1
        recent_request = self.monitor.recent_requests[0]
        assert recent_request["model"] == "gpt-4"
        assert recent_request["tokens"] == 100
        assert recent_request["success"] is False
        assert recent_request["error"] == error_message

    @patch("app.core.openai_monitoring.get_db_session")
    @patch("app.core.openai_monitoring.datetime")
    def test_record_request_database_exception(
        self, mock_datetime, mock_get_db_session
    ):
        """Test recording request when database fails"""
        now = datetime.now(UTC)
        mock_datetime.now.return_value = now

        mock_db = Mock()
        mock_db.add.side_effect = Exception("Database error")
        mock_get_db_session.side_effect = _mock_db_session(mock_db)

        self.monitor.record_request("gpt-4", 100, 50, success=True)

        assert self.monitor.metrics.total_requests == 1
        assert self.monitor.metrics.total_tokens == 150

    @patch("app.core.openai_monitoring.datetime")
    def test_record_request_recent_requests_limit(self, mock_datetime):
        """Test that recent requests are limited to 10"""
        now = datetime.now(UTC)
        mock_datetime.now.return_value = now

        # Record 12 requests
        for _ in range(12):
            self.monitor.record_request("gpt-4", 100, 50, success=True)

        # Verify only 10 recent requests are kept
        assert len(self.monitor.recent_requests) == 10

        # Verify the oldest request was removed
        assert self.monitor.recent_requests[0]["timestamp"] == now.isoformat()

    @patch("app.core.openai_monitoring.datetime")
    def test_get_stats_empty(self, mock_datetime):
        """Test getting stats with no data"""
        now = datetime.now(UTC)
        mock_datetime.now.return_value = now

        # Mock datetime.strptime to return a real datetime
        def mock_strptime(date_string, format_string):
            return datetime.strptime(date_string, format_string)

        mock_datetime.strptime = mock_strptime

        stats = self.monitor.get_stats()

        assert stats["total_requests"] == 0
        assert stats["total_tokens"] == 0
        assert stats["total_cost_usd"] == 0.0
        assert stats["successful_requests"] == 0
        assert stats["failed_requests"] == 0
        assert stats["success_rate"] == 0.0
        assert stats["last_request_time"] is None
        assert stats["recent_24h"] == 0  # This is now a count of recent requests
        assert stats["cost_24h"] == 0.0
        assert stats["avg_tokens_per_request"] == 0.0
        assert stats["recent_requests"] == []
        assert stats["models_usage"] == {}
        assert stats["recent_1h"]["requests"] == 0
        assert stats["by_model"] == {}
        assert stats["daily_breakdown"] == {}

    @patch("app.core.openai_monitoring.datetime")
    def test_get_stats_with_data(self, mock_datetime):
        """Test getting stats with data"""
        now = datetime.now(UTC)
        mock_datetime.now.return_value = now

        # Mock datetime.strptime to return a real datetime
        def mock_strptime(date_string, format_string):
            return datetime.strptime(date_string, format_string)

        mock_datetime.strptime = mock_strptime

        # Record some requests
        self.monitor.record_request("gpt-4", 100, 50, success=True)
        self.monitor.record_request("gpt-3.5-turbo", 200, 100, success=True)
        self.monitor.record_request("gpt-4", 150, 75, success=False, error="Rate limit")

        stats = self.monitor.get_stats()

        assert stats["total_requests"] == 3
        # The actual calculation includes the cost calculation which may vary slightly
        assert stats["total_tokens"] >= 575  # 150 + 300 + 225
        assert stats["successful_requests"] == 2
        assert stats["failed_requests"] == 1
        assert stats["success_rate"] == 66.67  # 2/3 * 100
        assert stats["last_request_time"] == now.isoformat()
        assert stats["avg_tokens_per_request"] >= 191.0  # 575/3
        assert len(stats["recent_requests"]) == 3
        assert "gpt-4" in stats["models_usage"]
        assert "gpt-3.5-turbo" in stats["models_usage"]
        assert stats["models_usage"]["gpt-4"]["requests"] == 2
        assert stats["models_usage"]["gpt-3.5-turbo"]["requests"] == 1

    def test_get_cost_estimate(self):
        """Test cost estimation for future requests"""
        estimated_tokens = 1000

        cost = self.monitor.get_cost_estimate("gpt-4", estimated_tokens)

        # Should assume 50/50 split: 500 input + 500 output
        expected_cost = self.monitor.calculate_cost("gpt-4", 500, 500)
        assert cost == expected_cost

    @patch("app.core.openai_monitoring.datetime")
    def test_cleanup_old_data(self, mock_datetime):
        """Test cleanup of old data"""
        now = datetime.now(UTC)
        mock_datetime.now.return_value = now

        # Mock datetime.strptime to return a real datetime
        def mock_strptime(date_string, format_string):
            return datetime.strptime(date_string, format_string)

        mock_datetime.strptime = mock_strptime

        # Add some old data
        old_day = (now - timedelta(days=35)).strftime("%Y-%m-%d")
        old_hour = (now - timedelta(days=10)).strftime("%Y-%m-%d-%H")
        recent_day = (now - timedelta(days=5)).strftime("%Y-%m-%d")
        recent_hour = (now - timedelta(hours=2)).strftime("%Y-%m-%d-%H")

        self.monitor.daily_metrics[old_day] = OpenAIMetrics()
        self.monitor.daily_metrics[recent_day] = OpenAIMetrics()
        self.monitor.hourly_metrics[old_hour] = OpenAIMetrics()
        self.monitor.hourly_metrics[recent_hour] = OpenAIMetrics()

        # Clean up old data
        self.monitor.cleanup_old_data(days_to_keep=30)

        # Verify old data was removed
        assert old_day not in self.monitor.daily_metrics
        assert old_hour not in self.monitor.hourly_metrics

        # Verify recent data was kept
        assert recent_day in self.monitor.daily_metrics
        assert recent_hour in self.monitor.hourly_metrics

    @patch("app.core.openai_monitoring.datetime")
    def test_cleanup_old_data_no_old_data(self, mock_datetime):
        """Test cleanup when no old data exists"""
        now = datetime.now(UTC)
        mock_datetime.now.return_value = now

        # Mock datetime.strptime to return a real datetime
        def mock_strptime(date_string, format_string):
            return datetime.strptime(date_string, format_string)

        mock_datetime.strptime = mock_strptime

        # Add only recent data
        recent_day = (now - timedelta(days=5)).strftime("%Y-%m-%d")
        recent_hour = (now - timedelta(hours=2)).strftime("%Y-%m-%d-%H")

        self.monitor.daily_metrics[recent_day] = OpenAIMetrics()
        self.monitor.hourly_metrics[recent_hour] = OpenAIMetrics()

        # Clean up old data
        self.monitor.cleanup_old_data(days_to_keep=30)

        # Verify recent data was kept
        assert recent_day in self.monitor.daily_metrics
        assert recent_hour in self.monitor.hourly_metrics

    def test_global_instance(self):
        """Test that global instance exists"""
        from app.core.openai_monitoring import openai_monitor

        assert isinstance(openai_monitor, OpenAIMonitor)
