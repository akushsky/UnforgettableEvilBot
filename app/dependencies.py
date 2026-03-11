"""
Dependency injection providers for FastAPI.

Usage in routes:
    from app.dependencies import get_telegram_service, get_openai_service

    @router.post("/endpoint")
    async def my_endpoint(
        telegram: TelegramService = Depends(get_telegram_service),
        db: Session = Depends(get_db),
    ):
        ...
"""

from functools import lru_cache

from app.openai_service.service import OpenAIService
from app.telegram.service import TelegramService
from app.whatsapp.official_service import WhatsAppOfficialService
from app.whatsapp.service import WhatsAppService
from config.settings import settings


@lru_cache(maxsize=1)
def get_openai_service() -> OpenAIService:
    return OpenAIService()


@lru_cache(maxsize=1)
def get_telegram_service() -> TelegramService:
    return TelegramService()


@lru_cache(maxsize=1)
def get_whatsapp_service() -> WhatsAppService:
    return WhatsAppService(settings.WHATSAPP_SESSION_PATH, settings.WHATSAPP_BRIDGE_URL)


@lru_cache(maxsize=1)
def get_whatsapp_official_service() -> WhatsAppOfficialService:
    return WhatsAppOfficialService(
        access_token=settings.WHATSAPP_ACCESS_TOKEN or "",
        phone_number_id=settings.WHATSAPP_PHONE_NUMBER_ID or "",
    )
