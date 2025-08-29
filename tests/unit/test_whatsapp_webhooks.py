from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.whatsapp_webhooks import get_active_users, router, whatsapp_webhook_health
from tests.unit.conftest import create_test_user


class TestWhatsAppWebhooks:
    """Test cases for WhatsApp webhooks functionality"""

    @pytest.fixture
    def client(self):
        """Create test client"""
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    @pytest.fixture
    def mock_db(self):
        """Create mock database session"""
        return Mock(spec=Session)

    @pytest.fixture
    def mock_user_repository(self):
        """Create mock user repository"""
        return Mock()

    @pytest.mark.asyncio
    async def test_whatsapp_webhook_health(self):
        """Test the health check endpoint"""
        response = await whatsapp_webhook_health()

        assert response["status"] == "healthy"
        assert response["service"] == "whatsapp-webhooks"

    @patch("app.api.whatsapp_webhooks.repository_factory")
    @pytest.mark.asyncio
    async def test_get_active_users_success(self, mock_repo_factory, mock_db):
        """Test successful retrieval of active users"""
        # Create mock users
        mock_users = [
            Mock(id=1, username="user1", whatsapp_connected=True, is_active=True),
            Mock(id=2, username="user2", whatsapp_connected=True, is_active=True),
            Mock(
                id=3,
                username="user3",
                whatsapp_connected=False,  # Should be filtered out
                is_active=True,
            ),
        ]

        # Setup mock repository
        mock_user_repo = Mock()
        mock_user_repo.get_active_users_with_whatsapp.return_value = mock_users[:2]
        mock_repo_factory.get_user_repository.return_value = mock_user_repo

        # Call the function
        response = await get_active_users(mock_db)

        # Verify the response
        assert "active_users" in response
        assert len(response["active_users"]) == 2

        user1 = response["active_users"][0]
        assert user1["id"] == 1
        assert user1["username"] == "user1"
        assert user1["whatsapp_connected"] is True
        assert user1["is_active"] is True

        user2 = response["active_users"][1]
        assert user2["id"] == 2
        assert user2["username"] == "user2"
        assert user2["whatsapp_connected"] is True
        assert user2["is_active"] is True

        # Verify repository was called correctly
        mock_user_repo.get_active_users_with_whatsapp.assert_called_once_with(mock_db)

    @patch("app.api.whatsapp_webhooks.repository_factory")
    @pytest.mark.asyncio
    async def test_get_active_users_empty(self, mock_repo_factory, mock_db):
        """Test retrieval when no active users exist"""
        # Setup mock repository to return empty list
        mock_user_repo = Mock()
        mock_user_repo.get_active_users_with_whatsapp.return_value = []
        mock_repo_factory.get_user_repository.return_value = mock_user_repo

        # Call the function
        response = await get_active_users(mock_db)

        # Verify the response
        assert "active_users" in response
        assert len(response["active_users"]) == 0

    @patch("app.api.whatsapp_webhooks.repository_factory")
    @pytest.mark.asyncio
    async def test_get_active_users_database_error(self, mock_repo_factory, mock_db):
        """Test handling of database errors"""
        from fastapi import HTTPException

        # Setup mock repository to raise an exception
        mock_user_repo = Mock()
        mock_user_repo.get_active_users_with_whatsapp.side_effect = Exception(
            "Database connection failed"
        )
        mock_repo_factory.get_user_repository.return_value = mock_user_repo

        # Call the function and expect an exception
        with pytest.raises(HTTPException) as exc_info:
            await get_active_users(mock_db)

        assert exc_info.value.status_code == 500
        assert "Database connection failed" in str(exc_info.value.detail)

    def test_active_users_endpoint_integration(self, client, mock_db):
        """Test the /active-users endpoint through the router"""
        with patch("app.api.whatsapp_webhooks.get_db", return_value=mock_db):
            with patch(
                "app.api.whatsapp_webhooks.repository_factory"
            ) as mock_repo_factory:
                # Setup mock users
                mock_users = [
                    Mock(
                        id=1,
                        username="testuser",
                        whatsapp_connected=True,
                        is_active=True,
                    )
                ]

                mock_user_repo = Mock()
                mock_user_repo.get_active_users_with_whatsapp.return_value = mock_users
                mock_repo_factory.get_user_repository.return_value = mock_user_repo

                # Make request to endpoint
                response = client.get("/webhook/whatsapp/active-users")

                # Verify response
                assert response.status_code == 200
                data = response.json()
                assert "active_users" in data
                assert len(data["active_users"]) == 1
                assert data["active_users"][0]["username"] == "testuser"

    def test_health_endpoint_integration(self, client):
        """Test the /health endpoint through the router"""
        response = client.get("/webhook/whatsapp/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "whatsapp-webhooks"

    def test_active_users_endpoint_with_real_user_data(self, client, mock_db):
        """Test with realistic user data structure"""
        with patch("app.api.whatsapp_webhooks.get_db", return_value=mock_db):
            with patch(
                "app.api.whatsapp_webhooks.repository_factory"
            ) as mock_repo_factory:
                # Create realistic user objects
                user1 = create_test_user(
                    id=1,
                    username="john_doe",
                    email="john@example.com",
                    whatsapp_connected=True,
                    is_active=True,
                )
                user2 = create_test_user(
                    id=2,
                    username="jane_smith",
                    email="jane@example.com",
                    whatsapp_connected=True,
                    is_active=False,  # Should still be included as it has WhatsApp connected
                )

                mock_user_repo = Mock()
                mock_user_repo.get_active_users_with_whatsapp.return_value = [
                    user1,
                    user2,
                ]
                mock_repo_factory.get_user_repository.return_value = mock_user_repo

                # Make request
                response = client.get("/webhook/whatsapp/active-users")

                # Verify response
                assert response.status_code == 200
                data = response.json()
                assert len(data["active_users"]) == 2

                # Check first user
                assert data["active_users"][0]["id"] == 1
                assert data["active_users"][0]["username"] == "john_doe"
                assert data["active_users"][0]["whatsapp_connected"] is True
                assert data["active_users"][0]["is_active"] is True

                # Check second user
                assert data["active_users"][1]["id"] == 2
                assert data["active_users"][1]["username"] == "jane_smith"
                assert data["active_users"][1]["whatsapp_connected"] is True
                assert data["active_users"][1]["is_active"] is False

    def test_endpoint_error_handling(self, client, mock_db):
        """Test proper error handling in endpoints"""
        with patch("app.api.whatsapp_webhooks.get_db", return_value=mock_db):
            with patch(
                "app.api.whatsapp_webhooks.repository_factory"
            ) as mock_repo_factory:
                # Setup repository to raise an exception
                mock_user_repo = Mock()
                mock_user_repo.get_active_users_with_whatsapp.side_effect = Exception(
                    "Test error"
                )
                mock_repo_factory.get_user_repository.return_value = mock_user_repo

                # Make request
                response = client.get("/webhook/whatsapp/active-users")

                # Verify error response
                assert response.status_code == 500
                data = response.json()
                assert "detail" in data
                assert "Test error" in data["detail"]
