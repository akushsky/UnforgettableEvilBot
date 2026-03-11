from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException

from app.core.base_service import BaseService


class TestBaseService:
    def setup_method(self):
        """Set up test fixtures"""

        # Create a concrete implementation of BaseService for testing
        class TestService(BaseService):
            async def validate_input(self, data):
                return isinstance(data, str) and len(data) > 0

        self.service = TestService()

    def test_initialization(self):
        """Test service initialization"""
        assert self.service.logger is not None
        assert hasattr(self.service, "logger")

    @pytest.mark.asyncio
    async def test_execute_with_db_success(self):
        """Test successful database operation execution"""
        mock_db = Mock()
        mock_operation = AsyncMock(return_value="success_result")

        result = await self.service.execute_with_db(mock_operation, mock_db)

        assert result == "success_result"
        mock_operation.assert_called_once_with(mock_db)

    @pytest.mark.asyncio
    async def test_execute_with_db_exception(self):
        """Test database operation execution with exception"""
        mock_db = Mock()
        mock_operation = AsyncMock(side_effect=Exception("Database error"))

        with pytest.raises(Exception, match="Database error"):
            await self.service.execute_with_db(mock_operation, mock_db)

        mock_db.rollback.assert_called_once()

    def test_handle_error(self):
        """Test error handling"""
        error = Exception("Test error")

        with pytest.raises(HTTPException) as exc_info:
            self.service.handle_error(error, "test_context", 400)

        assert exc_info.value.status_code == 400
        assert "Test error" in str(exc_info.value.detail)

    def test_handle_error_default_status_code(self):
        """Test error handling with default status code"""
        error = Exception("Test error")

        with pytest.raises(HTTPException) as exc_info:
            self.service.handle_error(error, "test_context")

        assert exc_info.value.status_code == 500
        assert "Test error" in str(exc_info.value.detail)

    def test_log_operation_without_details(self):
        """Test operation logging without details"""
        with patch.object(self.service.logger, "info") as mock_logger:
            self.service.log_operation("test_operation")

            mock_logger.assert_called_once_with("Operation: test_operation")

    def test_log_operation_with_details(self):
        """Test operation logging with details"""
        details = {"key": "value", "count": 5}

        with patch.object(self.service.logger, "info") as mock_logger:
            self.service.log_operation("test_operation", details)

            mock_logger.assert_called_once_with(
                "Operation: test_operation | Details: {'key': 'value', 'count': 5}"
            )

    @pytest.mark.asyncio
    async def test_validate_input_implementation(self):
        """Test that validate_input is implemented in concrete class"""
        # Test with valid input
        result = await self.service.validate_input("valid string")
        assert result

        # Test with invalid input
        result = await self.service.validate_input("")
        assert result is False

        result = await self.service.validate_input(123)
        assert result is False
