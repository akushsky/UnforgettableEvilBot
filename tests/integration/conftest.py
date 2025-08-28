import asyncio
import uuid
from datetime import datetime, timedelta
from typing import AsyncGenerator, Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.connection import get_db
from app.models.database import (
    Base,
    DigestLog,
    MonitoredChat,
    OpenAIMetrics,
    ResourceSavings,
    SystemLog,
    User,
    WhatsAppMessage,
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
    # Create all tables immediately
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture(scope="session")
def test_session_factory(test_engine):
    """Create a test session factory."""
    # Create all tables
    Base.metadata.create_all(bind=test_engine)

    # Create session factory
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=test_engine
    )
    return TestingSessionLocal


@pytest.fixture
def db_session(test_session_factory) -> Generator[Session, None, None]:
    """Create a fresh database session for each test."""
    session = test_session_factory()
    try:
        yield session
    finally:
        # Clean up all data after each test - more thorough cleanup
        try:
            # Disable foreign key checks temporarily for cleanup
            session.execute(text("SET session_replication_role = replica;"))

            # Delete all data in reverse dependency order
            session.query(OpenAIMetrics).delete()
            session.query(ResourceSavings).delete()
            session.query(SystemLog).delete()
            session.query(DigestLog).delete()
            session.query(WhatsAppMessage).delete()
            session.query(MonitoredChat).delete()
            session.query(User).delete()

            # Re-enable foreign key checks
            session.execute(text("SET session_replication_role = DEFAULT;"))
            session.commit()
        except Exception:
            session.rollback()
            # Fallback cleanup if the above fails
            try:
                session.query(OpenAIMetrics).delete()
                session.query(ResourceSavings).delete()
                session.query(SystemLog).delete()
                session.query(DigestLog).delete()
                session.query(WhatsAppMessage).delete()
                session.query(MonitoredChat).delete()
                session.query(User).delete()
                session.commit()
            except Exception:
                session.rollback()
        finally:
            session.close()


@pytest.fixture
async def async_db_session(db_session) -> AsyncGenerator[Session, None]:
    """Async wrapper for database session."""
    yield db_session


@pytest.fixture
def admin_user(db_session) -> User:
    """Create an admin user for testing."""
    # Generate unique admin user for each test
    unique_id = str(uuid.uuid4())[:8]
    user = User(
        username=f"admin_user_{unique_id}",
        email=f"admin_{unique_id}@example.com",
        hashed_password="hashed_password_123",
        digest_interval_hours=4,
        whatsapp_auto_reconnect=True,
        is_active=True,
        whatsapp_connected=True,
        telegram_channel_id=f"admin_channel_{unique_id}",
        created_at=datetime.utcnow(),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def sample_user(db_session) -> User:
    """Create a sample user for testing."""
    # Generate unique username and email for each test
    unique_id = str(uuid.uuid4())[:8]
    user = User(
        username=f"testuser_{unique_id}",
        email=f"test_{unique_id}@example.com",
        hashed_password="hashed_password_123",
        digest_interval_hours=4,
        whatsapp_auto_reconnect=True,
        is_active=True,
        whatsapp_connected=True,
        telegram_channel_id=f"test_channel_{unique_id}",
        created_at=datetime.utcnow(),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def sample_chat(db_session, sample_user) -> MonitoredChat:
    """Create a sample monitored chat for testing."""
    unique_id = str(uuid.uuid4())[:8]
    chat = MonitoredChat(
        user_id=sample_user.id,
        chat_name=f"Test Chat {unique_id}",
        chat_id=f"test_chat_{unique_id}",
        chat_type="group",  # Required field
        is_active=True,
        created_at=datetime.utcnow(),
    )
    db_session.add(chat)
    db_session.commit()
    db_session.refresh(chat)
    return chat


@pytest.fixture
def sample_messages(db_session, sample_chat) -> list[WhatsAppMessage]:
    """Create sample WhatsApp messages for testing."""
    # Generate unique message IDs for each test
    unique_id = str(uuid.uuid4())[:8]
    messages = []
    for i in range(5):
        message = WhatsAppMessage(
            chat_id=sample_chat.id,
            message_id=f"msg_{unique_id}_{i}",
            sender="test_sender",
            content=f"Test message {i}",
            timestamp=datetime.utcnow() - timedelta(hours=i),
            importance_score=i + 1,
            is_processed=False,
            created_at=datetime.utcnow() - timedelta(hours=i),
        )
        messages.append(message)

    db_session.add_all(messages)
    db_session.commit()

    for message in messages:
        db_session.refresh(message)

    return messages


@pytest.fixture
def sample_digest_logs(db_session, sample_user) -> list[DigestLog]:
    """Create sample digest logs for testing."""
    logs = []
    for i in range(3):
        log = DigestLog(
            user_id=sample_user.id,
            digest_content=f"Test digest {i}",
            message_count=i + 1,
            created_at=datetime.utcnow() - timedelta(days=i),
        )
        logs.append(log)

    db_session.add_all(logs)
    db_session.commit()

    for log in logs:
        db_session.refresh(log)

    return logs


@pytest.fixture
def sample_system_logs(db_session) -> list[SystemLog]:
    """Create sample system logs for testing."""
    logs = []
    for i in range(5):
        log = SystemLog(
            user_id=None,
            event_type="test_event",
            event_data=f"Test system log {i}",
            severity="info",
            created_at=datetime.utcnow() - timedelta(hours=i),
        )
        logs.append(log)

    db_session.add_all(logs)
    db_session.commit()

    for log in logs:
        db_session.refresh(log)

    return logs


@pytest.fixture
def sample_resource_savings(db_session, sample_user) -> list[ResourceSavings]:
    """Create sample resource savings for testing."""
    savings = []
    for i in range(3):
        saving = ResourceSavings(
            user_id=sample_user.id,
            period_start=datetime.utcnow() - timedelta(days=30),
            period_end=datetime.utcnow(),
            messages_processed_saved=i * 10,
            memory_mb_saved=i * 5.5,
            reason="test_savings",
            created_at=datetime.utcnow() - timedelta(days=i),
        )
        savings.append(saving)

    db_session.add_all(savings)
    db_session.commit()

    for saving in savings:
        db_session.refresh(saving)

    return savings


@pytest.fixture
def sample_openai_metrics(db_session) -> list[OpenAIMetrics]:
    """Create sample OpenAI metrics for testing."""
    metrics = []
    for i in range(5):
        metric = OpenAIMetrics(
            model="gpt-4o-mini",
            input_tokens=i * 100,
            output_tokens=i * 50,
            total_tokens=i * 150,  # Required field
            cost_usd=i * 0.01,
            success=True,
            request_time=datetime.utcnow() - timedelta(hours=i),
        )
        metrics.append(metric)

    db_session.add_all(metrics)
    db_session.commit()

    for metric in metrics:
        db_session.refresh(metric)

    return metrics


@pytest.fixture(autouse=True)
def clean_database(db_session):
    """Clean up database after each test."""
    yield
    # Cleanup is now handled in the db_session fixture


@pytest.fixture
def mock_settings():
    """Mock settings for integration tests."""
    # Override settings for testing
    settings.DATABASE_URL = "sqlite:///:memory:"
    settings.OPENAI_API_KEY = "test-api-key"
    settings.TELEGRAM_BOT_TOKEN = "test-bot-token"
    settings.REDIS_URL = "redis://localhost:6379/1"
    return settings


@pytest.fixture
def client(db_session) -> TestClient:
    """Create a test client with DB dependency override."""

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
