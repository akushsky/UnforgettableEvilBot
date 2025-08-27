import asyncio
import json
import threading
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from config.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class TraceSpan:
    """Tracing span for tracking operations"""

    span_id: str
    trace_id: str
    operation_name: str
    start_time: float
    end_time: Optional[float] = None
    duration: Optional[float] = None
    tags: Dict[str, Any] = field(default_factory=dict)
    logs: List[Dict[str, Any]] = field(default_factory=list)
    parent_span_id: Optional[str] = None
    error: Optional[str] = None
    status: str = "active"  # active, completed, error


class TraceContext:
    """Tracing context for a single request"""

    def __init__(self, trace_id: str):
        """Init  .

        Args:
            trace_id: Description of trace_id.
        """
        self.trace_id = trace_id
        self.spans: Dict[str, TraceSpan] = {}
        self.current_span_id: Optional[str] = None
        self.start_time = time.time()
        self.end_time: Optional[float] = None

    def add_span(self, span: TraceSpan):
        """Add span to context"""
        self.spans[span.span_id] = span

    def get_span(self, span_id: str) -> Optional[TraceSpan]:
        """Get span by ID"""
        return self.spans.get(span_id)

    def set_current_span(self, span_id: str):
        """Set current active span"""
        self.current_span_id = span_id

    def get_current_span(self) -> Optional[TraceSpan]:
        """Get current active span"""
        if self.current_span_id:
            return self.spans.get(self.current_span_id)
        return None

    def complete(self):
        """Complete trace"""
        self.end_time = time.time()

    def get_duration(self) -> float:
        """Get total trace duration"""
        end_time = self.end_time or time.time()
        return end_time - self.start_time

    def to_dict(self) -> Dict[str, Any]:
        """Convert trace to dictionary"""
        return {
            "trace_id": self.trace_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.get_duration(),
            "spans": [span.__dict__ for span in self.spans.values()],
            "span_count": len(self.spans),
        }


class TraceManager:
    """Tracing manager for managing traces"""

    def __init__(self):
        """Init  ."""
        self.logger = get_logger(__name__)
        self.active_traces: Dict[str, TraceContext] = {}
        self.completed_traces: List[TraceContext] = []
        self.max_completed_traces = 1000  # Maximum number of saved traces
        self._lock = threading.Lock()

    def create_trace(self, trace_id: Optional[str] = None) -> TraceContext:
        """Create new trace"""
        if not trace_id:
            trace_id = str(uuid.uuid4())

        trace_context = TraceContext(trace_id)

        with self._lock:
            self.active_traces[trace_id] = trace_context

        self.logger.debug(f"Created trace: {trace_id}")
        return trace_context

    def get_trace(self, trace_id: str) -> Optional[TraceContext]:
        """Get trace by ID"""
        with self._lock:
            return self.active_traces.get(trace_id)

    def complete_trace(self, trace_id: str):
        """Complete trace"""
        with self._lock:
            if trace_id in self.active_traces:
                trace = self.active_traces.pop(trace_id)
                trace.complete()
                self.completed_traces.append(trace)

                # Limit the number of saved traces
                if len(self.completed_traces) > self.max_completed_traces:
                    self.completed_traces.pop(0)

                self.logger.debug(
                    f"Completed trace: {trace_id}, duration: {trace.get_duration():.3f}s"
                )

    def create_span(
        self,
        trace_id: str,
        operation_name: str,
        parent_span_id: Optional[str] = None,
        **tags,
    ) -> TraceSpan:
        """Create a new span"""
        span_id = str(uuid.uuid4())
        span = TraceSpan(
            span_id=span_id,
            trace_id=trace_id,
            operation_name=operation_name,
            start_time=time.time(),
            parent_span_id=parent_span_id,
            tags=tags,
        )

        trace = self.get_trace(trace_id)
        if trace:
            trace.add_span(span)
            trace.set_current_span(span_id)

        self.logger.debug(f"Created span: {span_id} for operation: {operation_name}")
        return span

    def complete_span(self, span_id: str, error: Optional[str] = None, **tags):
        """Finish a span"""
        # Look for the span in all active traces
        for trace in self.active_traces.values():
            span = trace.get_span(span_id)
            if span:
                span.end_time = time.time()
                span.duration = span.end_time - span.start_time
                span.status = "error" if error else "completed"
                span.error = error
                span.tags.update(tags)

                self.logger.debug(
                    f"Completed span: {span_id}, duration: {span.duration:.3f}s"
                )
                break

    def add_span_log(self, span_id: str, message: str, level: str = "info", **fields):
        """Add a log entry to a span"""
        for trace in self.active_traces.values():
            span = trace.get_span(span_id)
            if span:
                log_entry = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "level": level,
                    "message": message,
                    **fields,
                }
                span.logs.append(log_entry)
                break

    def get_trace_summary(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """Get a trace summary"""
        trace = self.get_trace(trace_id)
        if trace:
            return trace.to_dict()

        # Look in completed traces
        for completed_trace in self.completed_traces:
            if completed_trace.trace_id == trace_id:
                return completed_trace.to_dict()

        return None

    def get_recent_traces(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get the latest traces"""
        recent_traces = []

        # Active traces
        for trace in self.active_traces.values():
            recent_traces.append(trace.to_dict())

        # Completed traces
        for trace in reversed(self.completed_traces[-limit:]):
            recent_traces.append(trace.to_dict())

        # Sort by start time
        recent_traces.sort(key=lambda x: x["start_time"], reverse=True)

        return recent_traces[:limit]

    def export_trace(self, trace_id: str) -> Optional[str]:
        """Export trace to JSON"""
        trace_data = self.get_trace_summary(trace_id)
        if trace_data:
            return json.dumps(trace_data, indent=2, ensure_ascii=False)
        return None


# Global instance of the tracing manager
trace_manager = TraceManager()


# Decorators for automatic tracing
def trace_operation(operation_name: str):
    """Decorator for tracing operations"""

    def decorator(func):
        """Decorator function.

        Args:
            func: Description of func.
        """
        import functools

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            """Async Wrapper."""
            # Get trace_id from context or create a new one
            trace_id = getattr(threading.current_thread(), "_trace_id", None)
            if not trace_id:
                trace_context = trace_manager.create_trace()
                trace_id = trace_context.trace_id
                setattr(threading.current_thread(), "_trace_id", trace_id)

            # Create a span
            span = trace_manager.create_span(trace_id, operation_name)

            try:
                result = await func(*args, **kwargs)
                trace_manager.complete_span(span.span_id)
                return result
            except Exception as e:
                trace_manager.complete_span(span.span_id, error=str(e))
                raise

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            """Sync Wrapper."""
            # Get trace_id from context or create a new one
            trace_id = getattr(threading.current_thread(), "_trace_id", None)
            if not trace_id:
                trace_context = trace_manager.create_trace()
                trace_id = trace_context.trace_id
                setattr(threading.current_thread(), "_trace_id", trace_id)

            # Create a span
            span = trace_manager.create_span(trace_id, operation_name)

            try:
                result = func(*args, **kwargs)
                trace_manager.complete_span(span.span_id)
                return result
            except Exception as e:
                trace_manager.complete_span(span.span_id, error=str(e))
                raise

        # Return an async or sync wrapper
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


@asynccontextmanager
async def trace_span(operation_name: str, **tags):
    """Context manager for creating a span"""
    trace_id = getattr(threading.current_thread(), "_trace_id", None)
    if not trace_id:
        trace_context = trace_manager.create_trace()
        trace_id = trace_context.trace_id
        setattr(threading.current_thread(), "_trace_id", trace_id)

    span = trace_manager.create_span(trace_id, operation_name, **tags)

    try:
        yield span
        trace_manager.complete_span(span.span_id)
    except Exception as e:
        trace_manager.complete_span(span.span_id, error=str(e))
        raise


@contextmanager
def trace_span_sync(operation_name: str, **tags):
    """Synchronous context manager for creating a span"""
    trace_id = getattr(threading.current_thread(), "_trace_id", None)
    if not trace_id:
        trace_context = trace_manager.create_trace()
        trace_id = trace_context.trace_id
        setattr(threading.current_thread(), "_trace_id", trace_id)

    span = trace_manager.create_span(trace_id, operation_name, **tags)

    try:
        yield span
        trace_manager.complete_span(span.span_id)
    except Exception as e:
        trace_manager.complete_span(span.span_id, error=str(e))
        raise


def set_trace_context(trace_id: str):
    """Set tracing context for the current thread"""
    setattr(threading.current_thread(), "_trace_id", trace_id)


def get_current_trace_id() -> Optional[str]:
    """Get the current trace ID"""
    return getattr(threading.current_thread(), "_trace_id", None)


def log_trace_event(message: str, level: str = "info", **fields):
    """Log an event to the current span"""
    trace_id = get_current_trace_id()
    if trace_id:
        trace = trace_manager.get_trace(trace_id)
        if trace:
            current_span = trace.get_current_span()
            if current_span:
                trace_manager.add_span_log(
                    current_span.span_id, message, level, **fields
                )
