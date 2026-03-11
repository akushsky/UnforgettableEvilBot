from collections.abc import Callable
from functools import wraps

from fastapi import HTTPException

from config.logging_config import get_logger

logger = get_logger(__name__)


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
                ) from e

        return wrapper

    return decorator
