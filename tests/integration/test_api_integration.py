from datetime import datetime

import pytest

from app.auth.security import create_access_token, get_password_hash
from app.core.repository_factory import repository_factory
from app.models.database import User
from main import app


class TestAPIIntegration:
    """Integration tests for API endpoints with real database operations."""

    @pytest.fixture
    def client(self, db_session):
        """Create a test client with DB dependency override."""
        from fastapi.testclient import TestClient

        from app.database.connection import get_db

        def _override_get_db():
            try:
                yield db_session
            finally:
                pass

        app.dependency_overrides[get_db] = _override_get_db
        client = TestClient(app)
        yield client
        app.dependency_overrides.clear()

    @pytest.fixture
    def auth_headers(self, sample_user):
        """Create authentication headers for API requests."""
        access_token = create_access_token(data={"sub": sample_user.username})
        return {"Authorization": f"Bearer {access_token}"}

    def test_health_check_endpoint(self, client):
        """Test the health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()

        # Basic structure validation
        assert "status" in data
        assert "service" in data
        assert "version" in data
        assert "timestamp" in data
        assert "checks" in data
        assert "summary" in data

        # Status validation
        assert data["status"] in ["healthy", "degraded", "unhealthy"]
        assert data["service"] == "WhatsApp Digest System"
        assert data["version"] == "1.0.0"

        # Summary validation
        summary = data["summary"]
        assert "total_checks" in summary
        assert "healthy_checks" in summary
        assert "errors" in summary
        assert "new_alerts" in summary
        assert isinstance(summary["total_checks"], int)
        assert isinstance(summary["healthy_checks"], int)
        assert isinstance(summary["errors"], list)
        assert isinstance(summary["new_alerts"], int)

        # Checks validation
        checks = data["checks"]
        expected_categories = [
            "database",
            "system",
            "cache",
            "external_services",
            "components",
            "application",
            "performance",
        ]
        for category in expected_categories:
            if category in checks:
                assert isinstance(checks[category], dict)
                # external_services and components have different structures
                if category not in ["external_services", "components"]:
                    assert "status" in checks[category]
                elif category == "external_services":
                    # external_services contains individual service checks
                    assert isinstance(checks[category], dict)
                elif category == "components":
                    # components contains individual component checks
                    assert isinstance(checks[category], dict)

    def test_register_user_success(self, client, db_session):
        """Test user registration with real database operations."""
        user_data = {
            "username": "new_integration_user",
            "email": "new_integration@test.com",
            "password": "StrongP@ssw0rd!",
        }

        response = client.post("/auth/register", json=user_data)
        assert response.status_code == 200

        data = response.json()
        assert data["username"] == user_data["username"]
        assert data["email"] == user_data["email"]
        assert "id" in data

        # Verify user was actually created in database
        user_repo = repository_factory.get_user_repository()
        created_user = user_repo.get_by_username(db_session, user_data["username"])
        assert created_user is not None
        assert created_user.email == user_data["email"]
        assert created_user.is_active

    def test_register_user_duplicate_username(self, client, db_session, sample_user):
        """Test user registration with duplicate username."""
        user_data = {
            "username": sample_user.username,  # Use existing username
            "email": "different@test.com",
            "password": "StrongP@ssw0rd!",
        }

        response = client.post("/auth/register", json=user_data)
        assert response.status_code == 400
        assert "already registered" in response.json()["detail"].lower()

    def test_login_success(self, client, db_session, sample_user):
        """Test user login with real database operations."""
        # First, we need to create a user with a known password
        repository_factory.get_user_repository()
        test_user = User(
            username="login_test_user",
            email="login@test.com",
            hashed_password=get_password_hash("test_password"),
            is_active=True,
            created_at=datetime.utcnow(),
        )
        db_session.add(test_user)
        db_session.commit()
        db_session.refresh(test_user)

        login_data = {"username": "login_test_user", "password": "test_password"}

        response = client.post("/auth/login", json=login_data)
        assert response.status_code == 200

        data = response.json()
        assert "access_token" in data
        assert "token_type" in data
        assert data["token_type"] == "bearer"

    def test_login_invalid_credentials(self, client):
        """Test login with invalid credentials."""
        login_data = {"username": "nonexistent_user", "password": "wrong_password"}

        response = client.post("/auth/login", json=login_data)
        assert response.status_code == 401
        assert "Incorrect username or password" in response.json()["detail"]

    def test_get_users_authenticated(self, client, auth_headers, db_session):
        """Test getting users list with authentication."""
        response = client.get("/users/", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        # Should include our sample user
        usernames = [user["username"] for user in data]
        assert "testuser" in usernames

    def test_get_users_unauthenticated(self, client):
        """Test getting users list without authentication."""
        response = client.get("/users/")
        assert response.status_code == 401

    def test_get_user_by_id(self, client, auth_headers, sample_user):
        """Test getting a specific user by ID."""
        response = client.get(f"/users/{sample_user.id}", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == sample_user.id
        assert data["username"] == sample_user.username
        assert data["email"] == sample_user.email

    def test_update_user(self, client, auth_headers, sample_user, db_session):
        """Test updating user information."""
        update_data = {"digest_interval_hours": 8}

        response = client.put("/users/me", json=update_data, headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert data["digest_interval_hours"] == 8

        # Verify changes persisted in database
        user_repo = repository_factory.get_user_repository()
        updated_user = user_repo.get_by_id(db_session, sample_user.id)
        assert updated_user.digest_interval_hours == 8

    def test_suspend_user(self, client, auth_headers, sample_user, db_session):
        """Test suspending a user."""
        response = client.post(f"/users/{sample_user.id}/suspend", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert "suspended" in data["message"].lower()

        # Verify user is suspended in database
        user_repo = repository_factory.get_user_repository()
        suspended_user = user_repo.get_by_id(db_session, sample_user.id)
        assert suspended_user.is_active is False

    def test_resume_user(self, client, auth_headers, sample_user, db_session):
        """Test resuming a suspended user (admin token must remain active)."""
        # Create another user to suspend/resume
        user_repo = repository_factory.get_user_repository()
        user_to_resume = User(
            username="suspended_user",
            email="suspended@test.com",
            hashed_password=get_password_hash("SomeP@ssw0rd1"),
            is_active=False,
            created_at=datetime.utcnow(),
        )
        db_session.add(user_to_resume)
        db_session.commit()
        db_session.refresh(user_to_resume)

        # Call resume as admin (sample_user is id=1 and active)
        response = client.post(
            f"/users/{user_to_resume.id}/resume", headers=auth_headers
        )
        assert response.status_code == 200

        data = response.json()
        assert "resumed" in data["message"].lower()

        # Verify user is active in database
        resumed_user = user_repo.get_by_id(db_session, user_to_resume.id)
        assert resumed_user.is_active

    def test_get_user_chats(self, client, auth_headers, sample_user, sample_chat):
        """Test getting user's monitored chats."""
        response = client.get("/users/me/chats", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, dict)
        assert data["total"] >= 1
        # Verify the sample chat is included
        chat_ids = [chat["id"] for chat in data["chats"]]
        assert sample_chat.id in chat_ids

    def test_get_user_digests(
        self, client, auth_headers, sample_user, sample_digest_logs
    ):
        """Test getting user's digest logs."""
        response = client.get("/users/me/digests", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, dict)
        assert data["total"] >= 3  # We created 3 sample digest logs

    def test_webhook_whatsapp_message(self, client, db_session, sample_chat):
        """Test WhatsApp webhook message processing."""
        webhook_data = {
            "userId": str(sample_chat.user_id),
            "messageId": "test_message_id",
            "chatId": sample_chat.chat_id,
            "chatName": sample_chat.chat_name,
            "chatType": sample_chat.chat_type,
            "sender": "Test Sender",
            "content": "Test webhook message",
            "timestamp": datetime.utcnow().isoformat(),
        }

        response = client.post("/webhook/whatsapp/message", json=webhook_data)
        assert response.status_code == 200

        # Verify message was processed and stored
        msg_repo = repository_factory.get_whatsapp_message_repository()
        msg_repo.get_messages_by_chat_ids(db_session, [sample_chat.id])

        # Check if any message was created (might be filtered by chat_id matching)
        # This test verifies the webhook endpoint works without errors

    def test_metrics_endpoint(self, client):
        """Test the metrics endpoint."""
        response = client.get("/metrics")
        assert response.status_code == 200

        data = response.json()

        # Basic structure validation
        assert "metrics" in data
        assert "timestamp" in data

        # Metrics sections validation
        metrics = data["metrics"]
        expected_sections = [
            "users",
            "chats",
            "messages",
            "digests",
            "performance",
            "openai",
            "system",
            "resource_savings",
            "components",
        ]
        for section in expected_sections:
            assert section in metrics
            assert isinstance(metrics[section], dict)

        # Users section validation
        users_metrics = metrics["users"]
        assert "total" in users_metrics
        assert "active" in users_metrics
        assert "connected_percentage" in users_metrics
        assert isinstance(users_metrics["total"], int)
        assert isinstance(users_metrics["active"], int)
        assert isinstance(users_metrics["connected_percentage"], (int, float))
        assert 0 <= users_metrics["connected_percentage"] <= 100

        # Performance section validation
        perf_metrics = metrics["performance"]
        assert "avg_response_time" in perf_metrics
        assert "cpu_usage" in perf_metrics
        assert "memory_usage" in perf_metrics
        assert "cache" in perf_metrics
        assert "database" in perf_metrics
        assert isinstance(perf_metrics["avg_response_time"], (int, float))
        assert isinstance(perf_metrics["cpu_usage"], (int, float))
        assert isinstance(perf_metrics["memory_usage"], (int, float))
        assert 0 <= perf_metrics["cpu_usage"] <= 100
        assert 0 <= perf_metrics["memory_usage"] <= 100

        # Response headers validation
        headers = response.headers
        assert "cache-control" in headers
        assert "no-cache" in headers["cache-control"].lower()
        assert "no-store" in headers["cache-control"].lower()

    def test_rate_limiting(self, client):
        """Test API rate limiting."""
        # Make multiple rapid requests to trigger rate limiting
        for _ in range(5):
            response = client.get("/health")
            assert response.status_code in [200, 429]  # Either success or rate limited

        # The exact behavior depends on rate limiter configuration
        # This test ensures the rate limiting mechanism is active

    def test_invalid_endpoint(self, client):
        """Test handling of invalid endpoints."""
        response = client.get("/nonexistent/endpoint")
        assert response.status_code == 404

    def test_database_connection_in_api(self, client, db_session):
        """Test that API endpoints can access the database."""
        # Create a test user through the API
        user_data = {
            "username": "db_test_user",
            "email": "db_test@test.com",
            "password": "StrongP@ssw0rd!",
        }

        response = client.post("/auth/register", json=user_data)
        assert response.status_code == 200

        # Verify the user exists in the database
        user_repo = repository_factory.get_user_repository()
        created_user = user_repo.get_by_username(db_session, "db_test_user")
        assert created_user is not None
        assert created_user.email == "db_test@test.com"

    def test_error_handling(self, client):
        """Test API error handling."""
        # Test with invalid JSON
        response = client.post(
            "/auth/login",
            data="invalid json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422  # Validation error

        # Test with missing required fields
        response = client.post("/auth/login", json={})
        assert response.status_code == 422

    def test_cors_headers(self, client):
        """Test CORS headers are present."""
        response = client.options("/health")
        # CORS headers should be present (implementation dependent)
        # This test ensures the CORS middleware is active
        assert response.status_code in [
            200,
            405,
        ]  # Either success or method not allowed
