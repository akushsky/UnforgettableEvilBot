"""Unit tests for OpenAI service functionality."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.middleware.circuit_breaker import CircuitBreakerOpenError
from app.middleware.openai_rate_limiter import RateLimitExceeded
from app.openai_service.analyzer import MessageAnalyzer
from app.openai_service.service import OpenAIService


class TestMessageAnalyzer:
    def setup_method(self):
        self.mock_client = Mock()
        self.analyzer = MessageAnalyzer(self.mock_client)

    def test_build_importance_prompt(self):
        """Test importance prompt building"""
        message = "Test message"
        chat_context = "Test context"
        prompt = self.analyzer._build_importance_prompt(message, chat_context)

        assert "Analyze the importance of this message" in prompt
        assert message in prompt
        assert chat_context in prompt
        assert "Answer only with a number from 1 to 5" in prompt

    def test_build_digest_prompt(self):
        """Test digest prompt building"""
        messages = [
            {"chat_name": "Chat1", "sender": "User1", "content": "Message1"},
            {"chat_name": "Chat2", "sender": "User2", "content": "Message2"},
        ]
        prompt = self.analyzer._build_digest_prompt(messages)

        assert "Create a brief digest" in prompt
        assert "Chat1" in prompt
        assert "Chat2" in prompt
        assert "Message1" in prompt
        assert "Message2" in prompt

    def test_build_digest_by_chats_prompt(self):
        """Test digest by chats prompt building"""
        chat_messages = {
            "Chat1": [
                {"content": "Message1", "importance": 4},
                {"content": "Message2", "importance": 5},
            ],
            "Chat2": [{"content": "Message3", "importance": 3}],
        }
        prompt = self.analyzer._build_digest_by_chats_prompt(chat_messages)

        assert "Create a structured digest" in prompt
        assert "Chat1" in prompt
        assert "Chat2" in prompt
        assert "Message1" in prompt
        assert "Message2" in prompt
        assert "Message3" in prompt

    def test_build_translation_prompt(self):
        """Test translation prompt building"""
        text = "Hello world"
        prompt = self.analyzer._build_translation_prompt(text)

        assert "Translate the following text" in prompt
        assert text in prompt
        assert "Translate only the text" in prompt

    def test_parse_importance_valid(self):
        """Test parsing valid importance scores"""
        assert self.analyzer._parse_importance("1") == 1
        assert self.analyzer._parse_importance("3") == 3
        assert self.analyzer._parse_importance("5") == 5

    def test_parse_importance_invalid(self):
        """Test parsing invalid importance scores"""
        assert self.analyzer._parse_importance("invalid") == 3
        assert self.analyzer._parse_importance("") == 3
        assert self.analyzer._parse_importance("0") == 1  # Clamped to minimum
        assert self.analyzer._parse_importance("10") == 5  # Clamped to maximum

    @patch.object(MessageAnalyzer, "validate_input")
    async def test_analyze_importance_success(self, mock_validate):
        """Test successful importance analysis"""
        mock_validate.return_value = True
        self.mock_client.make_request = AsyncMock(return_value="4")

        result = await self.analyzer.analyze_importance("Test message", "Test context")

        assert result == 4
        self.mock_client.make_request.assert_called_once()
        mock_validate.assert_called_once_with("Test message")

    @patch.object(MessageAnalyzer, "validate_input")
    async def test_analyze_importance_invalid_input(self, mock_validate):
        """Test importance analysis with invalid input"""
        mock_validate.return_value = False

        result = await self.analyzer.analyze_importance("", "Test context")

        assert result == 3
        self.mock_client.make_request.assert_not_called()

    @patch.object(MessageAnalyzer, "validate_input")
    async def test_create_digest_success(self, mock_validate):
        """Test successful digest creation"""
        mock_validate.return_value = True
        messages = [{"chat_name": "Chat1", "sender": "User1", "content": "Message1"}]
        self.mock_client.make_request = AsyncMock(return_value="Test digest")

        result = await self.analyzer.create_digest(messages)

        assert result == "Test digest"
        self.mock_client.make_request.assert_called_once()

    async def test_create_digest_empty_messages(self):
        """Test digest creation with empty messages"""
        result = await self.analyzer.create_digest([])

        assert "Нет новых важных сообщений" in result
        self.mock_client.make_request.assert_not_called()

    @patch.object(MessageAnalyzer, "validate_input")
    async def test_create_digest_invalid_input(self, mock_validate):
        """Test digest creation with invalid input"""
        mock_validate.return_value = False
        messages = [{"chat_name": "Chat1", "sender": "User1", "content": "Message1"}]

        result = await self.analyzer.create_digest(messages)

        assert "Ошибка при создании дайджеста" in result
        self.mock_client.make_request.assert_not_called()

    @patch.object(MessageAnalyzer, "validate_input")
    async def test_create_digest_by_chats_success(self, mock_validate):
        """Test successful digest creation by chats"""
        mock_validate.return_value = True
        chat_messages = {
            "Chat1": [{"content": "Message1", "importance": 4}],
            "Chat2": [{"content": "Message2", "importance": 5}],
        }
        self.mock_client.make_request = AsyncMock(return_value="Test digest by chats")

        result = await self.analyzer.create_digest_by_chats(chat_messages)

        assert result == "Test digest by chats"
        self.mock_client.make_request.assert_called_once()

    async def test_create_digest_by_chats_empty(self):
        """Test digest creation by chats with empty data"""
        result = await self.analyzer.create_digest_by_chats({})

        assert "Нет новых важных сообщений" in result
        self.mock_client.make_request.assert_not_called()

    async def test_create_digest_by_chats_empty_messages(self):
        """Test digest creation by chats with empty messages"""
        chat_messages: dict[str, list] = {"Chat1": [], "Chat2": []}

        result = await self.analyzer.create_digest_by_chats(chat_messages)

        assert "Нет новых важных сообщений" in result
        self.mock_client.make_request.assert_not_called()

    @patch.object(MessageAnalyzer, "validate_input")
    async def test_translate_to_russian_success(self, mock_validate):
        """Test successful translation"""
        mock_validate.return_value = True
        self.mock_client.make_request = AsyncMock(return_value="Hello world")

        result = await self.analyzer.translate_to_russian("Hello world")

        assert result == "Hello world"
        self.mock_client.make_request.assert_called_once()

    @patch.object(MessageAnalyzer, "validate_input")
    async def test_translate_to_russian_invalid_input(self, mock_validate):
        """Test translation with invalid input"""
        mock_validate.return_value = False

        result = await self.analyzer.translate_to_russian("")

        assert result == ""
        self.mock_client.make_request.assert_not_called()

    async def test_validate_input_string(self):
        """Test input validation for strings"""
        assert await self.analyzer.validate_input("valid string")
        assert await self.analyzer.validate_input("") is False
        assert await self.analyzer.validate_input("   ") is False

    async def test_validate_input_list(self):
        """Test input validation for lists"""
        valid_list = [{"key": "value"}]
        invalid_list = ["not dict"]
        empty_list: list = []

        assert await self.analyzer.validate_input(valid_list)
        assert await self.analyzer.validate_input(invalid_list) is False
        assert await self.analyzer.validate_input(empty_list) is False

    async def test_validate_input_other_types(self):
        """Test input validation for other types"""
        assert await self.analyzer.validate_input(123) is False
        assert await self.analyzer.validate_input(None) is False
        assert await self.analyzer.validate_input({}) is False


class TestOpenAIService:
    def setup_method(self):
        self.service = OpenAIService()

    @patch("app.openai_service.service.OpenAIClient")
    @patch("app.openai_service.service.MessageAnalyzer")
    @patch("app.openai_service.service.CircuitBreaker")
    def test_initialization(self, mock_circuit_breaker, mock_analyzer, mock_client):
        """Test service initialization"""
        service = OpenAIService()

        assert service.max_retries == 3
        assert service.base_delay == 1
        mock_client.assert_called_once()
        mock_analyzer.assert_called_once()
        mock_circuit_breaker.assert_called_once()

    @patch.object(OpenAIService, "_retry_with_backoff")
    @patch.object(OpenAIService, "_with_rate_limiting")
    async def test_analyze_message_importance_success(
        self, mock_rate_limit, mock_retry
    ):
        """Test successful message importance analysis"""
        mock_retry.return_value = 4
        self.service.circuit_breaker.call = AsyncMock(return_value=4)

        result = await self.service.analyze_message_importance(
            "Test message", "Test context"
        )

        assert result == 4
        self.service.circuit_breaker.call.assert_called_once()

    async def test_analyze_message_importance_rate_limit_exceeded(self):
        """Test message importance analysis with rate limit exceeded"""
        self.service.circuit_breaker.call = AsyncMock(
            side_effect=RateLimitExceeded("Rate limit")
        )

        result = await self.service.analyze_message_importance("Test message")

        assert result == 3  # Default value

    async def test_analyze_message_importance_circuit_breaker_open(self):
        """Test message importance analysis with circuit breaker open"""
        self.service.circuit_breaker.call = AsyncMock(
            side_effect=CircuitBreakerOpenError("Circuit open")
        )

        result = await self.service.analyze_message_importance("Test message")

        assert result == 3  # Default value

    async def test_analyze_message_importance_general_exception(self):
        """Test message importance analysis with general exception"""
        self.service.circuit_breaker.call = AsyncMock(
            side_effect=Exception("General error")
        )

        result = await self.service.analyze_message_importance("Test message")

        assert result == 3  # Default value

    @patch.object(OpenAIService, "_retry_with_backoff")
    @patch.object(OpenAIService, "_with_rate_limiting")
    async def test_create_digest_success(self, mock_rate_limit, mock_retry):
        """Test successful digest creation"""
        mock_retry.return_value = "Test digest"
        self.service.circuit_breaker.call = AsyncMock(return_value="Test digest")
        messages = [{"chat_name": "Chat1", "sender": "User1", "content": "Message1"}]

        result = await self.service.create_digest(messages)

        assert result == "Test digest"
        self.service.circuit_breaker.call.assert_called_once()

    async def test_create_digest_rate_limit_exceeded(self):
        """Test digest creation with rate limit exceeded"""
        self.service.circuit_breaker.call = AsyncMock(
            side_effect=RateLimitExceeded("Rate limit")
        )
        messages = [{"chat_name": "Chat1", "sender": "User1", "content": "Message1"}]

        result = await self.service.create_digest(messages)

        assert "API rate limits" in result

    async def test_create_digest_circuit_breaker_open(self):
        """Test digest creation with circuit breaker open"""
        self.service.circuit_breaker.call = AsyncMock(
            side_effect=CircuitBreakerOpenError("Circuit open")
        )
        messages = [{"chat_name": "Chat1", "sender": "User1", "content": "Message1"}]

        result = await self.service.create_digest(messages)

        assert "AI service issues" in result

    @patch.object(OpenAIService, "_retry_with_backoff")
    @patch.object(OpenAIService, "_with_rate_limiting")
    async def test_create_digest_by_chats_success(self, mock_rate_limit, mock_retry):
        """Test successful digest creation by chats"""
        mock_retry.return_value = "Test digest by chats"
        self.service.circuit_breaker.call = AsyncMock(
            return_value="Test digest by chats"
        )
        chat_messages = {
            "Chat1": [{"content": "Message1", "importance": 4}],
            "Chat2": [{"content": "Message2", "importance": 5}],
        }

        result = await self.service.create_digest_by_chats(chat_messages)

        assert result == "Test digest by chats"
        self.service.circuit_breaker.call.assert_called_once()

    async def test_create_digest_by_chats_rate_limit_exceeded(self):
        """Test digest creation by chats with rate limit exceeded"""
        self.service.circuit_breaker.call = AsyncMock(
            side_effect=RateLimitExceeded("Rate limit")
        )
        chat_messages = {"Chat1": [{"content": "Message1", "importance": 4}]}

        result = await self.service.create_digest_by_chats(chat_messages)

        assert "API rate limits" in result

    @patch.object(OpenAIService, "_retry_with_backoff")
    @patch.object(OpenAIService, "_with_rate_limiting")
    async def test_translate_to_russian_success(self, mock_rate_limit, mock_retry):
        """Test successful translation"""
        mock_retry.return_value = "Hello world"
        self.service.circuit_breaker.call = AsyncMock(return_value="Hello world")

        result = await self.service.translate_to_russian("Hello world")

        assert result == "Hello world"
        self.service.circuit_breaker.call.assert_called_once()

    async def test_translate_to_russian_exception(self):
        """Test translation with exception"""
        self.service.circuit_breaker.call = AsyncMock(
            side_effect=Exception("Translation error")
        )

        result = await self.service.translate_to_russian("Hello world")

        assert result == "Hello world"  # Return original text

    async def test_validate_input(self):
        """Test input validation"""
        self.service.analyzer.validate_input = AsyncMock(return_value=True)

        result = await self.service.validate_input("test input")

        assert result
        self.service.analyzer.validate_input.assert_called_once_with("test input")

    def test_get_service_status(self):
        """Test service status retrieval"""
        # Mock the circuit breaker state for testing
        self.service.circuit_breaker.state = "CLOSED"
        self.service.circuit_breaker.failure_count = 0

        with patch("app.openai_service.service.openai_rate_limiter") as mock_limiter:
            mock_limiter.get_stats.return_value = {"requests": 10}

            status = self.service.get_service_status()

            assert status["circuit_breaker_state"] == "CLOSED"
            assert status["failure_count"] == 0
            assert status["rate_limiter_stats"] == {"requests": 10}

    @patch("asyncio.sleep")
    async def test_retry_with_backoff_success(self, mock_sleep):
        """Test retry with backoff on success"""
        mock_func = AsyncMock(return_value="success")

        result = await self.service._retry_with_backoff(
            mock_func, "arg1", kwarg1="value1"
        )

        assert result == "success"
        mock_func.assert_called_once_with("arg1", kwarg1="value1")
        mock_sleep.assert_not_called()

    @patch("asyncio.sleep")
    async def test_retry_with_backoff_failure_then_success(self, mock_sleep):
        """Test retry with backoff on failure then success"""
        mock_func = AsyncMock(side_effect=[Exception("Error"), "success"])

        result = await self.service._retry_with_backoff(mock_func, "arg1")

        assert result == "success"
        assert mock_func.call_count == 2
        mock_sleep.assert_called_once_with(1)  # First retry delay

    @patch("asyncio.sleep")
    async def test_retry_with_backoff_all_failures(self, mock_sleep):
        """Test retry with backoff on all failures"""
        mock_func = AsyncMock(side_effect=Exception("Error"))

        with pytest.raises(Exception, match="Error"):
            await self.service._retry_with_backoff(mock_func, "arg1")

        assert mock_func.call_count == 3  # max_retries
        assert mock_sleep.call_count == 2  # Two retries

    async def test_with_rate_limiting(self):
        """Test rate limiting wrapper"""
        mock_func = AsyncMock(return_value="result")

        with patch("app.openai_service.service.openai_rate_limiter") as mock_limiter:
            mock_limiter.wait_if_needed = AsyncMock()

            result = await self.service._with_rate_limiting(
                mock_func, "arg1", kwarg1="value1"
            )

            assert result == "result"
            mock_limiter.wait_if_needed.assert_called_once()
            mock_func.assert_called_once_with("arg1", kwarg1="value1")
