from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException

from app.core.base_service import BaseService, ServiceMixin


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


class TestServiceMixin:
    def setup_method(self):
        """Set up test fixtures"""
        self.mixin = ServiceMixin()

    def test_initialization(self):
        """Test mixin initialization"""
        assert self.mixin.logger is not None
        assert hasattr(self.mixin, "logger")

    def test_safe_execute_success(self):
        """Test safe execution of function with success"""

        def test_func(a, b):
            return a + b

        result = self.mixin.safe_execute(test_func, 2, 3)

        assert result == 5

    def test_safe_execute_exception(self):
        """Test safe execution of function with exception"""

        def test_func(a, b):
            raise ValueError("Test error")

        with patch.object(self.mixin.logger, "error") as mock_logger:
            with pytest.raises(ValueError, match="Test error"):
                self.mixin.safe_execute(test_func, 2, 3)

            mock_logger.assert_called_once()

    @pytest.mark.asyncio
    async def test_safe_async_execute_success(self):
        """Test safe execution of async function with success"""

        async def test_async_func(a, b):
            return a * b

        result = await self.mixin.safe_async_execute(test_async_func, 4, 5)

        assert result == 20

    @pytest.mark.asyncio
    async def test_safe_async_execute_exception(self):
        """Test safe execution of async function with exception"""

        async def test_async_func(a, b):
            raise RuntimeError("Async test error")

        with patch.object(self.mixin.logger, "error") as mock_logger:
            with pytest.raises(RuntimeError, match="Async test error"):
                await self.mixin.safe_async_execute(test_async_func, 4, 5)

            mock_logger.assert_called_once()

    def test_safe_execute_with_kwargs(self):
        """Test safe execution with keyword arguments"""

        def test_func(a, b, multiplier=1):
            return (a + b) * multiplier

        result = self.mixin.safe_execute(test_func, 2, 3, multiplier=2)

        assert result == 10

    @pytest.mark.asyncio
    async def test_safe_async_execute_with_kwargs(self):
        """Test safe async execution with keyword arguments"""

        async def test_async_func(a, b, multiplier=1):
            return (a + b) * multiplier

        result = await self.mixin.safe_async_execute(
            test_async_func, 2, 3, multiplier=3
        )

        assert result == 15
