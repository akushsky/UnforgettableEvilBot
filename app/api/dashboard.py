from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from app.core.tracing import trace_manager
from app.database.connection import get_db_session
from config.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Web Interface"])
templates = Jinja2Templates(directory="web/templates")


@router.get("/", response_class=HTMLResponse)
async def main_dashboard(request: Request):
    """Main dashboard page"""
    try:
        trace_context = trace_manager.create_trace()
        span = trace_manager.create_span(trace_context.trace_id, "load_dashboard")

        with get_db_session() as db:
            user_count = db.execute(text("SELECT COUNT(*) FROM users")).scalar()
            active_users = db.execute(
                text("SELECT COUNT(*) FROM users WHERE whatsapp_connected = true")
            ).scalar()
            monitored_chats = db.execute(
                text("SELECT COUNT(*) FROM monitored_chats WHERE is_active = true")
            ).scalar()
            messages_24h = db.execute(
                text(
                    "SELECT COUNT(*) FROM whatsapp_messages WHERE created_at >= NOW() - INTERVAL '24 hours'"
                )
            ).scalar()
            digests_24h = db.execute(
                text(
                    "SELECT COUNT(*) FROM digest_logs WHERE created_at >= NOW() - INTERVAL '24 hours'"
                )
            ).scalar()

            from app.database.connection import health_check_database

            db_health = health_check_database()

            recent_users = db.execute(
                text(
                    "SELECT id, username, email, whatsapp_connected, created_at FROM users ORDER BY created_at DESC LIMIT 5"
                )
            ).fetchall()
            recent_digests = db.execute(
                text(
                    """
                    SELECT dl.id, dl.user_id, dl.message_count, dl.telegram_sent, dl.created_at, u.username
                    FROM digest_logs dl
                    JOIN users u ON dl.user_id = u.id
                    ORDER BY dl.created_at DESC LIMIT 5
                """
                )
            ).fetchall()

        trace_manager.complete_span(span.span_id)
        trace_manager.complete_trace(trace_context.trace_id)

        try:
            from app.core.resource_savings import resource_savings_service

            with get_db_session() as savings_db:
                resource_savings = resource_savings_service.get_total_savings(
                    savings_db, days_back=30
                )
        except Exception as e:
            logger.error(f"Error getting resource savings: {e}")
            resource_savings = {
                "total_whatsapp_connections_saved": 0,
                "total_messages_processed_saved": 0,
                "total_openai_requests_saved": 0,
                "total_memory_mb_saved": 0.0,
                "total_cpu_seconds_saved": 0.0,
                "total_openai_cost_saved_usd": 0.0,
                "period_days": 30,
                "records_count": 0,
            }

        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "stats": {
                    "user_count": user_count,
                    "active_users": active_users,
                    "monitored_chats": monitored_chats,
                    "messages_24h": messages_24h,
                    "digests_24h": digests_24h,
                    "resource_savings": resource_savings,
                },
                "system_health": db_health,
                "recent_users": recent_users,
                "recent_digests": recent_digests,
            },
        )

    except Exception as e:
        logger.error(f"Error loading dashboard: {e}")
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "error": str(e),
                "stats": {
                    "resource_savings": {
                        "total_whatsapp_connections_saved": 0,
                        "total_messages_processed_saved": 0,
                        "total_openai_requests_saved": 0,
                        "total_memory_mb_saved": 0.0,
                        "total_cpu_seconds_saved": 0.0,
                        "total_openai_cost_saved_usd": 0.0,
                        "period_days": 30,
                        "records_count": 0,
                    }
                },
                "system_health": {},
                "recent_users": [],
                "recent_digests": [],
            },
        )
