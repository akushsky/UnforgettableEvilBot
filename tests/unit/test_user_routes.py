"""Unit tests for user routes in app/api/user_routes.py."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database.connection import get_db
from main import app


@pytest.fixture
def mock_db():
    """Create a mock database session for unit tests."""
    db = Mock(spec=Session)
    db.commit = Mock()
    db.rollback = Mock()
    db.add = Mock()
    db.refresh = Mock()
    return db


@pytest.fixture
def client(mock_db):
    """Create TestClient with get_db override yielding mock session."""

    def _override_get_db():
        try:
            yield mock_db
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@patch("app.api.user_routes.get_telegram_service")
@patch("app.api.user_routes.repository_factory")
@patch("app.api.user_routes.require_admin_auth")
def test_users_page_returns_html(mock_auth, mock_repo_factory, mock_telegram, client):
    """Test GET /admin/users returns HTML user list page."""
    mock_auth.return_value = True
    mock_user_repo = Mock()
    mock_user_repo.get_all.return_value = []
    mock_repo_factory.get_user_repository.return_value = mock_user_repo

    response = client.get("/admin/users")

    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    mock_auth.assert_called_once()
    mock_user_repo.get_all.assert_called_once()


@patch("app.api.user_routes.repository_factory")
@patch("app.api.user_routes.require_admin_auth")
def test_create_user_success(mock_auth, mock_repo_factory, client, mock_db):
    """Test POST /admin/users/create creates new user successfully."""
    mock_auth.return_value = True
    mock_user_repo = Mock()
    mock_user_repo.get_by_username.return_value = None
    mock_user_repo.get_by_email.return_value = None
    mock_repo_factory.get_user_repository.return_value = mock_user_repo

    with (
        patch("app.api.user_routes.get_password_hash", return_value="hashed"),
        patch("app.api.user_routes.create_default_user_settings"),
    ):
        new_user = Mock()
        new_user.id = 1
        mock_db.add.side_effect = lambda u: setattr(u, "id", 1)

        response = client.post(
            "/admin/users/create",
            data={
                "username": "newuser",
                "email": "new@example.com",
                "password": "secret123",
            },
        )

    assert response.status_code == 303
    assert response.headers.get("location") == "/admin/users"
    mock_user_repo.get_by_username.assert_called_once_with(mock_db, "newuser")
    mock_db.add.assert_called()
    mock_db.commit.assert_called()


@patch("app.api.user_routes.repository_factory")
@patch("app.api.user_routes.require_admin_auth")
def test_create_user_duplicate_returns_400(
    mock_auth, mock_repo_factory, client, mock_db
):
    """Test POST /admin/users/create returns 400 when user already exists."""
    mock_auth.return_value = True
    mock_user_repo = Mock()
    existing_user = Mock()
    mock_user_repo.get_by_username.return_value = existing_user
    mock_repo_factory.get_user_repository.return_value = mock_user_repo

    response = client.post(
        "/admin/users/create",
        data={
            "username": "existing",
            "email": "existing@example.com",
            "password": "secret123",
        },
    )

    assert response.status_code == 400
    mock_user_repo.get_by_username.assert_called_once()


@patch("app.api.user_routes.repository_factory")
@patch("app.api.user_routes.require_admin_auth")
def test_user_detail_page(mock_auth, mock_repo_factory, client):
    """Test GET /admin/users/{user_id} returns user detail page."""
    mock_auth.return_value = True
    mock_user = Mock()
    mock_user.id = 1
    mock_user.username = "testuser"

    mock_user_repo = Mock()
    mock_user_repo.get_by_id_or_404.return_value = mock_user
    mock_repo_factory.get_user_repository.return_value = mock_user_repo

    mock_chat_repo = Mock()
    mock_chat_repo.get_active_chats_for_user.return_value = []
    mock_repo_factory.get_monitored_chat_repository.return_value = mock_chat_repo

    mock_digest_repo = Mock()
    mock_digest_repo.get_last_digest_for_user.return_value = None
    mock_digest_repo.get_digests_for_period.return_value = []
    mock_repo_factory.get_digest_log_repository.return_value = mock_digest_repo

    mock_pref_repo = Mock()
    mock_pref_repo.get_active_preferences.return_value = []
    mock_repo_factory.get_digest_preference_repository.return_value = mock_pref_repo

    mock_phone_repo = Mock()
    mock_phone_repo.get_active_phones_for_user.return_value = []
    mock_repo_factory.get_whatsapp_phone_repository.return_value = mock_phone_repo

    response = client.get("/admin/users/1")

    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    mock_user_repo.get_by_id_or_404.assert_called_once()


@patch("app.api.user_routes.repository_factory")
@patch("app.api.user_routes.require_admin_auth")
def test_user_detail_not_found_returns_404(mock_auth, mock_repo_factory, client):
    """Test GET /admin/users/{user_id} returns 404 when user not found."""
    mock_auth.return_value = True
    mock_user_repo = Mock()
    from fastapi import HTTPException

    mock_user_repo.get_by_id_or_404.side_effect = HTTPException(
        status_code=404, detail="User not found"
    )
    mock_repo_factory.get_user_repository.return_value = mock_user_repo

    response = client.get("/admin/users/999")

    assert response.status_code == 404


@patch("app.api.user_routes.repository_factory")
@patch("app.api.user_routes.require_admin_auth")
def test_suspend_user_success(mock_auth, mock_repo_factory, client):
    """Test POST /admin/users/{user_id}/suspend suspends user successfully."""
    mock_auth.return_value = True
    mock_user = Mock()
    mock_user.id = 1
    mock_user.username = "testuser"
    mock_user.is_active = True
    mock_user.updated_at = None

    mock_user_repo = Mock()
    mock_user_repo.get_by_id_or_404.return_value = mock_user
    mock_repo_factory.get_user_repository.return_value = mock_user_repo

    with patch("app.api.user_routes.httpx") as mock_httpx:
        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(
            return_value=mock_client
        )
        mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "app.api.user_routes.resource_savings_service",
            Mock(record_suspension_savings=Mock(return_value={})),
        ):
            response = client.post("/admin/users/1/suspend")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "suspended" in data["message"].lower()
    assert mock_user.is_active is False


@patch("app.api.user_routes.repository_factory")
@patch("app.api.user_routes.require_admin_auth")
def test_resume_user_success(mock_auth, mock_repo_factory, client):
    """Test POST /admin/users/{user_id}/resume resumes user successfully."""
    mock_auth.return_value = True
    mock_user = Mock()
    mock_user.id = 1
    mock_user.username = "testuser"
    mock_user.is_active = False

    mock_user_repo = Mock()
    mock_user_repo.get_by_id_or_404.return_value = mock_user
    mock_repo_factory.get_user_repository.return_value = mock_user_repo

    with patch("app.api.user_routes.httpx") as mock_httpx:
        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(
            return_value=mock_client
        )
        mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=None)

        response = client.post("/admin/users/1/resume")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert mock_user.is_active is True


@patch("app.api.user_routes.get_telegram_service")
@patch("app.api.user_routes.repository_factory")
@patch("app.api.user_routes.require_admin_auth")
def test_test_telegram_connection_success(
    mock_auth, mock_repo_factory, mock_telegram, client
):
    """Test POST /admin/users/{user_id}/telegram/test succeeds when connection works."""
    mock_auth.return_value = True
    mock_user = Mock()
    mock_user.id = 1
    mock_user.is_active = True
    mock_user.telegram_channel_id = "-100123456"

    mock_user_repo = Mock()
    mock_user_repo.get_by_id_or_404.return_value = mock_user
    mock_repo_factory.get_user_repository.return_value = mock_user_repo

    mock_telegram_svc = AsyncMock()
    mock_telegram_svc.verify_channel_access = AsyncMock(
        return_value={
            "success": True,
            "chat_info": {"title": "Test"},
            "bot_permissions": {},
        }
    )
    mock_telegram_svc.test_connection = AsyncMock(return_value=True)
    mock_telegram.return_value = mock_telegram_svc

    response = client.post("/admin/users/1/telegram/test")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "channel_info" in data


@patch("app.api.user_routes.get_telegram_service")
@patch("app.api.user_routes.repository_factory")
@patch("app.api.user_routes.require_admin_auth")
def test_test_telegram_connection_failure(
    mock_auth, mock_repo_factory, mock_telegram, client
):
    """Test POST /admin/users/{user_id}/telegram/test returns error on failure."""
    mock_auth.return_value = True
    mock_user = Mock()
    mock_user.id = 1
    mock_user.is_active = True
    mock_user.telegram_channel_id = "-100123456"

    mock_user_repo = Mock()
    mock_user_repo.get_by_id_or_404.return_value = mock_user
    mock_repo_factory.get_user_repository.return_value = mock_user_repo

    mock_telegram_svc = AsyncMock()
    mock_telegram_svc.verify_channel_access = AsyncMock(
        return_value={"success": False, "error": "No access", "suggestions": []}
    )
    mock_telegram.return_value = mock_telegram_svc

    response = client.post("/admin/users/1/telegram/test")

    assert response.status_code == 400
    data = response.json()
    assert data["status"] == "error"


@patch("app.api.user_routes.repository_factory")
@patch("app.api.user_routes.require_admin_auth")
def test_create_user_settings(mock_auth, mock_repo_factory, client):
    """Test POST /admin/users/{user_id}/settings/create creates default settings."""
    mock_auth.return_value = True
    mock_user = Mock()
    mock_user.id = 1

    mock_user_repo = Mock()
    mock_user_repo.get_by_id.return_value = mock_user
    mock_repo_factory.get_user_repository.return_value = mock_user_repo

    mock_settings_repo = Mock()
    mock_settings_repo.get_by_user_id.return_value = None
    mock_repo_factory.get_user_settings_repository.return_value = mock_settings_repo

    response = client.post("/admin/users/1/settings/create")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "settings" in data
