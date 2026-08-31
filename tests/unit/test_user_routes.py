"""Unit tests for user routes in app/api/user_routes.py."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.admin_auth import get_admin_auth_dependency
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
    app.dependency_overrides[get_admin_auth_dependency] = lambda: True
    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client(mock_db):
    """Create TestClient without an admin session."""

    def _override_get_db():
        try:
            yield mock_db
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/admin/users"),
        ("get", "/admin/users/1"),
        ("post", "/admin/users/create"),
        ("post", "/admin/users/1/suspend"),
        ("post", "/admin/users/1/resume"),
    ],
)
def test_admin_routes_require_authentication(method, path, unauthenticated_client):
    """Test that admin user routes redirect to login without a session."""
    response = getattr(unauthenticated_client, method)(path)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


@patch("app.api.user_routes.repository_factory")
def test_users_page_returns_html(mock_repo_factory, client):
    """Test GET /admin/users returns HTML user list page."""
    mock_user_repo = Mock()
    mock_user_repo.get_all.return_value = []
    mock_repo_factory.get_user_repository.return_value = mock_user_repo

    response = client.get("/admin/users")

    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    mock_user_repo.get_all.assert_called_once()


@patch("app.api.user_routes.repository_factory")
def test_create_user_success(mock_repo_factory, client, mock_db):
    """Test POST /admin/users/create creates new user successfully."""
    mock_user_repo = Mock()
    mock_user_repo.get_by_username.return_value = None
    mock_user_repo.get_by_email.return_value = None
    mock_repo_factory.get_user_repository.return_value = mock_user_repo

    with (
        patch("app.api.user_routes.get_password_hash", return_value="hashed"),
        patch("app.core.user_utils.create_default_user_settings"),
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
def test_create_user_duplicate_returns_400(mock_repo_factory, client, mock_db):
    """Test POST /admin/users/create returns 400 when user already exists."""
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


@patch("app.api.user_routes.can_generate_immediate_digest", return_value=False)
@patch("app.api.user_routes.repository_factory")
def test_user_detail_page(mock_repo_factory, mock_can_generate, client):
    """Test GET /admin/users/{user_id} returns user detail page."""
    mock_user = Mock()
    mock_user.id = 1
    mock_user.username = "testuser"
    mock_user.is_active = True
    mock_user.whatsapp_connected = False
    mock_user.telegram_channel_id = None
    mock_user.digest_preference = None

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
    mock_can_generate.assert_called_once()
    html = response.text
    assert 'id="generate-digest-btn"' in html
    assert "disabled" in html
    assert "WhatsApp не подключен." in html


@patch("app.api.user_routes.can_generate_immediate_digest", return_value=False)
@patch("app.api.user_routes.repository_factory")
def test_user_detail_suspended_shows_paused_reason(
    mock_repo_factory, mock_can_generate, client
):
    """Suspended users should see the paused reason, not a missing-channel fallback."""
    mock_user = Mock()
    mock_user.id = 1
    mock_user.username = "paused"
    mock_user.is_active = False
    mock_user.whatsapp_connected = True
    mock_user.telegram_channel_id = "-100123"
    mock_user.digest_preference = None

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
    assert "Пользователь приостановлен." in response.text
    assert "Нет канала доставки дайджеста." not in response.text


@patch("app.api.user_routes.repository_factory")
def test_user_detail_not_found_returns_404(mock_repo_factory, client):
    """Test GET /admin/users/{user_id} returns 404 when user not found."""
    mock_user_repo = Mock()
    from fastapi import HTTPException

    mock_user_repo.get_by_id_or_404.side_effect = HTTPException(
        status_code=404, detail="User not found"
    )
    mock_repo_factory.get_user_repository.return_value = mock_user_repo

    response = client.get("/admin/users/999")

    assert response.status_code == 404


@patch("app.api.user_routes.repository_factory")
def test_suspend_user_success(mock_repo_factory, client):
    """Test POST /admin/users/{user_id}/suspend suspends user successfully."""
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

        response = client.post("/admin/users/1/suspend")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "suspended" in data["message"].lower()
    assert mock_user.is_active is False


@patch("app.api.user_routes.repository_factory")
def test_resume_user_success(mock_repo_factory, client):
    """Test POST /admin/users/{user_id}/resume resumes user successfully."""
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
