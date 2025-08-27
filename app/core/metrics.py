from typing import Any, Dict, Optional

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client.exposition import start_http_server

from config.logging_config import get_logger

logger = get_logger(__name__)


class MetricsCollector:
    """Prometheus metrics collector for application monitoring"""

    def __init__(self):
        self.logger = get_logger(__name__)
        self.registry = CollectorRegistry()

        # Cache hit/miss tracking
        self.memory_cache_hits = 0
        self.memory_cache_misses = 0
        self.redis_cache_hits = 0
        self.redis_cache_misses = 0

        # HTTP metrics
        self.http_requests_total = Counter(
            "http_requests_total",
            "Total number of HTTP requests",
            ["method", "endpoint", "status_code"],
            registry=self.registry,
        )

        self.http_request_duration_seconds = Histogram(
            "http_request_duration_seconds",
            "HTTP request duration in seconds",
            ["method", "endpoint"],
            buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
            registry=self.registry,
        )

        # Database metrics
        self.db_queries_total = Counter(
            "db_queries_total",
            "Total number of database queries",
            ["operation", "table"],
            registry=self.registry,
        )

        self.db_query_duration_seconds = Histogram(
            "db_query_duration_seconds",
            "Database query duration in seconds",
            ["operation", "table"],
            buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
            registry=self.registry,
        )

        self.db_connections_active = Gauge(
            "db_connections_active",
            "Number of active database connections",
            registry=self.registry,
        )

        # Cache metrics
        self.cache_operations_total = Counter(
            "cache_operations_total",
            "Total number of cache operations",
            ["operation", "cache_type"],
            registry=self.registry,
        )

        self.cache_hit_ratio = Gauge(
            "cache_hit_ratio",
            "Cache hit ratio (0.0 to 1.0)",
            ["cache_type"],
            registry=self.registry,
        )

        self.cache_size_bytes = Gauge(
            "cache_size_bytes",
            "Cache size in bytes",
            ["cache_type"],
            registry=self.registry,
        )

        # OpenAI API metrics
        self.openai_requests_total = Counter(
            "openai_requests_total",
            "Total number of OpenAI API requests",
            ["model", "endpoint"],
            registry=self.registry,
        )

        self.openai_request_duration_seconds = Histogram(
            "openai_request_duration_seconds",
            "OpenAI API request duration in seconds",
            ["model", "endpoint"],
            buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
            registry=self.registry,
        )

        self.openai_tokens_used = Counter(
            "openai_tokens_used",
            "Total number of tokens used in OpenAI requests",
            ["model", "token_type"],
            registry=self.registry,
        )

        # WhatsApp metrics
        self.whatsapp_messages_total = Counter(
            "whatsapp_messages_total",
            "Total number of WhatsApp messages processed",
            ["chat_type", "message_type"],
            registry=self.registry,
        )

        self.whatsapp_message_importance = Histogram(
            "whatsapp_message_importance",
            "WhatsApp message importance scores",
            ["chat_type"],
            buckets=[1, 2, 3, 4, 5],
            registry=self.registry,
        )

        # System metrics
        self.active_users = Gauge(
            "active_users", "Number of active users", registry=self.registry
        )

        self.digests_created_total = Counter(
            "digests_created_total",
            "Total number of digests created",
            ["user_id"],
            registry=self.registry,
        )

        self.async_tasks_total = Counter(
            "async_tasks_total",
            "Total number of async tasks",
            ["priority", "status"],
            registry=self.registry,
        )

        self.async_task_duration_seconds = Histogram(
            "async_task_duration_seconds",
            "Async task duration in seconds",
            ["priority"],
            buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
            registry=self.registry,
        )

        # Errors and exceptions
        self.errors_total = Counter(
            "errors_total",
            "Total number of errors",
            ["error_type", "module"],
            registry=self.registry,
        )

        # Performance metrics
        self.memory_usage_bytes = Gauge(
            "memory_usage_bytes",
            "Memory usage in bytes",
            ["type"],
            registry=self.registry,
        )

        self.cpu_usage_percent = Gauge(
            "cpu_usage_percent", "CPU usage percentage", registry=self.registry
        )

        # Initialize counters
        self._init_counters()

    def _init_counters(self):
        """Initialize initial counter values"""
        # Set initial values for gauge metrics
        self.active_users.set(0)
        self.cache_hit_ratio.labels(cache_type="memory").set(0.0)
        self.cache_hit_ratio.labels(cache_type="redis").set(0.0)
        self.cache_size_bytes.labels(cache_type="memory").set(0)
        self.cache_size_bytes.labels(cache_type="redis").set(0)
        self.db_connections_active.set(0)
        self.memory_usage_bytes.labels(type="rss").set(0)
        self.memory_usage_bytes.labels(type="vms").set(0)
        self.cpu_usage_percent.set(0.0)

    def record_http_request(
        self, method: str, endpoint: str, status_code: int, duration: float
    ):
        """Record HTTP request metric"""
        self.http_requests_total.labels(
            method=method, endpoint=endpoint, status_code=status_code
        ).inc()
        self.http_request_duration_seconds.labels(
            method=method, endpoint=endpoint
        ).observe(duration)

    def record_db_query(self, operation: str, table: str, duration: float):
        """Record database query metric"""
        self.db_queries_total.labels(operation=operation, table=table).inc()
        self.db_query_duration_seconds.labels(operation=operation, table=table).observe(
            duration
        )

    def record_cache_operation(self, operation: str, cache_type: str, hit: bool):
        """Record cache operation metric"""
        self.cache_operations_total.labels(
            operation=operation, cache_type=cache_type
        ).inc()

        # Update hit ratio tracking
        if operation == "get":
            if cache_type == "memory":
                self.memory_cache_hits += 1
            elif cache_type == "redis":
                self.redis_cache_hits += 1
        elif operation == "miss":
            if cache_type == "memory":
                self.memory_cache_misses += 1
            elif cache_type == "redis":
                self.redis_cache_misses += 1

    def record_openai_request(
        self, model: str, endpoint: str, duration: float, tokens_used: int = 0
    ):
        """Record OpenAI request metric"""
        self.openai_requests_total.labels(model=model, endpoint=endpoint).inc()
        self.openai_request_duration_seconds.labels(
            model=model, endpoint=endpoint
        ).observe(duration)

        if tokens_used > 0:
            self.openai_tokens_used.labels(
                model=model, token_type="total"
            ).inc(  # nosec B106
                tokens_used
            )

    def record_whatsapp_message(
        self, chat_type: str, message_type: str, importance: Optional[int] = None
    ):
        """Record WhatsApp message metric"""
        self.whatsapp_messages_total.labels(
            chat_type=chat_type, message_type=message_type
        ).inc()

        if importance is not None:
            self.whatsapp_message_importance.labels(chat_type=chat_type).observe(
                importance
            )

    def record_digest_created(self, user_id: str):
        """Record digest creation metric"""
        self.digests_created_total.labels(user_id=user_id).inc()

    def record_async_task(self, priority: str, status: str, duration: float = 0):
        """Record async task metric"""
        self.async_tasks_total.labels(priority=priority, status=status).inc()

        if duration > 0:
            self.async_task_duration_seconds.labels(priority=priority).observe(duration)

    def record_error(self, error_type: str, module: str):
        """Record error metric"""
        self.errors_total.labels(error_type=error_type, module=module).inc()

    def update_system_metrics(self, metrics: Dict[str, Any]):
        """Update system metrics"""
        if "active_users" in metrics:
            self.active_users.set(metrics["active_users"])

        if "db_connections" in metrics:
            self.db_connections_active.set(metrics["db_connections"])

        if "cache_stats" in metrics:
            cache_stats = metrics["cache_stats"]
            if "memory_hit_ratio" in cache_stats:
                self.cache_hit_ratio.labels(cache_type="memory").set(
                    cache_stats["memory_hit_ratio"]
                )
            if "redis_hit_ratio" in cache_stats:
                self.cache_hit_ratio.labels(cache_type="redis").set(
                    cache_stats["redis_hit_ratio"]
                )
            if "memory_size" in cache_stats:
                self.cache_size_bytes.labels(cache_type="memory").set(
                    cache_stats["memory_size"]
                )
            if "redis_size" in cache_stats:
                self.cache_size_bytes.labels(cache_type="redis").set(
                    cache_stats["redis_size"]
                )

        if "memory_usage" in metrics:
            memory = metrics["memory_usage"]
            if "rss" in memory:
                self.memory_usage_bytes.labels(type="rss").set(memory["rss"])
            if "vms" in memory:
                self.memory_usage_bytes.labels(type="vms").set(memory["vms"])

        if "cpu_usage" in metrics:
            self.cpu_usage_percent.set(metrics["cpu_usage"])

    def get_metrics(self) -> str:
        """Get metrics in Prometheus format"""
        return generate_latest(self.registry)

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics including hit ratios"""
        memory_total = self.memory_cache_hits + self.memory_cache_misses
        redis_total = self.redis_cache_hits + self.redis_cache_misses

        return {
            "memory_hits": self.memory_cache_hits,
            "memory_misses": self.memory_cache_misses,
            "memory_hit_ratio": (
                self.memory_cache_hits / memory_total if memory_total > 0 else 0.0
            ),
            "redis_hits": self.redis_cache_hits,
            "redis_misses": self.redis_cache_misses,
            "redis_hit_ratio": (
                self.redis_cache_hits / redis_total if redis_total > 0 else 0.0
            ),
        }

    def start_metrics_server(self, port: int = 8000):
        """Start HTTP server for metrics"""
        try:
            start_http_server(port, registry=self.registry)
            self.logger.info(f"Prometheus metrics server started on port {port}")
        except Exception as e:
            self.logger.error(f"Failed to start metrics server: {e}")


# Global metrics collector instance
metrics_collector = MetricsCollector()


# Decorators for automatic metrics collection
def track_http_request(func):
    """Decorator for tracking HTTP requests"""
    import functools
    import time

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        """Wrapper function for HTTP request tracking."""
        start_time = time.time()
        try:
            result = await func(*args, **kwargs)
            duration = time.time() - start_time

            # Extract request information from arguments
            method = "GET"  # Default
            endpoint = func.__name__
            status_code = 200

            # Try to extract real request information from FastAPI request object
            for arg in args:
                if hasattr(arg, "method") and hasattr(arg, "url"):
                    # This is a FastAPI Request object
                    method = arg.method
                    endpoint = arg.url.path
                    break

            metrics_collector.record_http_request(
                method, endpoint, status_code, duration
            )
            return result
        except Exception as e:
            duration = time.time() - start_time
            metrics_collector.record_http_request("GET", func.__name__, 500, duration)
            metrics_collector.record_error(type(e).__name__, func.__module__)
            raise

    return wrapper


def track_db_operation(operation: str, table: str):
    """Decorator for tracking database operations"""

    def decorator(func):
        import functools
        import time

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            """Wrapper function for database operation tracking."""
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                metrics_collector.record_db_query(operation, table, duration)
                return result
            except Exception as e:
                duration = time.time() - start_time
                metrics_collector.record_db_query(operation, table, duration)
                metrics_collector.record_error(type(e).__name__, func.__module__)
                raise

        return wrapper

    return decorator


def track_async_task(priority: str):
    """Decorator for tracking async tasks"""

    def decorator(func):
        import functools
        import time

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            """Wrapper function for async task tracking."""
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start_time
                metrics_collector.record_async_task(priority, "completed", duration)
                return result
            except Exception as e:
                duration = time.time() - start_time
                metrics_collector.record_async_task(priority, "failed", duration)
                metrics_collector.record_error(type(e).__name__, func.__module__)
                raise

        return wrapper

    return decorator
