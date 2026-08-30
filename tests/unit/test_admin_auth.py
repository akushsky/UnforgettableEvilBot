from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException

from app.auth.admin_auth import (
    admin_sessions,
    create_admin_session,
    is_admin_authenticated,
    logout_admin,
    require_admin_auth,
    verify_admin_password,
)
from config.settings import settings


class TestAdminAuth:
    def setup_method(self):
        """Setup for each test"""
        # Clear admin sessions before each test
        from app.auth.admin_auth import admin_sessions

        admin_sessions.clear()

    def test_verify_admin_password_correct(self):
        """Test admin password verification with correct password"""
        with patch.object(settings, "ADMIN_PASSWORD", "test123"):
            assert verify_admin_password("test123") is True

    def test_verify_admin_password_incorrect(self):
        """Test admin password verification with incorrect password"""
        with patch.object(settings, "ADMIN_PASSWORD", "test123"):
            assert verify_admin_password("wrong") is False

    def test_verify_admin_password_prefix_is_rejected(self):
        """Test that a prefix of the password is not accepted"""
        with patch.object(settings, "ADMIN_PASSWORD", "test123"):
            assert verify_admin_password("test") is False
            assert verify_admin_password("test1234") is False
            assert verify_admin_password("") is False

    def test_verify_admin_password_not_configured(self):
        """Test that an unset admin password rejects every attempt"""
        with patch.object(settings, "ADMIN_PASSWORD", ""):
            assert verify_admin_password("") is False
            assert verify_admin_password("anything") is False

    def test_verify_admin_password_uses_constant_time_compare(self):
        """Test that password comparison goes through hmac.compare_digest"""
        with (
            patch.object(settings, "ADMIN_PASSWORD", "test123"),
            patch("app.auth.admin_auth.hmac.compare_digest") as mock_compare,
        ):
            mock_compare.return_value = True

            assert verify_admin_password("test123") is True
            mock_compare.assert_called_once_with(b"test123", b"test123")

    def test_verify_admin_password_non_ascii(self):
        """Test that non-ASCII passwords are compared without raising"""
        with patch.object(settings, "ADMIN_PASSWORD", "пароль"):
            assert verify_admin_password("пароль") is True
            assert verify_admin_password("parol") is False

    def test_create_admin_session(self):
        """Test admin session creation uses a random opaque identifier"""
        mock_request = Mock()
        mock_request.client.host = "127.0.0.1"

        session_id = create_admin_session(mock_request)

        assert session_id in admin_sessions
        # token_urlsafe(32) yields 43 url-safe characters
        assert len(session_id) >= 43
        assert "admin_" not in session_id
        assert "127.0.0.1" not in session_id

    def test_create_admin_session_ids_are_unique(self):
        """Test that repeated sessions from the same client are not guessable"""
        mock_request = Mock()
        mock_request.client.host = "127.0.0.1"

        session_ids = {create_admin_session(mock_request) for _ in range(10)}

        assert len(session_ids) == 10
        assert session_ids <= admin_sessions

    def test_create_admin_session_without_client(self):
        """Test session creation when the request has no client info"""
        mock_request = Mock()
        mock_request.client = None

        session_id = create_admin_session(mock_request)

        assert session_id in admin_sessions

    def test_is_admin_authenticated_with_valid_session(self):
        """Test admin authentication with valid session"""
        mock_request = Mock()
        mock_request.client.host = "127.0.0.1"

        session_id = create_admin_session(mock_request)
        mock_request.cookies = {"admin_session": session_id}

        assert is_admin_authenticated(mock_request) is True

    def test_is_admin_authenticated_with_invalid_session(self):
        """Test admin authentication with invalid session"""
        mock_request = Mock()
        mock_request.cookies = {"admin_session": "invalid_session"}

        assert is_admin_authenticated(mock_request) is False

    def test_is_admin_authenticated_without_session(self):
        """Test admin authentication without session"""
        mock_request = Mock()
        mock_request.cookies = {}

        assert is_admin_authenticated(mock_request) is False

    def test_require_admin_auth_authenticated(self):
        """Test require admin auth when authenticated"""
        mock_request = Mock()
        mock_request.client.host = "127.0.0.1"

        session_id = create_admin_session(mock_request)
        mock_request.cookies = {"admin_session": session_id}

        # Should not raise exception
        assert require_admin_auth(mock_request) is True

    def test_require_admin_auth_not_authenticated(self):
        """Test require admin auth when not authenticated"""
        mock_request = Mock()
        mock_request.cookies = {}
        mock_request.url.path = "/admin/users"
        mock_request.method = "GET"

        with pytest.raises(HTTPException) as exc_info:
            require_admin_auth(mock_request)

        assert exc_info.value.status_code == 303
        assert exc_info.value.headers["Location"] == "/admin/login"

    def test_require_admin_auth_login_attempt(self):
        """Test require admin auth allows login attempts"""
        mock_request = Mock()
        mock_request.cookies = {}
        mock_request.url.path = "/admin/login"
        mock_request.method = "POST"

        # Should not raise exception for login attempts
        assert require_admin_auth(mock_request) is True

    def test_logout_admin(self):
        """Test admin logout"""
        mock_request = Mock()
        mock_request.client.host = "127.0.0.1"

        # Create a session first
        session_id = create_admin_session(mock_request)
        mock_request.cookies = {"admin_session": session_id}

        # Verify session exists
        assert session_id in admin_sessions

        # Logout
        response = logout_admin(mock_request)

        # Verify session is removed
        assert session_id not in admin_sessions
        assert response.status_code == 303
        assert response.headers["location"] == "/admin/login"

    def test_logout_admin_no_session(self):
        """Test admin logout when no session exists"""
        mock_request = Mock()
        mock_request.cookies = {}

        # Should not raise exception
        response = logout_admin(mock_request)

        assert response.status_code == 303
        assert response.headers["location"] == "/admin/login"
