from datetime import datetime, timedelta
from unittest.mock import Mock

from sqlalchemy.exc import SQLAlchemyError

from app.core.optimized_repositories import (
    OptimizedDigestLogRepository,
    OptimizedUserRepository,
    OptimizedWhatsAppMessageRepository,
    optimized_digest_log_repository,
    optimized_user_repository,
    optimized_whatsapp_message_repository,
)
from app.models.database import DigestLog, User, WhatsAppMessage


class TestOptimizedUserRepository:
    def setup_method(self):
        """Set up test fixtures"""
        self.repository = OptimizedUserRepository()
        self.mock_db = Mock()

    def test_initialization(self):
        """Test repository initialization"""
        assert self.repository.model == User

    def test_get_by_username(self):
        """Test getting user by username"""
        mock_user = Mock(spec=User)
        mock_user.username = "testuser"
        self.mock_db.query.return_value.filter.return_value.first.return_value = (
            mock_user
        )

        result = self.repository.get_by_username(self.mock_db, "testuser")

        assert result == mock_user
        self.mock_db.query.assert_called_once()

    def test_get_by_email(self):
        """Test getting user by email"""
        mock_user = Mock(spec=User)
        mock_user.email = "test@example.com"
        self.mock_db.query.return_value.filter.return_value.first.return_value = (
            mock_user
        )

        result = self.repository.get_by_email(self.mock_db, "test@example.com")

        assert result == mock_user
        self.mock_db.query.assert_called_once()

    def test_get_active_users(self):
        """Test getting active users"""
        mock_users = [Mock(spec=User), Mock(spec=User)]
        self.mock_db.query.return_value.filter.return_value.all.return_value = (
            mock_users
        )

        result = self.repository.get_active_users(self.mock_db)

        assert result == mock_users
        self.mock_db.query.assert_called_once()

    def test_get_users_with_chats(self):
        """Test getting users with chats"""
        mock_users = [Mock(spec=User), Mock(spec=User)]
        self.mock_db.query.return_value.options.return_value.filter.return_value.all.return_value = (
            mock_users
        )

        result = self.repository.get_users_with_chats(self.mock_db)

        assert result == mock_users
        self.mock_db.query.assert_called_once()

    def test_get_user_with_full_data(self):
        """Test getting user with full data"""
        mock_user = Mock(spec=User)
        mock_user.id = 1
        self.mock_db.query.return_value.options.return_value.filter.return_value.first.return_value = (
            mock_user
        )

        result = self.repository.get_user_with_full_data(self.mock_db, 1)

        assert result == mock_user
        self.mock_db.query.assert_called_once()

    def test_update_whatsapp_status(self):
        """Test updating WhatsApp status"""
        mock_user = Mock(spec=User)
        mock_user.id = 1
        mock_user.whatsapp_connected = False

        self.repository.get_by_id_or_404 = Mock(return_value=mock_user)

        result = self.repository.update_whatsapp_status(self.mock_db, 1, True)

        assert result == mock_user
        assert mock_user.whatsapp_connected
        self.mock_db.commit.assert_called_once()
        self.mock_db.refresh.assert_called_once_with(mock_user)

    def test_get_users_batch_empty_list(self):
        """Test getting users batch with empty list"""
        result = self.repository.get_users_batch(self.mock_db, [])

        assert result == []
        self.mock_db.query.assert_not_called()

    def test_get_users_batch_with_ids(self):
        """Test getting users batch with IDs"""
        mock_users = [Mock(spec=User), Mock(spec=User)]
        self.mock_db.query.return_value.filter.return_value.all.return_value = (
            mock_users
        )

        result = self.repository.get_users_batch(self.mock_db, [1, 2])

        assert result == mock_users
        self.mock_db.query.assert_called_once()

    def test_update_users_batch_empty_list(self):
        """Test updating users batch with empty list"""
        result = self.repository.update_users_batch(self.mock_db, [])

        assert result == 0
        self.mock_db.commit.assert_not_called()

    def test_update_users_batch_success(self):
        """Test updating users batch successfully"""
        mock_user = Mock(spec=User)
        mock_user.id = 1
        self.repository.get_by_id = Mock(return_value=mock_user)

        updates = [(1, {"username": "newuser"})]
        result = self.repository.update_users_batch(self.mock_db, updates)

        assert result == 1
        assert mock_user.username == "newuser"
        self.mock_db.commit.assert_called_once()

    def test_update_users_batch_with_error(self):
        """Test updating users batch with error"""
        self.repository.get_by_id = Mock(side_effect=Exception("Database error"))

        updates = [(1, {"username": "newuser"})]
        result = self.repository.update_users_batch(self.mock_db, updates)

        assert result == 0
        self.mock_db.commit.assert_called_once()


class TestOptimizedWhatsAppMessageRepository:
    def setup_method(self):
        """Set up test fixtures"""
        self.repository = OptimizedWhatsAppMessageRepository()
        self.mock_db = Mock()

    def test_initialization(self):
        """Test repository initialization"""
        assert self.repository.model == WhatsAppMessage

    def test_get_by_message_id(self):
        """Test getting message by ID"""
        mock_message = Mock(spec=WhatsAppMessage)
        mock_message.message_id = "msg123"
        self.mock_db.query.return_value.filter.return_value.first.return_value = (
            mock_message
        )

        result = self.repository.get_by_message_id(self.mock_db, "msg123")

        assert result == mock_message
        self.mock_db.query.assert_called_once()

    def test_get_unprocessed_messages(self):
        """Test getting unprocessed messages"""
        mock_messages = [Mock(spec=WhatsAppMessage), Mock(spec=WhatsAppMessage)]
        self.mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = (
            mock_messages
        )

        result = self.repository.get_unprocessed_messages(self.mock_db, 1, 100)

        assert result == mock_messages
        self.mock_db.query.assert_called_once()

    def test_get_important_messages(self):
        """Test getting important messages"""
        mock_messages = [Mock(spec=WhatsAppMessage), Mock(spec=WhatsAppMessage)]
        self.mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = (
            mock_messages
        )

        result = self.repository.get_important_messages(self.mock_db, 1, 3, 50)

        assert result == mock_messages
        self.mock_db.query.assert_called_once()

    def test_get_messages_for_digest(self):
        """Test getting messages for digest"""
        mock_messages = [Mock(spec=WhatsAppMessage), Mock(spec=WhatsAppMessage)]
        self.mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
            mock_messages
        )

        result = self.repository.get_messages_for_digest(self.mock_db, 1, 24)

        assert result == mock_messages
        self.mock_db.query.assert_called_once()

    def test_mark_as_processed_batch_empty_list(self):
        """Test marking messages as processed with empty list"""
        result = self.repository.mark_as_processed_batch(self.mock_db, [])

        assert result == 0
        self.mock_db.commit.assert_not_called()

    def test_mark_as_processed_batch_success(self):
        """Test marking messages as processed successfully"""
        self.mock_db.query.return_value.filter.return_value.update.return_value = 5

        result = self.repository.mark_as_processed_batch(self.mock_db, [1, 2, 3])

        assert result == 5
        self.mock_db.commit.assert_called_once()

    def test_mark_as_processed_batch_error(self):
        """Test marking messages as processed with error"""
        self.mock_db.query.return_value.filter.return_value.update.side_effect = (
            SQLAlchemyError("Database error")
        )

        result = self.repository.mark_as_processed_batch(self.mock_db, [1, 2, 3])

        assert result == 0
        self.mock_db.rollback.assert_called_once()

    def test_get_message_stats(self):
        """Test getting message statistics"""
        mock_stats = Mock()
        mock_stats.total_messages = 100
        mock_stats.avg_importance = 3.5
        mock_stats.max_importance = 5
        mock_stats.unprocessed_messages = 10

        self.mock_db.query.return_value.filter.return_value.first.return_value = (
            mock_stats
        )

        result = self.repository.get_message_stats(self.mock_db, 1, 7)

        assert result["total_messages"] == 100
        assert result["avg_importance"] == 3.5
        assert result["max_importance"] == 5
        assert result["unprocessed_messages"] == 10
        assert result["period_days"] == 7

    def test_cleanup_old_messages_success(self):
        """Test cleaning up old messages successfully"""
        self.mock_db.query.return_value.filter.return_value.delete.return_value = 50

        result = self.repository.cleanup_old_messages(self.mock_db, 30)

        assert result == 50
        self.mock_db.commit.assert_called_once()

    def test_cleanup_old_messages_error(self):
        """Test cleaning up old messages with error"""
        self.mock_db.query.return_value.filter.return_value.delete.side_effect = (
            SQLAlchemyError("Database error")
        )

        result = self.repository.cleanup_old_messages(self.mock_db, 30)

        assert result == 0
        self.mock_db.rollback.assert_called_once()


class TestOptimizedDigestLogRepository:
    def setup_method(self):
        """Set up test fixtures"""
        self.repository = OptimizedDigestLogRepository()
        self.mock_db = Mock()

    def test_initialization(self):
        """Test repository initialization"""
        assert self.repository.model == DigestLog

    def test_get_last_digest_for_user(self):
        """Test getting last digest for user"""
        mock_digest = Mock(spec=DigestLog)
        mock_digest.user_id = 1
        self.mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (
            mock_digest
        )

        result = self.repository.get_last_digest_for_user(self.mock_db, 1)

        assert result == mock_digest
        self.mock_db.query.assert_called_once()

    def test_get_digests_for_period(self):
        """Test getting digests for period"""
        mock_digests = [Mock(spec=DigestLog), Mock(spec=DigestLog)]
        self.mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
            mock_digests
        )

        result = self.repository.get_digests_for_period(self.mock_db, 1, 7)

        assert result == mock_digests
        self.mock_db.query.assert_called_once()

    def test_should_create_digest_no_previous_digest(self):
        """Test should create digest when no previous digest exists"""
        self.repository.get_last_digest_for_user = Mock(return_value=None)

        result = self.repository.should_create_digest(self.mock_db, 1, 24)

        assert result

    def test_should_create_digest_interval_not_reached(self):
        """Test should create digest when interval not reached"""
        mock_digest = Mock(spec=DigestLog)
        mock_digest.created_at = datetime.utcnow() - timedelta(hours=12)  # 12 hours ago

        self.repository.get_last_digest_for_user = Mock(return_value=mock_digest)

        result = self.repository.should_create_digest(self.mock_db, 1, 24)

        assert result is False

    def test_should_create_digest_interval_reached(self):
        """Test should create digest when interval reached"""
        mock_digest = Mock(spec=DigestLog)
        mock_digest.created_at = datetime.utcnow() - timedelta(hours=25)  # 25 hours ago

        self.repository.get_last_digest_for_user = Mock(return_value=mock_digest)

        result = self.repository.should_create_digest(self.mock_db, 1, 24)

        assert result

    def test_get_digest_stats(self):
        """Test getting digest statistics"""
        mock_stats = Mock()
        mock_stats.total_digests = 10
        mock_stats.avg_interval_hours = 7200  # 2 hours in seconds

        self.mock_db.query.return_value.filter.return_value.first.return_value = (
            mock_stats
        )

        result = self.repository.get_digest_stats(self.mock_db, 1, 30)

        assert result["total_digests"] == 10
        assert result["avg_interval_hours"] == 2.0  # 7200 / 3600
        assert result["period_days"] == 30


class TestGlobalInstances:
    def test_optimized_user_repository_instance(self):
        """Test that global optimized user repository instance exists"""
        assert isinstance(optimized_user_repository, OptimizedUserRepository)

    def test_optimized_whatsapp_message_repository_instance(self):
        """Test that global optimized WhatsApp message repository instance exists"""
        assert isinstance(
            optimized_whatsapp_message_repository, OptimizedWhatsAppMessageRepository
        )

    def test_optimized_digest_log_repository_instance(self):
        """Test that global optimized digest log repository instance exists"""
        assert isinstance(optimized_digest_log_repository, OptimizedDigestLogRepository)
