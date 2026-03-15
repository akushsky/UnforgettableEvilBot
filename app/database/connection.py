import time
from contextlib import contextmanager
from typing import TypedDict

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from config.logging_config import get_logger
from config.settings import settings

logger = get_logger(__name__)

_engine: Engine | None = None
_session_local: sessionmaker[Session] | None = None


def get_engine():
    """Lazily create and return the SQLAlchemy engine (cached after first call)."""
    global _engine
    if _engine is not None:
        return _engine

    connect_args = {}
    if settings.DATABASE_URL.startswith("postgresql"):
        connect_args = {
            "connect_timeout": 10,
            "application_name": "WhatsAppDigestBot",
        }

    _engine = create_engine(
        settings.DATABASE_URL,
        poolclass=QueuePool,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=False,
        connect_args=connect_args,
    )

    @event.listens_for(_engine, "before_cursor_execute")
    def _before_cursor_execute(
        conn, cursor, statement, parameters, context, executemany
    ):
        context._query_start_time = time.time()

    @event.listens_for(_engine, "after_cursor_execute")
    def _after_cursor_execute(
        conn, cursor, statement, parameters, context, executemany
    ):
        total = time.time() - context._query_start_time
        _db_stats["total_queries"] = _db_stats["total_queries"] + 1
        query_times = _db_stats["query_times"]
        if isinstance(query_times, list):
            query_times.append(total)

        if total > 1.0:
            _db_stats["slow_queries"] = _db_stats["slow_queries"] + 1
            logger.warning(f"Slow query detected: {total:.3f}s - {statement[:100]}...")

    return _engine


def _get_session_local():
    """Lazily create and return the session factory."""
    global _session_local
    if _session_local is None:
        _session_local = sessionmaker(
            autocommit=False, autoflush=False, bind=get_engine()
        )
    return _session_local


def reset_engine():
    """Reset the cached engine and session factory (for testing)."""
    global _engine, _session_local
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_local = None


class DatabaseStats(TypedDict):
    total_queries: int
    slow_queries: int
    connection_errors: int
    query_times: list[float]
    avg_query_time: float
    max_query_time: float
    min_query_time: float


_db_stats: DatabaseStats = {
    "total_queries": 0,
    "slow_queries": 0,
    "connection_errors": 0,
    "query_times": [],
    "avg_query_time": 0.0,
    "max_query_time": 0.0,
    "min_query_time": 0.0,
}


def get_db():
    """Get database session with automatic closing"""
    db = _get_session_local()()
    try:
        yield db
    except Exception as e:
        _db_stats["connection_errors"] = _db_stats["connection_errors"] + 1
        logger.error(f"Database error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def get_db_session():
    """Context manager for working with database"""
    db = _get_session_local()()
    try:
        yield db
        db.commit()
    except Exception as e:
        _db_stats["connection_errors"] = _db_stats["connection_errors"] + 1
        logger.error(f"Database error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


def get_db_stats():
    """Get database statistics"""
    stats = _db_stats.copy()

    query_times = stats["query_times"]
    if isinstance(query_times, list) and query_times:
        avg_time = sum(query_times) / len(query_times)
        max_time = max(query_times)
        min_time = min(query_times)
        stats["avg_query_time"] = avg_time
        stats["max_query_time"] = max_time
        stats["min_query_time"] = min_time
    else:
        stats["avg_query_time"] = 0
        stats["max_query_time"] = 0
        stats["min_query_time"] = 0

    if isinstance(query_times, list):
        limited_times = query_times[-1000:]
        stats["query_times"] = limited_times

    return stats


def reset_db_stats():
    """Reset database statistics"""
    global _db_stats
    _db_stats = {
        "total_queries": 0,
        "slow_queries": 0,
        "connection_errors": 0,
        "query_times": [],
        "avg_query_time": 0.0,
        "max_query_time": 0.0,
        "min_query_time": 0.0,
    }


def optimize_database():
    """Database optimization for PostgreSQL"""
    try:
        with get_db_session() as db:
            db.execute(text("ANALYZE"))
            logger.info("Database analysis completed")

            result = db.execute(text("""
                SELECT
                    pg_size_pretty(pg_database_size(current_database())) as db_size,
                    pg_size_pretty(pg_total_relation_size('users')) as users_size,
                    pg_size_pretty(pg_total_relation_size('whatsapp_messages')) as messages_size
            """)).fetchone()

            logger.info(f"Database size: {result[0]}")
            logger.info(f"Users table size: {result[1]}")
            logger.info(f"Messages table size: {result[2]}")

    except Exception as e:
        logger.error(f"Database optimization failed: {e}")


def health_check_database():
    """Check database health"""
    try:
        eng = get_engine()
        with get_db_session() as db:
            result = db.execute(text("SELECT 1")).scalar()

            pool_info = {
                "pool_size": eng.pool.size(),
                "checked_in": eng.pool.checkedin(),
                "checked_out": eng.pool.checkedout(),
                "overflow": eng.pool.overflow(),
            }

            return {
                "status": "healthy" if result == 1 else "unhealthy",
                "pool_info": pool_info,
                "stats": get_db_stats(),
            }

    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "pool_info": {},
            "stats": get_db_stats(),
        }
