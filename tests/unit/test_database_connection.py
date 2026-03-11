import contextlib
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.database.connection import (
    get_db,
    get_db_session,
    get_db_stats,
    get_engine,
    health_check_database,
    optimize_database,
    reset_db_stats,
)


class TestDatabaseConnection:
    def setup_method(self):
        """Reset stats before each test"""
        reset_db_stats()

    def test_get_db_stats_initial(self):
        """Test initial database statistics"""
        stats = get_db_stats()

        assert stats["total_queries"] == 0
        assert stats["slow_queries"] == 0
        assert stats["connection_errors"] == 0
        assert stats["query_times"] == []
        assert stats["avg_query_time"] == 0
        assert stats["max_query_time"] == 0
        assert stats["min_query_time"] == 0

    def test_get_db_stats_with_queries(self):
        """Test database statistics with query data"""
        from app.database.connection import _db_stats

        _db_stats["total_queries"] = 5
        _db_stats["slow_queries"] = 1
        _db_stats["connection_errors"] = 2
        _db_stats["query_times"] = [0.1, 0.2, 1.5, 0.3, 0.4]

        stats = get_db_stats()

        assert stats["total_queries"] == 5
        assert stats["slow_queries"] == 1
        assert stats["connection_errors"] == 2
        assert stats["avg_query_time"] == 0.5
        assert stats["max_query_time"] == 1.5
        assert stats["min_query_time"] == 0.1

    def test_get_db_stats_query_times_limit(self):
        """Test that query times array is limited"""
        from app.database.connection import _db_stats

        _db_stats["query_times"] = [0.1] * 1500

        stats = get_db_stats()

        assert len(stats["query_times"]) == 1000
        assert stats["query_times"] == [0.1] * 1000

    def test_reset_db_stats(self):
        """Test resetting database statistics"""
        from app.database.connection import _db_stats

        _db_stats["total_queries"] = 10
        _db_stats["slow_queries"] = 2
        _db_stats["connection_errors"] = 1
        _db_stats["query_times"] = [0.1, 0.2, 0.3]

        reset_db_stats()

        stats = get_db_stats()
        assert stats["total_queries"] == 0
        assert stats["slow_queries"] == 0
        assert stats["connection_errors"] == 0
        assert stats["query_times"] == []

    @patch("app.database.connection._get_session_local")
    def test_get_db_success(self, mock_get_session_local):
        """Test successful database session creation"""
        mock_session = Mock()
        mock_get_session_local.return_value.return_value = mock_session

        db_gen = get_db()
        db = next(db_gen)

        assert db == mock_session
        mock_get_session_local.assert_called_once()

        with contextlib.suppress(StopIteration):
            next(db_gen)

        mock_session.close.assert_called_once()

    @patch("app.database.connection._get_session_local")
    def test_get_db_exception(self, mock_get_session_local):
        """Test database session with exception"""
        mock_session = Mock()
        mock_get_session_local.return_value.return_value = mock_session

        mock_session.some_operation.side_effect = SQLAlchemyError("Database error")

        db_gen = get_db()
        db = next(db_gen)

        with pytest.raises(SQLAlchemyError):
            db.some_operation()
            with contextlib.suppress(StopIteration):
                next(db_gen)

        mock_get_session_local.assert_called_once()

    @patch("app.database.connection._get_session_local")
    def test_get_db_session_success(self, mock_get_session_local):
        """Test successful database session context manager"""
        mock_session = Mock()
        mock_get_session_local.return_value.return_value = mock_session

        with get_db_session() as db:
            assert db == mock_session

        mock_session.commit.assert_called_once()
        mock_session.close.assert_called_once()

    @patch("app.database.connection._get_session_local")
    def test_get_db_session_exception(self, mock_get_session_local):
        """Test database session context manager with exception"""
        mock_session = Mock()
        mock_get_session_local.return_value.return_value = mock_session

        mock_session.some_operation.side_effect = SQLAlchemyError("Database error")

        with pytest.raises(SQLAlchemyError), get_db_session() as db:
            db.some_operation()

        mock_session.rollback.assert_called_once()
        mock_session.close.assert_called_once()
        mock_session.commit.assert_not_called()

    @patch("app.database.connection.settings")
    @patch("app.database.connection.get_db_session")
    def test_optimize_database_postgresql(self, mock_get_session, mock_settings):
        """Test database optimization for PostgreSQL"""
        mock_settings.DATABASE_URL = "postgresql://localhost/test"

        mock_session = Mock()
        mock_result = Mock()
        mock_result.fetchone.return_value = ("1.5 MB", "500 KB", "1.0 MB")
        mock_session.execute.return_value = mock_result

        mock_context = Mock()
        mock_context.__enter__ = Mock(return_value=mock_session)
        mock_context.__exit__ = Mock(return_value=None)
        mock_get_session.return_value = mock_context

        optimize_database()

        assert mock_session.execute.call_count == 2

    @patch("app.database.connection.settings")
    @patch("app.database.connection.get_db_session")
    def test_optimize_database_postgresql_with_size_info(
        self, mock_get_session, mock_settings
    ):
        """Test database optimization for PostgreSQL with size information"""
        mock_settings.DATABASE_URL = "postgresql://localhost/test"

        mock_session = Mock()
        mock_result = Mock()
        mock_result.fetchone.return_value = ("1.5 MB", "500 KB", "1.0 MB")
        mock_session.execute.return_value = mock_result

        mock_context = Mock()
        mock_context.__enter__ = Mock(return_value=mock_session)
        mock_context.__exit__ = Mock(return_value=None)
        mock_get_session.return_value = mock_context

        optimize_database()

        assert mock_session.execute.call_count == 2

    @patch("app.database.connection.settings")
    @patch("app.database.connection.get_db_session")
    def test_optimize_database_exception(self, mock_get_session, mock_settings):
        """Test database optimization with exception"""
        mock_settings.DATABASE_URL = "postgresql://localhost/test"

        mock_session = Mock()
        mock_session.execute.side_effect = SQLAlchemyError("Optimization failed")

        mock_context = Mock()
        mock_context.__enter__ = Mock(return_value=mock_session)
        mock_context.__exit__ = Mock(return_value=None)
        mock_get_session.return_value = mock_context

        optimize_database()

    @patch("app.database.connection.get_engine")
    @patch("app.database.connection.get_db_session")
    def test_health_check_database_success(self, mock_get_session, mock_get_engine):
        """Test successful database health check"""
        mock_session = Mock()
        mock_session.execute.return_value.scalar.return_value = 1

        mock_context = Mock()
        mock_context.__enter__ = Mock(return_value=mock_session)
        mock_context.__exit__ = Mock(return_value=None)
        mock_get_session.return_value = mock_context

        mock_pool = Mock()
        mock_pool.size.return_value = 20
        mock_pool.checkedin.return_value = 15
        mock_pool.checkedout.return_value = 5
        mock_pool.overflow.return_value = 0
        mock_engine = Mock()
        mock_engine.pool = mock_pool
        mock_get_engine.return_value = mock_engine

        result = health_check_database()

        assert result["status"] == "healthy"
        assert result["pool_info"]["pool_size"] == 20
        assert result["pool_info"]["checked_in"] == 15
        assert result["pool_info"]["checked_out"] == 5
        assert result["pool_info"]["overflow"] == 0
        assert "stats" in result

    @patch("app.database.connection.get_db_session")
    def test_health_check_database_failure(self, mock_get_session):
        """Test database health check with failure"""
        mock_session = Mock()
        mock_session.execute.side_effect = OperationalError(
            "Connection failed", None, None
        )

        mock_context = Mock()
        mock_context.__enter__ = Mock(return_value=mock_session)
        mock_context.__exit__ = Mock(return_value=None)
        mock_get_session.return_value = mock_context

        result = health_check_database()

        assert result["status"] == "unhealthy"
        assert "error" in result
        assert "pool_info" in result
        assert "stats" in result

    @patch("app.database.connection.get_engine")
    @patch("app.database.connection.get_db_session")
    def test_health_check_database_wrong_result(
        self, mock_get_session, mock_get_engine
    ):
        """Test database health check with wrong result"""
        mock_session = Mock()
        mock_session.execute.return_value.scalar.return_value = 0

        mock_context = Mock()
        mock_context.__enter__ = Mock(return_value=mock_session)
        mock_context.__exit__ = Mock(return_value=None)
        mock_get_session.return_value = mock_context

        mock_engine = Mock()
        mock_engine.pool = Mock()
        mock_engine.pool.size.return_value = 5
        mock_engine.pool.checkedin.return_value = 5
        mock_engine.pool.checkedout.return_value = 0
        mock_engine.pool.overflow.return_value = 0
        mock_get_engine.return_value = mock_engine

        result = health_check_database()

        assert result["status"] == "unhealthy"

    def test_engine_configuration(self):
        """Test engine configuration"""
        eng = get_engine()
        assert eng.echo is False
        assert hasattr(eng, "pool")

    def test_session_local_configuration(self):
        """Test session factory configuration"""
        from app.database.connection import _get_session_local

        session_local = _get_session_local()
        assert session_local.kw["autocommit"] is False
        assert session_local.kw["autoflush"] is False
        assert session_local.kw["bind"] == get_engine()

    def test_slow_query_detection_basic(self):
        """Test slow query detection basic functionality"""
        from app.database.connection import _db_stats

        _db_stats["total_queries"] = 1
        _db_stats["slow_queries"] = 1
        _db_stats["query_times"] = [1.5]

        stats = get_db_stats()
        assert stats["total_queries"] == 1
        assert stats["slow_queries"] == 1
        assert len(stats["query_times"]) == 1

    def test_connection_error_tracking(self):
        """Test connection error tracking"""
        from app.database.connection import _db_stats

        _db_stats["connection_errors"] = 3

        stats = get_db_stats()
        assert stats["connection_errors"] == 3

    def test_stats_persistence(self):
        """Test that stats persist between calls"""
        from app.database.connection import _db_stats

        _db_stats["total_queries"] = 5
        _db_stats["slow_queries"] = 1

        stats1 = get_db_stats()
        stats2 = get_db_stats()

        assert stats1["total_queries"] == stats2["total_queries"]
        assert stats1["slow_queries"] == stats2["slow_queries"]
