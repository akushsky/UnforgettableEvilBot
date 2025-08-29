from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from app.models.database import User


def create_test_user(
    id=None,
    username="testuser",
    email="test@example.com",
    whatsapp_connected=False,
    is_active=True,
    **kwargs,
):
    """Create a test user object for unit tests"""
    user = Mock(spec=User)
    user.id = id or 1
    user.username = username
    user.email = email
    user.whatsapp_connected = whatsapp_connected
    user.is_active = is_active

    # Add any additional attributes
    for key, value in kwargs.items():
        setattr(user, key, value)

    return user


@pytest.fixture
def mock_db():
    """Create a mock database session for unit tests"""
    return Mock(spec=Session)


@pytest.fixture
def sample_user():
    """Create a sample user for testing"""
    return create_test_user(
        id=1,
        username="testuser",
        email="test@example.com",
        whatsapp_connected=True,
        is_active=True,
    )


@pytest.fixture
def sample_users():
    """Create multiple sample users for testing"""
    return [
        create_test_user(
            id=1,
            username="user1",
            email="user1@example.com",
            whatsapp_connected=True,
            is_active=True,
        ),
        create_test_user(
            id=2,
            username="user2",
            email="user2@example.com",
            whatsapp_connected=True,
            is_active=False,
        ),
        create_test_user(
            id=3,
            username="user3",
            email="user3@example.com",
            whatsapp_connected=False,
            is_active=True,
        ),
    ]
