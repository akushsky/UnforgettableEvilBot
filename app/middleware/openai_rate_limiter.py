import asyncio
import time
from typing import List

from config.logging_config import get_logger

logger = get_logger(__name__)


class RateLimitExceeded(Exception):
    """Exception when rate limit is exceeded"""


class OpenAIRateLimiter:
    """Rate limiter for OpenAI API requests"""

    def __init__(self, requests_per_minute: int = 60, requests_per_hour: int = 1000):
        """Init  .

        Args:
            requests_per_minute: Description of requests_per_minute.
            requests_per_hour: Description of requests_per_hour.
        """
        self.requests_per_minute = requests_per_minute
        self.requests_per_hour = requests_per_hour
        self.request_times: List[float] = []
        self._lock = asyncio.Lock()

    async def check_rate_limit(self) -> bool:
        """Check request rate limits"""
        async with self._lock:
            now = time.time()

            # Remove old requests (older than 1 hour)
            self.request_times = [t for t in self.request_times if now - t < 3600]

            # Check hourly limit
            if len(self.request_times) >= self.requests_per_hour:
                logger.warning(
                    f"Hourly rate limit exceeded: {len(self.request_times)} requests"
                )
                raise RateLimitExceeded("Hourly rate limit exceeded")

            # Check minute limit
            recent_requests = [t for t in self.request_times if now - t < 60]
            if len(recent_requests) >= self.requests_per_minute:
                logger.warning(
                    f"Minute rate limit exceeded: {len(recent_requests)} requests"
                )
                raise RateLimitExceeded("Minute rate limit exceeded")

            # Add current request
            self.request_times.append(now)
            return True

    async def wait_if_needed(self) -> None:
        """Wait if rate limit is reached"""
        try:
            await self.check_rate_limit()
        except RateLimitExceeded:
            # Wait until next minute
            now = time.time()
            wait_time = 60 - (now % 60)
            logger.info(f"Rate limit reached, waiting {wait_time:.1f} seconds")
            await asyncio.sleep(wait_time)
            await self.check_rate_limit()

    def get_stats(self) -> dict:
        """Get usage statistics"""
        now = time.time()
        recent_minute = [t for t in self.request_times if now - t < 60]
        recent_hour = [t for t in self.request_times if now - t < 3600]

        return {
            "requests_last_minute": len(recent_minute),
            "requests_last_hour": len(recent_hour),
            "minute_limit": self.requests_per_minute,
            "hour_limit": self.requests_per_hour,
            "minute_remaining": max(0, self.requests_per_minute - len(recent_minute)),
            "hour_remaining": max(0, self.requests_per_hour - len(recent_hour)),
        }


# Global rate limiter instance
openai_rate_limiter = OpenAIRateLimiter()
