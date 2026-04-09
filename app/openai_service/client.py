from typing import Any

import openai

from app.core.base_service import BaseService
from app.core.openai_monitoring import openai_monitor
from config.logging_config import get_logger
from config.settings import settings

logger = get_logger(__name__)


class OpenAIClient(BaseService):
    """Client for working with OpenAI API - API requests only"""

    REASONING_MODELS = {"o1", "o1-mini", "o3", "o3-mini", "gpt-5-mini", "gpt-5"}
    REASONING_TOKEN_MULTIPLIER = 8

    def __init__(self):
        """Init  ."""
        super().__init__()
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required but not configured")

        self.client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def make_request(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        system_message: str | None = None,
    ) -> str:
        """Execute request to OpenAI API"""
        model = model or settings.OPENAI_MODEL
        max_tokens = max_tokens or settings.OPENAI_MAX_TOKENS
        temperature = temperature or settings.OPENAI_TEMPERATURE

        # Reasoning models don't support system messages;
        # prepend as context in the user prompt instead.
        if model in self.REASONING_MODELS and system_message:
            prompt = f"{system_message}\n\n---\n\n{prompt}"
            system_message = None

        try:
            messages: list[dict[str, str]] = []
            if system_message:
                messages.append({"role": "system", "content": system_message})
            messages.append({"role": "user", "content": prompt})

            kwargs: dict = {
                "model": model,
                "messages": messages,
            }
            if model in self.REASONING_MODELS:
                # Reasoning models spend most of max_completion_tokens on
                # internal chain-of-thought, so we need a larger budget
                # to ensure visible output is produced.
                kwargs["max_completion_tokens"] = (
                    max_tokens * self.REASONING_TOKEN_MULTIPLIER
                )
            else:
                kwargs["max_tokens"] = max_tokens
                kwargs["temperature"] = temperature

            response = await self.client.chat.completions.create(**kwargs)

            content = response.choices[0].message.content
            if not content or not content.strip():
                raise ValueError("OpenAI returned empty content")
            content = content.strip()

            # Record metrics
            if response.usage:
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
            else:
                openai_monitor.record_request(
                    model=model,
                    input_tokens=0,
                    output_tokens=0,
                    success=True,
                )

                self.log_operation(
                    "openai_request",
                    {"model": model, "tokens_used": 0},
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
        return bool(isinstance(data, str) and len(data) > 0)
