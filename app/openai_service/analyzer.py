from typing import Any

from app.core.base_service import BaseService
from app.openai_service.client import OpenAIClient
from config.logging_config import get_logger
from config.settings import settings

logger = get_logger(__name__)


class MessageAnalyzer(BaseService):
    """Message analyzer - only importance analysis and digest creation"""

    _DIGEST_SYSTEM_PROMPT = (
        "Ты — помощник русскоязычной семьи, живущей в Израиле. "
        "Твоя задача — читать сообщения из семейных и школьных WhatsApp-чатов на иврите "
        "и составлять краткий, живой дайджест на русском языке.\n\n"
        "Требования к языку:\n"
        "— Пиши на естественном, грамотном русском языке. Никакого подстрочника.\n"
        "— Стиль — информационный: кратко, по делу, без воды.\n"
        "— Формулируй так, как рассказал бы живой человек: "
        "«В школе отменили занятия в четверг», а не «Занятия — отменены — четверг».\n"
        "— Не переводи дословно: передавай смысл, а не слова.\n\n"
        "Обработка иврита:\n"
        "— Имена людей оставляй как есть или давай русскую транслитерацию: "
        "הדס → Хадас, יוסי → Йоси.\n"
        "— Названия мест, школ, организаций — транслитерируй с пояснением "
        "при первом упоминании, если это не очевидно из контекста.\n"
        "— Даты и время переводи полностью: "
        "יום חמישי → четверг, 10:00 בבוקר → 10:00 утра.\n"
        "— Всё остальное — описывай на русском, своими словами.\n\n"
        "Форматирование:\n"
        "— Используй эмодзи-индикаторы важности (🔴🟡🟢) строго по данным, "
        "не меняя уровень.\n"
        "— Не придумывай информацию, которой нет в сообщениях."
    )

    _TRANSLATION_SYSTEM_PROMPT = (
        "Ты — переводчик с иврита на русский для русскоязычной семьи в Израиле. "
        "Переводи естественно, не дословно. "
        "Имена собственные транслитерируй на русский."
    )

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
        You are analyzing the importance of a WhatsApp message in Hebrew.

        STEP 1: First, translate this Hebrew message to English:
        "{message}"

        STEP 2: Based on the translation, evaluate the importance on a scale from 1 to 5:

        1 - unimportant (casual chat, emojis, greetings, general conversation)
        2 - low significance (personal conversations, non-critical information, minor updates)
        3 - medium (useful information, but not urgent, general announcements)
        4 - important (requires attention, school matters, schedule changes, deadlines, class updates)
        5 - critically important (urgent matters, problems, important notifications, immediate actions needed)

        IMPORTANT CRITERIA for school/family context:
        - Schedule and timing information (dates, deadlines, appointments, class times) = HIGH IMPORTANCE
        - School updates and changes (classes, homework, exams, events) = HIGH IMPORTANCE
        - Children's activities and sports (practice times, games, competitions) = HIGH IMPORTANCE
        - Family schedule changes and important dates = HIGH IMPORTANCE

        Chat context: {chat_context}
        Hebrew message: {message}

        Answer only with a number from 1 to 5.
        """

    _MARKDOWNV2_FORMATTING_INSTRUCTIONS = """
OUTPUT FORMAT: valid Telegram MarkdownV2.
Use these formatting options to improve readability:
- *bold* for section headers and key facts
- _italic_ for timestamps, context, and secondary details
- __underline__ for critical or urgent items
- ~strikethrough~ for resolved or cancelled items
Any special character that is NOT part of formatting markup must be escaped
with a preceding backslash. Characters requiring escaping:
\\. \\- \\( \\) \\! \\> \\# \\+ \\= \\| \\{ \\} \\[ \\] \\~
Example: "встреча в 12:00 — с Хадас \\(הדס\\)" is correct because the
parentheses are escaped.
"""

    def _build_digest_prompt(self, messages: list[dict]) -> str:
        """Build prompt for digest creation"""
        messages_text = ""
        for msg in messages:
            messages_text += f"\n[{msg['chat_name']}] {msg['sender']}: {msg['content']}"

        return f"""Составь краткий дайджест самых важных событий на основе этих сообщений из WhatsApp-чатов.
Сгруппируй по темам, выдели ключевые моменты.
Используй эмодзи для наглядности.
Формат: заголовок темы, краткое описание события своими словами.

{self._MARKDOWNV2_FORMATTING_INSTRUCTIONS}

Сообщения:{messages_text}

Перескажи важные события кратко и естественно."""

    def _build_digest_by_chats_prompt(
        self, chat_messages: dict[str, list[dict]]
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
                    else "🟡" if msg["importance"] >= 4 else "🟢"
                )
                chat_sections += f"{importance_emoji} {msg['content']}\n"

        return f"""Составь дайджест важных сообщений, сгруппированный по чатам.

ВАЖНО: используй ТОЛЬКО чаты и сообщения, приведённые ниже.
НЕ придумывай дополнительные чаты или сообщения.

Для каждого чата — отдельный раздел с заголовком и кратким пересказом важных событий.
Сохраняй эмодзи-индикаторы важности (🔴🟡🟢) из исходных данных.

{self._MARKDOWNV2_FORMATTING_INSTRUCTIONS}

Пример оформления:

📱 *Школа «Мигдаль»*
─────────────────
🔴 *Занятия отменены в четверг* — _из\\-за ракетной тревоги, уроки перенесены на воскресенье_
🟡 Собрание родителей перенесли на 18:00 вместо 17:00
🟢 Хадас напомнила принести тетради по математике

Сообщения по чатам:{chat_sections}

Перескажи важные события по каждому чату кратко и естественно.
Используй ТОЛЬКО предоставленные данные."""

    def _build_translation_prompt(self, text: str) -> str:
        """Build prompt for translation"""
        return f"""Переведи следующий текст на русский язык. Сохрани смысл и контекст.

{text}

Переведи только текст, без дополнительных комментариев."""

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

    async def create_digest(self, messages: list[dict]) -> str:
        """Create digest from messages"""
        if not messages:
            return "📋 Нет новых важных сообщений для дайджеста."

        if not await self.validate_input(messages):
            return "❌ Ошибка при создании дайджеста."

        prompt = self._build_digest_prompt(messages)
        digest = await self.client.make_request(
            prompt,
            max_tokens=600,
            temperature=0.7,
            system_message=self._DIGEST_SYSTEM_PROMPT,
        )

        self.log_operation("digest_creation", {"messages_count": len(messages)})
        return digest

    async def create_digest_by_chats(self, chat_messages: dict[str, list[dict]]) -> str:
        """Create digest grouped by chats"""
        if not chat_messages:
            return "📋 Нет новых важных сообщений для дайджеста."

        total_messages = sum(len(messages) for messages in chat_messages.values())
        if total_messages == 0:
            return "📋 Нет новых важных сообщений для дайджеста."

        prompt = self._build_digest_by_chats_prompt(chat_messages)
        digest = await self.client.make_request(
            prompt,
            max_tokens=settings.OPENAI_MAX_TOKENS,
            temperature=0.7,
            system_message=self._DIGEST_SYSTEM_PROMPT,
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
            prompt,
            max_tokens=200,
            temperature=settings.OPENAI_TEMPERATURE,
            system_message=self._TRANSLATION_SYSTEM_PROMPT,
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
