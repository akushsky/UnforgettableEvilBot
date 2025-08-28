import time
from contextlib import contextmanager
from typing import List, TypedDict

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import QueuePool

from config.logging_config import get_logger
from config.settings import settings

logger = get_logger(__name__)

# Create engine with PostgreSQL settings
_db_url = make_url(settings.DATABASE_URL)

_connect_args = {"connect_timeout": 10, "application_name": "WhatsAppDigestBot"}

engine = create_engine(
    settings.DATABASE_URL,
    poolclass=QueuePool,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False,
    connect_args=_connect_args,
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


class DatabaseStats(TypedDict):
    total_queries: int
    slow_queries: int
    connection_errors: int
    query_times: List[float]
    avg_query_time: float
    max_query_time: float
    min_query_time: float


# Global variable for tracking statistics
_db_stats: DatabaseStats = {
    "total_queries": 0,
    "slow_queries": 0,
    "connection_errors": 0,
    "query_times": [],
    "avg_query_time": 0.0,
    "max_query_time": 0.0,
    "min_query_time": 0.0,
}


@event.listens_for(engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    """Log query execution time"""
    context._query_start_time = time.time()


@event.listens_for(engine, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    """Analyze query execution time"""
    total = time.time() - context._query_start_time
    _db_stats["total_queries"] = _db_stats["total_queries"] + 1
    query_times = _db_stats["query_times"]
    if isinstance(query_times, list):
        query_times.append(total)

    # Track slow queries (> 1 second)
    if total > 1.0:
        _db_stats["slow_queries"] = _db_stats["slow_queries"] + 1
        logger.warning(f"Slow query detected: {total:.3f}s - {statement[:100]}...")


def get_db():
    """Get database session with automatic closing"""
    db = SessionLocal()
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
    db = SessionLocal()
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

    # Calculate average query time
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

    # Limit the size of query times array
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
            # Analyze tables for PostgreSQL
            db.execute(text("ANALYZE"))
            logger.info("Database analysis completed")

            # Get information about database size
            result = db.execute(
                text(
                    """
                SELECT
                    pg_size_pretty(pg_database_size(current_database())) as db_size,
                    pg_size_pretty(pg_total_relation_size('users')) as users_size,
                    pg_size_pretty(pg_total_relation_size('whatsapp_messages')) as messages_size
            """
                )
            ).fetchone()

            logger.info(f"Database size: {result[0]}")
            logger.info(f"Users table size: {result[1]}")
            logger.info(f"Messages table size: {result[2]}")

    except Exception as e:
        logger.error(f"Database optimization failed: {e}")


def health_check_database():
    """Check database health"""
    try:
        with get_db_session() as db:
            # Simple request to check connection
            result = db.execute(text("SELECT 1")).scalar()

            # Check connection pool
            pool_info = {
                "pool_size": engine.pool.size(),
                "checked_in": engine.pool.checkedin(),
                "checked_out": engine.pool.checkedout(),
                "overflow": engine.pool.overflow(),
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
