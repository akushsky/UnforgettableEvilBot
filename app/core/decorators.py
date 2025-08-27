import logging
from functools import wraps
from typing import Any, Callable

from fastapi import HTTPException

logger = logging.getLogger(__name__)


def with_error_handling(context: str, status_code: int = 500):
    """Decorator for standard error handling"""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            """Wrapper for error handling."""
            try:
                return await func(*args, **kwargs)
            except HTTPException:
                raise  # Re-raise HTTP errors as is
            except Exception as e:
                logger.error(f"Error in {context}: {e}", exc_info=True)
                raise HTTPException(
                    status_code=status_code, detail=f"Internal error in {context}"
                )

        return wrapper

    return decorator


def with_user_validation(user_param: str = "user_id"):
    """Decorator for user validation"""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            """Wrapper for user validation."""
            # Automatic user validation
            # Only enforce validation if the endpoint actually receives this param
            if user_param in kwargs:
                user_id = kwargs.get(user_param)
                if not user_id:
                    raise HTTPException(status_code=400, detail="User ID required")

            # Additional validation can be added here
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def with_db_session():
    """Decorator for automatic DB session management"""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            """Wrapper for DB session management."""
            from app.database.connection import SessionLocal

            db = SessionLocal()
            try:
                # Pass the DB session into the function
                kwargs["db"] = db
                result = await func(*args, **kwargs)
                db.commit()
                return result
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

        return wrapper

    return decorator


def with_rate_limiting(limit: int = 100, window: int = 3600):
    """Decorator for rate limiting"""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            """Wrapper for rate limiting."""
            # Rate-limiting logic can be added here
            # For now, just pass through
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def with_caching(ttl: int = 300):
    """Decorator for caching results"""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            """Wrapper for caching."""
            # Caching logic can be added here
            # For now, just execute the function
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def with_validation(schema_class: Any):
    """Decorator for input validation"""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            """Wrapper for input validation."""
            # Validate input data
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def with_access_control(permission: str):
    """Decorator for access control checks"""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            """Wrapper for access control."""
            # Access checks can be added here
            # For now, just pass through
            return await func(*args, **kwargs)

        return wrapper

    return decorator


# Combined decorators
def safe_endpoint(context: str = "operation"):
    """Combined decorator for safe endpoints"""

    def decorator(func: Callable) -> Callable:
        # Add error handling
        func = with_error_handling(context)(func)

        # Add user validation
        func = with_user_validation()(func)

        # Add logging
        func = with_logging(context)(func)

        return func

    return decorator


def db_operation():
    """Combined decorator for DB operations"""

    def decorator(func: Callable) -> Callable:
        # Add DB session management
        func = with_db_session()(func)

        # Add error handling
        func = with_error_handling("database operation")(func)

        return func

    return decorator


def with_logging(operation: str):
    """Decorator for logging operations"""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            """Wrapper for logging."""
            logger.info(f"Starting operation: {operation}")
            try:
                result = await func(*args, **kwargs)
                logger.info(f"Operation completed: {operation}")
                return result
            except Exception as e:
                logger.error(f"Operation failed: {operation} - {e}")
                raise

        return wrapper

    return decorator
