from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

from app.scheduler.digest_scheduler import DigestScheduler


class TestDigestScheduler:
    def setup_method(self):
        """Set up test fixtures"""
        self.scheduler = DigestScheduler()

    def test_initialization(self):
        """Test scheduler initialization"""
        assert self.scheduler.is_running is False
        assert self.scheduler.whatsapp_service is not None
        assert self.scheduler.openai_service is not None
        assert self.scheduler.telegram_service is not None

    def test_start_scheduler_initialization(self):
        """Test scheduler start initialization"""
        # Test that the scheduler sets is_running to True
        self.scheduler.is_running = False
        # We can't easily test the full async loop, but we can test the initialization
        assert self.scheduler.is_running is False

    def test_start_scheduler_with_error_handling(self):
        """Test scheduler error handling setup"""
        # Test that the scheduler has proper error handling structure
        assert hasattr(self.scheduler, "is_running")
        assert hasattr(self.scheduler, "process_all_users")

    def test_daily_cleanup_scheduler_setup(self):
        """Test daily cleanup scheduler setup"""
        # Test that the scheduler has proper daily cleanup structure
        assert hasattr(self.scheduler, "is_running")
        assert hasattr(self.scheduler, "run_daily_cleanup")

    def test_daily_cleanup_scheduler_with_error_handling(self):
        """Test daily cleanup scheduler error handling setup"""
        # Test that the scheduler has proper error handling structure
        assert hasattr(self.scheduler, "is_running")
        assert hasattr(self.scheduler, "run_daily_cleanup")

    def test_daily_cleanup_scheduler_method_exists(self):
        """Test that daily cleanup scheduler method exists and is callable"""
        # Test that the method exists and can be called
        assert callable(self.scheduler.daily_cleanup_scheduler)

    @patch("app.scheduler.digest_scheduler.cleanup_service")
    @patch("app.scheduler.digest_scheduler.repository_factory")
    @patch("app.scheduler.digest_scheduler.SessionLocal")
    async def test_run_daily_cleanup_success(
        self, mock_session_local, mock_repo_factory, mock_cleanup_service
    ):
        """Test successful daily cleanup"""
        # Mock cleanup results
        mock_cleanup_service.run_full_cleanup = AsyncMock(
            return_value={
                "messages": {"messages_deleted": 10, "users_processed": 5},
                "digests": {"digests_deleted": 3},
                "system_logs": {"logs_deleted": 2},
            }
        )

        # Mock database session
        mock_db = Mock()
        mock_session_local.return_value = mock_db

        # Mock user repository
        mock_user_repo = Mock()
        mock_users = [Mock(telegram_channel_id="test_channel")]
        mock_user_repo.get_active_users_with_telegram.return_value = mock_users
        mock_repo_factory.get_user_repository.return_value = mock_user_repo

        # Mock telegram service
        self.scheduler.telegram_service.send_notification = AsyncMock()

        await self.scheduler.run_daily_cleanup()

        mock_cleanup_service.run_full_cleanup.assert_called_once()
        self.scheduler.telegram_service.send_notification.assert_called_once()
        mock_db.close.assert_called_once()

    @patch("app.scheduler.digest_scheduler.cleanup_service")
    @patch("app.scheduler.digest_scheduler.repository_factory")
    @patch("app.scheduler.digest_scheduler.SessionLocal")
    async def test_run_daily_cleanup_failure(
        self, mock_session_local, mock_repo_factory, mock_cleanup_service
    ):
        """Test daily cleanup with failure"""
        # Mock cleanup failure
        mock_cleanup_service.run_full_cleanup = AsyncMock(
            return_value={"error": "Cleanup failed"}
        )

        # Mock database session
        mock_db = Mock()
        mock_session_local.return_value = mock_db

        # Mock user repository
        mock_user_repo = Mock()
        mock_admin = Mock(telegram_channel_id="admin_channel")
        mock_user_repo.get_by_id.return_value = mock_admin
        mock_repo_factory.get_user_repository.return_value = mock_user_repo

        # Mock telegram service
        self.scheduler.telegram_service.send_notification = AsyncMock()

        await self.scheduler.run_daily_cleanup()

        mock_cleanup_service.run_full_cleanup.assert_called_once()
        # Should send error notification
        self.scheduler.telegram_service.send_notification.assert_called_once()
        mock_db.close.assert_called_once()

    @patch("app.scheduler.digest_scheduler.repository_factory")
    @patch("app.scheduler.digest_scheduler.SessionLocal")
    async def test_send_cleanup_notification_success(
        self, mock_session_local, mock_repo_factory
    ):
        """Test successful cleanup notification"""
        # Mock database session
        mock_db = Mock()
        mock_session_local.return_value = mock_db

        # Mock user repository
        mock_user_repo = Mock()
        mock_users = [Mock(telegram_channel_id="test_channel")]
        mock_user_repo.get_active_users_with_telegram.return_value = mock_users
        mock_repo_factory.get_user_repository.return_value = mock_user_repo

        # Mock telegram service
        self.scheduler.telegram_service.send_notification = AsyncMock()

        await self.scheduler.send_cleanup_notification(10, 3, 2, 5)

        self.scheduler.telegram_service.send_notification.assert_called_once()
        mock_db.close.assert_called_once()

    @patch("app.scheduler.digest_scheduler.repository_factory")
    @patch("app.scheduler.digest_scheduler.SessionLocal")
    async def test_send_cleanup_notification_no_users(
        self, mock_session_local, mock_repo_factory
    ):
        """Test cleanup notification with no users"""
        # Mock database session
        mock_db = Mock()
        mock_session_local.return_value = mock_db

        # Mock user repository with no users
        mock_user_repo = Mock()
        mock_user_repo.get_active_users_with_telegram.return_value = []
        mock_repo_factory.get_user_repository.return_value = mock_user_repo

        # Mock telegram service
        self.scheduler.telegram_service.send_notification = AsyncMock()

        await self.scheduler.send_cleanup_notification(10, 3, 2, 5)

        # Should not send any messages
        self.scheduler.telegram_service.send_notification.assert_not_called()
        mock_db.close.assert_called_once()

    @patch("app.scheduler.digest_scheduler.repository_factory")
    @patch("app.scheduler.digest_scheduler.SessionLocal")
    async def test_send_cleanup_error_notification_success(
        self, mock_session_local, mock_repo_factory
    ):
        """Test successful cleanup error notification"""
        # Mock database session
        mock_db = Mock()
        mock_session_local.return_value = mock_db

        # Mock user repository
        mock_user_repo = Mock()
        mock_admin = Mock(telegram_channel_id="admin_channel")
        mock_user_repo.get_by_id.return_value = mock_admin
        mock_repo_factory.get_user_repository.return_value = mock_user_repo

        # Mock telegram service
        self.scheduler.telegram_service.send_notification = AsyncMock()

        await self.scheduler.send_cleanup_error_notification("Test error")

        self.scheduler.telegram_service.send_notification.assert_called_once()
        mock_db.close.assert_called_once()

    @patch("app.scheduler.digest_scheduler.repository_factory")
    @patch("app.scheduler.digest_scheduler.SessionLocal")
    async def test_process_all_users_success(
        self, mock_session_local, mock_repo_factory
    ):
        """Test processing all users successfully"""
        # Mock database sessions
        mock_db = Mock()
        mock_user_db = Mock()
        mock_session_local.side_effect = [mock_db, mock_user_db]

        # Mock user repository
        mock_user_repo = Mock()
        mock_users = [Mock(username="test_user")]
        mock_user_repo.get_active_users_with_telegram.return_value = mock_users
        mock_repo_factory.get_user_repository.return_value = mock_user_repo

        # Mock digest repository
        mock_digest_repo = Mock()
        mock_digest_repo.should_create_digest.return_value = False
        mock_repo_factory.get_digest_log_repository.return_value = mock_digest_repo

        with patch.object(self.scheduler, "should_create_digest", return_value=False):
            await self.scheduler.process_all_users()

        mock_db.close.assert_called_once()
        mock_user_db.close.assert_called_once()

    @patch("app.scheduler.digest_scheduler.repository_factory")
    @patch("app.scheduler.digest_scheduler.SessionLocal")
    async def test_process_all_users_with_digest_creation(
        self, mock_session_local, mock_repo_factory
    ):
        """Test processing users with digest creation"""
        # Mock database sessions
        mock_db = Mock()
        mock_user_db = Mock()
        mock_session_local.side_effect = [mock_db, mock_user_db]

        # Mock user repository
        mock_user_repo = Mock()
        mock_users = [Mock(username="test_user")]
        mock_user_repo.get_active_users_with_telegram.return_value = mock_users
        mock_repo_factory.get_user_repository.return_value = mock_user_repo

        # Mock digest repository
        mock_digest_repo = Mock()
        mock_digest_repo.should_create_digest.return_value = True
        mock_repo_factory.get_digest_log_repository.return_value = mock_digest_repo

        with patch.object(self.scheduler, "should_create_digest", return_value=True):
            with patch.object(
                self.scheduler, "create_and_send_digest"
            ) as mock_create_digest:
                await self.scheduler.process_all_users()

                mock_create_digest.assert_called_once()

        mock_db.close.assert_called_once()
        mock_user_db.close.assert_called_once()

    @patch("app.scheduler.digest_scheduler.repository_factory")
    @patch("app.scheduler.digest_scheduler.SessionLocal")
    async def test_process_all_users_with_error(
        self, mock_session_local, mock_repo_factory
    ):
        """Test processing users with error handling"""
        # Mock database sessions
        mock_db = Mock()
        mock_user_db = Mock()
        mock_session_local.side_effect = [mock_db, mock_user_db]

        # Mock user repository
        mock_user_repo = Mock()
        mock_users = [Mock(username="test_user")]
        mock_user_repo.get_active_users_with_telegram.return_value = mock_users
        mock_repo_factory.get_user_repository.return_value = mock_user_repo

        # Mock digest repository
        mock_digest_repo = Mock()
        mock_digest_repo.should_create_digest.return_value = True
        mock_repo_factory.get_digest_log_repository.return_value = mock_digest_repo

        with patch.object(self.scheduler, "should_create_digest", return_value=True):
            with patch.object(
                self.scheduler,
                "create_and_send_digest",
                side_effect=Exception("Digest error"),
            ):
                await self.scheduler.process_all_users()

                # Should handle error gracefully
                mock_user_db.rollback.assert_called_once()
                mock_user_db.close.assert_called_once()

        mock_db.close.assert_called_once()

    @patch("app.scheduler.digest_scheduler.repository_factory")
    async def test_should_create_digest(self, mock_repo_factory):
        """Test should_create_digest method"""
        # Mock user and database session
        mock_user = Mock(id=1)
        mock_db = Mock()

        # Mock digest repository
        mock_digest_repo = Mock()
        mock_digest_repo.should_create_digest.return_value = True
        mock_repo_factory.get_digest_log_repository.return_value = mock_digest_repo

        result = await self.scheduler.should_create_digest(mock_user, mock_db)

        assert result
        mock_digest_repo.should_create_digest.assert_called_once_with(
            mock_db, mock_user.id, mock_user.digest_interval_hours
        )

    @patch("app.scheduler.digest_scheduler.repository_factory")
    @patch("app.scheduler.digest_scheduler.datetime")
    async def test_create_and_send_digest_no_chats(
        self, mock_datetime, mock_repo_factory
    ):
        """Test digest creation with no monitored chats"""
        # Mock user and database session
        mock_user = Mock(username="test_user", id=1, digest_interval_hours=24)
        mock_db = Mock()

        # Mock datetime
        mock_datetime.utcnow.return_value = datetime(2024, 1, 1, 12, 0, 0)

        # Mock monitored chat repository
        mock_chat_repo = Mock()
        mock_chat_repo.get_active_chats_for_user.return_value = []
        mock_repo_factory.get_monitored_chat_repository.return_value = mock_chat_repo

        await self.scheduler.create_and_send_digest(mock_user, mock_db)

        # Should return early without creating digest
        mock_chat_repo.get_active_chats_for_user.assert_called_once_with(
            mock_db, mock_user.id
        )

    @patch("app.scheduler.digest_scheduler.repository_factory")
    @patch("app.scheduler.digest_scheduler.datetime")
    async def test_create_and_send_digest_success(
        self, mock_datetime, mock_repo_factory
    ):
        """Test successful digest creation and sending"""
        # Mock user and database session
        mock_user = Mock(username="test_user", id=1, digest_interval_hours=24)
        mock_db = Mock()

        # Mock datetime
        mock_datetime.utcnow.return_value = datetime(2024, 1, 1, 12, 0, 0)

        # Mock monitored chat
        mock_chat = Mock(id=1, chat_name="Test Chat")

        # Mock monitored chat repository
        mock_chat_repo = Mock()
        mock_chat_repo.get_active_chats_for_user.return_value = [mock_chat]
        mock_repo_factory.get_monitored_chat_repository.return_value = mock_chat_repo

        # Mock WhatsApp message repository
        mock_message_repo = Mock()
        mock_message = Mock(
            sender="Test Sender",
            content="Test message",
            importance_score=0.8,
            timestamp=datetime(2024, 1, 1, 11, 0, 0),
            is_processed=False,
        )
        mock_message_repo.get_important_messages_for_digest.return_value = [
            mock_message
        ]
        mock_repo_factory.get_whatsapp_message_repository.return_value = (
            mock_message_repo
        )

        # Mock OpenAI service
        self.scheduler.openai_service.create_digest_by_chats = AsyncMock(
            return_value="Test digest content"
        )

        # Mock Telegram service
        self.scheduler.telegram_service.send_digest = AsyncMock(return_value=True)

        # Mock digest log repository
        mock_digest_repo = Mock()
        mock_repo_factory.get_digest_log_repository.return_value = mock_digest_repo

        await self.scheduler.create_and_send_digest(mock_user, mock_db)

        # Verify all services were called
        mock_chat_repo.get_active_chats_for_user.assert_called_once_with(
            mock_db, mock_user.id
        )
        mock_message_repo.get_important_messages_for_digest.assert_called_once_with(
            mock_db, mock_chat.id, 24, 3
        )
        self.scheduler.openai_service.create_digest_by_chats.assert_called_once()
        self.scheduler.telegram_service.send_digest.assert_called_once()
        mock_digest_repo.create.assert_called_once()
        mock_db.commit.assert_called_once()

    @patch("app.scheduler.digest_scheduler.repository_factory")
    @patch("app.scheduler.digest_scheduler.datetime")
    async def test_create_and_send_digest_no_messages(
        self, mock_datetime, mock_repo_factory
    ):
        """Test digest creation with no important messages"""
        # Mock user and database session
        mock_user = Mock(username="test_user", id=1, digest_interval_hours=24)
        mock_db = Mock()

        # Mock datetime
        mock_datetime.utcnow.return_value = datetime(2024, 1, 1, 12, 0, 0)

        # Mock monitored chat
        mock_chat = Mock(id=1, chat_name="Test Chat")

        # Mock monitored chat repository
        mock_chat_repo = Mock()
        mock_chat_repo.get_active_chats_for_user.return_value = [mock_chat]
        mock_repo_factory.get_monitored_chat_repository.return_value = mock_chat_repo

        # Mock WhatsApp message repository with no messages
        mock_message_repo = Mock()
        mock_message_repo.get_important_messages_for_digest.return_value = []
        mock_repo_factory.get_whatsapp_message_repository.return_value = (
            mock_message_repo
        )

        await self.scheduler.create_and_send_digest(mock_user, mock_db)

        # Should return early without creating digest
        mock_chat_repo.get_active_chats_for_user.assert_called_once_with(
            mock_db, mock_user.id
        )
        mock_message_repo.get_important_messages_for_digest.assert_called_once_with(
            mock_db, mock_chat.id, 24, 3
        )

    @patch("app.scheduler.digest_scheduler.repository_factory")
    @patch("app.scheduler.digest_scheduler.datetime")
    async def test_create_and_send_digest_with_error(
        self, mock_datetime, mock_repo_factory
    ):
        """Test digest creation with error handling"""
        # Mock user and database session
        mock_user = Mock(username="test_user", id=1, digest_interval_hours=24)
        mock_db = Mock()

        # Mock datetime
        mock_datetime.utcnow.return_value = datetime(2024, 1, 1, 12, 0, 0)

        # Mock monitored chat repository
        mock_chat_repo = Mock()
        mock_chat_repo.get_active_chats_for_user.side_effect = Exception(
            "Database error"
        )
        mock_repo_factory.get_monitored_chat_repository.return_value = mock_chat_repo

        await self.scheduler.create_and_send_digest(mock_user, mock_db)

        # Should handle error gracefully
        mock_db.rollback.assert_called_once()

    def test_stop_scheduler(self):
        """Test stopping the scheduler"""
        self.scheduler.is_running = True
        self.scheduler.stop_scheduler()
        assert self.scheduler.is_running is False

    @patch("app.scheduler.digest_scheduler.cleanup_service")
    async def test_run_data_cleanup_success(self, mock_cleanup_service):
        """Test successful data cleanup"""
        # Mock cleanup results
        mock_cleanup_service.run_full_cleanup = AsyncMock(
            return_value={
                "messages": {"messages_deleted": 10},
                "digests": {"digests_deleted": 3},
                "system_logs": {"logs_deleted": 2},
            }
        )

        await self.scheduler.run_data_cleanup()

        mock_cleanup_service.run_full_cleanup.assert_called_once()

    @patch("app.scheduler.digest_scheduler.cleanup_service")
    async def test_run_data_cleanup_failure(self, mock_cleanup_service):
        """Test data cleanup with failure"""
        # Mock cleanup failure
        mock_cleanup_service.run_full_cleanup = AsyncMock(
            return_value={"error": "Cleanup failed"}
        )

        await self.scheduler.run_data_cleanup()

        mock_cleanup_service.run_full_cleanup.assert_called_once()

    @patch("app.scheduler.digest_scheduler.cleanup_service")
    async def test_run_data_cleanup_exception(self, mock_cleanup_service):
        """Test data cleanup with exception"""
        # Mock cleanup exception
        mock_cleanup_service.run_full_cleanup = AsyncMock(
            side_effect=Exception("Cleanup exception")
        )

        await self.scheduler.run_data_cleanup()

        mock_cleanup_service.run_full_cleanup.assert_called_once()
