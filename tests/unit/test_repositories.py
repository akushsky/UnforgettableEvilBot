from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from sqlalchemy.orm import Session

from app.core.repositories import (
    DigestLogRepository,
    MonitoredChatRepository,
    OpenAIMetricsRepository,
    ResourceSavingsRepository,
    SystemLogRepository,
    UserRepository,
    UserSettingsRepository,
    WhatsAppMessageRepository,
)
from app.models.database import (
    DigestLog,
    MonitoredChat,
    OpenAIMetrics,
    ResourceSavings,
    User,
    UserSettings,
    WhatsAppMessage,
)


class TestUserRepository:
    """Test UserRepository functionality"""

    def setup_method(self):
        """Setup test method"""
        self.repository = UserRepository()
        self.mock_db = Mock(spec=Session)

    def test_get_by_id(self):
        """Test get_by_id method"""
        # Arrange
        user_id = 1
        mock_user = Mock(spec=User)
        mock_user.id = user_id
        self.mock_db.query.return_value.filter.return_value.first.return_value = (
            mock_user
        )

        # Act
        result = self.repository.get_by_id(self.mock_db, user_id)

        # Assert
        assert result == mock_user
        self.mock_db.query.assert_called_once_with(User)

    def test_get_by_id_not_found(self):
        """Test get_by_id method when user not found"""
        # Arrange
        user_id = 999
        self.mock_db.query.return_value.filter.return_value.first.return_value = None

        # Act
        result = self.repository.get_by_id(self.mock_db, user_id)

        # Assert
        assert result is None

    def test_get_by_username(self):
        """Test get_by_username method"""
        # Arrange
        username = "testuser"
        mock_user = Mock(spec=User)
        mock_user.username = username
        self.mock_db.query.return_value.filter.return_value.first.return_value = (
            mock_user
        )

        # Act
        result = self.repository.get_by_username(self.mock_db, username)

        # Assert
        assert result == mock_user

    def test_get_by_email(self):
        """Test get_by_email method"""
        # Arrange
        email = "test@example.com"
        mock_user = Mock(spec=User)
        mock_user.email = email
        self.mock_db.query.return_value.filter.return_value.first.return_value = (
            mock_user
        )

        # Act
        result = self.repository.get_by_email(self.mock_db, email)

        # Assert
        assert result == mock_user

    def test_get_all(self):
        """Test get_all method"""
        # Arrange
        mock_users = [Mock(spec=User), Mock(spec=User)]
        self.mock_db.query.return_value.offset.return_value.limit.return_value.all.return_value = (
            mock_users
        )

        # Act
        result = self.repository.get_all(self.mock_db)

        # Assert
        assert result == mock_users

    def test_get_active_users_with_telegram(self):
        """Test get_active_users_with_telegram method"""
        # Arrange
        mock_users = [Mock(spec=User), Mock(spec=User)]
        self.mock_db.query.return_value.filter.return_value.all.return_value = (
            mock_users
        )

        # Act
        result = self.repository.get_active_users_with_telegram(self.mock_db)

        # Assert
        assert result == mock_users

    def test_get_active_users_with_whatsapp(self):
        """Test get_active_users_with_whatsapp method"""
        # Arrange
        mock_users = [Mock(spec=User), Mock(spec=User)]
        self.mock_db.query.return_value.filter.return_value.all.return_value = (
            mock_users
        )

        # Act
        result = self.repository.get_active_users_with_whatsapp(self.mock_db)

        # Assert
        assert result == mock_users

    def test_get_suspended_users_with_whatsapp(self):
        """Test get_suspended_users_with_whatsapp method"""
        # Arrange
        mock_users = [Mock(spec=User), Mock(spec=User)]
        self.mock_db.query.return_value.filter.return_value.all.return_value = (
            mock_users
        )

        # Act
        result = self.repository.get_suspended_users_with_whatsapp(self.mock_db)

        # Assert
        assert result == mock_users


class TestMonitoredChatRepository:
    """Test MonitoredChatRepository functionality"""

    def setup_method(self):
        """Setup test method"""
        self.repository = MonitoredChatRepository()
        self.mock_db = Mock(spec=Session)

    def test_get_active_chats_for_user(self):
        """Test get_active_chats_for_user method"""
        # Arrange
        user_id = 1
        mock_chats = [Mock(spec=MonitoredChat), Mock(spec=MonitoredChat)]
        self.mock_db.query.return_value.filter.return_value.all.return_value = (
            mock_chats
        )

        # Act
        result = self.repository.get_active_chats_for_user(self.mock_db, user_id)

        # Assert
        assert result == mock_chats

    def test_get_by_user_and_chat_id(self):
        """Test get_by_user_and_chat_id method"""
        # Arrange
        user_id = 1
        chat_id = "chat123"
        mock_chat = Mock(spec=MonitoredChat)
        self.mock_db.query.return_value.filter.return_value.first.return_value = (
            mock_chat
        )

        # Act
        result = self.repository.get_by_user_and_chat_id(self.mock_db, user_id, chat_id)

        # Assert
        assert result == mock_chat


class TestWhatsAppMessageRepository:
    """Test WhatsAppMessageRepository functionality"""

    def setup_method(self):
        """Setup test method"""
        self.repository = WhatsAppMessageRepository()
        self.mock_db = Mock(spec=Session)

    def test_get_by_message_id(self):
        """Test get_by_message_id method"""
        # Arrange
        message_id = "msg123"
        mock_message = Mock(spec=WhatsAppMessage)
        self.mock_db.query.return_value.filter.return_value.first.return_value = (
            mock_message
        )

        # Act
        result = self.repository.get_by_message_id(self.mock_db, message_id)

        # Assert
        assert result == mock_message

    def test_get_messages_by_chat_ids(self):
        """Test get_messages_by_chat_ids method"""
        # Arrange
        chat_ids = [1, 2, 3]
        mock_messages = [Mock(spec=WhatsAppMessage), Mock(spec=WhatsAppMessage)]
        self.mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = (
            mock_messages
        )

        # Act
        result = self.repository.get_messages_by_chat_ids(self.mock_db, chat_ids)

        # Assert
        assert result == mock_messages

    def test_get_important_messages_for_digest(self):
        """Test get_important_messages_for_digest method"""
        # Arrange
        chat_id = 1
        hours_back = 24
        importance_threshold = 3
        mock_messages = [Mock(spec=WhatsAppMessage), Mock(spec=WhatsAppMessage)]
        self.mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
            mock_messages
        )

        # Act
        result = self.repository.get_important_messages_for_digest(
            self.mock_db, chat_id, hours_back, importance_threshold
        )

        # Assert
        assert result == mock_messages

    def test_get_messages_count(self):
        """Test get_messages_count method"""
        # Arrange
        self.mock_db.query.return_value.count.return_value = 42

        # Act
        result = self.repository.get_messages_count(self.mock_db)

        # Assert
        assert result == 42

    def test_get_old_messages_count(self):
        """Test get_old_messages_count method"""
        # Arrange
        cutoff_time = datetime.utcnow() - timedelta(days=30)
        self.mock_db.query.return_value.filter.return_value.count.return_value = 10

        # Act
        result = self.repository.get_old_messages_count(self.mock_db, cutoff_time)

        # Assert
        assert result == 10

    def test_delete_old_messages(self):
        """Test delete_old_messages method"""
        # Arrange
        chat_ids = [1, 2, 3]
        cutoff_time = datetime.utcnow() - timedelta(days=30)
        self.mock_db.query.return_value.filter.return_value.delete.return_value = 5

        # Act
        result = self.repository.delete_old_messages(
            self.mock_db, chat_ids, cutoff_time
        )

        # Assert
        assert result == 5


class TestDigestLogRepository:
    """Test DigestLogRepository functionality"""

    def setup_method(self):
        """Setup test method"""
        self.repository = DigestLogRepository()
        self.mock_db = Mock(spec=Session)

    def test_get_last_digest_for_user(self):
        """Test get_last_digest_for_user method"""
        # Arrange
        user_id = 1
        mock_digest = Mock(spec=DigestLog)
        self.mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (
            mock_digest
        )

        # Act
        result = self.repository.get_last_digest_for_user(self.mock_db, user_id)

        # Assert
        assert result == mock_digest

    def test_get_digests_for_period(self):
        """Test get_digests_for_period method"""
        # Arrange
        user_id = 1
        days_back = 30
        mock_digests = [Mock(spec=DigestLog), Mock(spec=DigestLog)]
        self.mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
            mock_digests
        )

        # Act
        result = self.repository.get_digests_for_period(
            self.mock_db, user_id, days_back
        )

        # Assert
        assert result == mock_digests

    def test_should_create_digest(self):
        """Test should_create_digest method"""
        # Arrange
        user_id = 1
        hours_back = 24
        mock_digest = Mock(spec=DigestLog)
        mock_digest.created_at = datetime.utcnow() - timedelta(
            hours=25
        )  # More than 24 hours ago

        with patch.object(self.repository, "get_last_digest_for_user") as mock_get_last:
            mock_get_last.return_value = mock_digest

            # Act
            result = self.repository.should_create_digest(
                self.mock_db, user_id, hours_back
            )

        # Assert
        assert (
            result is True
        )  # Should return True if last digest is older than interval

    def test_should_create_digest_no_last_digest(self):
        """Test should_create_digest method when no last digest exists"""
        # Arrange
        user_id = 1
        hours_back = 24

        with patch.object(self.repository, "get_last_digest_for_user") as mock_get_last:
            mock_get_last.return_value = None

            # Act
            result = self.repository.should_create_digest(
                self.mock_db, user_id, hours_back
            )

        # Assert
        assert result is True  # Should return True if no digest exists

    def test_get_digests_count(self):
        """Test get_digests_count method"""
        # Arrange
        self.mock_db.query.return_value.count.return_value = 15

        # Act
        result = self.repository.get_digests_count(self.mock_db)

        # Assert
        assert result == 15

    def test_get_old_digests_count(self):
        """Test get_old_digests_count method"""
        # Arrange
        cutoff_time = datetime.utcnow() - timedelta(days=30)
        self.mock_db.query.return_value.filter.return_value.count.return_value = 8

        # Act
        result = self.repository.get_old_digests_count(self.mock_db, cutoff_time)

        # Assert
        assert result == 8

    def test_delete_old_digests(self):
        """Test delete_old_digests method"""
        # Arrange
        cutoff_time = datetime.utcnow() - timedelta(days=30)
        self.mock_db.query.return_value.filter.return_value.delete.return_value = 3

        # Act
        result = self.repository.delete_old_digests(self.mock_db, cutoff_time)

        # Assert
        assert result == 3


class TestSystemLogRepository:
    """Test SystemLogRepository functionality"""

    def setup_method(self):
        """Setup test method"""
        self.repository = SystemLogRepository()
        self.mock_db = Mock(spec=Session)

    def test_delete_old_logs(self):
        """Test delete_old_logs method"""
        # Arrange
        cutoff_time = datetime.utcnow() - timedelta(days=30)
        self.mock_db.query.return_value.filter.return_value.delete.return_value = 25

        # Act
        result = self.repository.delete_old_logs(self.mock_db, cutoff_time)

        # Assert
        assert result == 25

    def test_get_logs_count(self):
        """Test get_logs_count method"""
        # Arrange
        self.mock_db.query.return_value.count.return_value = 100

        # Act
        result = self.repository.get_logs_count(self.mock_db)

        # Assert
        assert result == 100

    def test_get_old_logs_count(self):
        """Test get_old_logs_count method"""
        # Arrange
        cutoff_time = datetime.utcnow() - timedelta(days=30)
        self.mock_db.query.return_value.filter.return_value.count.return_value = 50

        # Act
        result = self.repository.get_old_logs_count(self.mock_db, cutoff_time)

        # Assert
        assert result == 50


class TestUserSettingsRepository:
    """Test UserSettingsRepository functionality"""

    def setup_method(self):
        """Setup test method"""
        self.repository = UserSettingsRepository()
        self.mock_db = Mock(spec=Session)

    def test_get_by_user_id(self):
        """Test get_by_user_id method"""
        # Arrange
        user_id = 1
        mock_settings = Mock(spec=UserSettings)
        self.mock_db.query.return_value.filter.return_value.first.return_value = (
            mock_settings
        )

        # Act
        result = self.repository.get_by_user_id(self.mock_db, user_id)

        # Assert
        assert result == mock_settings


class TestResourceSavingsRepository:
    """Test ResourceSavingsRepository functionality"""

    def setup_method(self):
        """Setup test method"""
        self.repository = ResourceSavingsRepository()
        self.mock_db = Mock(spec=Session)

    def test_get_savings_in_period(self):
        """Test get_savings_in_period method"""
        # Arrange
        period_start = datetime.utcnow() - timedelta(days=30)
        period_end = datetime.utcnow()
        mock_savings = [Mock(spec=ResourceSavings), Mock(spec=ResourceSavings)]
        self.mock_db.query.return_value.filter.return_value.all.return_value = (
            mock_savings
        )

        # Act
        result = self.repository.get_savings_in_period(
            self.mock_db, period_start, period_end
        )

        # Assert
        assert result == mock_savings

    def test_get_savings_by_user_in_period(self):
        """Test get_savings_by_user_in_period method"""
        # Arrange
        user_id = 1
        period_start = datetime.utcnow() - timedelta(days=30)
        mock_savings = [Mock(spec=ResourceSavings), Mock(spec=ResourceSavings)]
        self.mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
            mock_savings
        )

        # Act
        result = self.repository.get_savings_by_user_in_period(
            self.mock_db, user_id, period_start
        )

        # Assert
        assert result == mock_savings


class TestOpenAIMetricsRepository:
    """Test OpenAIMetricsRepository functionality"""

    def setup_method(self):
        """Setup test method"""
        self.repository = OpenAIMetricsRepository()
        self.mock_db = Mock(spec=Session)

    def test_get_all_metrics_ordered(self):
        """Test get_all_metrics_ordered method"""
        # Arrange
        mock_metrics = [Mock(spec=OpenAIMetrics), Mock(spec=OpenAIMetrics)]
        self.mock_db.query.return_value.order_by.return_value.all.return_value = (
            mock_metrics
        )

        # Act
        result = self.repository.get_all_metrics_ordered(self.mock_db)

        # Assert
        assert result == mock_metrics
