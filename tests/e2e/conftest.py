"""
E2E test configuration.

Uses FastAPI TestClient against the real app with a real database (PostgreSQL in CI).
External services (OpenAI, Telegram, WhatsApp) are mocked.
"""

import asyncio
import uuid
from collections.abc import Generator
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.connection import get_db
from app.models.database import (
    Base,
    DigestLog,
    DigestPreference,
    MonitoredChat,
    OpenAIMetrics,
    ResourceSavings,
    SystemLog,
    User,
    WhatsAppMessage,
    WhatsAppPhone,
)
from config.settings import settings
from main import app


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def test_engine():
    """Create a test database engine using PostgreSQL."""
    engine = create_engine(
        settings.DATABASE_URL,
        poolclass=StaticPool,
        echo=False,
    )
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture(scope="session")
def test_session_factory(test_engine):
    """Create a test session factory."""
    Base.metadata.create_all(bind=test_engine)
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=test_engine
    )
    return TestingSessionLocal


@pytest.fixture
def db_session(test_session_factory) -> Generator[Session, None, None]:
    """Create a fresh database session for each test with cleanup."""
    session = test_session_factory()
    try:
        yield session
    finally:
        try:
            session.execute(text("SET session_replication_role = replica;"))
            session.query(OpenAIMetrics).delete()
            session.query(ResourceSavings).delete()
            session.query(SystemLog).delete()
            session.query(DigestLog).delete()
            session.query(WhatsAppMessage).delete()
            session.query(MonitoredChat).delete()
            session.query(WhatsAppPhone).delete()
            session.query(User).delete()
            session.execute(text("SET session_replication_role = DEFAULT;"))
            session.commit()
        except Exception:
            session.rollback()
            try:
                session.query(OpenAIMetrics).delete()
                session.query(ResourceSavings).delete()
                session.query(SystemLog).delete()
                session.query(DigestLog).delete()
                session.query(WhatsAppMessage).delete()
                session.query(MonitoredChat).delete()
                session.query(WhatsAppPhone).delete()
                session.query(User).delete()
                session.commit()
            except Exception:
                session.rollback()
        finally:
            session.close()


@pytest.fixture
def client(db_session) -> Generator[TestClient, None, None]:
    """Create a test client with DB dependency override."""

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app, base_url="https://testserver")
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def authenticated_client(
    client: TestClient, db_session
) -> Generator[TestClient, None, None]:
    """Client with admin session cookie set via patched verify_admin_password."""
    with patch("app.api.auth_routes.verify_admin_password", return_value=True):
        response = client.post(
            "/admin/login",
            data={"password": "test_admin_password"},
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert "Location" in response.headers
    assert "/admin/users" in response.headers["Location"]
    cookies = response.cookies
    client.cookies = cookies
    yield client


@pytest.fixture
def mock_openai_service():
    """Mock OpenAI service for e2e tests."""
    mock = AsyncMock()
    mock.analyze_message_importance = AsyncMock(return_value=2)
    mock.translate_to_russian = AsyncMock(return_value="Translated text")
    mock.create_digest_by_chats = AsyncMock(return_value="Mock digest content")
    with patch("app.dependencies.get_openai_service", lambda: mock):
        yield mock


@pytest.fixture
def mock_telegram_service():
    """Mock Telegram service for e2e tests."""
    mock = AsyncMock()
    mock.send_notification = AsyncMock(return_value=None)
    mock.send_digest = AsyncMock(return_value=True)
    mock.check_bot_health = AsyncMock(return_value=True)
    mock.verify_channel_access = AsyncMock(
        return_value={"success": True, "chat_info": {}, "bot_permissions": {}}
    )
    mock.test_connection = AsyncMock(return_value=True)
    mock.get_channel_statistics = AsyncMock(
        return_value={"success": True, "statistics": {}}
    )
    mock.create_channel_for_user = AsyncMock(
        return_value={"instructions": "Setup guide", "bot_username": "test_bot"}
    )
    with patch("app.dependencies.get_telegram_service", lambda: mock):
        yield mock


@pytest.fixture
def mock_whatsapp_service():
    """Mock WhatsApp service for e2e tests."""
    mock = AsyncMock()
    mock.get_chats = AsyncMock(return_value=[])
    with patch("app.dependencies.get_whatsapp_service", lambda: mock):
        yield mock
