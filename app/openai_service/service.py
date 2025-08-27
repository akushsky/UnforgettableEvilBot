import asyncio
from typing import Any, Dict, List

from app.core.base_service import BaseService
from app.middleware.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from app.middleware.openai_rate_limiter import RateLimitExceeded, openai_rate_limiter
from app.openai_service.analyzer import MessageAnalyzer
from app.openai_service.client import OpenAIClient
from config.logging_config import get_logger

logger = get_logger(__name__)


class OpenAIService(BaseService):
    """Main OpenAI service - component coordination"""

    def __init__(self):
        """Init  ."""
        super().__init__()
        self.max_retries = 3
        self.base_delay = 1  # base delay in seconds

        # Initialize components
        self.client = OpenAIClient()
        self.analyzer = MessageAnalyzer(self.client)

        # Circuit Breaker for OpenAI API
        self.circuit_breaker = CircuitBreaker(
            name="OpenAI_API",
            failure_threshold=5,
            recovery_timeout=60,
            expected_exception=Exception,
        )

    async def _retry_with_backoff(self, func, *args, **kwargs):
        """Universal retry function with exponential backoff"""
        for attempt in range(self.max_retries):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                if attempt == self.max_retries - 1:  # last attempt
                    self.logger.error(f"All retry attempts failed: {e}")
                    raise

                delay = self.base_delay * (2**attempt)  # exponential backoff
                self.logger.warning(
                    f"OpenAI request failed (attempt {attempt + 1}), retrying in {delay}s: {e}"
                )
                await asyncio.sleep(delay)

    async def _with_rate_limiting(self, func, *args, **kwargs):
        """Execute function with rate limit check"""
        await openai_rate_limiter.wait_if_needed()
        return await func(*args, **kwargs)

    async def analyze_message_importance(
        self, message: str, chat_context: str = ""
    ) -> int:
        """Analyze message importance using Circuit Breaker and Rate Limiting"""

        async def _analyze():
            """Analyze."""
            return await self.analyzer.analyze_importance(message, chat_context)

        try:
            # Use Circuit Breaker + Retry mechanism
            return await self.circuit_breaker.call(
                lambda: self._retry_with_backoff(self._with_rate_limiting, _analyze)
            )
        except RateLimitExceeded as e:
            self.logger.warning(
                f"Rate limit exceeded for message importance analysis: {e}"
            )
            return 3  # Return average value when limit exceeded
        except (CircuitBreakerOpenError, Exception) as e:
            self.logger.error(
                f"Error analyzing message importance (with circuit breaker): {e}"
            )
            return 3  # Return average value on error

    async def create_digest(self, messages: List[Dict]) -> str:
        """Create digest using Circuit Breaker and Rate Limiting"""

        async def _create():
            """Create."""
            return await self.analyzer.create_digest(messages)

        try:
            # Use Circuit Breaker + Retry mechanism
            return await self.circuit_breaker.call(
                lambda: self._retry_with_backoff(self._with_rate_limiting, _create)
            )
        except RateLimitExceeded as e:
            self.logger.warning(f"Rate limit exceeded for digest creation: {e}")
            return "❌ Digest temporarily unavailable due to API rate limits. Please try later."
        except (CircuitBreakerOpenError, Exception) as e:
            self.logger.error(f"Error creating digest (with circuit breaker): {e}")
            return "❌ Digest temporarily unavailable due to AI service issues. Please try later."

    async def create_digest_by_chats(self, chat_messages: Dict[str, List[Dict]]) -> str:
        """Create digest grouped by chats using Circuit Breaker and Rate Limiting"""

        async def _create():
            """Create."""
            return await self.analyzer.create_digest_by_chats(chat_messages)

        try:
            # Use Circuit Breaker + Retry mechanism
            return await self.circuit_breaker.call(
                lambda: self._retry_with_backoff(self._with_rate_limiting, _create)
            )
        except RateLimitExceeded as e:
            self.logger.warning(f"Rate limit exceeded for digest creation: {e}")
            return "❌ Digest temporarily unavailable due to API rate limits. Please try later."
        except (CircuitBreakerOpenError, Exception) as e:
            self.logger.error(f"Error creating digest (with circuit breaker): {e}")
            return "❌ Digest temporarily unavailable due to AI service issues. Please try later."

    async def translate_to_russian(self, text: str) -> str:
        """Translate text to Russian"""

        async def _translate():
            """Translate."""
            return await self.analyzer.translate_to_russian(text)

        try:
            return await self.circuit_breaker.call(
                lambda: self._retry_with_backoff(self._with_rate_limiting, _translate)
            )
        except (RateLimitExceeded, CircuitBreakerOpenError, Exception) as e:
            self.logger.error(f"Error translating text: {e}")
            return text  # Return original text on error

    async def validate_input(self, data: Any) -> bool:
        """Validate input data"""
        return await self.analyzer.validate_input(data)

    def get_service_status(self) -> Dict:
        """Get service status"""
        return {
            "circuit_breaker_state": self.circuit_breaker.state,
            "failure_count": self.circuit_breaker.failure_count,
            "rate_limiter_stats": openai_rate_limiter.get_stats(),
        }
