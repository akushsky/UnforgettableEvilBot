import time

import psutil
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.auth.admin_auth import get_admin_auth_dependency
from app.core.alerts import alert_manager, check_system_health
from app.core.async_processor import task_processor
from app.core.cache import cache_manager
from app.core.metrics import metrics_collector
from app.core.openai_monitoring import openai_monitor
from app.core.tracing import trace_manager
from app.database.connection import (
    get_db_session,
    get_db_stats,
    health_check_database,
)
from app.dependencies import get_telegram_service
from config.logging_config import get_logger
from config.settings import settings

logger = get_logger(__name__)

router = APIRouter(
    tags=["Monitoring"],
    dependencies=[Depends(get_admin_auth_dependency)],
)

process_start_time = psutil.Process().create_time()


def get_scheduler():
    """Get the global scheduler instance."""
    from app.state import scheduler

    return scheduler


async def check_telegram_availability() -> bool:
    try:
        telegram_service = get_telegram_service()
        return await telegram_service.check_bot_health()
    except Exception as e:
        logger.error(f"Error checking Telegram availability: {e}")
        return False


@router.get("/metrics")
async def get_metrics():
    """Endpoint for collecting system metrics"""
    try:
        trace_context = trace_manager.create_trace()
        span = trace_manager.create_span(trace_context.trace_id, "collect_metrics")

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

        trace_manager.complete_span(span.span_id)
        trace_manager.complete_trace(trace_context.trace_id)

        scheduler = get_scheduler()
        async_processor_status = (
            "healthy"
            if task_processor and getattr(task_processor, "running", False)
            else "disabled"
        )

        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
        except Exception as e:
            logger.error(f"Error getting system metrics: {e}")
            cpu_percent = 0.0
            memory = type("Memory", (), {"percent": 0.0})()

        db_stats = get_db_stats()
        pool_info = health_check_database().get("pool_info", {})

        db_performance = {
            "total_connections": pool_info.get("pool_size", 0),
            "active_connections": pool_info.get("checked_out", 0),
            "avg_query_time": db_stats.get("avg_query_time", 0.02),
            "total_queries": db_stats.get("total_queries", 0),
            "slow_queries": db_stats.get("slow_queries", 0),
        }

        cache_stats = cache_manager.get_stats()
        metrics_cache_stats = (
            metrics_collector.get_cache_stats() if metrics_collector else {}
        )
        # Only report hit ratios when the collector has real values — no fake defaults.
        memory_hit_ratio = metrics_cache_stats.get("memory_hit_ratio")
        redis_hit_ratio = (
            metrics_cache_stats.get("redis_hit_ratio")
            if settings.REDIS_ENABLED and cache_stats.get("redis_available")
            else None
        )

        cache_performance = {
            "memory_cache_size": cache_stats.get("memory_cache_size", 0),
            "redis_available": cache_stats.get("redis_available", False),
        }
        if memory_hit_ratio is not None:
            cache_performance["memory_hit_ratio"] = memory_hit_ratio
        if redis_hit_ratio is not None:
            cache_performance["redis_hit_ratio"] = redis_hit_ratio

        try:
            metrics_data = (
                metrics_collector.get_stats()
                if hasattr(metrics_collector, "get_stats")
                else {}
            )
            avg_response_time = metrics_data.get("avg_response_time", 0.0)
        except Exception as e:
            logger.warning(f"Error collecting metrics stats: {e}")
            avg_response_time = 0.0

        openai_stats = openai_monitor.get_stats()

        system_data = {
            "cpu_usage": cpu_percent,
            "memory_usage": memory.percent,
            "avg_response_time": avg_response_time,
            "db_errors": db_stats.get("slow_queries", 0),
            "openai_available": openai_stats.get("success_rate", 1.0) > 0.8
            and openai_stats.get("recent_errors", 0) < 5,
            "telegram_available": await check_telegram_availability(),
            "redis_available": cache_stats.get("redis_available", False),
        }

        check_system_health(system_data)

        active_alerts_count = (
            len(alert_manager.get_active_alerts()) if alert_manager else 0
        )

        response_data = {
            "metrics": {
                "users": {
                    "total": user_count,
                    "active": active_users,
                    "connected_percentage": round(
                        (active_users / user_count * 100) if user_count > 0 else 0, 2
                    ),
                },
                "chats": {"monitored": monitored_chats},
                "messages": {"last_24h": messages_24h},
                "digests": {"last_24h": digests_24h},
                "performance": {
                    "avg_response_time": avg_response_time,
                    "cpu_usage": cpu_percent,
                    "memory_usage": memory.percent,
                    "cache": cache_performance,
                    "database": db_performance,
                },
                "openai": {
                    "total_requests": openai_stats["total_requests"],
                    "total_cost_usd": openai_stats["total_cost_usd"],
                    "success_rate": openai_stats["success_rate"],
                    "recent_24h": openai_stats["recent_24h"],
                    "last_request": openai_stats["last_request_time"],
                    "avg_tokens_per_request": openai_stats.get(
                        "avg_tokens_per_request", 0
                    ),
                    "cost_24h": openai_stats.get("cost_24h", 0),
                    "recent_requests": openai_stats.get("recent_requests", []),
                    "models_usage": openai_stats.get("models_usage", {}),
                },
                "system": {
                    "active_alerts": active_alerts_count,
                    "uptime_seconds": int(time.time() - process_start_time),
                    "process_memory_mb": round(
                        psutil.Process().memory_info().rss / 1024 / 1024, 1
                    ),
                },
                "components": {
                    "scheduler": (
                        "healthy" if scheduler and scheduler.is_running else "disabled"
                    ),
                    "metrics": "healthy" if metrics_collector else "disabled",
                    "async_processor": async_processor_status,
                    "tracing": "healthy" if trace_manager else "disabled",
                    "alerts": "healthy" if alert_manager else "disabled",
                },
            },
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        }

        return JSONResponse(
            content=response_data,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    except Exception as e:
        logger.error(f"Error getting metrics: {e}")
        raise HTTPException(status_code=500, detail="Error getting metrics") from e
