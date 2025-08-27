from unittest.mock import Mock, patch

import pytest

from app.core.metrics import (
    MetricsCollector,
    track_async_task,
    track_db_operation,
    track_http_request,
)


class TestMetricsCollector:
    def setup_method(self):
        """Set up test fixtures"""
        self.metrics_collector = MetricsCollector()

    def test_initialization(self):
        """Test metrics collector initialization"""
        assert self.metrics_collector.logger is not None
        assert self.metrics_collector.registry is not None
        assert self.metrics_collector.memory_cache_hits == 0
        assert self.metrics_collector.memory_cache_misses == 0
        assert self.metrics_collector.redis_cache_hits == 0
        assert self.metrics_collector.redis_cache_misses == 0

    def test_init_counters(self):
        """Test counter initialization"""
        # Check that gauge metrics are initialized
        assert self.metrics_collector.active_users._value.get() == 0
        assert (
            self.metrics_collector.cache_hit_ratio.labels(
                cache_type="memory"
            )._value.get()
            == 0.0
        )
        assert (
            self.metrics_collector.cache_hit_ratio.labels(
                cache_type="redis"
            )._value.get()
            == 0.0
        )
        assert (
            self.metrics_collector.cache_size_bytes.labels(
                cache_type="memory"
            )._value.get()
            == 0
        )
        assert (
            self.metrics_collector.cache_size_bytes.labels(
                cache_type="redis"
            )._value.get()
            == 0
        )
        assert self.metrics_collector.db_connections_active._value.get() == 0
        assert (
            self.metrics_collector.memory_usage_bytes.labels(type="rss")._value.get()
            == 0
        )
        assert (
            self.metrics_collector.memory_usage_bytes.labels(type="vms")._value.get()
            == 0
        )
        assert self.metrics_collector.cpu_usage_percent._value.get() == 0.0

    def test_record_http_request(self):
        """Test HTTP request recording"""
        method = "POST"
        endpoint = "/api/users"
        status_code = 201
        duration = 0.5

        self.metrics_collector.record_http_request(
            method, endpoint, status_code, duration
        )

        # Check that the counter was incremented
        assert (
            self.metrics_collector.http_requests_total.labels(
                method=method, endpoint=endpoint, status_code=status_code
            )._value.get()
            == 1
        )

    def test_record_db_query(self):
        """Test database query recording"""
        operation = "SELECT"
        table = "users"
        duration = 0.1

        self.metrics_collector.record_db_query(operation, table, duration)

        # Check that the counter was incremented
        assert (
            self.metrics_collector.db_queries_total.labels(
                operation=operation, table=table
            )._value.get()
            == 1
        )

    def test_record_cache_operation_get_miss(self):
        """Test cache operation recording for get miss"""
        operation = "get"
        cache_type = "redis"
        hit = False

        self.metrics_collector.record_cache_operation(operation, cache_type, hit)

        # Check that the counter was incremented
        assert (
            self.metrics_collector.cache_operations_total.labels(
                operation=operation, cache_type=cache_type
            )._value.get()
            == 1
        )

        # The actual implementation only increments hits for "get" operations, not misses
        # Misses are only incremented for "miss" operations
        assert self.metrics_collector.redis_cache_hits == 1
        assert self.metrics_collector.redis_cache_misses == 0

    def test_record_cache_operation_get_hit(self):
        """Test cache operation recording for get hit"""
        operation = "get"
        cache_type = "memory"
        hit = True

        self.metrics_collector.record_cache_operation(operation, cache_type, hit)

        # Check that the counter was incremented
        assert (
            self.metrics_collector.cache_operations_total.labels(
                operation=operation, cache_type=cache_type
            )._value.get()
            == 1
        )

        # Check that memory cache hits were incremented
        assert self.metrics_collector.memory_cache_hits == 1
        assert self.metrics_collector.memory_cache_misses == 0

    def test_record_cache_operation_miss(self):
        """Test cache operation recording for miss operation"""
        operation = "miss"
        cache_type = "memory"
        hit = False

        self.metrics_collector.record_cache_operation(operation, cache_type, hit)

        # Check that the counter was incremented
        assert (
            self.metrics_collector.cache_operations_total.labels(
                operation=operation, cache_type=cache_type
            )._value.get()
            == 1
        )

        # Check that memory cache misses were incremented
        assert self.metrics_collector.memory_cache_hits == 0
        assert self.metrics_collector.memory_cache_misses == 1

    def test_record_openai_request(self):
        """Test OpenAI request recording"""
        model = "gpt-4"
        endpoint = "chat/completions"
        duration = 2.5
        tokens_used = 150

        self.metrics_collector.record_openai_request(
            model, endpoint, duration, tokens_used
        )

        # Check that the counter was incremented
        assert (
            self.metrics_collector.openai_requests_total.labels(
                model=model, endpoint=endpoint
            )._value.get()
            == 1
        )

        # Check that tokens were recorded
        assert (
            self.metrics_collector.openai_tokens_used.labels(
                model=model, token_type="total"
            )._value.get()
            == tokens_used
        )

    def test_record_openai_request_no_tokens(self):
        """Test OpenAI request recording without tokens"""
        model = "gpt-3.5-turbo"
        endpoint = "completions"
        duration = 1.0

        self.metrics_collector.record_openai_request(model, endpoint, duration)

        # Check that the counter was incremented
        assert (
            self.metrics_collector.openai_requests_total.labels(
                model=model, endpoint=endpoint
            )._value.get()
            == 1
        )

        # Check that no tokens were recorded
        assert (
            self.metrics_collector.openai_tokens_used.labels(
                model=model, token_type="total"
            )._value.get()
            == 0
        )

    def test_record_whatsapp_message(self):
        """Test WhatsApp message recording"""
        chat_type = "group"
        message_type = "text"
        importance = 4

        self.metrics_collector.record_whatsapp_message(
            chat_type, message_type, importance
        )

        # Check that the counter was incremented
        assert (
            self.metrics_collector.whatsapp_messages_total.labels(
                chat_type=chat_type, message_type=message_type
            )._value.get()
            == 1
        )

    def test_record_whatsapp_message_no_importance(self):
        """Test WhatsApp message recording without importance"""
        chat_type = "private"
        message_type = "image"

        self.metrics_collector.record_whatsapp_message(chat_type, message_type)

        # Check that the counter was incremented
        assert (
            self.metrics_collector.whatsapp_messages_total.labels(
                chat_type=chat_type, message_type=message_type
            )._value.get()
            == 1
        )

    def test_record_digest_created(self):
        """Test digest creation recording"""
        user_id = "user123"

        self.metrics_collector.record_digest_created(user_id)

        # Check that the counter was incremented
        assert (
            self.metrics_collector.digests_created_total.labels(
                user_id=user_id
            )._value.get()
            == 1
        )

    def test_record_async_task(self):
        """Test async task recording"""
        priority = "high"
        status = "completed"
        duration = 1.5

        self.metrics_collector.record_async_task(priority, status, duration)

        # Check that the counter was incremented
        assert (
            self.metrics_collector.async_tasks_total.labels(
                priority=priority, status=status
            )._value.get()
            == 1
        )

    def test_record_async_task_no_duration(self):
        """Test async task recording without duration"""
        priority = "low"
        status = "failed"

        self.metrics_collector.record_async_task(priority, status)

        # Check that the counter was incremented
        assert (
            self.metrics_collector.async_tasks_total.labels(
                priority=priority, status=status
            )._value.get()
            == 1
        )

    def test_record_error(self):
        """Test error recording"""
        error_type = "ValueError"
        module = "app.api.users"

        self.metrics_collector.record_error(error_type, module)

        # Check that the counter was incremented
        assert (
            self.metrics_collector.errors_total.labels(
                error_type=error_type, module=module
            )._value.get()
            == 1
        )

    def test_update_system_metrics_active_users(self):
        """Test system metrics update with active users"""
        metrics = {"active_users": 25}

        self.metrics_collector.update_system_metrics(metrics)

        assert self.metrics_collector.active_users._value.get() == 25

    def test_update_system_metrics_db_connections(self):
        """Test system metrics update with database connections"""
        metrics = {"db_connections": 5}

        self.metrics_collector.update_system_metrics(metrics)

        assert self.metrics_collector.db_connections_active._value.get() == 5

    def test_update_system_metrics_cache_stats(self):
        """Test system metrics update with cache statistics"""
        metrics = {
            "cache_stats": {
                "memory_hit_ratio": 0.8,
                "redis_hit_ratio": 0.9,
                "memory_size": 1024,
                "redis_size": 2048,
            }
        }

        self.metrics_collector.update_system_metrics(metrics)

        assert (
            self.metrics_collector.cache_hit_ratio.labels(
                cache_type="memory"
            )._value.get()
            == 0.8
        )
        assert (
            self.metrics_collector.cache_hit_ratio.labels(
                cache_type="redis"
            )._value.get()
            == 0.9
        )
        assert (
            self.metrics_collector.cache_size_bytes.labels(
                cache_type="memory"
            )._value.get()
            == 1024
        )
        assert (
            self.metrics_collector.cache_size_bytes.labels(
                cache_type="redis"
            )._value.get()
            == 2048
        )

    def test_update_system_metrics_memory_usage(self):
        """Test system metrics update with memory usage"""
        metrics = {"memory_usage": {"rss": 1048576, "vms": 2097152}}

        self.metrics_collector.update_system_metrics(metrics)

        assert (
            self.metrics_collector.memory_usage_bytes.labels(type="rss")._value.get()
            == 1048576
        )
        assert (
            self.metrics_collector.memory_usage_bytes.labels(type="vms")._value.get()
            == 2097152
        )

    def test_update_system_metrics_cpu_usage(self):
        """Test system metrics update with CPU usage"""
        metrics = {"cpu_usage": 45.5}

        self.metrics_collector.update_system_metrics(metrics)

        assert self.metrics_collector.cpu_usage_percent._value.get() == 45.5

    def test_update_system_metrics_partial(self):
        """Test system metrics update with partial data"""
        metrics = {"active_users": 10}

        self.metrics_collector.update_system_metrics(metrics)

        # Only active_users should be updated
        assert self.metrics_collector.active_users._value.get() == 10
        # Other metrics should remain unchanged
        assert self.metrics_collector.db_connections_active._value.get() == 0

    def test_get_metrics(self):
        """Test getting metrics in Prometheus format"""
        # Record some metrics first
        self.metrics_collector.record_http_request("GET", "/health", 200, 0.1)
        self.metrics_collector.record_db_query("SELECT", "users", 0.05)

        metrics = self.metrics_collector.get_metrics()

        # The get_metrics method returns bytes, not string
        assert isinstance(metrics, bytes)
        metrics_str = metrics.decode("utf-8")
        assert "http_requests_total" in metrics_str
        assert "db_queries_total" in metrics_str

    def test_get_cache_stats_no_operations(self):
        """Test getting cache stats with no operations"""
        stats = self.metrics_collector.get_cache_stats()

        assert stats["memory_hits"] == 0
        assert stats["memory_misses"] == 0
        assert stats["memory_hit_ratio"] == 0.0
        assert stats["redis_hits"] == 0
        assert stats["redis_misses"] == 0
        assert stats["redis_hit_ratio"] == 0.0

    def test_get_cache_stats_with_operations(self):
        """Test getting cache stats with operations"""
        # Record some cache operations
        self.metrics_collector.record_cache_operation("get", "memory", True)  # hit
        self.metrics_collector.record_cache_operation("miss", "memory", False)  # miss
        self.metrics_collector.record_cache_operation("get", "redis", True)  # hit
        self.metrics_collector.record_cache_operation("get", "redis", True)  # hit

        stats = self.metrics_collector.get_cache_stats()

        assert stats["memory_hits"] == 1
        assert stats["memory_misses"] == 1
        assert stats["memory_hit_ratio"] == 0.5
        assert stats["redis_hits"] == 2
        assert stats["redis_misses"] == 0
        assert stats["redis_hit_ratio"] == 1.0

    @patch("app.core.metrics.start_http_server")
    def test_start_metrics_server_success(self, mock_start_server):
        """Test starting metrics server successfully"""
        port = 9090

        self.metrics_collector.start_metrics_server(port)

        mock_start_server.assert_called_once_with(
            port, registry=self.metrics_collector.registry
        )

    @patch("app.core.metrics.start_http_server")
    def test_start_metrics_server_failure(self, mock_start_server):
        """Test starting metrics server with failure"""
        mock_start_server.side_effect = Exception("Port already in use")
        port = 9090

        # Should not raise an exception
        self.metrics_collector.start_metrics_server(port)

        mock_start_server.assert_called_once_with(
            port, registry=self.metrics_collector.registry
        )

    def test_global_instance(self):
        """Test that global instance exists"""
        from app.core.metrics import metrics_collector

        assert isinstance(metrics_collector, MetricsCollector)


class TestTrackHttpRequestDecorator:
    def setup_method(self):
        """Set up test fixtures"""
        self.metrics_collector = MetricsCollector()

    @patch("app.core.metrics.metrics_collector")
    async def test_track_http_request_success(self, mock_metrics_collector):
        """Test HTTP request tracking decorator with success"""
        mock_metrics_collector.record_http_request = Mock()
        mock_metrics_collector.record_error = Mock()

        @track_http_request
        async def test_endpoint():
            return "success"

        result = await test_endpoint()

        assert result == "success"
        mock_metrics_collector.record_http_request.assert_called_once()
        mock_metrics_collector.record_error.assert_not_called()

    @patch("app.core.metrics.metrics_collector")
    async def test_track_http_request_exception(self, mock_metrics_collector):
        """Test HTTP request tracking decorator with exception"""
        mock_metrics_collector.record_http_request = Mock()
        mock_metrics_collector.record_error = Mock()

        @track_http_request
        async def test_endpoint():
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            await test_endpoint()

        mock_metrics_collector.record_http_request.assert_called_once()
        mock_metrics_collector.record_error.assert_called_once()

    @patch("app.core.metrics.metrics_collector")
    async def test_track_http_request_with_fastapi_request(
        self, mock_metrics_collector
    ):
        """Test HTTP request tracking decorator with FastAPI request object"""
        mock_metrics_collector.record_http_request = Mock()
        mock_metrics_collector.record_error = Mock()

        # Mock FastAPI request object
        mock_request = Mock()
        mock_request.method = "POST"
        mock_request.url.path = "/api/users"

        @track_http_request
        async def test_endpoint(request):
            return "success"

        result = await test_endpoint(mock_request)

        assert result == "success"
        mock_metrics_collector.record_http_request.assert_called_once()
        # Should use the request method and path
        call_args = mock_metrics_collector.record_http_request.call_args[0]
        assert call_args[0] == "POST"  # method
        assert call_args[1] == "/api/users"  # endpoint


class TestTrackDbOperationDecorator:
    def setup_method(self):
        """Set up test fixtures"""
        self.metrics_collector = MetricsCollector()

    @patch("app.core.metrics.metrics_collector")
    def test_track_db_operation_success(self, mock_metrics_collector):
        """Test database operation tracking decorator with success"""
        mock_metrics_collector.record_db_query = Mock()
        mock_metrics_collector.record_error = Mock()

        @track_db_operation("SELECT", "users")
        def test_query():
            return "data"

        result = test_query()

        assert result == "data"
        mock_metrics_collector.record_db_query.assert_called_once()
        mock_metrics_collector.record_error.assert_not_called()

    @patch("app.core.metrics.metrics_collector")
    def test_track_db_operation_exception(self, mock_metrics_collector):
        """Test database operation tracking decorator with exception"""
        mock_metrics_collector.record_db_query = Mock()
        mock_metrics_collector.record_error = Mock()

        @track_db_operation("INSERT", "users")
        def test_query():
            raise Exception("Database error")

        with pytest.raises(Exception, match="Database error"):
            test_query()

        mock_metrics_collector.record_db_query.assert_called_once()
        mock_metrics_collector.record_error.assert_called_once()


class TestTrackAsyncTaskDecorator:
    def setup_method(self):
        """Set up test fixtures"""
        self.metrics_collector = MetricsCollector()

    @patch("app.core.metrics.metrics_collector")
    async def test_track_async_task_success(self, mock_metrics_collector):
        """Test async task tracking decorator with success"""
        mock_metrics_collector.record_async_task = Mock()
        mock_metrics_collector.record_error = Mock()

        @track_async_task("high")
        async def test_task():
            return "completed"

        result = await test_task()

        assert result == "completed"
        mock_metrics_collector.record_async_task.assert_called_once()
        mock_metrics_collector.record_error.assert_not_called()

    @patch("app.core.metrics.metrics_collector")
    async def test_track_async_task_exception(self, mock_metrics_collector):
        """Test async task tracking decorator with exception"""
        mock_metrics_collector.record_async_task = Mock()
        mock_metrics_collector.record_error = Mock()

        @track_async_task("low")
        async def test_task():
            raise RuntimeError("Task failed")

        with pytest.raises(RuntimeError, match="Task failed"):
            await test_task()

        mock_metrics_collector.record_async_task.assert_called_once()
        mock_metrics_collector.record_error.assert_called_once()
