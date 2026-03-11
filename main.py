import asyncio
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.dashboard import router as dashboard_router
from app.api.health import router as health_router
from app.api.monitoring import router as monitoring_router

try:
    from app.api.web import router as web_router
except ImportError:
    from fastapi import APIRouter

    web_router = APIRouter(prefix="/admin", tags=["web-admin"])

    @web_router.get("/health")
    async def fallback_health():
        return {"status": "degraded", "message": "Web router import failed"}


import app.state as app_state
from app.api.whatsapp_webhooks import router as whatsapp_webhooks_router
from app.core.async_processor import task_processor
from app.core.metrics import metrics_collector
from app.core.tracing import set_trace_context
from app.database.connection import engine, optimize_database
from app.middleware.rate_limiter import RateLimiterMiddleware
from app.models.database import Base
from app.scheduler.digest_scheduler import DigestScheduler
from config.logging_config import get_logger, request_context_filter, setup_logging
from config.settings import settings

setup_logging()
logger = get_logger(__name__)

app_start_time = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global app_start_time
    scheduler_task = None

    try:
        app_start_time = time.time()
        logger.info("Application starting...")

        settings.validate_required_settings()

        logger.info("Creating database tables...")
        Base.metadata.create_all(bind=engine)

        logger.info("Optimizing database...")
        optimize_database()

        logger.info("Starting async task processor...")
        try:
            task_processor.start()
        except Exception as e:
            logger.error(f"Failed to start async task processor: {e}")
            if not settings.DEBUG:
                raise
            logger.warning(
                "Continuing without async task processor in development mode"
            )

        logger.info("Starting metrics server...")
        metrics_collector.start_metrics_server(port=9090)

        logger.info("Starting digest scheduler...")
        app_state.scheduler = DigestScheduler()
        scheduler_task = asyncio.create_task(app_state.scheduler.start_scheduler())

        yield

    except Exception as e:
        logger.error(f"Error during application startup: {e}")
        raise
    finally:
        if app_state.scheduler:
            app_state.scheduler.stop_scheduler()
        if scheduler_task and not scheduler_task.done():
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                logger.info("Scheduler task cancelled successfully")
        if task_processor:
            try:
                task_processor.stop()
            except Exception as e:
                logger.error(f"Error stopping async task processor: {e}")
        try:
            engine.dispose()
            logger.info("Database engine disposed")
        except Exception as e:
            logger.error(f"Error disposing database engine: {e}")
        logger.info("Application shutdown complete")


app = FastAPI(
    title="WhatsApp Digest System",
    description="Intelligent WhatsApp chat monitoring system using AI for analysis and creating digests of important messages.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        f"Unhandled exception on {request.method} {request.url.path}: {exc}",
        exc_info=True,
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(f"Validation error on {request.method} {request.url.path}: {exc}")
    return JSONResponse(
        status_code=422,
        content={"detail": "Validation error", "errors": exc.errors()},
    )


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
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


@app.middleware("http")
async def trace_requests(request: Request, call_next):
    start_time = time.time()
    trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))
    set_trace_context(trace_id)

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
        metrics_collector.record_http_request(
            request.method, request.url.path, response.status_code, duration
        )
        return response
    except Exception:
        duration = time.time() - start_time
        metrics_collector.record_http_request(
            request.method, request.url.path, 500, duration
        )
        raise
    finally:
        if request_context_filter:
            request_context_filter.clear_context()


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)
app.add_middleware(RateLimiterMiddleware, calls_per_minute=60)

app.mount("/static", StaticFiles(directory="web/static"), name="static")

app.include_router(dashboard_router)
app.include_router(health_router)
app.include_router(monitoring_router)
app.include_router(web_router)
app.include_router(whatsapp_webhooks_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=settings.PORT, log_level="info")
