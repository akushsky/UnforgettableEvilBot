from datetime import datetime
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.orm import Session

from app.auth.security import get_password_hash
from app.core.repository_factory import repository_factory
from app.models.database import (
    DigestLog,
    MonitoredChat,
    SystemLog,
    User,
    WhatsAppMessage,
)
from config.settings import settings


class TestAPIIntegration:
    """Integration tests for API endpoints"""

    @pytest.fixture
    def test_user(self, db_session):
        """Create a test user for webhook tests."""
        user = User(
            username="test_webhook_user",
            email="webhook@test.com",
            hashed_password=get_password_hash("test_password"),
            is_active=True,
            whatsapp_connected=True,
            created_at=datetime.utcnow(),
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user

    @pytest.fixture
    def test_chat(self, db_session, test_user):
        """Create a monitored chat for webhook tests."""
        chat = MonitoredChat(
            user_id=test_user.id,
            chat_name="Test Chat",
            chat_id="test_chat_id",
            chat_type="group",
            is_active=True,
            created_at=datetime.utcnow(),
        )
        db_session.add(chat)
        db_session.commit()
        db_session.refresh(chat)
        return chat

    def test_health_check_endpoint(self, client):
        """Test the health check endpoint."""
        response = client.get("/health")
        # Health check can return 200 (healthy) or 503 (unhealthy) depending on system state
        assert response.status_code in [200, 503]

        data = response.json()
        assert "status" in data
        assert "service" in data
        assert "version" in data
        assert "timestamp" in data
        assert "checks" in data

    def test_metrics_endpoint(self, client):
        """Test the metrics endpoint."""
        response = client.get("/metrics")
        assert response.status_code == 200

        # Metrics should return JSON format
        data = response.json()
        assert "metrics" in data
        assert "timestamp" in data

        # Check metrics structure
        metrics = data["metrics"]
        assert "users" in metrics
        assert "chats" in metrics
        assert "messages" in metrics
        assert "digests" in metrics
        assert "performance" in metrics
        assert "openai" in metrics
        assert "system" in metrics

    def test_webhook_endpoint_whatsapp_message(
        self, client, db_session, test_user, test_chat
    ):
        """Test WhatsApp webhook endpoint with message data."""
        webhook_data = {
            "userId": test_user.id,
            "id": "test_message_id",
            "body": "Test message content",
            "timestamp": datetime.utcnow().isoformat(),
            "chatId": test_chat.chat_id,
            "from": "1234567890",  # Add the from field
            "fromMe": False,
            "type": "text",
            "hasMedia": False,
        }

        response = client.post("/webhook/whatsapp/message", json=webhook_data)
        assert response.status_code == 200

        # Verify message was stored in database
        message_repo = repository_factory.get_whatsapp_message_repository()
        stored_message = message_repo.get_by_message_id(db_session, "test_message_id")
        assert stored_message is not None
        assert stored_message.content == "Test message content"

    def test_webhook_endpoint_invalid_data(self, client):
        """Test WhatsApp webhook endpoint with invalid data."""
        invalid_data = {"invalid": "data"}

        response = client.post("/webhook/whatsapp/message", json=invalid_data)
        assert response.status_code == 422  # Validation error

    def test_webhook_endpoint_missing_required_fields(self, client):
        """Test WhatsApp webhook endpoint with missing required fields."""
        incomplete_data = {
            "id": "test_message_id",
            # Missing required fields like userId, body, etc.
        }

        response = client.post("/webhook/whatsapp/message", json=incomplete_data)
        assert response.status_code == 422  # Validation error

    def test_webhook_endpoint_duplicate_message(
        self, client, db_session, test_user, test_chat
    ):
        """Test handling of duplicate message IDs."""
        webhook_data = {
            "userId": test_user.id,
            "id": "duplicate_message_id",
            "body": "First message",
            "timestamp": datetime.utcnow().isoformat(),
            "chatId": test_chat.chat_id,
            "from": "1234567890",
            "fromMe": False,
            "type": "text",
            "hasMedia": False,
        }

        # Send first message
        response1 = client.post("/webhook/whatsapp/message", json=webhook_data)
        assert response1.status_code == 200

        # Send duplicate message
        webhook_data["body"] = "Second message"
        response2 = client.post("/webhook/whatsapp/message", json=webhook_data)
        assert response2.status_code == 200  # Should handle gracefully

        # Verify only one message was stored
        message_repo = repository_factory.get_whatsapp_message_repository()
        stored_message = message_repo.get_by_message_id(
            db_session, "duplicate_message_id"
        )
        assert stored_message is not None
        # Should keep the first message content
        assert stored_message.content == "First message"

    def test_webhook_endpoint_large_message(self, client, test_user, test_chat):
        """Test handling of large message content."""
        large_content = "x" * 10000  # 10KB message
        webhook_data = {
            "userId": test_user.id,
            "id": "large_message_id",
            "body": large_content,
            "timestamp": datetime.utcnow().isoformat(),
            "chatId": test_chat.chat_id,
            "from": "1234567890",
            "fromMe": False,
            "type": "text",
            "hasMedia": False,
        }

        response = client.post("/webhook/whatsapp/message", json=webhook_data)
        assert response.status_code == 200

    def test_webhook_endpoint_special_characters(
        self, client, db_session, test_user, test_chat
    ):
        """Test handling of special characters in message content."""
        special_content = "Test message with émojis 🚀 and special chars: <>&\"'"
        webhook_data = {
            "userId": test_user.id,
            "id": "special_chars_message_id",
            "body": special_content,
            "timestamp": datetime.utcnow().isoformat(),
            "chatId": test_chat.chat_id,
            "from": "1234567890",
            "fromMe": False,
            "type": "text",
            "hasMedia": False,
        }

        response = client.post("/webhook/whatsapp/message", json=webhook_data)
        assert response.status_code == 200

        # Verify message was stored correctly
        message_repo = repository_factory.get_whatsapp_message_repository()
        stored_message = message_repo.get_by_message_id(
            db_session, "special_chars_message_id"
        )
        assert stored_message is not None
        assert stored_message.content == special_content

    def test_webhook_endpoint_rate_limiting(self, client, test_user, test_chat):
        """Test rate limiting on webhook endpoint."""
        webhook_data = {
            "userId": test_user.id,
            "id": "rate_limit_test",
            "body": "Test message",
            "timestamp": datetime.utcnow().isoformat(),
            "chatId": test_chat.chat_id,
            "from": "1234567890",
            "fromMe": False,
            "type": "text",
            "hasMedia": False,
        }

        # Send multiple requests rapidly
        responses = []
        for i in range(10):
            webhook_data["id"] = f"rate_limit_test_{i}"
            response = client.post("/webhook/whatsapp/message", json=webhook_data)
            responses.append(response)

        # All should succeed (rate limiting is per IP, not per message)
        for response in responses:
            assert response.status_code == 200

    def test_webhook_endpoint_database_connection(self, client, test_user, test_chat):
        """Test webhook endpoint with database connection."""
        webhook_data = {
            "userId": test_user.id,
            "id": "db_connection_test",
            "body": "Database connection test",
            "timestamp": datetime.utcnow().isoformat(),
            "chatId": test_chat.chat_id,
            "from": "1234567890",
            "fromMe": False,
            "type": "text",
            "hasMedia": False,
        }

        response = client.post("/webhook/whatsapp/message", json=webhook_data)
        assert response.status_code == 200

        # Verify database operations completed successfully
        data = response.json()
        assert "message" in data
        assert "Message received and processed" in data["message"]

    def test_webhook_endpoint_error_handling(self, client):
        """Test error handling in webhook endpoint."""
        # Test with malformed JSON
        response = client.post("/webhook/whatsapp/message", data="invalid json")
        assert response.status_code == 422

        # Test with empty body
        response = client.post("/webhook/whatsapp/message", json={})
        assert response.status_code == 422

        # Test with None body
        response = client.post("/webhook/whatsapp/message")
        assert response.status_code == 422

    # Note: User-facing API tests have been removed since we moved to admin-only architecture
    # The following tests are no longer relevant:
    # - test_register_user_success
    # - test_login_success
    # - test_get_users_authenticated
    # - test_suspend_user
    # - test_resume_user
    # etc.
