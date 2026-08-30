import hmac
import time
from collections import defaultdict

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

from config.logging_config import get_logger
from config.settings import settings

logger = get_logger(__name__)

BRIDGE_SECRET_HEADER = "X-Bridge-Secret"  # noqa: S105 - header name, not a credential
FORWARDING_HEADERS = ("X-Forwarded-For", "X-Real-IP")
LOOPBACK_ADDRESSES = frozenset({"127.0.0.1", "::1", "localhost"})


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
        self.requests: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        """Dispatch.

        Args:
            request: Description of request.
            call_next: Description of call_next.
        """
        # Apply rate limiting only to unauthenticated external webhook calls
        if request.url.path.startswith("/webhook/") and not self._is_exempt(request):
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

    def _is_exempt(self, request: Request) -> bool:
        """Whether the caller is the trusted in-container bridge.

        The bridge posts one webhook per WhatsApp message and legitimately
        bursts past the per-minute budget, so it is exempted - but only when it
        proves itself with the shared secret or reaches us over the loopback
        interface it actually uses. Everything else stays rate limited.
        """
        return self._has_valid_bridge_secret(request) or self._is_loopback_peer(request)

    @staticmethod
    def _has_valid_bridge_secret(request: Request) -> bool:
        """Constant-time check of the bridge shared secret, when configured."""
        configured_secret = getattr(settings, "BRIDGE_WEBHOOK_SECRET", "") or ""
        if not configured_secret:
            return False

        provided_secret = request.headers.get(BRIDGE_SECRET_HEADER)
        if not provided_secret:
            return False

        return hmac.compare_digest(
            provided_secret.encode("utf-8"), configured_secret.encode("utf-8")
        )

    @staticmethod
    def _is_loopback_peer(request: Request) -> bool:
        """Whether the TCP peer itself is loopback.

        Deliberately ignores X-Forwarded-For / X-Real-IP: those are attacker
        controlled, so honouring them here would let any external client claim
        to be 127.0.0.1 and skip the limiter. Their mere presence also means the
        request was proxied rather than sent by the local bridge.
        """
        if any(request.headers.get(header) for header in FORWARDING_HEADERS):
            return False

        peer_host = request.client.host if request.client else None
        return bool(peer_host) and peer_host in LOOPBACK_ADDRESSES

    def _get_client_ip(self, request: Request) -> str:
        """Bucket key for the limiter: the TCP peer, never proxy headers.

        X-Forwarded-For / X-Real-IP are caller controlled, so keying buckets on
        them lets a single client mint a fresh bucket per request and bypass
        the limit entirely. Behind a real proxy this collapses all callers into
        the proxy's bucket, which throttles too much rather than too little.
        """
        return (
            request.client.host if request.client and request.client.host else "unknown"
        )
