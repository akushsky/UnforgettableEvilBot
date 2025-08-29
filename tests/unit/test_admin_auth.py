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

    def test_create_admin_session(self):
        """Test admin session creation"""
        mock_request = Mock()
        mock_request.client.host = "127.0.0.1"

        session_id = create_admin_session(mock_request)

        assert session_id.startswith("admin_127.0.0.1_")
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
