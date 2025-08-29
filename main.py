import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

import psutil
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from app.api.web import router as web_router
from app.api.whatsapp_webhooks import router as whatsapp_webhooks_router

# Import all components
from app.core.alerts import alert_manager, check_system_health, get_system_alerts
from app.core.async_processor import task_processor
from app.core.cache import cache_manager
from app.core.metrics import metrics_collector
from app.core.openai_monitoring import openai_monitor
from app.core.tracing import set_trace_context, trace_manager
from app.database.connection import (
    SessionLocal,
    engine,
    get_db_stats,
    health_check_database,
    optimize_database,
)
from app.middleware.rate_limiter import RateLimiterMiddleware
from app.models.database import Base
from app.scheduler.digest_scheduler import DigestScheduler
from config.logging_config import get_logger, request_context_filter, setup_logging
from config.settings import settings

# Enhanced logging setup
setup_logging()
logger = get_logger(__name__)

# Global variables
scheduler = None
app_start_time = None  # Will be set when app starts

# Get process start time (doesn't reset on reload)

process_start_time = psutil.Process().create_time()

# Test traces removed - real traces will be created during actual operations


async def check_telegram_availability():
    """Helper function to check Telegram bot availability"""
    try:
        from app.telegram.service import TelegramService

        telegram_service = TelegramService()
        return await telegram_service.check_bot_health()
    except Exception as e:
        logger.error(f"Error checking Telegram availability: {e}")
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management with optimizations and monitoring"""
    global scheduler, app_start_time
    scheduler_task = None

    try:
        # Set application start time
        app_start_time = time.time()
        logger.info(
            f"Application started at {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(app_start_time))}"
        )
        logger.info(
            f"Process started at {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(process_start_time))}"
        )

        # Validation of critical settings at startup
        logger.info("Validating required settings...")
        settings.validate_required_settings()

        # Create database tables
        logger.info("Creating database tables...")
        Base.metadata.create_all(bind=engine)

        # Database optimization at startup
        logger.info("Optimizing database...")
        optimize_database()

        # Start async task processor
        logger.info("Starting async task processor...")
        try:
            task_processor.start()
        except Exception as e:
            logger.error(f"Failed to start async task processor: {e}")
            if not settings.DEBUG:
                raise  # Re-raise in production
            else:
                logger.warning(
                    "Continuing without async task processor in development mode"
                )

        # Start metrics server
        logger.info("Starting metrics server...")
        metrics_collector.start_metrics_server(port=9090)

        # Start digest scheduler
        logger.info("Starting digest scheduler...")
        scheduler = DigestScheduler()
        scheduler_task = asyncio.create_task(scheduler.start_scheduler())

        # Test traces creation removed - real traces will be created during operations

        yield

    except Exception as e:
        logger.error(f"Error during application startup: {e}")
        raise
    finally:
        # Stop scheduler on shutdown
        if scheduler:
            scheduler.stop_scheduler()
            logger.info("Scheduler stop signal sent")

        # Proper cancellation of scheduler task
        if scheduler_task and not scheduler_task.done():
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                logger.info("Scheduler task cancelled successfully")

        # Stop async task processor
        if task_processor:
            logger.info("Stopping async task processor...")
            try:
                task_processor.stop()
            except Exception as e:
                logger.error(f"Error stopping async task processor: {e}")

        logger.info("Application shutdown complete")


# Create application
app = FastAPI(
    title="WhatsApp Digest System",
    description="""
    ## 📱 WhatsApp Digest System

    Intelligent WhatsApp chat monitoring system using AI for analysis
    and creating digests of important messages.

    ### 🌟 Main Features:
    - **AI Message Analysis**: Automatic importance assessment of messages
    - **Smart Digests**: Creating summaries of important events
    - **Telegram Integration**: Notifications via Telegram bot
    - **Web Interface**: Convenient management through browser
    - **Monitoring**: Comprehensive system monitoring

    ### 🔧 Technologies:
    - FastAPI + SQLAlchemy
    - OpenAI GPT for analysis
    - WhatsApp Web Bridge
    - Prometheus metrics
    - Redis caching

    ### 📚 Documentation Sections:
    - **Auth**: Authentication and authorization
    - **Users**: User management
    - **WhatsApp**: WhatsApp integration
    - **Monitoring**: Monitoring systems
    - **Web**: Web interface
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
    contact={
        "name": "WhatsApp Digest Team",
        "url": "https://github.com/whatsapp-digest/bot",
        "email": "team@whatsappdigest.com",
    },
    license_info={
        "name": "MIT License",
        "url": "https://opensource.org/licenses/MIT",
    },
    openapi_tags=[
        {
            "name": "Authentication",
            "description": "Authentication and access token management",
        },
        {
            "name": "Users",
            "description": "User management and their settings",
        },
        {
            "name": "WhatsApp",
            "description": "WhatsApp integration and chat management",
        },
        {
            "name": "Webhooks",
            "description": "Processing webhooks from external services",
        },
        {
            "name": "Monitoring",
            "description": "System monitoring, metrics and alerts",
        },
        {
            "name": "Web Interface",
            "description": "Web interface for system management",
        },
        {
            "name": "Health & Metrics",
            "description": "System health checks and metrics collection",
        },
    ],
)

# Initialize templates
templates = Jinja2Templates(directory="web/templates")

# Trusted Host middleware - allow all hosts
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"],
)


# Security Headers middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Adding security headers"""
    response = await call_next(request)

    # Security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

    # Content Security Policy
    csp_policy = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fastapi.tiangolo.com; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fastapi.tiangolo.com; "
        "img-src 'self' data: https: https://fastapi.tiangolo.com; "
        "font-src 'self' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "connect-src 'self' https://api.openai.com https://api.telegram.org; "
        "frame-ancestors 'none';"
    )
    response.headers["Content-Security-Policy"] = csp_policy

    return response


# Request tracing middleware
@app.middleware("http")
async def trace_requests(request: Request, call_next):
    """Simplified middleware for request tracing"""
    start_time = time.time()

    # Create trace_id for request
    trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))
    set_trace_context(trace_id)

    # Set logging context
    if request_context_filter:
        request_context_filter.set_context(
            request_id=trace_id,
            method=request.method,
            path=request.url.path,
            user_agent=request.headers.get("user-agent", ""),
            client_ip=request.client.host if request.client else "unknown",
        )

    try:
        response = await call_next(request)
        duration = time.time() - start_time

        # Log request
        logger.info(
            f"Request: {request.method} {request.url.path} -> {response.status_code} ({duration:.3f}s)",
            extra={
                "request_id": trace_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration": duration,
            },
        )

        # Record metrics
        metrics_collector.record_http_request(
            request.method, request.url.path, response.status_code, duration
        )

        return response

    except Exception as e:
        duration = time.time() - start_time

        # Log error
        logger.error(
            f"Request failed: {request.method} {request.url.path} -> ERROR ({duration:.3f}s)",
            extra={
                "request_id": trace_id,
                "method": request.method,
                "path": request.url.path,
                "error": str(e),
                "duration": duration,
            },
        )

        # Record error metrics
        metrics_collector.record_http_request(
            request.method, request.url.path, 500, duration
        )

        raise
    finally:
        # Clear context
        if request_context_filter:
            request_context_filter.clear_context()


# CORS middleware - secure configuration through environment variables
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Rate Limiter middleware - fix parameters
app.add_middleware(
    RateLimiterMiddleware, calls_per_minute=60  # Fix to correct parameter
)

# Static files
app.mount("/static", StaticFiles(directory="web/static"), name="static")

# Connect routers
app.include_router(web_router)
app.include_router(whatsapp_webhooks_router)


# Main dashboard endpoint
@app.get("/", response_class=HTMLResponse)
async def main_dashboard(request: Request):
    """Main dashboard page"""
    try:
        # Create a trace for dashboard loading
        trace_context = trace_manager.create_trace()
        span = trace_manager.create_span(trace_context.trace_id, "load_dashboard")

        db = SessionLocal()

        # Get system statistics
        user_count = db.execute(text("SELECT COUNT(*) FROM users")).scalar()
        active_users = db.execute(
            text("SELECT COUNT(*) FROM users WHERE whatsapp_connected = true")
        ).scalar()
        monitored_chats = db.execute(
            text("SELECT COUNT(*) FROM monitored_chats WHERE is_active = true")
        ).scalar()

        # Recent activity (last 24 hours)
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

        # System health
        from app.database.connection import health_check_database

        db_health = health_check_database()

        # Get recent users
        recent_users = db.execute(
            text(
                "SELECT id, username, email, whatsapp_connected, created_at FROM users ORDER BY created_at DESC LIMIT 5"
            )
        ).fetchall()

        # Get recent digests
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

        db.close()

        # Complete the trace
        trace_manager.complete_span(span.span_id)
        trace_manager.complete_trace(trace_context.trace_id)

        # Get resource savings data
        try:
            from app.core.resource_savings import resource_savings_service

            # Create a new database session for resource savings
            with SessionLocal() as savings_db:
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


# Health check endpoint
@app.get("/health")
async def health_check():  # noqa: C901
    """Comprehensive health check with real system monitoring"""
    health_status = "healthy"
    checks = {}
    errors = []

    try:
        # Create a trace for health check
        trace_context = trace_manager.create_trace()
        span = trace_manager.create_span(trace_context.trace_id, "health_check")

        # 1. Database Health Check
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
            errors.append(f"Database check failed: {str(e)}")

        # 2. System Resources Check
        try:
            import psutil

            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage("/")

            # Get process-specific metrics
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

            # Check for resource alerts
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
            errors.append(f"System metrics check failed: {str(e)}")

        # 3. Cache Health Check
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

            # Check cache performance (skip in test environment and when optimized repositories are disabled)
            if (
                memory_hit_ratio < 0.5
                and not settings.TESTING
                and settings.USE_OPTIMIZED_REPOSITORIES
            ):
                # Treat as a warning, not outage
                errors.append(f"Low cache hit ratio: {memory_hit_ratio}")

        except Exception as e:
            checks["cache"] = {"status": "error", "error": str(e)}
            errors.append(f"Cache check failed: {str(e)}")

        # 4. External Services Check
        external_services = {}

        # Check WhatsApp Bridge (skip in test environment)
        if settings.TESTING:
            external_services["whatsapp_bridge"] = {
                "status": "healthy",
                "response_time_ms": 0,
            }
        else:
            try:
                import aiohttp

                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as session:
                    async with session.get(
                        f"{settings.WHATSAPP_BRIDGE_URL}/health"
                    ) as resp:
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
                            # Do not mark overall unhealthy; record as issue
                            errors.append(
                                f"WhatsApp Bridge unhealthy: HTTP {resp.status}"
                            )
            except Exception as e:
                external_services["whatsapp_bridge"] = {
                    "status": "error",
                    "error": str(e),
                }
                # Do not mark overall unhealthy; record as issue
                errors.append(f"WhatsApp Bridge unreachable: {str(e)}")

        # Check OpenAI API availability
        try:
            from app.core.openai_monitoring import openai_monitor

            openai_stats = openai_monitor.get_stats()
            recent_errors = openai_stats.get("recent_errors", 0)
            success_rate = openai_stats.get("success_rate", 1.0)

            openai_status = "healthy"
            if success_rate < 0.9:
                openai_status = "degraded"
                # Do not mark overall unhealthy; record as issue
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
            errors.append(f"OpenAI check failed: {str(e)}")

        # Check Telegram Bot availability (skip in test environment)
        if settings.TESTING:
            external_services["telegram"] = {
                "status": "healthy",
                "bot_available": True,
            }
        else:
            try:
                from app.telegram.service import TelegramService

                telegram_service = TelegramService()
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
                errors.append(f"Telegram check failed: {str(e)}")

        checks["external_services"] = external_services

        # 5. Component Health Check
        components = {}

        # Scheduler check
        scheduler_healthy = scheduler and scheduler.is_running
        components["scheduler"] = {
            "status": "healthy" if scheduler_healthy else "disabled",
            "running": scheduler_healthy,
            "next_run": (
                scheduler.get_next_run_time()
                if scheduler_healthy and scheduler
                else None
            ),
        }

        # Async processor check
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

        # Metrics collector check
        components["metrics"] = {
            "status": "healthy" if metrics_collector else "disabled",
            "active": bool(metrics_collector),
        }

        # Tracing check
        components["tracing"] = {
            "status": "healthy" if trace_manager else "disabled",
            "active": bool(trace_manager),
            "active_traces": len(trace_manager.active_traces) if trace_manager else 0,
        }

        # Alert manager check
        alert_count = len(alert_manager.get_active_alerts()) if alert_manager else 0
        components["alerts"] = {
            "status": "healthy" if alert_manager else "disabled",
            "active": bool(alert_manager),
            "active_alerts": alert_count,
        }

        if alert_count > 10:
            health_status = "unhealthy"
            errors.append(f"High number of active alerts: {alert_count}")

        checks["components"] = components

        # 6. Application-specific checks
        try:
            with SessionLocal() as db:
                # Check recent activity
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

                active_users = (
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
                    "active_users": active_users,
                    "uptime_seconds": int(time.time() - process_start_time),
                }

        except Exception as e:
            checks["application"] = {"status": "error", "error": str(e)}
            errors.append(f"Application metrics check failed: {str(e)}")

        # 7. Performance metrics
        try:
            # Get real performance metrics
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

            if avg_response_time > 2.0:  # 2 seconds
                health_status = "unhealthy"
                errors.append(f"High response time: {avg_response_time}s")

        except Exception as e:
            checks["performance"] = {"status": "error", "error": str(e)}

        # Collect system data for alert checking
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

        # Check for new alerts (skip in test environment)
        new_alerts = check_system_health(system_data) if not settings.TESTING else []

        # Complete the trace
        trace_manager.complete_span(span.span_id)
        trace_manager.complete_trace(trace_context.trace_id)

        # Determine final status
        # If only non-critical issues were detected, consider status degraded
        if health_status == "healthy" and errors:
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

        # Set appropriate HTTP status code
        status_code = (
            200
            if health_status == "healthy"
            else (503 if health_status == "unhealthy" else 200)
        )

        from fastapi.responses import JSONResponse

        return JSONResponse(
            content=response_data,
            status_code=status_code,
            headers={"Content-Type": "application/json"},
        )

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        from fastapi.responses import JSONResponse

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
                    "errors": [f"Health check system failure: {str(e)}"],
                    "new_alerts": 0,
                },
            },
            status_code=503,
            headers={"Content-Type": "application/json"},
        )


@app.get("/metrics")
async def get_metrics():
    """Simplified endpoint for collecting system metrics"""
    try:
        # Create a trace for metrics collection
        trace_context = trace_manager.create_trace()
        span = trace_manager.create_span(trace_context.trace_id, "collect_metrics")

        db = SessionLocal()

        # Counters from database
        user_count = db.execute(text("SELECT COUNT(*) FROM users")).scalar()
        active_users = db.execute(
            text("SELECT COUNT(*) FROM users WHERE whatsapp_connected = true")
        ).scalar()
        monitored_chats = db.execute(
            text("SELECT COUNT(*) FROM monitored_chats WHERE is_active = true")
        ).scalar()

        # Message statistics for last 24 hours
        messages_24h = db.execute(
            text(
                """
            SELECT COUNT(*) FROM whatsapp_messages
            WHERE created_at >= NOW() - INTERVAL '24 hours'
        """
            )
        ).scalar()

        # Digest statistics for last 24 hours
        digests_24h = db.execute(
            text(
                """
            SELECT COUNT(*) FROM digest_logs
            WHERE created_at >= NOW() - INTERVAL '24 hours'
        """
            )
        ).scalar()

        db.close()

        # Complete the trace
        trace_manager.complete_span(span.span_id)
        trace_manager.complete_trace(trace_context.trace_id)

        # Determine async processor status
        async_processor_status = (
            "healthy"
            if task_processor and getattr(task_processor, "running", False)
            else "disabled"
        )

        # Get real performance metrics

        import psutil

        # System metrics
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
        except Exception as e:
            logger.error(f"Error getting system metrics: {e}")
            cpu_percent = 0.0
            memory = type("Memory", (), {"percent": 0.0})()

        # Database performance (real data from connection pool and stats)
        db_stats = get_db_stats()
        pool_info = health_check_database().get("pool_info", {})

        db_performance = {
            "total_connections": pool_info.get("pool_size", 0),
            "active_connections": pool_info.get("checked_out", 0),
            "avg_query_time": db_stats.get("avg_query_time", 0.02),
            "total_queries": db_stats.get("total_queries", 0),
            "slow_queries": db_stats.get("slow_queries", 0),
        }

        # Cache performance (real data from cache manager and metrics collector)
        cache_stats = cache_manager.get_stats()
        metrics_cache_stats = (
            metrics_collector.get_cache_stats() if metrics_collector else {}
        )

        # Use real hit ratios from metrics collector, fallback to cache manager
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

        # Response time (real data from metrics collector)
        try:
            # Get average response time from metrics collector
            metrics_data = (
                metrics_collector.get_stats()
                if hasattr(metrics_collector, "get_stats")
                else {}
            )
            avg_response_time = metrics_data.get("avg_response_time", 0.5)
        except BaseException:
            avg_response_time = 0.5  # Fallback

        # Resource savings metrics
        try:
            from app.core.resource_savings import resource_savings_service

            resource_savings = resource_savings_service.get_total_savings(
                db, days_back=30
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
                "timestamp": datetime.utcnow().isoformat(),
            }

        # OpenAI statistics
        openai_stats = openai_monitor.get_stats()

        # Check for alerts based on collected metrics
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

        # Check for new alerts
        check_system_health(system_data)

        # Active alerts count
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
                    "total_whatsapp_connections_saved": resource_savings[
                        "total_whatsapp_connections_saved"
                    ],
                    "total_messages_processed_saved": resource_savings[
                        "total_messages_processed_saved"
                    ],
                    "total_openai_requests_saved": resource_savings[
                        "total_openai_requests_saved"
                    ],
                    "total_memory_mb_saved": resource_savings["total_memory_mb_saved"],
                    "total_cpu_seconds_saved": resource_savings[
                        "total_cpu_seconds_saved"
                    ],
                    "total_openai_cost_saved_usd": resource_savings[
                        "total_openai_cost_saved_usd"
                    ],
                    "period_days": resource_savings["period_days"],
                    "records_count": resource_savings["records_count"],
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
        raise HTTPException(status_code=500, detail="Error getting metrics")


@app.get("/performance/optimize")
async def optimize_performance():
    """Simplified endpoint for performance optimization"""
    try:
        # Database optimization
        optimize_database()

        return {
            "message": "Database optimization completed",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        }

    except Exception as e:
        logger.error(f"Error during performance optimization: {e}")
        raise HTTPException(status_code=500, detail="Error during optimization")


@app.get("/monitoring/traces")
async def get_traces(limit: int = 10):
    """Endpoint for getting traces"""
    try:
        # Get traces from trace manager
        traces = trace_manager.get_recent_traces(limit)

        # Count active and total traces
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
        raise HTTPException(status_code=500, detail="Error getting traces")


@app.get("/monitoring/traces/{trace_id}")
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
        raise HTTPException(status_code=500, detail="Error getting trace")


@app.get("/monitoring/traces/{trace_id}/export")
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
        raise HTTPException(status_code=500, detail="Error exporting trace")


@app.get("/monitoring/alerts")
async def get_alerts():
    """Endpoint for getting system alerts"""
    try:
        return get_system_alerts()
    except Exception as e:
        logger.error(f"Error getting alerts: {e}")
        raise HTTPException(status_code=500, detail="Error getting alerts")


@app.get("/monitoring/openai")
async def get_openai_stats():
    """Get OpenAI usage statistics"""
    try:
        return {
            "openai": openai_monitor.get_stats(),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        }
    except Exception as e:
        logger.error(f"Error getting OpenAI stats: {e}")
        raise HTTPException(status_code=500, detail="Error getting OpenAI stats")


@app.post("/monitoring/alerts/clear")
async def clear_alerts():
    """Clear all alerts"""
    try:
        from app.core.alerts import clear_all_alerts

        clear_all_alerts()
        return {"message": "All alerts cleared successfully"}
    except Exception as e:
        logger.error(f"Error clearing alerts: {e}")
        raise HTTPException(status_code=500, detail="Error clearing alerts")


@app.post("/monitoring/alerts/clear/{title_pattern}")
async def clear_alerts_by_title(title_pattern: str):
    """Clear alerts by title pattern"""
    try:
        from app.core.alerts import clear_alerts_by_title

        clear_alerts_by_title(title_pattern)
        return {"message": f"Alerts matching '{title_pattern}' cleared successfully"}
    except Exception as e:
        logger.error(f"Error clearing alerts: {e}")
        raise HTTPException(status_code=500, detail="Error clearing alerts")


@app.post("/monitoring/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str, user: str):
    """Endpoint for acknowledging alert"""
    try:
        alert_manager.acknowledge_alert(alert_id, user)
        return {"message": "Alert acknowledged successfully"}
    except Exception as e:
        logger.error(f"Error acknowledging alert {alert_id}: {e}")
        raise HTTPException(status_code=500, detail="Error acknowledging alert")


@app.post("/monitoring/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: str):
    """Endpoint for resolving alert"""
    try:
        alert_manager.resolve_alert(alert_id)
        return {"message": "Alert resolved successfully"}
    except Exception as e:
        logger.error(f"Error resolving alert {alert_id}: {e}")
        raise HTTPException(status_code=500, detail="Error resolving alert")


@app.post("/monitoring/health-check")
async def trigger_health_check():
    """Endpoint for triggering system health check"""
    try:
        # Collect system data
        system_data = {
            "cpu_usage": 0.0,  # In real system get from psutil
            "memory_usage": 0.0,  # In real system get from psutil
            "avg_response_time": 0.5,  # In real system get from metrics
            "db_errors": 0,  # In real system get from metrics
            "openai_available": True,  # In real system check
            "telegram_available": True,  # In real system check
            "cache_hit_ratio": 0.8,  # In real system get from cache
            "use_optimized_repositories": settings.USE_OPTIMIZED_REPOSITORIES,
        }

        # Check alerts
        new_alerts = check_system_health(system_data)

        return {
            "message": "Health check completed",
            "new_alerts": len(new_alerts),
            "system_data": system_data,
        }
    except Exception as e:
        logger.error(f"Error during health check: {e}")
        raise HTTPException(status_code=500, detail="Error during health check")


@app.get("/monitoring/dashboard")
async def monitoring_dashboard(request: Request):
    """Monitoring dashboard"""
    return templates.TemplateResponse("monitoring_dashboard.html", {"request": request})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=settings.PORT, log_level="info")
