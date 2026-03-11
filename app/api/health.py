import time

import psutil
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.alerts import AlertSeverity, alert_manager, check_system_health
from app.core.async_processor import task_processor
from app.core.cache import cache_manager
from app.core.metrics import metrics_collector
from app.core.openai_monitoring import openai_monitor
from app.core.tracing import trace_manager
from app.database.connection import get_db_session, health_check_database
from app.dependencies import get_telegram_service
from config.logging_config import get_logger
from config.settings import settings

logger = get_logger(__name__)

router = APIRouter(tags=["Health & Metrics"])

process_start_time = psutil.Process().create_time()


def get_scheduler():
    """Get the global scheduler instance."""
    from app.state import scheduler

    return scheduler


@router.get("/health")
async def health_check():
    """Comprehensive health check with real system monitoring"""
    health_status = "healthy"
    checks = {}
    errors = []

    try:
        trace_context = trace_manager.create_trace()
        span = trace_manager.create_span(trace_context.trace_id, "health_check")

        try:
            db_health = health_check_database()
            checks["database"] = {
                "status": db_health["status"],
                "pool_info": db_health["pool_info"],
                "response_time_ms": db_health.get("response_time_ms", 0),
            }
            if db_health["status"] != "healthy":
                health_status = "unhealthy"
                errors.append(f"Database: {db_health.get('error', 'Unknown error')}")
        except Exception as e:
            checks["database"] = {"status": "unhealthy", "error": str(e)}
            health_status = "unhealthy"
            errors.append(f"Database check failed: {e!s}")

        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            process = psutil.Process()
            process_memory = process.memory_info()
            process_cpu = process.cpu_percent()

            checks["system"] = {
                "status": "healthy",
                "cpu_usage_percent": cpu_percent,
                "memory_usage_percent": memory.percent,
                "disk_usage_percent": disk.percent,
                "process_memory_mb": round(process_memory.rss / 1024 / 1024, 1),
                "process_cpu_percent": process_cpu,
                "load_average": (
                    list(psutil.getloadavg()) if hasattr(psutil, "getloadavg") else None
                ),
            }

            if cpu_percent > 90:
                health_status = "unhealthy"
                errors.append(f"High CPU usage: {cpu_percent}%")
            if memory.percent > 90:
                health_status = "unhealthy"
                errors.append(f"High memory usage: {memory.percent}%")
            if disk.percent > 90:
                health_status = "unhealthy"
                errors.append(f"High disk usage: {disk.percent}%")

        except Exception as e:
            checks["system"] = {"status": "error", "error": str(e)}
            errors.append(f"System metrics check failed: {e!s}")

        try:
            cache_stats = cache_manager.get_stats()
            redis_available = cache_stats.get("redis_available", False)
            memory_hit_ratio = cache_stats.get("memory_hit_ratio", 0.0)

            checks["cache"] = {
                "status": "healthy",
                "redis_available": redis_available,
                "memory_cache_size": cache_stats.get("memory_cache_size", 0),
                "memory_hit_ratio": memory_hit_ratio,
                "redis_hit_ratio": (
                    cache_stats.get("redis_hit_ratio", 0.0) if redis_available else None
                ),
            }

            if (
                memory_hit_ratio < 0.5
                and not settings.TESTING
                and settings.USE_OPTIMIZED_REPOSITORIES
            ):
                errors.append(f"Low cache hit ratio: {memory_hit_ratio}")

        except Exception as e:
            checks["cache"] = {"status": "error", "error": str(e)}
            errors.append(f"Cache check failed: {e!s}")

        external_services = {}

        if settings.TESTING:
            external_services["whatsapp_bridge"] = {
                "status": "healthy",
                "response_time_ms": 0,
            }
        else:
            try:
                import aiohttp

                async with (
                    aiohttp.ClientSession(
                        timeout=aiohttp.ClientTimeout(total=5)
                    ) as session,
                    session.get(f"{settings.WHATSAPP_BRIDGE_URL}/health") as resp,
                ):
                    if resp.status == 200:
                        external_services["whatsapp_bridge"] = {
                            "status": "healthy",
                            "response_time_ms": 0,
                        }
                    else:
                        external_services["whatsapp_bridge"] = {
                            "status": "unhealthy",
                            "http_status": resp.status,
                        }
                        errors.append(f"WhatsApp Bridge unhealthy: HTTP {resp.status}")
            except Exception as e:
                external_services["whatsapp_bridge"] = {
                    "status": "error",
                    "error": str(e),
                }
                errors.append(f"WhatsApp Bridge unreachable: {e!s}")

        try:
            openai_stats = openai_monitor.get_stats()
            recent_errors = openai_stats.get("recent_errors", 0)
            success_rate = openai_stats.get("success_rate", 1.0)

            openai_status = "healthy"
            if success_rate < 0.9:
                openai_status = "degraded"
                errors.append(f"OpenAI low success rate: {success_rate}")
            if recent_errors > 10:
                openai_status = "unhealthy"
                errors.append(f"OpenAI recent errors: {recent_errors}")

            external_services["openai"] = {
                "status": openai_status,
                "success_rate": success_rate,
                "recent_errors": recent_errors,
                "total_requests": openai_stats.get("total_requests", 0),
            }
        except Exception as e:
            external_services["openai"] = {"status": "error", "error": str(e)}
            errors.append(f"OpenAI check failed: {e!s}")

        if settings.TESTING:
            external_services["telegram"] = {
                "status": "healthy",
                "bot_available": True,
            }
        else:
            try:
                telegram_service = get_telegram_service()
                telegram_available = await telegram_service.check_bot_health()
                external_services["telegram"] = {
                    "status": "healthy" if telegram_available else "unhealthy",
                    "bot_available": telegram_available,
                }
                if not telegram_available:
                    health_status = "unhealthy"
                    errors.append("Telegram Bot unavailable")
            except Exception as e:
                external_services["telegram"] = {"status": "error", "error": str(e)}
                errors.append(f"Telegram check failed: {e!s}")

        checks["external_services"] = external_services

        scheduler = get_scheduler()
        components = {}
        scheduler_healthy = scheduler and scheduler.is_running
        components["scheduler"] = {
            "status": "healthy" if scheduler_healthy else "disabled",
            "running": scheduler_healthy,
            "next_run": (scheduler.get_next_run_time() if scheduler_healthy else None),
        }

        async_processor_running = task_processor and getattr(
            task_processor, "running", False
        )
        components["async_processor"] = {
            "status": "healthy" if async_processor_running else "disabled",
            "running": async_processor_running,
            "queue_size": (
                getattr(task_processor, "queue_size", 0)
                if async_processor_running
                else 0
            ),
        }
        components["metrics"] = {
            "status": "healthy" if metrics_collector else "disabled",
            "active": bool(metrics_collector),
        }
        components["tracing"] = {
            "status": "healthy" if trace_manager else "disabled",
            "active": bool(trace_manager),
            "active_traces": (len(trace_manager.active_traces) if trace_manager else 0),
        }

        alert_count = len(alert_manager.get_active_alerts()) if alert_manager else 0
        critical_alert_count = (
            len(alert_manager.get_active_alerts(AlertSeverity.CRITICAL))
            if alert_manager
            else 0
        )
        components["alerts"] = {
            "status": "healthy" if alert_manager else "disabled",
            "active": bool(alert_manager),
            "active_alerts": alert_count,
            "critical_alerts": critical_alert_count,
        }

        if alert_count > 10 and critical_alert_count > 0:
            errors.append(
                f"High number of active alerts: {alert_count} (including {critical_alert_count} critical)"
            )

        checks["components"] = components

        try:
            with get_db_session() as db:
                recent_messages = (
                    db.execute(
                        text(
                            "SELECT COUNT(*) FROM whatsapp_messages WHERE created_at >= NOW() - INTERVAL '1 hour'"
                        )
                    ).scalar()
                    or 0
                )
                recent_digests = (
                    db.execute(
                        text(
                            "SELECT COUNT(*) FROM digest_logs WHERE created_at >= NOW() - INTERVAL '1 hour'"
                        )
                    ).scalar()
                    or 0
                )
                active_users_count = (
                    db.execute(
                        text(
                            "SELECT COUNT(*) FROM users WHERE whatsapp_connected = true"
                        )
                    ).scalar()
                    or 0
                )
                checks["application"] = {
                    "status": "healthy",
                    "recent_messages_1h": recent_messages,
                    "recent_digests_1h": recent_digests,
                    "active_users": active_users_count,
                    "uptime_seconds": int(time.time() - process_start_time),
                }
        except Exception as e:
            checks["application"] = {"status": "error", "error": str(e)}
            errors.append(f"Application metrics check failed: {e!s}")

        try:
            try:
                from app.core.resource_savings import resource_savings_service

                with get_db_session() as rs_db:
                    resource_savings = resource_savings_service.get_total_savings(
                        rs_db, days_back=30
                    )
            except Exception as e:
                logger.warning(f"Error getting resource savings in health check: {e}")
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

            if hasattr(metrics_collector, "get_stats"):
                metrics_data = metrics_collector.get_stats()
                avg_response_time = metrics_data.get("avg_response_time", 0)
            else:
                avg_response_time = 0

            checks["performance"] = {
                "status": "healthy",
                "avg_response_time_ms": avg_response_time * 1000,
                "requests_per_minute": (
                    metrics_data.get("requests_per_minute", 0)
                    if "metrics_data" in locals()
                    else 0
                ),
            }

            if avg_response_time > 2.0:
                health_status = "unhealthy"
                errors.append(f"High response time: {avg_response_time}s")

        except Exception as e:
            checks["performance"] = {"status": "error", "error": str(e)}

        system_data = {
            "cpu_usage": checks.get("system", {}).get("cpu_usage_percent", 0),
            "memory_usage": checks.get("system", {}).get("memory_usage_percent", 0),
            "avg_response_time": checks.get("performance", {}).get(
                "avg_response_time_ms", 0
            )
            / 1000,
            "db_errors": (
                1 if checks.get("database", {}).get("status") != "healthy" else 0
            ),
            "openai_available": external_services.get("openai", {}).get("status")
            == "healthy",
            "telegram_available": external_services.get("telegram", {}).get("status")
            == "healthy",
            "cache_hit_ratio": checks.get("cache", {}).get("memory_hit_ratio", 0),
            "use_optimized_repositories": settings.USE_OPTIMIZED_REPOSITORIES,
        }

        new_alerts = check_system_health(system_data) if not settings.TESTING else []

        trace_manager.complete_span(span.span_id)
        trace_manager.complete_trace(trace_context.trace_id)

        if health_status == "healthy" and errors:
            non_critical_warnings = [
                "low success rate",
                "low cache hit ratio",
                "unreachable",
                "unhealthy",
            ]
            all_non_critical = all(
                any(warning in error.lower() for warning in non_critical_warnings)
                for error in errors
            )
            if all_non_critical:
                health_status = "degraded"

        response_data = {
            "status": health_status,
            "service": "WhatsApp Digest System",
            "version": "1.0.0",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "checks": checks,
            "summary": {
                "total_checks": len(
                    [c for c in checks.values() if isinstance(c, dict)]
                ),
                "healthy_checks": len(
                    [
                        c
                        for c in checks.values()
                        if isinstance(c, dict) and c.get("status") == "healthy"
                    ]
                ),
                "errors": errors,
                "new_alerts": len(new_alerts) if new_alerts else 0,
            },
        }

        status_code = (
            200
            if health_status == "healthy"
            else (503 if health_status == "unhealthy" else 200)
        )

        return JSONResponse(
            content=response_data,
            status_code=status_code,
            headers={"Content-Type": "application/json"},
        )

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            content={
                "status": "unhealthy",
                "error": str(e),
                "service": "WhatsApp Digest System",
                "version": "1.0.0",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
                "checks": checks,
                "summary": {
                    "total_checks": 0,
                    "healthy_checks": 0,
                    "errors": [f"Health check system failure: {e!s}"],
                    "new_alerts": 0,
                },
            },
            status_code=503,
            headers={"Content-Type": "application/json"},
        )
