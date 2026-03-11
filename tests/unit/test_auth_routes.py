"""Unit tests for auth routes in app/api/auth_routes.py."""

from unittest.mock import patch

import pytest
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    """Create TestClient for the main app."""
    return TestClient(app)


class TestAdminLoginPage:
    """Tests for GET /admin/login."""

    @patch("app.api.auth_routes.get_admin_login_page")
    def test_login_page_returns_html(self, mock_get_login_page, client):
        """Test that login page returns HTML content."""
        mock_get_login_page.return_value = HTMLResponse(
            content="<html><body>Login</body></html>"
        )

        response = client.get("/admin/login")

        assert response.status_code == 200
        assert "Login" in response.text
        mock_get_login_page.assert_called_once()


class TestAdminLoginPost:
    """Tests for POST /admin/login."""

    @patch("app.api.auth_routes.create_admin_session")
    @patch("app.api.auth_routes.verify_admin_password")
    def test_login_success_sets_cookie_and_redirects(
        self, mock_verify_password, mock_create_session, client
    ):
        """Test successful login sets cookie and redirects to /admin/users."""
        mock_verify_password.return_value = True
        mock_create_session.return_value = "session-123"

        response = client.post(
            "/admin/login",
            data={"password": "correct-password"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/admin/users"
        assert "admin_session" in response.headers.get("set-cookie", "")
        mock_verify_password.assert_called_once_with("correct-password")
        mock_create_session.assert_called_once()

    @patch("app.api.auth_routes.get_admin_login_page_with_error")
    @patch("app.api.auth_routes.verify_admin_password")
    def test_login_failure_returns_error(
        self, mock_verify_password, mock_get_login_with_error, client
    ):
        """Test failed login returns login page with error."""
        mock_verify_password.return_value = False
        mock_get_login_with_error.return_value = (
            "<html><body>Invalid password</body></html>"
        )

        response = client.post(
            "/admin/login",
            data={"password": "wrong-password"},
        )

        assert response.status_code == 200
        assert "Invalid password" in response.text
        mock_verify_password.assert_called_once_with("wrong-password")
        mock_get_login_with_error.assert_called_once()
        assert mock_get_login_with_error.call_args[0][1] == "Invalid admin password"


class TestAdminLogout:
    """Tests for GET /admin/logout."""

    @patch("app.api.auth_routes.logout_admin")
    def test_logout_clears_session(self, mock_logout, client):
        """Test logout redirects to login page and clears session."""
        from fastapi.responses import RedirectResponse

        mock_response = RedirectResponse(url="/admin/login", status_code=303)
        mock_response.delete_cookie = lambda x: None
        mock_logout.return_value = mock_response

        response = client.get("/admin/logout", follow_redirects=False)

        assert response.status_code == 303
        assert response.headers["location"] == "/admin/login"
        mock_logout.assert_called_once()
