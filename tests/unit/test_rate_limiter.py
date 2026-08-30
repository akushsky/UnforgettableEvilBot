"""Unit tests for rate limiting functionality."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException

from app.middleware.rate_limiter import RateLimiterMiddleware

EXTERNAL_IP = "203.0.113.10"


def _make_request(path="/webhook/test", host=EXTERNAL_IP, headers=None):
    """Build a mock request for the middleware."""
    request = Mock()
    request.client.host = host
    request.url.path = path
    request.headers = headers or {}
    return request


class TestRateLimiter:
    """Test rate limiting functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        mock_app = Mock()
        self.rate_limiter = RateLimiterMiddleware(mock_app)
        self.mock_request = _make_request()

    def test_rate_limiter_initialization(self):
        """Test rate limiter initialization."""
        assert hasattr(self.rate_limiter, "calls_per_minute")
        assert hasattr(self.rate_limiter, "requests")
        assert self.rate_limiter.calls_per_minute == 60

    @pytest.mark.asyncio
    async def test_rate_limiter_allows_first_request(self):
        """Test that first request is allowed."""
        mock_call_next = AsyncMock()

        await self.rate_limiter.dispatch(self.mock_request, mock_call_next)

        assert mock_call_next.called
        assert len(self.rate_limiter.requests[EXTERNAL_IP]) == 1

    @pytest.mark.asyncio
    async def test_rate_limiter_blocks_excessive_requests(self):
        """Test that excessive requests are blocked."""
        mock_call_next = AsyncMock()

        # Make 60 requests (at the limit)
        for _ in range(60):
            await self.rate_limiter.dispatch(self.mock_request, mock_call_next)

        # Next request should be blocked
        with pytest.raises(Exception) as exc_info:
            await self.rate_limiter.dispatch(self.mock_request, mock_call_next)

        assert "Rate limit exceeded" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_rate_limiter_resets_after_window(self):
        """Test that rate limiter resets after time window."""
        mock_call_next = AsyncMock()

        # Make some requests
        for _ in range(10):
            await self.rate_limiter.dispatch(self.mock_request, mock_call_next)

        # Mock time to be 61 seconds later
        with patch("time.time") as mock_time:
            mock_time.return_value = 100.0  # Fixed time value
            await self.rate_limiter.dispatch(self.mock_request, mock_call_next)
            assert mock_call_next.called

    @pytest.mark.asyncio
    async def test_different_ips_have_separate_limits(self):
        """Test that different IPs have separate rate limits."""
        mock_call_next = AsyncMock()

        request1 = _make_request(host="198.51.100.7")
        request2 = _make_request(host="192.168.1.1")

        # Make requests from different IPs
        for _ in range(30):
            await self.rate_limiter.dispatch(request1, mock_call_next)
            await self.rate_limiter.dispatch(request2, mock_call_next)

        # Both should still be allowed
        await self.rate_limiter.dispatch(request1, mock_call_next)
        await self.rate_limiter.dispatch(request2, mock_call_next)

        assert mock_call_next.called

    @pytest.mark.asyncio
    async def test_non_webhook_endpoints_not_limited(self):
        """Test that non-webhook endpoints are not rate limited."""
        mock_call_next = AsyncMock()

        non_webhook_request = _make_request(path="/api/users")

        # Make many requests to non-webhook endpoint
        for _ in range(100):
            await self.rate_limiter.dispatch(non_webhook_request, mock_call_next)

        # Should not be blocked
        await self.rate_limiter.dispatch(non_webhook_request, mock_call_next)
        assert mock_call_next.called

    def test_get_client_ip_ignores_forwarded_for(self):
        """X-Forwarded-For is caller controlled and must not key the bucket."""
        request = _make_request(
            host=EXTERNAL_IP, headers={"X-Forwarded-For": "192.168.1.1, 10.0.0.1"}
        )

        ip = self.rate_limiter._get_client_ip(request)
        assert ip == EXTERNAL_IP

    def test_get_client_ip_ignores_real_ip(self):
        """X-Real-IP is caller controlled and must not key the bucket."""
        request = _make_request(host=EXTERNAL_IP, headers={"X-Real-IP": "192.168.1.1"})

        ip = self.rate_limiter._get_client_ip(request)
        assert ip == EXTERNAL_IP

    def test_get_client_ip_falls_back_when_peer_is_unknown(self):
        """A request without a TCP peer still lands in a single bucket."""
        request = _make_request()
        request.client = None

        assert self.rate_limiter._get_client_ip(request) == "unknown"

    @pytest.mark.asyncio
    async def test_rotating_forwarded_for_cannot_escape_the_limit(self):
        """One peer forging a new X-Forwarded-For per request stays in one bucket."""
        mock_call_next = AsyncMock()

        for i in range(60):
            await self.rate_limiter.dispatch(
                _make_request(headers={"X-Forwarded-For": f"10.0.0.{i}"}),
                mock_call_next,
            )

        with pytest.raises(HTTPException) as exc_info:
            await self.rate_limiter.dispatch(
                _make_request(headers={"X-Forwarded-For": "10.0.1.1"}),
                mock_call_next,
            )

        assert exc_info.value.status_code == 429
        assert len(self.rate_limiter.requests[EXTERNAL_IP]) == 60


class TestRateLimiterExemptions:
    """Test that trusted bridge traffic bypasses the limiter."""

    def setup_method(self):
        """Set up test fixtures."""
        self.rate_limiter = RateLimiterMiddleware(Mock())

    @staticmethod
    def _secret(value: str):
        """Patch the configured bridge secret."""
        from config.settings import settings

        return patch.object(settings, "BRIDGE_WEBHOOK_SECRET", value)

    async def _flood(self, request, count=70):
        """Send more requests than the per-minute budget allows."""
        mock_call_next = AsyncMock()
        for _ in range(count):
            await self.rate_limiter.dispatch(request, mock_call_next)
        return mock_call_next

    @pytest.mark.asyncio
    async def test_loopback_peer_is_exempt(self):
        """Test that the in-container bridge on loopback is never throttled."""
        request = _make_request(host="127.0.0.1")

        with self._secret(""):
            mock_call_next = await self._flood(request)

        assert mock_call_next.await_count == 70
        assert self.rate_limiter.requests == {}

    @pytest.mark.asyncio
    async def test_ipv6_loopback_peer_is_exempt(self):
        """Test that ::1 is treated as loopback too."""
        request = _make_request(host="::1")

        with self._secret(""):
            mock_call_next = await self._flood(request)

        assert mock_call_next.await_count == 70

    @pytest.mark.asyncio
    async def test_valid_bridge_secret_is_exempt(self):
        """Test that an authenticated bridge from any IP is not throttled."""
        request = _make_request(headers={"X-Bridge-Secret": "s3cret-token"})

        with self._secret("s3cret-token"):
            mock_call_next = await self._flood(request)

        assert mock_call_next.await_count == 70

    @pytest.mark.asyncio
    async def test_wrong_bridge_secret_is_rate_limited(self):
        """Test that an invalid secret does not buy an exemption."""
        request = _make_request(headers={"X-Bridge-Secret": "wrong-token"})

        with self._secret("s3cret-token"), pytest.raises(HTTPException) as exc_info:
            await self._flood(request)

        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_secret_header_ignored_when_not_configured(self):
        """Test that an unset secret cannot be matched by an empty header."""
        request = _make_request(headers={"X-Bridge-Secret": ""})

        with self._secret(""), pytest.raises(HTTPException) as exc_info:
            await self._flood(request)

        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_spoofed_forwarded_for_loopback_is_rate_limited(self):
        """Test that a forged X-Forwarded-For cannot fake a loopback peer."""
        request = _make_request(
            host=EXTERNAL_IP, headers={"X-Forwarded-For": "127.0.0.1"}
        )

        with self._secret(""), pytest.raises(HTTPException) as exc_info:
            await self._flood(request)

        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_proxied_request_claiming_loopback_peer_is_rate_limited(self):
        """Test that proxy headers disable the loopback exemption entirely."""
        request = _make_request(host="127.0.0.1", headers={"X-Real-IP": EXTERNAL_IP})

        with self._secret(""), pytest.raises(HTTPException) as exc_info:
            await self._flood(request)

        assert exc_info.value.status_code == 429
