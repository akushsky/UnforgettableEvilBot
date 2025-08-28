import logging
import ssl
from typing import Dict, Optional

from telegram import Bot
from telegram.error import TelegramError
from telegram.request import HTTPXRequest

from config.settings import settings

logger = logging.getLogger(__name__)


class TelegramService:
    """
    Telegram service with HTTPS certificate verification DISABLED by default.
    Set disable_ssl_verify=False to re-enable verification using system defaults.

    WARNING: Disabling TLS verification allows man-in-the-middle attacks.
    Use only for debugging or in controlled environments.
    """

    def __init__(self, disable_ssl_verify: Optional[bool] = None):
        """Init  .

        Args:
            disable_ssl_verify: Description of disable_ssl_verify.
        """
        self._bot: Optional[Bot] = None
        if disable_ssl_verify is None:
            disable_ssl_verify = not settings.TELEGRAM_SSL_VERIFY
        self.disable_ssl_verify = disable_ssl_verify

    def _make_request(self) -> HTTPXRequest:
        """
        Build a request adapter for python-telegram-bot (HTTPX-based).
        By default, TLS verification is disabled.
        """
        if self.disable_ssl_verify:
            # No cert validation at all
            return HTTPXRequest(
                http_version="1.1",
                connect_timeout=10.0,
                read_timeout=15.0,
                write_timeout=15.0,
                httpx_kwargs={
                    "verify": False,  # <- disables certificate verification
                    "trust_env": False,  # ignore system proxy/SSL env vars unless you need them
                },
            )
        else:
            # If you later want secure mode, flip the flag above or pass disable_ssl_verify=False
            # and optionally load a custom CA here.
            ctx = ssl.create_default_context()
            return HTTPXRequest(
                http_version="1.1",
                connect_timeout=10.0,
                read_timeout=15.0,
                write_timeout=15.0,
                httpx_kwargs={
                    "verify": ctx,
                    "trust_env": False,
                },
            )

    @property
    def bot(self) -> Bot:
        """Lazy initialization of Telegram Bot"""
        if self._bot is None:
            if not settings.TELEGRAM_BOT_TOKEN:
                raise ValueError("TELEGRAM_BOT_TOKEN not configured")
            self._bot = Bot(
                token=settings.TELEGRAM_BOT_TOKEN,
                request=self._make_request(),
            )
        return self._bot

    async def send_digest(self, channel_id: str, digest_text: str) -> bool:
        """Send a digest to a Telegram channel"""
        try:
            formatted_message = f"📋 *Дайджест WhatsApp сообщений*\n\n{digest_text}"
            await self.bot.send_message(
                chat_id=channel_id,
                text=formatted_message,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
            logger.info(f"Digest sent successfully to channel {channel_id}")
            return True
        except TelegramError as e:
            logger.error(f"Error sending digest to Telegram: {e}")
            return False

    async def send_notification(self, channel_id: str, message: str) -> bool:
        """Send a notification to a Telegram channel"""
        try:
            await self.bot.send_message(
                chat_id=channel_id, text=f"🔔 {message}", parse_mode="Markdown"
            )
            return True
        except TelegramError as e:
            logger.error(f"Error sending notification: {e}")
            return False

    async def test_connection(self, channel_id: str) -> bool:
        """Test connection with the channel"""
        try:
            await self.bot.send_message(
                chat_id=channel_id, text="✅ Подключение к боту установлено успешно!"
            )
            return True
        except TelegramError as e:
            logger.error(f"Error testing connection: {e}")
            return False

    async def check_bot_health(self) -> bool:
        """Check if the Telegram bot is healthy and accessible"""
        try:
            # Try to get bot info to verify the token is valid
            bot_info = await self.bot.get_me()
            return bot_info is not None
        except Exception as e:
            logger.error(f"Telegram bot health check failed: {e}")
            return False

    async def create_channel_for_user(self, user_name: str) -> Dict:
        """Helper for creating a channel (instructions for the user)"""
        return {
            "instructions": [
                "1. Создайте новый канал в Telegram:",
                f"   • Название: 'WhatsApp Дайджест - {user_name}'",
                "   • Описание: 'Автоматические дайджесты важных сообщений из WhatsApp'",
                "   • Тип: Приватный канал",
                "",
                "2. Добавьте бота в канал:",
                "   • Найдите настройки канала → Администраторы",
                f"   • Добавьте бота @{await self.get_bot_username()} как администратора",
                "   • Дайте права: отправка сообщений, удаление сообщений",
                "",
                "3. Получите ID канала:",
                "   • Перешлите любое сообщение из канала боту @userinfobot",
                "   • Скопируйте Chat ID (начинается с -100)",
                "   • Введите этот ID в настройках системы",
            ],
            "bot_username": await self.get_bot_username(),
        }

    async def get_bot_username(self) -> str:
        """Get the bot's username"""
        try:
            bot_info = await self.bot.get_me()
            return bot_info.username or "unknown_bot"
        except Exception:
            return "unknown_bot"

    async def verify_channel_access(self, channel_id: str) -> Dict:
        """Check the bot's access to the channel"""
        try:
            chat = await self.bot.get_chat(chat_id=channel_id)
            bot_member = await self.bot.get_chat_member(
                chat_id=channel_id, user_id=self.bot.id
            )
            return {
                "success": True,
                "chat_info": {
                    "title": chat.title,
                    "type": chat.type,
                    "description": chat.description,
                },
                "bot_permissions": {
                    "is_admin": bot_member.status in ["administrator", "creator"],
                    "can_post": getattr(bot_member, "can_post_messages", False),
                    "can_edit": getattr(bot_member, "can_edit_messages", False),
                },
            }
        except TelegramError as e:
            return {
                "success": False,
                "error": str(e),
                "suggestions": [
                    "Убедитесь, что бот добавлен в канал как администратор",
                    "Проверьте правильность ID канала",
                    "Убедитесь, что канал не был удален",
                ],
            }

    async def get_channel_statistics(self, channel_id: str) -> Dict:
        """Get channel statistics"""
        try:
            chat = await self.bot.get_chat(chat_id=channel_id)
            member_count = await self.bot.get_chat_member_count(chat_id=channel_id)
            return {
                "success": True,
                "statistics": {
                    "title": chat.title,
                    "member_count": member_count,
                    "type": chat.type,
                    "description": chat.description,
                },
            }
        except TelegramError as e:
            return {"success": False, "error": str(e)}

    async def send_formatted_digest(self, channel_id: str, digest_data: Dict) -> bool:
        """Send a formatted digest with additional information"""
        try:
            header = "📱 *WhatsApp Дайджест*\n"
            header += f"🕐 {digest_data.get('timestamp', 'Не указано')}\n"
            header += f"📊 Сообщений: {digest_data.get('message_count', 0)}\n"
            header += "─" * 30 + "\n\n"

            footer = "\n\n" + "─" * 30
            footer += "\n🤖 Автоматический дайджест системы WhatsApp Monitor"
            footer += (
                f"\n⚙️ Интервал: каждые {digest_data.get('interval_hours', '?')} часов"
            )

            full_message = header + digest_data.get("content", "") + footer

            await self.bot.send_message(
                chat_id=channel_id,
                text=full_message,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
            logger.info(f"Formatted digest sent to {channel_id}")
            return True
        except TelegramError as e:
            logger.error(f"Error sending formatted digest: {e}")
            return False
