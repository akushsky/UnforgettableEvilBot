"""Unit tests for dependency injection providers in app/dependencies.py."""

from unittest.mock import Mock, patch

import pytest

from app.dependencies import (
    get_openai_service,
    get_telegram_service,
    get_whatsapp_official_service,
    get_whatsapp_service,
)


class TestGetOpenAIService:
    """Tests for get_openai_service provider."""

    def teardown_method(self):
        """Clear lru_cache between tests to avoid singleton leakage."""
        get_openai_service.cache_clear()

    @patch("app.dependencies.OpenAIService")
    def test_returns_openai_service_instance(self, mock_openai_service):
        """Test that get_openai_service returns an OpenAIService instance."""
        mock_instance = Mock()
        mock_openai_service.return_value = mock_instance

        result = get_openai_service()

        assert result is mock_instance
        mock_openai_service.assert_called_once_with()

    @patch("app.dependencies.OpenAIService")
    def test_returns_same_instance_on_repeated_calls(self, mock_openai_service):
        """Test singleton behavior via lru_cache - same instance on repeated calls."""
        mock_instance = Mock()
        mock_openai_service.return_value = mock_instance

        result1 = get_openai_service()
        result2 = get_openai_service()

        assert result1 is result2
        mock_openai_service.assert_called_once()


class TestGetTelegramService:
    """Tests for get_telegram_service provider."""

    def teardown_method(self):
        """Clear lru_cache between tests."""
        get_telegram_service.cache_clear()

    @patch("app.dependencies.TelegramService")
    def test_returns_telegram_service_instance(self, mock_telegram_service):
        """Test that get_telegram_service returns a TelegramService instance."""
        mock_instance = Mock()
        mock_telegram_service.return_value = mock_instance

        result = get_telegram_service()

        assert result is mock_instance
        mock_telegram_service.assert_called_once_with()

    @patch("app.dependencies.TelegramService")
    def test_returns_same_instance_on_repeated_calls(self, mock_telegram_service):
        """Test singleton behavior via lru_cache."""
        mock_instance = Mock()
        mock_telegram_service.return_value = mock_instance

        result1 = get_telegram_service()
        result2 = get_telegram_service()

        assert result1 is result2
        mock_telegram_service.assert_called_once()


class TestGetWhatsAppService:
    """Tests for get_whatsapp_service provider."""

    def teardown_method(self):
        """Clear lru_cache between tests."""
        get_whatsapp_service.cache_clear()

    @patch("app.dependencies.settings")
    @patch("app.dependencies.WhatsAppService")
    def test_returns_whatsapp_service_instance(
        self, mock_whatsapp_service, mock_settings
    ):
        """Test that get_whatsapp_service returns a WhatsAppService instance."""
        mock_settings.WHATSAPP_SESSION_PATH = "/path/session"
        mock_settings.WHATSAPP_BRIDGE_URL = "http://localhost:3000"
        mock_instance = Mock()
        mock_whatsapp_service.return_value = mock_instance

        result = get_whatsapp_service()

        assert result is mock_instance
        mock_whatsapp_service.assert_called_once_with(
            "/path/session", "http://localhost:3000"
        )

    @patch("app.dependencies.settings")
    @patch("app.dependencies.WhatsAppService")
    def test_returns_same_instance_on_repeated_calls(
        self, mock_whatsapp_service, mock_settings
    ):
        """Test singleton behavior via lru_cache."""
        mock_settings.WHATSAPP_SESSION_PATH = "/path/session"
        mock_settings.WHATSAPP_BRIDGE_URL = "http://localhost:3000"
        mock_instance = Mock()
        mock_whatsapp_service.return_value = mock_instance

        result1 = get_whatsapp_service()
        result2 = get_whatsapp_service()

        assert result1 is result2
        mock_whatsapp_service.assert_called_once()


class TestGetWhatsAppOfficialService:
    """Tests for get_whatsapp_official_service provider."""

    def teardown_method(self):
        """Clear lru_cache between tests."""
        get_whatsapp_official_service.cache_clear()

    @patch("app.dependencies.settings")
    @patch("app.dependencies.WhatsAppOfficialService")
    def test_returns_whatsapp_official_service_instance(
        self, mock_official_service, mock_settings
    ):
        """Test that get_whatsapp_official_service returns WhatsAppOfficialService."""
        mock_settings.WHATSAPP_ACCESS_TOKEN = "test-token"
        mock_settings.WHATSAPP_PHONE_NUMBER_ID = "phone-123"
        mock_instance = Mock()
        mock_official_service.return_value = mock_instance

        result = get_whatsapp_official_service()

        assert result is mock_instance
        mock_official_service.assert_called_once_with(
            access_token="test-token", phone_number_id="phone-123"
        )

    @patch("app.dependencies.settings")
    @patch("app.dependencies.WhatsAppOfficialService")
    def test_uses_empty_string_when_settings_missing(
        self, mock_official_service, mock_settings
    ):
        """Test that empty strings are used when settings are None."""
        mock_settings.WHATSAPP_ACCESS_TOKEN = None
        mock_settings.WHATSAPP_PHONE_NUMBER_ID = None
        mock_instance = Mock()
        mock_official_service.return_value = mock_instance

        get_whatsapp_official_service()

        mock_official_service.assert_called_once_with(
            access_token="", phone_number_id=""
        )

    @patch("app.dependencies.settings")
    @patch("app.dependencies.WhatsAppOfficialService")
    def test_returns_same_instance_on_repeated_calls(
        self, mock_official_service, mock_settings
    ):
        """Test singleton behavior via lru_cache."""
        mock_settings.WHATSAPP_ACCESS_TOKEN = "token"
        mock_settings.WHATSAPP_PHONE_NUMBER_ID = "phone"
        mock_instance = Mock()
        mock_official_service.return_value = mock_instance

        result1 = get_whatsapp_official_service()
        result2 = get_whatsapp_official_service()

        assert result1 is result2
        mock_official_service.assert_called_once()
