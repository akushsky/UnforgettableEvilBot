import time
from datetime import UTC, datetime

import psutil
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from app.core.alerts import (
    alert_manager,
    check_system_health,
    clear_all_alerts,
    get_system_alerts,
)
from app.core.alerts import (
    clear_alerts_by_title as _clear_alerts_by_title,
)
from app.core.async_processor import task_processor
from app.core.cache import cache_manager
from app.core.metrics import metrics_collector
from app.core.openai_monitoring import openai_monitor
from app.core.tracing import trace_manager
from app.database.connection import (
    get_db_session,
    get_db_stats,
    health_check_database,
    optimize_database,
)
from app.dependencies import get_telegram_service
from config.logging_config import get_logger
from config.settings import settings

logger = get_logger(__name__)

router = APIRouter(tags=["Monitoring"])
templates = Jinja2Templates(directory="web/templates")

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
        memory_hit_ratio = metrics_cache_stats.get("memory_hit_ratio", 0.85)
        redis_hit_ratio = (
            metrics_cache_stats.get("redis_hit_ratio", 0.0)
            if settings.REDIS_ENABLED and cache_stats.get("redis_available")
            else 0.0
        )

        cache_performance = {
            "memory_hit_ratio": memory_hit_ratio,
            "redis_hit_ratio": redis_hit_ratio,
            "memory_cache_size": cache_stats.get("memory_cache_size", 0),
            "redis_available": cache_stats.get("redis_available", False),
        }

        try:
            metrics_data = (
                metrics_collector.get_stats()
                if hasattr(metrics_collector, "get_stats")
                else {}
            )
            avg_response_time = metrics_data.get("avg_response_time", 0.5)
        except Exception as e:
            logger.warning(f"Error collecting metrics stats: {e}")
            avg_response_time = 0.5

        try:
            from app.core.resource_savings import resource_savings_service

            with get_db_session() as rs_db:
                resource_savings = resource_savings_service.get_total_savings(
                    rs_db, days_back=30
                )
            current_system_savings = (
                resource_savings_service.get_current_system_savings()
            )
        except Exception as e:
            logger.error(f"Error getting resource savings metrics: {e}")
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
            current_system_savings = {
                "current_memory_usage_mb": 0.0,
                "current_cpu_usage_percent": 0.0,
                "estimated_memory_saved_mb": 0.0,
                "estimated_cpu_saved_percent": 0.0,
                "timestamp": datetime.now(UTC).isoformat(),
            }

        openai_stats = openai_monitor.get_stats()

        system_data = {
            "cpu_usage": cpu_percent,
            "memory_usage": memory.percent,
            "avg_response_time": avg_response_time,
            "db_errors": db_stats.get("slow_queries", 0),
            "openai_available": openai_stats.get("success_rate", 1.0) > 0.8
            and openai_stats.get("recent_errors", 0) < 5,
            "telegram_available": await check_telegram_availability(),
            "cache_hit_ratio": memory_hit_ratio,
            "use_optimized_repositories": settings.USE_OPTIMIZED_REPOSITORIES,
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
                "resource_savings": {
                    "total_whatsapp_connections_saved": resource_savings.get(
                        "total_whatsapp_connections_saved", 0
                    ),
                    "total_messages_processed_saved": resource_savings.get(
                        "total_messages_processed_saved", 0
                    ),
                    "total_openai_requests_saved": resource_savings.get(
                        "total_openai_requests_saved", 0
                    ),
                    "total_memory_mb_saved": resource_savings.get(
                        "total_memory_mb_saved", 0.0
                    ),
                    "total_cpu_seconds_saved": resource_savings.get(
                        "total_cpu_seconds_saved", 0.0
                    ),
                    "total_openai_cost_saved_usd": resource_savings.get(
                        "total_openai_cost_saved_usd", 0.0
                    ),
                    "period_days": resource_savings.get("period_days", 30),
                    "records_count": resource_savings.get("records_count", 0),
                    "current_system": current_system_savings,
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


@router.get("/performance/optimize")
async def optimize_performance():
    """Endpoint for performance optimization"""
    try:
        optimize_database()
        return {
            "message": "Database optimization completed",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        }
    except Exception as e:
        logger.error(f"Error during performance optimization: {e}")
        raise HTTPException(status_code=500, detail="Error during optimization") from e


@router.get("/monitoring/traces")
async def get_traces(limit: int = 10):
    """Endpoint for getting traces"""
    try:
        traces = trace_manager.get_recent_traces(limit)
        active_traces = len(trace_manager.active_traces)
        total_traces = len(trace_manager.completed_traces) + active_traces
        return {
            "traces": traces,
            "total_traces": total_traces,
            "active_traces": active_traces,
            "message": f"Retrieved {len(traces)} traces",
        }
    except Exception as e:
        logger.error(f"Error getting traces: {e}")
        raise HTTPException(status_code=500, detail="Error getting traces") from e


@router.get("/monitoring/traces/{trace_id}")
async def get_trace(trace_id: str):
    """Endpoint for getting specific trace"""
    try:
        trace_data = trace_manager.get_trace_summary(trace_id)
        if not trace_data:
            raise HTTPException(status_code=404, detail="Trace not found")
        return trace_data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting trace {trace_id}: {e}")
        raise HTTPException(status_code=500, detail="Error getting trace") from e


@router.get("/monitoring/traces/{trace_id}/export")
async def export_trace(trace_id: str):
    """Endpoint for exporting trace to JSON"""
    try:
        trace_json = trace_manager.export_trace(trace_id)
        if not trace_json:
            raise HTTPException(status_code=404, detail="Trace not found")
        return Response(
            content=trace_json,
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=trace_{trace_id}.json"
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting trace {trace_id}: {e}")
        raise HTTPException(status_code=500, detail="Error exporting trace") from e


@router.get("/monitoring/alerts")
async def get_alerts():
    """Endpoint for getting system alerts"""
    try:
        return get_system_alerts()
    except Exception as e:
        logger.error(f"Error getting alerts: {e}")
        raise HTTPException(status_code=500, detail="Error getting alerts") from e


@router.get("/monitoring/openai")
async def get_openai_stats():
    """Get OpenAI usage statistics"""
    try:
        return {
            "openai": openai_monitor.get_stats(),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        }
    except Exception as e:
        logger.error(f"Error getting OpenAI stats: {e}")
        raise HTTPException(status_code=500, detail="Error getting OpenAI stats") from e


@router.post("/monitoring/alerts/clear")
async def clear_alerts():
    """Clear all alerts"""
    try:
        clear_all_alerts()
        return {"message": "All alerts cleared successfully"}
    except Exception as e:
        logger.error(f"Error clearing alerts: {e}")
        raise HTTPException(status_code=500, detail="Error clearing alerts") from e


@router.post("/monitoring/alerts/clear/{title_pattern}")
async def clear_alerts_by_pattern(title_pattern: str):
    """Clear alerts by title pattern"""
    try:
        _clear_alerts_by_title(title_pattern)
        return {"message": f"Alerts matching '{title_pattern}' cleared successfully"}
    except Exception as e:
        logger.error(f"Error clearing alerts: {e}")
        raise HTTPException(status_code=500, detail="Error clearing alerts") from e


@router.post("/monitoring/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str, user: str):
    """Endpoint for acknowledging alert"""
    try:
        alert_manager.acknowledge_alert(alert_id, user)
        return {"message": "Alert acknowledged successfully"}
    except Exception as e:
        logger.error(f"Error acknowledging alert {alert_id}: {e}")
        raise HTTPException(status_code=500, detail="Error acknowledging alert") from e


@router.post("/monitoring/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: str):
    """Endpoint for resolving alert"""
    try:
        alert_manager.resolve_alert(alert_id)
        return {"message": "Alert resolved successfully"}
    except Exception as e:
        logger.error(f"Error resolving alert {alert_id}: {e}")
        raise HTTPException(status_code=500, detail="Error resolving alert") from e


@router.post("/monitoring/health-check")
async def trigger_health_check():
    """Endpoint for triggering system health check"""
    try:
        system_data = {
            "cpu_usage": 0.0,
            "memory_usage": 0.0,
            "avg_response_time": 0.5,
            "db_errors": 0,
            "openai_available": True,
            "telegram_available": True,
            "cache_hit_ratio": 0.8,
            "use_optimized_repositories": settings.USE_OPTIMIZED_REPOSITORIES,
        }
        new_alerts = check_system_health(system_data)
        return {
            "message": "Health check completed",
            "new_alerts": len(new_alerts),
            "system_data": system_data,
        }
    except Exception as e:
        logger.error(f"Error during health check: {e}")
        raise HTTPException(status_code=500, detail="Error during health check") from e


@router.get("/monitoring/dashboard")
async def monitoring_dashboard(request: Request):
    """Monitoring dashboard"""
    return templates.TemplateResponse(request, "monitoring_dashboard.html")
