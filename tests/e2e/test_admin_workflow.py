"""E2E tests for full admin workflow through the API."""

from unittest.mock import patch

import pytest

from app.core.repository_factory import repository_factory
from app.models.database import User


@pytest.mark.e2e
def test_login_page_accessible(client):
    """GET /admin/login returns 200."""
    response = client.get("/admin/login")
    assert response.status_code == 200


@pytest.mark.e2e
def test_login_with_valid_credentials(client):
    """POST /admin/login with patched verify_admin_password redirects to /admin/users."""
    with patch("app.api.auth_routes.verify_admin_password", return_value=True):
        response = client.post(
            "/admin/login",
            data={"password": "any_password"},
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert "Location" in response.headers
    assert "/admin/users" in response.headers["Location"]


@pytest.mark.e2e
def test_login_with_invalid_credentials(client):
    """POST /admin/login with wrong password stays on login page."""
    with patch("app.api.auth_routes.verify_admin_password", return_value=False):
        response = client.post(
            "/admin/login",
            data={"password": "wrong_password"},
            follow_redirects=False,
        )
    assert response.status_code == 200
    assert "Invalid" in response.text or "error" in response.text.lower()


@pytest.mark.e2e
def test_users_page_requires_auth(client):
    """GET /admin/users without auth redirects to login."""
    response = client.get("/admin/users", follow_redirects=False)
    assert response.status_code == 303
    assert "Location" in response.headers
    assert "/admin/login" in response.headers["Location"]


@pytest.mark.e2e
def test_create_user_flow(authenticated_client, db_session):
    """Authenticated POST /admin/users/create creates user, verify in DB."""
    response = authenticated_client.post(
        "/admin/users/create",
        data={
            "username": "e2e_testuser",
            "email": "e2e_test@example.com",
            "password": "testpass123",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "/admin/users" in response.headers.get("Location", "")

    user = repository_factory.get_user_repository().get_by_username(
        db_session, "e2e_testuser"
    )
    assert user is not None
    assert user.email == "e2e_test@example.com"


@pytest.mark.e2e
def test_user_detail_page(authenticated_client, db_session):
    """Authenticated GET /admin/users/{id} returns user detail."""
    from app.auth.security import get_password_hash

    user = User(
        username="detail_testuser",
        email="detail_test@example.com",
        hashed_password=get_password_hash("testpass"),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    response = authenticated_client.get(f"/admin/users/{user.id}")
    assert response.status_code == 200
    assert "detail_testuser" in response.text


@pytest.mark.e2e
def test_suspend_and_resume_user(authenticated_client, db_session):
    """POST suspend then resume, verify state changes."""
    from app.auth.security import get_password_hash

    user = User(
        username="suspend_testuser",
        email="suspend_test@example.com",
        hashed_password=get_password_hash("testpass"),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    suspend_response = authenticated_client.post(f"/admin/users/{user.id}/suspend")
    assert suspend_response.status_code == 200
    db_session.refresh(user)
    assert user.is_active is False

    resume_response = authenticated_client.post(f"/admin/users/{user.id}/resume")
    assert resume_response.status_code == 200
    db_session.refresh(user)
    assert user.is_active is True


@pytest.mark.e2e
def test_logout_clears_session(authenticated_client):
    """GET /admin/logout clears session, can no longer access /admin/users."""
    response = authenticated_client.get("/admin/logout", follow_redirects=False)
    assert response.status_code == 303

    users_response = authenticated_client.get("/admin/users", follow_redirects=False)
    assert users_response.status_code == 303
    assert "/admin/login" in users_response.headers.get("Location", "")
