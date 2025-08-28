import redis
from sqlalchemy import text

from app.database.connection import SessionLocal
from app.openai_service.service import OpenAIService
from app.telegram.service import TelegramService
from config.logging_config import get_logger
from config.settings import settings

logger = get_logger(__name__)


class HealthChecker:
    """System for checking health of all components"""

    async def check_database(self) -> dict:
        """Check database status"""
        try:
            db = SessionLocal()
            db.execute(text("SELECT 1"))
            db.close()
            return {"status": "healthy", "error": None}
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return {"status": "unhealthy", "error": str(e)}

    async def check_redis(self) -> dict:
        """Check Redis status"""
        try:
            if not settings.REDIS_URL:
                return {"status": "not_configured", "error": "Redis URL not configured"}

            redis_client = redis.from_url(settings.REDIS_URL)
            redis_client.ping()
            return {"status": "healthy", "error": None}
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return {"status": "unhealthy", "error": str(e)}

    async def check_openai(self) -> dict:
        """Check OpenAI API status"""
        try:
            if not settings.OPENAI_API_KEY:
                return {
                    "status": "not_configured",
                    "error": "OpenAI API key not configured",
                }

            openai_service = OpenAIService()
            # Check Circuit Breaker state
            cb_state = openai_service.circuit_breaker.state.value
            failure_count = openai_service.circuit_breaker.failure_count

            # Return degraded status for open circuit breaker
            if cb_state == "open":
                status = "degraded"
            elif cb_state == "half_open":
                status = "degraded"
            else:
                status = "healthy"

            return {
                "status": status,
                "circuit_breaker_state": cb_state,
                "failure_count": failure_count,
                "error": None,
            }
        except Exception as e:
            logger.error(f"OpenAI health check failed: {e}")
            return {"status": "unhealthy", "error": str(e)}

    async def check_telegram(self) -> dict:
        """Check Telegram Bot status"""
        try:
            if not settings.TELEGRAM_BOT_TOKEN:
                return {
                    "status": "not_configured",
                    "error": "Telegram bot token not configured",
                }

            telegram_service = TelegramService()
            # Check that bot can be initialized
            telegram_service.bot
            return {"status": "healthy", "error": None}
        except Exception as e:
            logger.error(f"Telegram health check failed: {e}")
            return {"status": "unhealthy", "error": str(e)}

    async def check_whatsapp_bridge(self) -> dict:
        """Check WhatsApp Bridge status"""
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{settings.WHATSAPP_BRIDGE_URL}/health", timeout=5.0
                )
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "status": "healthy",
                        "clients": data.get("clients", 0),
                        "error": None,
                    }
                else:
                    return {
                        "status": "unhealthy",
                        "error": f"HTTP {response.status_code}",
                    }
        except Exception as e:
            logger.error(f"WhatsApp Bridge health check failed: {e}")
            return {"status": "unhealthy", "error": str(e)}

    async def check_rate_limiter(self) -> dict:
        """Check Rate Limiter status"""
        try:
            from app.middleware.openai_rate_limiter import openai_rate_limiter

            stats = openai_rate_limiter.get_stats()

            # Check if we're approaching limits
            minute_usage = stats["requests_last_minute"] / stats["minute_limit"]
            hour_usage = stats["requests_last_hour"] / stats["hour_limit"]

            status = "healthy"
            # Treat exactly 1.0 as warning; consider >1.0 unhealthy
            if minute_usage > 1.0 or hour_usage > 1.0:
                status = "unhealthy"
            elif minute_usage > 0.8 or hour_usage > 0.8:
                status = "warning"

            return {"status": status, "stats": stats, "error": None}
        except Exception as e:
            logger.error(f"Rate limiter health check failed: {e}")
            return {"status": "unhealthy", "error": str(e)}

    async def run_all_checks(self) -> dict:
        """Run all health checks"""
        checks = {
            "database": await self.check_database(),
            "redis": await self.check_redis(),
            "openai": await self.check_openai(),
            "telegram": await self.check_telegram(),
            "whatsapp_bridge": await self.check_whatsapp_bridge(),
            "rate_limiter": await self.check_rate_limiter(),
        }

        # Determine overall status
        unhealthy_count = sum(
            1 for check in checks.values() if check["status"] == "unhealthy"
        )
        degraded_count = sum(
            1 for check in checks.values() if check["status"] == "degraded"
        )
        warning_count = sum(
            1 for check in checks.values() if check["status"] == "warning"
        )

        if unhealthy_count > 0:
            overall_status = "unhealthy"
        elif degraded_count > 0:
            overall_status = "degraded"
        elif warning_count > 0:
            overall_status = "warning"
        else:
            overall_status = "healthy"

        return {
            "status": overall_status,
            "checks": checks,
            "summary": {
                "total_checks": len(checks),
                "healthy": sum(
                    1 for check in checks.values() if check["status"] == "healthy"
                ),
                "degraded": degraded_count,
                "warning": warning_count,
                "unhealthy": unhealthy_count,
                "not_configured": sum(
                    1
                    for check in checks.values()
                    if check["status"] == "not_configured"
                ),
            },
        }


# Global instance of the health checker
health_checker = HealthChecker()
