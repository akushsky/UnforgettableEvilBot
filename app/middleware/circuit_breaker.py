import inspect
import time
from enum import Enum
from typing import Any, Callable, Optional, Type

from config.logging_config import get_logger

logger = get_logger(__name__)


class CircuitBreakerState(Enum):
    """CircuitBreakerState class."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Circuit broken, requests blocked
    HALF_OPEN = "half_open"  # Test mode


class CircuitBreaker:
    """Circuit Breaker for protection against cascading failures of external APIs"""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,  # Number of errors to open circuit
        recovery_timeout: int = 60,  # Time in seconds before recovery attempt
        expected_exception: Type[Exception] = Exception,
    ):
        """Initialize circuit breaker.

        Args:
            name: Circuit breaker name.
            failure_threshold: Number of failures before opening circuit.
            recovery_timeout: Seconds before attempting recovery.
            expected_exception: Type of exceptions to handle.
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception

        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = CircuitBreakerState.CLOSED

    def _should_attempt_reset(self) -> bool:
        """Checks if circuit breaker reset can be attempted"""
        return (
            self.state == CircuitBreakerState.OPEN
            and self.last_failure_time is not None
            and time.time() - self.last_failure_time >= self.recovery_timeout
        )

    def _record_success(self):
        """Records successful execution"""
        self.failure_count = 0
        self.success_count += 1
        if self.state == CircuitBreakerState.HALF_OPEN:
            logger.info(
                f"Circuit breaker {self.name} recovery successful, closing circuit"
            )
            self.state = CircuitBreakerState.CLOSED

    def _record_failure(self):
        """Records execution error"""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            if self.state == CircuitBreakerState.CLOSED:
                logger.warning(
                    f"Circuit breaker {self.name} opened due to {self.failure_count} failures"
                )
                self.state = CircuitBreakerState.OPEN
            elif self.state == CircuitBreakerState.HALF_OPEN:
                logger.warning(
                    f"Circuit breaker {self.name} failed during recovery, reopening"
                )
                self.state = CircuitBreakerState.OPEN

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function through circuit breaker"""

        # Check circuit breaker state
        if self.state == CircuitBreakerState.OPEN:
            if self._should_attempt_reset():
                logger.info(f"Circuit breaker {self.name} attempting recovery")
                self.state = CircuitBreakerState.HALF_OPEN
            else:
                logger.warning(f"Circuit breaker {self.name} is open, request blocked")
                raise CircuitBreakerOpenError(f"Circuit breaker {self.name} is open")

        try:
            # Execute function and await if it returns an awaitable
            result = func(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result

            self._record_success()
            return result

        except self.expected_exception as e:
            self._record_failure()
            logger.error(f"Circuit breaker {self.name} recorded failure: {e}")
            raise
        except Exception as e:
            # Unexpected errors are not counted in circuit breaker
            logger.error(f"Unexpected error in circuit breaker {self.name}: {e}")
            raise


class CircuitBreakerOpenError(Exception):
    """Error when circuit breaker is open"""
