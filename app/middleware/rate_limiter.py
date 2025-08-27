import time
from collections import defaultdict
from typing import Dict, List

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

from config.logging_config import get_logger

logger = get_logger(__name__)


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """Middleware for request rate limiting"""

    def __init__(self, app, calls_per_minute: int = 60):
        """Init  .

        Args:
            app: Description of app.
            calls_per_minute: Description of calls_per_minute.
        """
        super().__init__(app)
        self.calls_per_minute = calls_per_minute
        self.requests: Dict[str, List[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        """Dispatch.

        Args:
            request: Description of request.
            call_next: Description of call_next.
        """
        # Apply rate limiting only to webhook endpoints
        if request.url.path.startswith("/webhook/"):
            client_ip = self._get_client_ip(request)
            current_time = time.time()

            # Clean old records (older than 1 minute)
            cutoff_time = current_time - 60
            self.requests[client_ip] = [
                req_time
                for req_time in self.requests[client_ip]
                if req_time > cutoff_time
            ]

            # Check limit
            if len(self.requests[client_ip]) >= self.calls_per_minute:
                logger.info(
                    f"⚠️ Rate limit protection activated for IP {client_ip} - blocking excessive requests"
                )
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Maximum {self.calls_per_minute} requests per minute",
                )

            # Add current request
            self.requests[client_ip].append(current_time)

        response = await call_next(request)
        return response

    def _get_client_ip(self, request: Request) -> str:
        """Get client IP considering proxy headers"""
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        return (
            request.client.host if request.client and request.client.host else "unknown"
        )
