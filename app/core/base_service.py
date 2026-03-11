from abc import ABC, abstractmethod
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from config.logging_config import get_logger

logger = get_logger(__name__)


class BaseService(ABC):
    """Base class for all services with common methods"""

    def __init__(self):
        """Init  ."""
        self.logger = get_logger(self.__class__.__name__)

    async def execute_with_db(self, operation, db: Session) -> Any:
        """Generic execution of operations with the DB"""
        try:
            result = await operation(db)
            return result
        except Exception as e:
            self.logger.error(f"Database operation failed: {e}")
            db.rollback()
            raise

    def handle_error(
        self, error: Exception, context: str, status_code: int = 500
    ) -> None:
        """Standard error handling"""
        self.logger.error(f"Error in {context}: {error}", exc_info=True)
        raise HTTPException(status_code=status_code, detail=str(error))

    def log_operation(self, operation: str, details: dict | None = None) -> None:
        """Operation logging"""
        message = f"Operation: {operation}"
        if details:
            message += f" | Details: {details}"
        self.logger.info(message)

    @abstractmethod
    async def validate_input(self, data: Any) -> bool:
        """Input validation — must be implemented in subclasses"""
