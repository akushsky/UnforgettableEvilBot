from typing import Any, Dict, List

from app.core.base_service import BaseService
from app.openai_service.client import OpenAIClient
from config.logging_config import get_logger
from config.settings import settings

logger = get_logger(__name__)


class MessageAnalyzer(BaseService):
    """Message analyzer - only importance analysis and digest creation"""

    def __init__(self, client: OpenAIClient):
        """Init  .

        Args:
            client: Description of client.
        """
        super().__init__()
        self.client = client

    def _build_importance_prompt(self, message: str, chat_context: str = "") -> str:
        """Build prompt for importance analysis"""
        return f"""
        Analyze the importance of this message on a scale from 1 to 5, where:
        1 - unimportant (casual chat, emojis, greetings)
        2 - low significance (personal conversations, non-critical information)
        3 - medium (useful information, but not urgent)
        4 - important (requires attention, work matters)
        5 - critically important (urgent matters, problems, important notifications)

        Chat context: {chat_context}
        message: {message}

        Answer only with a number from 1 to 5.
        """

    def _build_digest_prompt(self, messages: List[Dict]) -> str:
        """Build prompt for digest creation"""
        messages_text = ""
        for msg in messages:
            messages_text += f"\n[{msg['chat_name']}] {msg['sender']}: {msg['content']}"

        return f"""
        Create a brief digest of the most important events based on these messages from WhatsApp chats.
        Group by topics, highlight key points.
        Use emojis for better perception.
        Format: topic header, brief description.

        Messages:{messages_text}

        Create a structured digest in Russian language.
        """

    def _build_digest_by_chats_prompt(
        self, chat_messages: Dict[str, List[Dict]]
    ) -> str:
        """Build prompt for digest creation grouped by chats"""
        chat_sections = ""

        for chat_name, messages in chat_messages.items():
            chat_sections += f"\n\n📱 ЧАТ: {chat_name}\n"
            chat_sections += "─" * 20 + "\n"

            for msg in messages:
                importance_emoji = (
                    "🔴"
                    if msg["importance"] >= 5
                    else "🟡"
                    if msg["importance"] >= 4
                    else "🟢"
                )
                chat_sections += f"{importance_emoji} {msg['content']}\n"

        return f"""
        Create a structured digest of important messages, grouped by chats.

        IMPORTANT: Use ONLY the chats and messages provided below.
        DO NOT invent additional chats or messages.

        For each chat, create a separate section with a header and brief summary of important events.
        Use emojis for better perception and highlighting importance.

        Format:
        📱 CHAT NAME
        ─────────────────
        🔴/🟡/🟢 Message

        Messages by chats:{chat_sections}

        Create a digest in Russian language, grouped by chats.
        For each chat, provide a brief summary of important events.
        Use ONLY the provided data, do not add anything of your own.
        """

    def _build_translation_prompt(self, text: str) -> str:
        """Build prompt for translation"""
        return f"""
        Translate the following text to Russian language, preserving meaning and context:

        {text}

        Translate only the text, without additional comments.
        """

    def _parse_importance(self, response: str) -> int:
        """Parse importance score from response"""
        try:
            importance = int(response.strip())
            return max(1, min(5, importance))  # Ensure value is in range 1-5
        except (ValueError, TypeError):
            self.logger.warning(f"Failed to parse importance from response: {response}")
            return 3  # Return average value on error

    async def analyze_importance(self, message: str, chat_context: str = "") -> int:
        """Analyze message importance"""
        if not await self.validate_input(message):
            logger.warning("Invalid input for importance analysis")
            return 3

        prompt = self._build_importance_prompt(message, chat_context)
        response = await self.client.make_request(
            prompt, max_tokens=1, temperature=settings.OPENAI_TEMPERATURE
        )

        importance = self._parse_importance(response)
        self.log_operation("message_importance_analysis", {"importance": importance})

        return importance

    async def create_digest(self, messages: List[Dict]) -> str:
        """Create digest from messages"""
        if not messages:
            return "📋 Нет новых важных сообщений для дайджеста."

        if not await self.validate_input(messages):
            return "❌ Ошибка при создании дайджеста."

        prompt = self._build_digest_prompt(messages)
        digest = await self.client.make_request(prompt, max_tokens=600, temperature=0.7)

        self.log_operation("digest_creation", {"messages_count": len(messages)})
        return digest

    async def create_digest_by_chats(self, chat_messages: Dict[str, List[Dict]]) -> str:
        """Create digest grouped by chats"""
        if not chat_messages:
            return "📋 Нет новых важных сообщений для дайджеста."

        total_messages = sum(len(messages) for messages in chat_messages.values())
        if total_messages == 0:
            return "📋 Нет новых важных сообщений для дайджеста."

        prompt = self._build_digest_by_chats_prompt(chat_messages)
        digest = await self.client.make_request(
            prompt, max_tokens=settings.OPENAI_MAX_TOKENS, temperature=0.7
        )

        self.log_operation(
            "digest_creation_by_chats",
            {"chats_count": len(chat_messages), "total_messages": total_messages},
        )
        return digest

    async def translate_to_russian(self, text: str) -> str:
        """Translate text to Russian"""
        if not await self.validate_input(text):
            return text

        prompt = self._build_translation_prompt(text)
        translation = await self.client.make_request(
            prompt, max_tokens=200, temperature=settings.OPENAI_TEMPERATURE
        )

        self.log_operation("text_translation", {"original_length": len(text)})
        return translation

    async def validate_input(self, data: Any) -> bool:
        """Validate input data for analyzer"""
        if isinstance(data, str):
            # Check if string is not empty and contains actual content
            stripped = data.strip()
            if len(stripped) == 0:
                return False

            # Check if string contains at least some printable characters
            # This handles Hebrew, Arabic, and other Unicode text properly
            import unicodedata

            printable_chars = sum(
                1 for char in stripped if unicodedata.category(char).startswith("L")
            )
            return printable_chars > 0

        elif isinstance(data, list):
            return len(data) > 0 and all(isinstance(item, dict) for item in data)
        return False
