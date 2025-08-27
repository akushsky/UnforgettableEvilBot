"""
Centralized logging configuration for the WhatsApp Digest System
"""

import json
import logging
import logging.handlers
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from .settings import settings


class StructuredFormatter(logging.Formatter):
    """Formatter for structured logs in JSON format"""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON"""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "message": record.getMessage(),
            "process_id": record.process,
            "thread_id": record.thread,
        }

        # Add additional fields if available
        if hasattr(record, "user_id"):
            log_entry["user_id"] = record.user_id
        if hasattr(record, "request_id"):
            log_entry["request_id"] = record.request_id
        if hasattr(record, "operation"):
            log_entry["operation"] = record.operation
        if hasattr(record, "duration"):
            log_entry["duration_ms"] = record.duration
        if hasattr(record, "error_code"):
            log_entry["error_code"] = record.error_code

        # Add exception info if available
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": self.formatException(record.exc_info),
            }

        return json.dumps(log_entry, ensure_ascii=False)


class HumanReadableFormatter(logging.Formatter):
    """Formatter for human-readable logs"""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record for human reading"""
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")

        # Basic format
        log_line = f"{timestamp} | {record.levelname:8} | {record.name:30} | {record.funcName:20}:{record.lineno:4} | {record.getMessage()}"

        # Add additional fields
        extra_fields = []
        if hasattr(record, "user_id"):
            extra_fields.append(f"user_id={record.user_id}")
        if hasattr(record, "request_id"):
            extra_fields.append(f"request_id={record.request_id}")
        if hasattr(record, "operation"):
            extra_fields.append(f"operation={record.operation}")
        if hasattr(record, "duration"):
            extra_fields.append(f"duration={record.duration}ms")

        if extra_fields:
            log_line += f" | {' | '.join(extra_fields)}"

        # Add exception info if available
        if record.exc_info:
            log_line += f"\n{self.formatException(record.exc_info)}"

        return log_line


class RequestContextFilter(logging.Filter):
    """Filter for adding request context to logs"""

    def __init__(self):
        """Initialize the filter."""
        super().__init__()
        self.request_context = {}

    def filter(self, record: logging.LogRecord) -> bool:
        """Add request context to log record"""
        for key, value in self.request_context.items():
            setattr(record, key, value)
        return True

    def set_context(self, **kwargs):
        """Set context for current request"""
        self.request_context.update(kwargs)

    def clear_context(self):
        """Clear context"""
        self.request_context.clear()


class PerformanceFilter(logging.Filter):
    """Filter for performance logging"""

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter records by performance"""
        # Log all operations longer than 100ms
        if hasattr(record, "duration") and record.duration > 100:
            return True

        # Log all errors
        if record.levelno >= logging.ERROR:
            return True

        # Log important operations
        if hasattr(record, "operation") and record.operation in [
            "database_query",
            "api_call",
            "cache_operation",
        ]:
            return True

        return True


def setup_logging():
    """Setup logging system"""
    # Create logs directory
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL))

    # Clear existing handlers
    root_logger.handlers.clear()

    # Create filters
    request_filter = RequestContextFilter()
    performance_filter = PerformanceFilter()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(HumanReadableFormatter())
    console_handler.addFilter(request_filter)
    console_handler.addFilter(performance_filter)
    root_logger.addHandler(console_handler)

    # JSON logs file handler
    json_handler = logging.handlers.RotatingFileHandler(
        log_dir / "app.json",
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8",
    )
    json_handler.setLevel(logging.DEBUG)
    json_handler.setFormatter(StructuredFormatter())
    json_handler.addFilter(request_filter)
    root_logger.addHandler(json_handler)

    # Error handler
    error_handler = logging.handlers.RotatingFileHandler(
        log_dir / "errors.log",
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=3,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(HumanReadableFormatter())
    error_handler.addFilter(request_filter)
    root_logger.addHandler(error_handler)

    # Performance handler
    perf_handler = logging.handlers.RotatingFileHandler(
        log_dir / "performance.log",
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=3,
        encoding="utf-8",
    )
    perf_handler.setLevel(logging.INFO)
    perf_handler.setFormatter(StructuredFormatter())
    perf_handler.addFilter(performance_filter)
    root_logger.addHandler(perf_handler)

    # Configure logging for third-party libraries
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

    # Global variables for filter access
    global request_context_filter
    request_context_filter = request_filter


def get_logger(name: str) -> logging.Logger:
    """Get logger with name"""
    return logging.getLogger(name)


def log_with_context(logger: logging.Logger, level: int, message: str, **context):
    """Logging with additional context"""
    extra = {}
    for key, value in context.items():
        extra[key] = value

    logger.log(level, message, extra=extra)


def log_performance(logger: logging.Logger, operation: str, duration: float, **context):
    """Performance logging for operations"""
    log_with_context(
        logger,
        logging.INFO,
        f"Performance: {operation} completed in {duration:.2f}ms",
        operation=operation,
        duration=duration,
        **context,
    )


def log_error(logger: logging.Logger, message: str, error: Exception, **context):
    """Error logging with context"""
    log_with_context(
        logger,
        logging.ERROR,
        f"Error: {message}",
        error_code=type(error).__name__,
        **context,
        exc_info=True,
    )


def log_request(
    logger: logging.Logger,
    method: str,
    path: str,
    status_code: int,
    duration: float,
    **context,
):
    """HTTP request logging"""
    log_with_context(
        logger,
        logging.INFO,
        f"Request: {method} {path} -> {status_code} ({duration:.2f}ms)",
        operation="http_request",
        duration=duration,
        method=method,
        path=path,
        status_code=status_code,
        **context,
    )


def log_database_operation(
    logger: logging.Logger, operation: str, table: str, duration: float, **context
):
    """Database operation logging"""
    log_with_context(
        logger,
        logging.INFO,
        f"Database: {operation} on {table} completed in {duration:.2f}ms",
        operation="database_query",
        duration=duration,
        table=table,
        query_type=operation,
        **context,
    )


def log_cache_operation(
    logger: logging.Logger,
    operation: str,
    key: str,
    hit: bool,
    duration: float,
    **context,
):
    """Cache operation logging"""
    status = "HIT" if hit else "MISS"
    log_with_context(
        logger,
        logging.DEBUG,
        f"Cache: {operation} {key} -> {status} ({duration:.2f}ms)",
        operation="cache_operation",
        duration=duration,
        cache_key=key,
        cache_hit=hit,
        **context,
    )


def log_api_call(
    logger: logging.Logger,
    service: str,
    endpoint: str,
    duration: float,
    success: bool,
    **context,
):
    """External API call logging"""
    status = "SUCCESS" if success else "FAILED"
    log_with_context(
        logger,
        logging.INFO,
        f"API: {service} {endpoint} -> {status} ({duration:.2f}ms)",
        operation="api_call",
        duration=duration,
        service=service,
        endpoint=endpoint,
        success=success,
        **context,
    )


# Global variable for context filter access
request_context_filter: Optional[RequestContextFilter] = None
