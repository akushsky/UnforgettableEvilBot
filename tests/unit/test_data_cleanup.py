from unittest.mock import Mock, patch

from sqlalchemy.orm import Session

from app.core.data_cleanup import DataCleanupService
from app.models.database import MonitoredChat, User


class TestDataCleanupService:
    def setup_method(self):
        self.service = DataCleanupService()
        self.mock_db = Mock(spec=Session)

    @patch("app.core.data_cleanup.repository_factory")
    @patch("app.core.user_utils.get_user_settings")
    async def test_cleanup_old_messages_success(self, mock_get_settings, mock_factory):
        """Test successful cleanup of old messages"""
        # Arrange
        mock_user = Mock(spec=User)
        mock_user.id = 1
        mock_user.username = "testuser"

        mock_chat = Mock(spec=MonitoredChat)
        mock_chat.id = 1

        mock_users = [mock_user]
        mock_chats = [mock_chat]

        mock_user_repo = Mock()
        mock_user_repo.get_all.return_value = mock_users
        mock_factory.get_user_repository.return_value = mock_user_repo

        mock_chat_repo = Mock()
        mock_chat_repo.get_active_chats_for_user.return_value = mock_chats
        mock_factory.get_monitored_chat_repository.return_value = mock_chat_repo

        mock_message_repo = Mock()
        mock_message_repo.delete_old_messages.return_value = 5
        mock_factory.get_whatsapp_message_repository.return_value = mock_message_repo

        mock_settings = Mock()
        mock_settings.max_message_age_hours = 24
        mock_settings.user_id = 1
        mock_get_settings.return_value = mock_settings

        # Act
        result = await self.service.cleanup_old_messages(self.mock_db)

        # Assert
        assert result["messages_deleted"] == 5
        assert result["users_processed"] == 1
        assert result["errors"] == 0

    @patch("app.core.data_cleanup.repository_factory")
    async def test_cleanup_old_messages_no_users(self, mock_factory):
        """Test cleanup when no users exist"""
        # Arrange
        mock_user_repo = Mock()
        mock_user_repo.get_all.return_value = []
        mock_factory.get_user_repository.return_value = mock_user_repo

        # Act
        result = await self.service.cleanup_old_messages(self.mock_db)

        # Assert
        assert result["messages_deleted"] == 0
        assert result["users_processed"] == 0
        assert result["errors"] == 0

    @patch("app.core.data_cleanup.repository_factory")
    @patch("app.core.user_utils.get_user_settings")
    async def test_cleanup_old_messages_no_chats(self, mock_get_settings, mock_factory):
        """Test cleanup when user has no monitored chats"""
        # Arrange
        mock_user = Mock(spec=User)
        mock_user.id = 1

        mock_users = [mock_user]

        mock_user_repo = Mock()
        mock_user_repo.get_all.return_value = mock_users
        mock_factory.get_user_repository.return_value = mock_user_repo

        mock_chat_repo = Mock()
        mock_chat_repo.get_active_chats_for_user.return_value = []
        mock_factory.get_monitored_chat_repository.return_value = mock_chat_repo

        mock_settings = Mock()
        mock_settings.max_message_age_hours = 24
        mock_settings.user_id = 1
        mock_get_settings.return_value = mock_settings

        # Act
        result = await self.service.cleanup_old_messages(self.mock_db)

        # Assert
        assert result["messages_deleted"] == 0
        assert (
            result["users_processed"] == 0
        )  # Users without chats are not counted as processed
        assert result["errors"] == 0

    @patch("app.core.data_cleanup.repository_factory")
    async def test_cleanup_old_digests_success(self, mock_factory):
        """Test successful cleanup of old digests"""
        # Arrange
        mock_digest_repo = Mock()
        mock_digest_repo.delete_old_digests.return_value = 3
        mock_factory.get_digest_log_repository.return_value = mock_digest_repo

        # Act
        result = await self.service.cleanup_old_digests(self.mock_db)

        # Assert
        assert result["digests_deleted"] == 3
        assert result["days_to_keep"] == 1  # Default setting is 30 days

    @patch("app.core.data_cleanup.repository_factory")
    async def test_cleanup_old_system_logs_success(self, mock_factory):
        """Test successful cleanup of old system logs"""
        # Arrange
        mock_log_repo = Mock()
        mock_log_repo.delete_old_logs.return_value = 10
        mock_factory.get_system_log_repository.return_value = mock_log_repo

        # Act
        result = await self.service.cleanup_old_system_logs(self.mock_db)

        # Assert
        assert result["logs_deleted"] == 10
        assert result["days_to_keep"] == 1  # Default setting is 7 days

    @patch("app.core.data_cleanup.repository_factory")
    async def test_get_storage_stats_success(self, mock_factory):
        """Test getting storage statistics successfully"""
        # Arrange
        mock_message_repo = Mock()
        mock_message_repo.get_messages_count.return_value = 100
        mock_message_repo.get_old_messages_count.return_value = 20
        mock_factory.get_whatsapp_message_repository.return_value = mock_message_repo

        mock_digest_repo = Mock()
        mock_digest_repo.get_digests_count.return_value = 50
        mock_digest_repo.get_old_digests_count.return_value = 10
        mock_factory.get_digest_log_repository.return_value = mock_digest_repo

        mock_log_repo = Mock()
        mock_log_repo.get_logs_count.return_value = 200
        mock_factory.get_system_log_repository.return_value = mock_log_repo

        # Act
        result = await self.service.get_storage_stats(self.mock_db)

        # Assert
        assert result["total_messages"] == 100
        assert result["total_digests"] == 50
        assert result["total_system_logs"] == 200
        assert result["old_messages_7_days"] == 20
        assert result["old_digests_30_days"] == 10

    @patch("app.core.data_cleanup.repository_factory")
    async def test_run_full_cleanup_success(self, mock_factory):
        """Test running full cleanup successfully"""
        # Arrange
        mock_message_repo = Mock()
        mock_message_repo.delete_old_messages.return_value = 5
        mock_factory.get_whatsapp_message_repository.return_value = mock_message_repo

        mock_digest_repo = Mock()
        mock_digest_repo.delete_old_digests.return_value = 3
        mock_factory.get_digest_log_repository.return_value = mock_digest_repo

        mock_log_repo = Mock()
        mock_log_repo.delete_old_logs.return_value = 10
        mock_factory.get_system_log_repository.return_value = mock_log_repo

        mock_message_repo.get_messages_count.return_value = 100
        mock_message_repo.get_old_messages_count.return_value = 20
        mock_digest_repo.get_digests_count.return_value = 50
        mock_digest_repo.get_old_digests_count.return_value = 10
        mock_log_repo.get_logs_count.return_value = 200

        # Act
        result = await self.service.run_full_cleanup()

        # Assert
        assert "messages" in result
        assert "digests" in result
        assert "system_logs" in result
        assert "storage_stats" in result

    @patch("app.core.data_cleanup.repository_factory")
    @patch("app.core.user_utils.get_user_settings")
    async def test_cleanup_old_messages_database_error(
        self, mock_get_settings, mock_factory
    ):
        """Test cleanup of old messages with database error"""
        # Arrange
        mock_user = Mock(spec=User)
        mock_user.id = 1

        mock_users = [mock_user]

        mock_user_repo = Mock()
        mock_user_repo.get_all.return_value = mock_users
        mock_factory.get_user_repository.return_value = mock_user_repo

        mock_chat_repo = Mock()
        mock_chat_repo.get_active_chats_for_user.side_effect = Exception(
            "Database error"
        )
        mock_factory.get_monitored_chat_repository.return_value = mock_chat_repo

        mock_settings = Mock()
        mock_settings.max_message_age_hours = 24
        mock_settings.user_id = 1
        mock_get_settings.return_value = mock_settings

        # Act
        result = await self.service.cleanup_old_messages(self.mock_db)

        # Assert
        assert result["errors"] == 1

    @patch("app.core.data_cleanup.repository_factory")
    async def test_cleanup_old_digests_database_error(self, mock_factory):
        """Test cleanup of old digests with database error"""
        # Arrange
        mock_digest_repo = Mock()
        mock_digest_repo.delete_old_digests.side_effect = Exception("Database error")
        mock_factory.get_digest_log_repository.return_value = mock_digest_repo

        # Act
        result = await self.service.cleanup_old_digests(self.mock_db)

        # Assert
        assert result["errors"] == 1

    @patch("app.core.data_cleanup.repository_factory")
    async def test_cleanup_old_system_logs_database_error(self, mock_factory):
        """Test cleanup of old logs with database error"""
        # Arrange
        mock_log_repo = Mock()
        mock_log_repo.delete_old_logs.side_effect = Exception("Database error")
        mock_factory.get_system_log_repository.return_value = mock_log_repo

        # Act
        result = await self.service.cleanup_old_system_logs(self.mock_db)

        # Assert
        assert result["errors"] == 1

    @patch("app.core.data_cleanup.repository_factory")
    async def test_get_storage_stats_database_error(self, mock_factory):
        """Test getting storage stats with database error"""
        # Arrange
        mock_message_repo = Mock()
        mock_message_repo.get_messages_count.side_effect = Exception("Database error")
        mock_factory.get_whatsapp_message_repository.return_value = mock_message_repo

        # Act
        result = await self.service.get_storage_stats(self.mock_db)

        # Assert
        assert "error" in result

    @patch("app.core.data_cleanup.repository_factory")
    @patch("app.core.user_utils.get_user_settings")
    async def test_cleanup_old_messages_custom_retention(
        self, mock_get_settings, mock_factory
    ):
        """Test cleanup with custom retention period"""
        # Arrange
        mock_user = Mock(spec=User)
        mock_user.id = 1

        mock_users = [mock_user]

        mock_user_repo = Mock()
        mock_user_repo.get_all.return_value = mock_users
        mock_factory.get_user_repository.return_value = mock_user_repo

        mock_chat_repo = Mock()
        mock_chat_repo.get_active_chats_for_user.return_value = []
        mock_factory.get_monitored_chat_repository.return_value = mock_chat_repo

        mock_settings = Mock()
        mock_settings.max_message_age_hours = 7 * 24  # 7 days
        mock_settings.user_id = 1
        mock_get_settings.return_value = mock_settings

        # Act
        result = await self.service.cleanup_old_messages(self.mock_db)

        # Assert
        assert (
            result["users_processed"] == 0
        )  # Users without chats are not counted as processed
        assert result["errors"] == 0

    @patch("app.core.data_cleanup.repository_factory")
    async def test_cleanup_old_digests_custom_days(self, mock_factory):
        """Test cleanup with custom days to keep"""
        # Arrange
        custom_days = 7
        mock_digest_repo = Mock()
        mock_digest_repo.delete_old_digests.return_value = 2
        mock_factory.get_digest_log_repository.return_value = mock_digest_repo

        # Act
        result = await self.service.cleanup_old_digests(
            self.mock_db, days_to_keep=custom_days
        )

        # Assert
        assert result["digests_deleted"] == 2
        assert result["days_to_keep"] == custom_days

    @patch("app.core.data_cleanup.repository_factory")
    async def test_cleanup_old_system_logs_custom_days(self, mock_factory):
        """Test cleanup with custom days to keep"""
        # Arrange
        custom_days = 14
        mock_log_repo = Mock()
        mock_log_repo.delete_old_logs.return_value = 5
        mock_factory.get_system_log_repository.return_value = mock_log_repo

        # Act
        result = await self.service.cleanup_old_system_logs(
            self.mock_db, days_to_keep=custom_days
        )

        # Assert
        assert result["logs_deleted"] == 5
        assert result["days_to_keep"] == custom_days
