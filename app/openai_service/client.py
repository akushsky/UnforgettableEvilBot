from typing import Any, Optional

import openai

from app.core.base_service import BaseService
from app.core.openai_monitoring import openai_monitor
from config.logging_config import get_logger
from config.settings import settings

logger = get_logger(__name__)


class OpenAIClient(BaseService):
    """Client for working with OpenAI API - API requests only"""

    def __init__(self):
        """Init  ."""
        super().__init__()
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required but not configured")

        self.client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def make_request(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Execute request to OpenAI API"""
        # Use settings defaults if not provided
        model = model or settings.OPENAI_MODEL
        max_tokens = max_tokens or settings.OPENAI_MAX_TOKENS
        temperature = temperature or settings.OPENAI_TEMPERATURE

        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
            )

            content = response.choices[0].message.content.strip()

            # Record metrics
            openai_monitor.record_request(
                model=model,
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
                success=True,
            )

            self.log_operation(
                "openai_request",
                {"model": model, "tokens_used": response.usage.total_tokens},
            )

            return content

        except Exception as e:
            # Record failed request
            openai_monitor.record_request(
                model=model,
                input_tokens=0,  # We don't know exact tokens for failed requests
                output_tokens=0,
                success=False,
                error=str(e),
            )

            self.logger.error(f"OpenAI API request failed: {e}")
            raise

    async def validate_input(self, data: Any) -> bool:
        """Validate input data for OpenAI"""
        if isinstance(data, str) and len(data) > 0:
            return True
        return False
