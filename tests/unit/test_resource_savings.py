from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from sqlalchemy.orm import Session

from app.core.resource_savings import ResourceSavingsService
from app.models.database import MonitoredChat, ResourceSavings, User, WhatsAppMessage


class TestResourceSavingsService:
    """Test ResourceSavingsService functionality"""

    def setup_method(self):
        """Setup test method"""
        self.service = ResourceSavingsService()
        self.mock_db = Mock(spec=Session)

    def test_calculate_savings_for_user_success(self):
        """Test calculate_savings_for_user with valid data"""
        # Arrange
        user_id = 1
        period_start = datetime.utcnow() - timedelta(hours=24)
        period_end = datetime.utcnow()
        reason = "user_suspended"

        mock_user = Mock(spec=User)
        mock_user.id = user_id
        mock_user.username = "testuser"
        mock_user.whatsapp_connected = True

        with patch("app.core.resource_savings.repository_factory") as mock_factory:
            mock_user_repo = Mock()
            mock_user_repo.get_by_id.return_value = mock_user
            mock_factory.get_user_repository.return_value = mock_user_repo

            mock_chat_repo = Mock()
            mock_chat_repo.get_active_chats_for_user.return_value = []
            mock_factory.get_monitored_chat_repository.return_value = mock_chat_repo

            mock_message_repo = Mock()
            mock_message_repo.get_messages_by_chat_ids.return_value = []
            mock_factory.get_whatsapp_message_repository.return_value = (
                mock_message_repo
            )

            # Act
            result = self.service.calculate_savings_for_user(
                self.mock_db, user_id, period_start, period_end, reason
            )

        # Assert
        assert "error" not in result
        assert result["user_id"] == user_id
        assert result["username"] == "testuser"
        assert result["whatsapp_connections_saved"] == 1
        assert result["reason"] == reason
        self.mock_db.add.assert_called_once()
        self.mock_db.commit.assert_called_once()

    def test_calculate_savings_for_user_not_found(self):
        """Test calculate_savings_for_user when user not found"""
        # Arrange
        user_id = 999
        period_start = datetime.utcnow() - timedelta(hours=24)
        period_end = datetime.utcnow()

        with patch("app.core.resource_savings.repository_factory") as mock_factory:
            mock_user_repo = Mock()
            mock_user_repo.get_by_id.return_value = None
            mock_factory.get_user_repository.return_value = mock_user_repo

            # Act
            result = self.service.calculate_savings_for_user(
                self.mock_db, user_id, period_start, period_end
            )

        # Assert
        assert "error" in result
        assert result["error"] == "User not found"

    def test_calculate_savings_for_user_with_messages(self):
        """Test calculate_savings_for_user with existing messages"""
        # Arrange
        user_id = 1
        period_start = datetime.utcnow() - timedelta(hours=24)
        period_end = datetime.utcnow()

        mock_user = Mock(spec=User)
        mock_user.id = user_id
        mock_user.username = "testuser"
        mock_user.whatsapp_connected = True

        mock_chat = Mock(spec=MonitoredChat)
        mock_chat.id = 1

        mock_message = Mock(spec=WhatsAppMessage)
        mock_message.created_at = datetime.utcnow() - timedelta(hours=12)

        with patch("app.core.resource_savings.repository_factory") as mock_factory:
            mock_user_repo = Mock()
            mock_user_repo.get_by_id.return_value = mock_user
            mock_factory.get_user_repository.return_value = mock_user_repo

            mock_chat_repo = Mock()
            mock_chat_repo.get_active_chats_for_user.return_value = [mock_chat]
            mock_factory.get_monitored_chat_repository.return_value = mock_chat_repo

            mock_message_repo = Mock()
            mock_message_repo.get_messages_by_chat_ids.return_value = [mock_message]
            mock_factory.get_whatsapp_message_repository.return_value = (
                mock_message_repo
            )

            # Act
            result = self.service.calculate_savings_for_user(
                self.mock_db, user_id, period_start, period_end
            )

        # Assert
        assert "error" not in result
        assert result["messages_processed_saved"] == 1
        assert result["openai_requests_saved"] == 1

    def test_calculate_savings_for_user_database_error(self):
        """Test calculate_savings_for_user handles database errors"""
        # Arrange
        user_id = 1
        period_start = datetime.utcnow() - timedelta(hours=24)
        period_end = datetime.utcnow()

        mock_user = Mock(spec=User)
        mock_user.id = user_id
        mock_user.username = "testuser"
        mock_user.whatsapp_connected = True

        with patch("app.core.resource_savings.repository_factory") as mock_factory:
            mock_user_repo = Mock()
            mock_user_repo.get_by_id.return_value = mock_user
            mock_factory.get_user_repository.return_value = mock_user_repo

            self.mock_db.commit.side_effect = Exception("Database error")

            # Act
            result = self.service.calculate_savings_for_user(
                self.mock_db, user_id, period_start, period_end
            )

        # Assert
        assert "error" in result
        assert "Database error" in result["error"]
        self.mock_db.rollback.assert_called_once()

    def test_get_total_savings(self):
        """Test get_total_savings method"""
        # Arrange
        days_back = 30

        mock_savings1 = Mock(spec=ResourceSavings)
        mock_savings1.whatsapp_connections_saved = 2
        mock_savings1.messages_processed_saved = 10
        mock_savings1.openai_requests_saved = 10
        mock_savings1.memory_mb_saved = 100.0
        mock_savings1.cpu_seconds_saved = 3600.0
        mock_savings1.openai_cost_saved_usd = 0.02

        mock_savings2 = Mock(spec=ResourceSavings)
        mock_savings2.whatsapp_connections_saved = 1
        mock_savings2.messages_processed_saved = 5
        mock_savings2.openai_requests_saved = 5
        mock_savings2.memory_mb_saved = 50.0
        mock_savings2.cpu_seconds_saved = 1800.0
        mock_savings2.openai_cost_saved_usd = 0.01

        with patch("app.core.resource_savings.repository_factory") as mock_factory:
            mock_savings_repo = Mock()
            mock_savings_repo.get_savings_in_period.return_value = [
                mock_savings1,
                mock_savings2,
            ]
            mock_factory.get_resource_savings_repository.return_value = (
                mock_savings_repo
            )

            # Act
            result = self.service.get_total_savings(self.mock_db, days_back)

        # Assert
        assert "error" not in result
        assert result["total_whatsapp_connections_saved"] == 3
        assert result["total_messages_processed_saved"] == 15
        assert result["total_openai_requests_saved"] == 15
        assert result["total_memory_mb_saved"] == 150.0
        assert result["total_cpu_seconds_saved"] == 5400.0
        assert result["total_openai_cost_saved_usd"] == 0.03
        assert result["period_days"] == days_back
        assert result["records_count"] == 2

    def test_get_savings_by_user(self):
        """Test get_savings_by_user method"""
        # Arrange
        user_id = 1
        days_back = 30

        mock_savings = Mock(spec=ResourceSavings)
        mock_savings.id = 1
        mock_savings.whatsapp_connections_saved = 1
        mock_savings.messages_processed_saved = 5
        mock_savings.openai_requests_saved = 5
        mock_savings.memory_mb_saved = 50.0
        mock_savings.cpu_seconds_saved = 1800.0
        mock_savings.openai_cost_saved_usd = 0.01
        mock_savings.period_start = datetime.utcnow() - timedelta(days=1)
        mock_savings.period_end = datetime.utcnow()
        mock_savings.reason = "user_suspended"
        mock_savings.created_at = datetime.utcnow()

        with patch("app.core.resource_savings.repository_factory") as mock_factory:
            mock_savings_repo = Mock()
            mock_savings_repo.get_savings_by_user_in_period.return_value = [
                mock_savings
            ]
            mock_factory.get_resource_savings_repository.return_value = (
                mock_savings_repo
            )

            # Act
            result = self.service.get_savings_by_user(self.mock_db, user_id, days_back)

        # Assert
        assert len(result) == 1
        savings_record = result[0]
        assert savings_record["id"] == 1
        assert savings_record["whatsapp_connections_saved"] == 1
        assert savings_record["messages_processed_saved"] == 5
        assert savings_record["openai_requests_saved"] == 5
        assert savings_record["memory_mb_saved"] == 50.0
        assert savings_record["cpu_seconds_saved"] == 1800.0
        assert savings_record["openai_cost_saved_usd"] == 0.01
        assert savings_record["reason"] == "user_suspended"

    def test_record_suspension_savings(self):
        """Test record_suspension_savings method"""
        # Arrange
        user_id = 1
        suspension_start = datetime.utcnow() - timedelta(hours=12)

        with patch.object(self.service, "calculate_savings_for_user") as mock_calculate:
            mock_calculate.return_value = {"status": "success", "user_id": user_id}

            # Act
            result = self.service.record_suspension_savings(
                self.mock_db, user_id, suspension_start
            )

        # Assert
        assert result == {"status": "success", "user_id": user_id}
        # Verify the method was called with correct parameters (ignoring exact datetime)
        assert mock_calculate.call_count == 1
        call_args = mock_calculate.call_args[0]
        assert call_args[0] == self.mock_db
        assert call_args[1] == user_id
        assert call_args[2] == suspension_start
        assert call_args[4] == "user_suspended"

    def test_get_current_system_savings(self):
        """Test get_current_system_savings method"""
        # Act
        result = self.service.get_current_system_savings()

        # Assert
        assert "current_memory_usage_mb" in result
        assert "current_cpu_usage_percent" in result
        assert "estimated_memory_saved_mb" in result
        assert "estimated_cpu_saved_percent" in result

    def test_count_messages_in_period_no_chats(self):
        """Test _count_messages_in_period when no monitored chats"""
        # Arrange
        user_id = 1
        period_start = datetime.utcnow() - timedelta(hours=24)
        period_end = datetime.utcnow()

        with patch("app.core.resource_savings.repository_factory") as mock_factory:
            mock_chat_repo = Mock()
            mock_chat_repo.get_active_chats_for_user.return_value = []
            mock_factory.get_monitored_chat_repository.return_value = mock_chat_repo

            # Act
            result = self.service._count_messages_in_period(
                self.mock_db, user_id, period_start, period_end
            )

        # Assert
        assert result == 0

    def test_count_messages_in_period_with_messages(self):
        """Test _count_messages_in_period with existing messages"""
        # Arrange
        user_id = 1
        period_start = datetime.utcnow() - timedelta(hours=24)
        period_end = datetime.utcnow()

        mock_chat = Mock(spec=MonitoredChat)
        mock_chat.id = 1

        mock_message1 = Mock(spec=WhatsAppMessage)
        mock_message1.created_at = datetime.utcnow() - timedelta(hours=12)

        mock_message2 = Mock(spec=WhatsAppMessage)
        mock_message2.created_at = datetime.utcnow() - timedelta(hours=6)

        with patch("app.core.resource_savings.repository_factory") as mock_factory:
            mock_chat_repo = Mock()
            mock_chat_repo.get_active_chats_for_user.return_value = [mock_chat]
            mock_factory.get_monitored_chat_repository.return_value = mock_chat_repo

            mock_message_repo = Mock()
            mock_message_repo.get_messages_by_chat_ids.return_value = [
                mock_message1,
                mock_message2,
            ]
            mock_factory.get_whatsapp_message_repository.return_value = (
                mock_message_repo
            )

            # Act
            result = self.service._count_messages_in_period(
                self.mock_db, user_id, period_start, period_end
            )

        # Assert
        assert result == 2

    def test_count_messages_in_period_filters_by_time(self):
        """Test _count_messages_in_period filters messages by time period"""
        # Arrange
        user_id = 1
        period_start = datetime.utcnow() - timedelta(hours=24)
        period_end = datetime.utcnow()

        mock_chat = Mock(spec=MonitoredChat)
        mock_chat.id = 1

        mock_message1 = Mock(spec=WhatsAppMessage)
        mock_message1.created_at = datetime.utcnow() - timedelta(
            hours=12
        )  # Within period

        mock_message2 = Mock(spec=WhatsAppMessage)
        mock_message2.created_at = datetime.utcnow() - timedelta(
            hours=48
        )  # Outside period

        with patch("app.core.resource_savings.repository_factory") as mock_factory:
            mock_chat_repo = Mock()
            mock_chat_repo.get_active_chats_for_user.return_value = [mock_chat]
            mock_factory.get_monitored_chat_repository.return_value = mock_chat_repo

            mock_message_repo = Mock()
            mock_message_repo.get_messages_by_chat_ids.return_value = [
                mock_message1,
                mock_message2,
            ]
            mock_factory.get_whatsapp_message_repository.return_value = (
                mock_message_repo
            )

            # Act
            result = self.service._count_messages_in_period(
                self.mock_db, user_id, period_start, period_end
            )

        # Assert
        assert result == 1  # Only message1 should be counted
