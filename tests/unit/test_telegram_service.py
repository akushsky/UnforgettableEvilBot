from unittest.mock import AsyncMock, Mock, patch

import pytest
from telegram.error import TelegramError
from telegram.request import HTTPXRequest

from app.telegram.service import TelegramService


class TestTelegramService:
    def setup_method(self):
        self.service = TelegramService(disable_ssl_verify=True)

    def test_initialization_default(self):
        """Test service initialization with default settings"""
        service = TelegramService()
        assert service.disable_ssl_verify is not None
        assert service._bot is None

    def test_initialization_with_ssl_verify(self):
        """Test service initialization with SSL verification enabled"""
        service = TelegramService(disable_ssl_verify=False)
        assert service.disable_ssl_verify is False

    def test_initialization_without_ssl_verify(self):
        """Test service initialization with SSL verification disabled"""
        service = TelegramService(disable_ssl_verify=True)
        assert service.disable_ssl_verify

    def test_make_request_with_ssl_disabled(self):
        """Test request creation with SSL verification disabled"""
        request = self.service._make_request()
        assert isinstance(request, HTTPXRequest)
        # HTTPXRequest doesn't expose httpx_kwargs directly, so we test the
        # creation works
        assert request is not None

    def test_make_request_with_ssl_enabled(self):
        """Test request creation with SSL verification enabled"""
        service = TelegramService(disable_ssl_verify=False)
        request = service._make_request()
        assert isinstance(request, HTTPXRequest)
        # HTTPXRequest doesn't expose httpx_kwargs directly, so we test the
        # creation works
        assert request is not None

    @patch("app.telegram.service.settings")
    def test_bot_property_initialization(self, mock_settings):
        """Test bot property lazy initialization"""
        mock_settings.TELEGRAM_BOT_TOKEN = "test_token"

        with patch("app.telegram.service.Bot") as mock_bot_class:
            mock_bot_instance = Mock()
            mock_bot_class.return_value = mock_bot_instance

            bot = self.service.bot

            assert bot == mock_bot_instance
            mock_bot_class.assert_called_once()
            assert self.service._bot == mock_bot_instance

    @patch("app.telegram.service.settings")
    def test_bot_property_cached(self, mock_settings):
        """Test bot property returns cached instance"""
        mock_settings.TELEGRAM_BOT_TOKEN = "test_token"

        with patch("app.telegram.service.Bot") as mock_bot_class:
            mock_bot_instance = Mock()
            mock_bot_class.return_value = mock_bot_instance

            # First call - should create new instance
            bot1 = self.service.bot
            # Second call - should return cached instance
            bot2 = self.service.bot

            assert bot1 == bot2
            mock_bot_class.assert_called_once()  # Only called once

    @patch("app.telegram.service.settings")
    def test_bot_property_no_token(self, mock_settings):
        """Test bot property raises error when no token configured"""
        mock_settings.TELEGRAM_BOT_TOKEN = None

        with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN not configured"):
            _ = self.service.bot

    @patch.object(TelegramService, "bot")
    async def test_send_digest_success(self, mock_bot):
        """Test successful digest sending"""
        mock_bot.send_message = AsyncMock()
        channel_id = "-1001234567890"
        digest_text = "Test digest content"

        result = await self.service.send_digest(channel_id, digest_text)

        assert result
        mock_bot.send_message.assert_called_once()
        call_args = mock_bot.send_message.call_args
        assert call_args[1]["chat_id"] == channel_id
        assert "📋 *Дайджест WhatsApp сообщений*" in call_args[1]["text"]
        assert digest_text in call_args[1]["text"]
        assert call_args[1]["parse_mode"] == "Markdown"
        assert call_args[1]["disable_web_page_preview"]

    @patch.object(TelegramService, "bot")
    async def test_send_digest_failure(self, mock_bot):
        """Test digest sending failure"""
        mock_bot.send_message = AsyncMock(side_effect=TelegramError("Network error"))
        channel_id = "-1001234567890"
        digest_text = "Test digest content"

        result = await self.service.send_digest(channel_id, digest_text)

        assert result is False
        mock_bot.send_message.assert_called_once()

    @patch.object(TelegramService, "bot")
    async def test_send_notification_success(self, mock_bot):
        """Test successful notification sending"""
        mock_bot.send_message = AsyncMock()
        channel_id = "-1001234567890"
        message = "Test notification"

        result = await self.service.send_notification(channel_id, message)

        assert result
        mock_bot.send_message.assert_called_once()
        call_args = mock_bot.send_message.call_args
        assert call_args[1]["chat_id"] == channel_id
        assert "🔔 Test notification" in call_args[1]["text"]
        assert call_args[1]["parse_mode"] == "Markdown"

    @patch.object(TelegramService, "bot")
    async def test_send_notification_failure(self, mock_bot):
        """Test notification sending failure"""
        mock_bot.send_message = AsyncMock(side_effect=TelegramError("Network error"))
        channel_id = "-1001234567890"
        message = "Test notification"

        result = await self.service.send_notification(channel_id, message)

        assert result is False
        mock_bot.send_message.assert_called_once()

    @patch.object(TelegramService, "bot")
    async def test_test_connection_success(self, mock_bot):
        """Test successful connection test"""
        mock_bot.send_message = AsyncMock()
        channel_id = "-1001234567890"

        result = await self.service.test_connection(channel_id)

        assert result
        mock_bot.send_message.assert_called_once()
        call_args = mock_bot.send_message.call_args
        assert call_args[1]["chat_id"] == channel_id
        assert "✅ Подключение к боту установлено успешно!" in call_args[1]["text"]

    @patch.object(TelegramService, "bot")
    async def test_test_connection_failure(self, mock_bot):
        """Test connection test failure"""
        mock_bot.send_message = AsyncMock(side_effect=TelegramError("Network error"))
        channel_id = "-1001234567890"

        result = await self.service.test_connection(channel_id)

        assert result is False
        mock_bot.send_message.assert_called_once()

    @patch.object(TelegramService, "get_bot_username")
    async def test_create_channel_for_user(self, mock_get_username):
        """Test channel creation instructions"""
        mock_get_username.return_value = "test_bot"
        user_name = "TestUser"

        result = await self.service.create_channel_for_user(user_name)

        assert "instructions" in result
        assert "bot_username" in result
        assert result["bot_username"] == "test_bot"
        assert len(result["instructions"]) > 0
        assert "WhatsApp Дайджест - TestUser" in result["instructions"][1]
        # Check that bot username appears in the instructions (adjust index as needed)
        instructions_text = " ".join(result["instructions"])
        assert "test_bot" in instructions_text

    @patch.object(TelegramService, "bot")
    async def test_get_bot_username_success(self, mock_bot):
        """Test successful bot username retrieval"""
        mock_bot_info = Mock()
        mock_bot_info.username = "test_bot_username"
        mock_bot.get_me = AsyncMock(return_value=mock_bot_info)

        result = await self.service.get_bot_username()

        assert result == "test_bot_username"
        mock_bot.get_me.assert_called_once()

    @patch.object(TelegramService, "bot")
    async def test_get_bot_username_failure(self, mock_bot):
        """Test bot username retrieval failure"""
        mock_bot.get_me = AsyncMock(side_effect=Exception("API error"))

        result = await self.service.get_bot_username()

        assert result == "unknown_bot"
        mock_bot.get_me.assert_called_once()

    @patch.object(TelegramService, "bot")
    async def test_verify_channel_access_success(self, mock_bot):
        """Test successful channel access verification"""
        mock_chat = Mock()
        mock_chat.title = "Test Channel"
        mock_chat.type = "channel"
        mock_chat.description = "Test description"

        mock_bot_member = Mock()
        mock_bot_member.status = "administrator"
        mock_bot_member.can_post_messages = True
        mock_bot_member.can_edit_messages = False

        mock_bot.get_chat = AsyncMock(return_value=mock_chat)
        mock_bot.get_chat_member = AsyncMock(return_value=mock_bot_member)

        channel_id = "-1001234567890"
        result = await self.service.verify_channel_access(channel_id)

        assert result["success"]
        assert result["chat_info"]["title"] == "Test Channel"
        assert result["chat_info"]["type"] == "channel"
        assert result["chat_info"]["description"] == "Test description"
        assert result["bot_permissions"]["is_admin"]
        assert result["bot_permissions"]["can_post"]
        assert result["bot_permissions"]["can_edit"] is False

    @patch.object(TelegramService, "bot")
    async def test_verify_channel_access_failure(self, mock_bot):
        """Test channel access verification failure"""
        mock_bot.get_chat = AsyncMock(side_effect=TelegramError("Chat not found"))
        channel_id = "-1001234567890"

        result = await self.service.verify_channel_access(channel_id)

        assert result["success"] is False
        assert "error" in result
        assert "suggestions" in result
        assert len(result["suggestions"]) > 0

    @patch.object(TelegramService, "bot")
    async def test_get_channel_statistics_success(self, mock_bot):
        """Test successful channel statistics retrieval"""
        mock_chat = Mock()
        mock_chat.title = "Test Channel"
        mock_chat.type = "channel"
        mock_chat.description = "Test description"

        mock_bot.get_chat = AsyncMock(return_value=mock_chat)
        mock_bot.get_chat_member_count = AsyncMock(return_value=150)

        channel_id = "-1001234567890"
        result = await self.service.get_channel_statistics(channel_id)

        assert result["success"]
        assert result["statistics"]["title"] == "Test Channel"
        assert result["statistics"]["member_count"] == 150
        assert result["statistics"]["type"] == "channel"
        assert result["statistics"]["description"] == "Test description"

    @patch.object(TelegramService, "bot")
    async def test_get_channel_statistics_failure(self, mock_bot):
        """Test channel statistics retrieval failure"""
        mock_bot.get_chat = AsyncMock(side_effect=TelegramError("Chat not found"))
        channel_id = "-1001234567890"

        result = await self.service.get_channel_statistics(channel_id)

        assert result["success"] is False
        assert "error" in result

    @patch.object(TelegramService, "bot")
    async def test_send_formatted_digest_success(self, mock_bot):
        """Test successful formatted digest sending"""
        mock_bot.send_message = AsyncMock()
        channel_id = "-1001234567890"
        digest_data = {
            "timestamp": "2024-01-01 12:00:00",
            "message_count": 25,
            "content": "Test digest content",
            "interval_hours": 6,
        }

        result = await self.service.send_formatted_digest(channel_id, digest_data)

        assert result
        mock_bot.send_message.assert_called_once()
        call_args = mock_bot.send_message.call_args
        assert call_args[1]["chat_id"] == channel_id
        assert "📱 *WhatsApp Дайджест*" in call_args[1]["text"]
        assert "🕐 2024-01-01 12:00:00" in call_args[1]["text"]
        assert "📊 Сообщений: 25" in call_args[1]["text"]
        assert "Test digest content" in call_args[1]["text"]
        assert (
            "Автоматический дайджест системы WhatsApp Monitor" in call_args[1]["text"]
        )
        assert "Интервал: каждые 6 часов" in call_args[1]["text"]
        assert call_args[1]["parse_mode"] == "Markdown"
        assert call_args[1]["disable_web_page_preview"]

    @patch.object(TelegramService, "bot")
    async def test_send_formatted_digest_failure(self, mock_bot):
        """Test formatted digest sending failure"""
        mock_bot.send_message = AsyncMock(side_effect=TelegramError("Network error"))
        channel_id = "-1001234567890"
        digest_data = {
            "timestamp": "2024-01-01 12:00:00",
            "message_count": 25,
            "content": "Test digest content",
            "interval_hours": 6,
        }

        result = await self.service.send_formatted_digest(channel_id, digest_data)

        assert result is False
        mock_bot.send_message.assert_called_once()

    @patch.object(TelegramService, "bot")
    async def test_send_formatted_digest_minimal_data(self, mock_bot):
        """Test formatted digest sending with minimal data"""
        mock_bot.send_message = AsyncMock()
        channel_id = "-1001234567890"
        digest_data = {"content": "Test digest content"}

        result = await self.service.send_formatted_digest(channel_id, digest_data)

        assert result
        mock_bot.send_message.assert_called_once()
        call_args = mock_bot.send_message.call_args
        assert "🕐 Не указано" in call_args[1]["text"]
        assert "📊 Сообщений: 0" in call_args[1]["text"]
        assert "Интервал: каждые ? часов" in call_args[1]["text"]

    def test_ssl_context_creation(self):
        """Test SSL context creation when SSL verification is enabled"""
        service = TelegramService(disable_ssl_verify=False)
        request = service._make_request()

        assert isinstance(request, HTTPXRequest)
        # HTTPXRequest doesn't expose httpx_kwargs directly, so we test the
        # creation works
        assert request is not None

    @patch("app.telegram.service.settings")
    def test_initialization_with_settings(self, mock_settings):
        """Test initialization using settings"""
        mock_settings.TELEGRAM_SSL_VERIFY = False

        service = TelegramService()
        assert service.disable_ssl_verify

        mock_settings.TELEGRAM_SSL_VERIFY = True
        service = TelegramService()
        assert service.disable_ssl_verify is False
