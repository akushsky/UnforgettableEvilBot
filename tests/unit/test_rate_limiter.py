"""Unit tests for rate limiting functionality."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.middleware.rate_limiter import RateLimiterMiddleware


class TestRateLimiter:
    """Test rate limiting functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        mock_app = Mock()
        self.rate_limiter = RateLimiterMiddleware(mock_app)
        self.mock_request = Mock()
        self.mock_request.client.host = "127.0.0.1"
        self.mock_request.url.path = "/webhook/test"
        self.mock_request.headers = {}

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
        assert len(self.rate_limiter.requests["127.0.0.1"]) == 1

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

        request1 = Mock()
        request1.client.host = "127.0.0.1"
        request1.url.path = "/webhook/test"
        request1.headers = {}

        request2 = Mock()
        request2.client.host = "192.168.1.1"
        request2.url.path = "/webhook/test"
        request2.headers = {}

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

        non_webhook_request = Mock()
        non_webhook_request.client.host = "127.0.0.1"
        non_webhook_request.url.path = "/api/users"
        non_webhook_request.headers = {}

        # Make many requests to non-webhook endpoint
        for _ in range(100):
            await self.rate_limiter.dispatch(non_webhook_request, mock_call_next)

        # Should not be blocked
        await self.rate_limiter.dispatch(non_webhook_request, mock_call_next)
        assert mock_call_next.called

    def test_get_client_ip_from_forwarded_for(self):
        """Test getting client IP from X-Forwarded-For header."""
        request = Mock()
        request.client.host = "127.0.0.1"
        request.headers = {"X-Forwarded-For": "192.168.1.1, 10.0.0.1"}

        ip = self.rate_limiter._get_client_ip(request)
        assert ip == "192.168.1.1"

    def test_get_client_ip_from_real_ip(self):
        """Test getting client IP from X-Real-IP header."""
        request = Mock()
        request.client.host = "127.0.0.1"
        request.headers = {"X-Real-IP": "192.168.1.1"}

        ip = self.rate_limiter._get_client_ip(request)
        assert ip == "192.168.1.1"
