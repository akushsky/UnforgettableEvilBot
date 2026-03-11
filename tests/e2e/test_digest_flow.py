"""E2E tests for digest-related operations."""

from datetime import datetime, timedelta

import pytest

from app.core.repository_factory import repository_factory
from app.models.database import DigestLog, MonitoredChat, User, WhatsAppMessage


@pytest.mark.e2e
def test_generate_digest_for_user(
    authenticated_client,
    db_session,
    mock_openai_service,
    mock_telegram_service,
):
    """Create user + chat + messages, POST digest/generate with mocked services -> digest created."""
    from app.auth.security import get_password_hash

    user = User(
        username="digest_testuser",
        email="digest_test@example.com",
        hashed_password=get_password_hash("testpass"),
        whatsapp_connected=True,
        telegram_channel_id="-1001234567890",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    chat = MonitoredChat(
        user_id=user.id,
        chat_id="digest_chat_1",
        chat_name="Digest Chat",
        chat_type="group",
        is_active=True,
    )
    db_session.add(chat)
    db_session.commit()
    db_session.refresh(chat)

    msg = WhatsAppMessage(
        chat_id=chat.id,
        message_id="digest_msg_1",
        sender="Alice",
        content="Important message for digest",
        timestamp=datetime.utcnow() - timedelta(hours=1),
        importance_score=4,
        is_processed=False,
    )
    db_session.add(msg)
    db_session.commit()

    response = authenticated_client.post(f"/admin/users/{user.id}/digest/generate")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "success"

    db_session.expire_all()
    digests = repository_factory.get_digest_log_repository().get_digests_for_period(
        db_session, user.id, 365
    )
    assert len(digests) >= 1
    assert digests[0].digest_content
    assert digests[0].message_count >= 1


@pytest.mark.e2e
def test_generate_digest_no_messages(
    authenticated_client, db_session, mock_openai_service, mock_telegram_service
):
    """Create user + chat but no messages -> appropriate response."""
    from app.auth.security import get_password_hash

    user = User(
        username="nodigest_testuser",
        email="nodigest_test@example.com",
        hashed_password=get_password_hash("testpass"),
        whatsapp_connected=True,
        telegram_channel_id="-1001234567890",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    chat = MonitoredChat(
        user_id=user.id,
        chat_id="empty_chat",
        chat_name="Empty Chat",
        chat_type="group",
        is_active=True,
    )
    db_session.add(chat)
    db_session.commit()

    response = authenticated_client.post(f"/admin/users/{user.id}/digest/generate")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "success"


@pytest.mark.e2e
def test_view_user_digests(authenticated_client, db_session):
    """Create user with digest logs, GET /admin/users/{id}/digests returns digest list."""
    from app.auth.security import get_password_hash

    user = User(
        username="viewdigest_testuser",
        email="viewdigest_test@example.com",
        hashed_password=get_password_hash("testpass"),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    digest_log = DigestLog(
        user_id=user.id,
        digest_content="Test digest content",
        message_count=3,
        telegram_sent=True,
    )
    db_session.add(digest_log)
    db_session.commit()

    response = authenticated_client.get(f"/admin/users/{user.id}/digests")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "success"
    assert "digests" in data
    assert len(data["digests"]) >= 1
    assert data["digests"][0]["digest_content"] == "Test digest content"


@pytest.mark.e2e
def test_view_user_messages(authenticated_client, db_session):
    """Create user + chat + messages, GET /admin/users/{id}/messages returns messages."""
    from app.auth.security import get_password_hash

    user = User(
        username="viewmsg_testuser",
        email="viewmsg_test@example.com",
        hashed_password=get_password_hash("testpass"),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    chat = MonitoredChat(
        user_id=user.id,
        chat_id="view_chat",
        chat_name="View Chat",
        chat_type="group",
        is_active=True,
    )
    db_session.add(chat)
    db_session.commit()
    db_session.refresh(chat)

    msg = WhatsAppMessage(
        chat_id=chat.id,
        message_id="view_msg_1",
        sender="Bob",
        content="Test message",
        timestamp=datetime.utcnow(),
        importance_score=3,
        is_processed=False,
    )
    db_session.add(msg)
    db_session.commit()

    response = authenticated_client.get(f"/admin/users/{user.id}/messages")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "success"
    assert "messages" in data
    assert len(data["messages"]) >= 1
    assert data["messages"][0]["content"] == "Test message"
