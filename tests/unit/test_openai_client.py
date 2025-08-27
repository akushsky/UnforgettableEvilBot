from unittest.mock import AsyncMock, Mock, patch

import pytest
from openai import AsyncOpenAI

from app.openai_service.client import OpenAIClient


class TestOpenAIClient:
    def setup_method(self):
        """Set up test fixtures"""
        with patch("app.openai_service.client.settings") as mock_settings:
            mock_settings.OPENAI_API_KEY = "test-api-key"
            self.client = OpenAIClient()

    def test_initialization_success(self):
        """Test successful client initialization"""
        with patch("app.openai_service.client.settings") as mock_settings:
            mock_settings.OPENAI_API_KEY = "test-api-key"
            client = OpenAIClient()

            assert client.client is not None
            assert isinstance(client.client, AsyncOpenAI)

    def test_initialization_missing_api_key(self):
        """Test client initialization with missing API key"""
        with patch("app.openai_service.client.settings") as mock_settings:
            mock_settings.OPENAI_API_KEY = None

            with pytest.raises(
                ValueError, match="OPENAI_API_KEY is required but not configured"
            ):
                OpenAIClient()

    def test_initialization_empty_api_key(self):
        """Test client initialization with empty API key"""
        with patch("app.openai_service.client.settings") as mock_settings:
            mock_settings.OPENAI_API_KEY = ""

            with pytest.raises(
                ValueError, match="OPENAI_API_KEY is required but not configured"
            ):
                OpenAIClient()

    @pytest.mark.asyncio
    async def test_make_request_success(self):
        """Test successful API request"""
        # Mock the OpenAI response
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "Test response"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 20
        mock_response.usage.total_tokens = 30

        # Mock the client
        self.client.client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )

        # Mock the openai_monitor
        with patch("app.openai_service.client.openai_monitor") as mock_monitor:
            with patch.object(self.client, "log_operation") as mock_log:
                result = await self.client.make_request("Test prompt")

                assert result == "Test response"

                # Verify the API call
                self.client.client.chat.completions.create.assert_called_once_with(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": "Test prompt"}],
                    max_tokens=1000,
                    temperature=0.3,
                )

                # Verify metrics recording
                mock_monitor.record_request.assert_called_once_with(
                    model="gpt-4o-mini", input_tokens=10, output_tokens=20, success=True
                )

                # Verify logging
                mock_log.assert_called_once_with(
                    "openai_request", {"model": "gpt-4o-mini", "tokens_used": 30}
                )

    @pytest.mark.asyncio
    async def test_make_request_custom_parameters(self):
        """Test API request with custom parameters"""
        # Mock the OpenAI response
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "Custom response"
        mock_response.usage.prompt_tokens = 15
        mock_response.usage.completion_tokens = 25
        mock_response.usage.total_tokens = 40

        # Mock the client
        self.client.client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )

        # Mock the openai_monitor
        with patch("app.openai_service.client.openai_monitor") as mock_monitor:
            result = await self.client.make_request(
                "Custom prompt", model="gpt-4", max_tokens=200, temperature=0.7
            )

            assert result == "Custom response"

            # Verify the API call with custom parameters
            self.client.client.chat.completions.create.assert_called_once_with(
                model="gpt-4",
                messages=[{"role": "user", "content": "Custom prompt"}],
                max_tokens=200,
                temperature=0.7,
            )

            # Verify metrics recording
            mock_monitor.record_request.assert_called_once_with(
                model="gpt-4", input_tokens=15, output_tokens=25, success=True
            )

    @pytest.mark.asyncio
    async def test_make_request_failure(self):
        """Test API request failure"""
        # Mock the client to raise an exception
        self.client.client.chat.completions.create = AsyncMock(
            side_effect=Exception("API Error")
        )

        # Mock the openai_monitor
        with patch("app.openai_service.client.openai_monitor") as mock_monitor:
            with patch.object(self.client.logger, "error") as mock_logger:
                with pytest.raises(Exception, match="API Error"):
                    await self.client.make_request("Test prompt")

                # Verify failed metrics recording
                mock_monitor.record_request.assert_called_once_with(
                    model="gpt-4o-mini",
                    input_tokens=0,
                    output_tokens=0,
                    success=False,
                    error="API Error",
                )

                # Verify error logging
                mock_logger.assert_called_once_with(
                    "OpenAI API request failed: API Error"
                )

    @pytest.mark.asyncio
    async def test_make_request_strips_whitespace(self):
        """Test that response content is stripped of whitespace"""
        # Mock the OpenAI response with whitespace
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "  Test response  \n"
        mock_response.usage.prompt_tokens = 5
        mock_response.usage.completion_tokens = 10
        mock_response.usage.total_tokens = 15

        # Mock the client
        self.client.client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )

        # Mock the openai_monitor
        with patch("app.openai_service.client.openai_monitor"):
            result = await self.client.make_request("Test prompt")

            assert result == "Test response"

    @pytest.mark.asyncio
    async def test_validate_input_valid_string(self):
        """Test input validation with valid string"""
        result = await self.client.validate_input("Valid input string")
        assert result

    @pytest.mark.asyncio
    async def test_validate_input_empty_string(self):
        """Test input validation with empty string"""
        result = await self.client.validate_input("")
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_input_non_string(self):
        """Test input validation with non-string input"""
        result = await self.client.validate_input(123)
        assert result is False

        result = await self.client.validate_input(None)
        assert result is False

        result = await self.client.validate_input([])
        assert result is False

        result = await self.client.validate_input({})
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_input_whitespace_only(self):
        """Test input validation with whitespace-only string"""
        result = await self.client.validate_input("   \n\t  ")
        assert result  # This should be valid as it's a non-empty string
