"""E2E tests for WhatsApp webhook message processing pipeline."""

from datetime import datetime

import pytest

from app.core.repository_factory import repository_factory
from app.models.database import MonitoredChat, User, WhatsAppMessage


@pytest.mark.e2e
def test_webhook_health_check(client):
    """GET /webhook/whatsapp/health returns 200."""
    response = client.get("/webhook/whatsapp/health")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "healthy"


@pytest.mark.e2e
def test_receive_message_valid(
    client, db_session, mock_openai_service, mock_telegram_service
):
    """Create user + monitored chat, POST message -> 200, verify message queued."""
    from app.auth.security import get_password_hash

    user = User(
        username="whatsapp_testuser",
        email="whatsapp_test@example.com",
        hashed_password=get_password_hash("testpass"),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    chat = MonitoredChat(
        user_id=user.id,
        chat_id="chat_123",
        chat_name="Test Chat",
        chat_type="group",
        is_active=True,
    )
    db_session.add(chat)
    db_session.commit()
    db_session.refresh(chat)

    payload = {
        "userId": str(user.id),
        "chatId": "chat_123",
        "chatName": "Test Chat",
        "chatType": "group",
        "messageId": "msg_unique_123",
        "sender": "John",
        "content": "Hello",
        "timestamp": "2024-01-01T12:00:00Z",
        "importance": 3,
        "hasMedia": False,
    }

    response = client.post("/webhook/whatsapp/message", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "success"
    assert "queued" in data.get("message", "").lower()

    db_session.expire_all()
    msg = repository_factory.get_whatsapp_message_repository().get_by_message_id(
        db_session, "msg_unique_123"
    )
    assert msg is not None


@pytest.mark.e2e
def test_receive_message_unknown_user(client, db_session):
    """POST with invalid userId returns 404."""
    payload = {
        "userId": "99999",
        "chatId": "chat_123",
        "chatName": "Test Chat",
        "chatType": "group",
        "messageId": "msg_unknown",
        "sender": "John",
        "content": "Hello",
        "timestamp": "2024-01-01T12:00:00Z",
        "importance": 3,
        "hasMedia": False,
    }

    response = client.post("/webhook/whatsapp/message", json=payload)
    assert response.status_code == 404


@pytest.mark.e2e
def test_receive_message_unmonitored_chat(client, db_session):
    """POST with valid user but unmonitored chat -> skipped."""
    from app.auth.security import get_password_hash

    user = User(
        username="unmonitored_user",
        email="unmonitored@example.com",
        hashed_password=get_password_hash("testpass"),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    payload = {
        "userId": str(user.id),
        "chatId": "unmonitored_chat_456",
        "chatName": "Unmonitored Chat",
        "chatType": "group",
        "messageId": "msg_unmonitored",
        "sender": "Jane",
        "content": "Hello",
        "timestamp": "2024-01-01T12:00:00Z",
        "importance": 3,
        "hasMedia": False,
    }

    response = client.post("/webhook/whatsapp/message", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "skipped"
    assert "not monitored" in data.get("message", "").lower()


@pytest.mark.e2e
def test_receive_duplicate_message(
    client, db_session, mock_openai_service, mock_telegram_service
):
    """POST same messageId twice -> second is skipped."""
    from app.auth.security import get_password_hash

    user = User(
        username="dup_testuser",
        email="dup_test@example.com",
        hashed_password=get_password_hash("testpass"),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    chat = MonitoredChat(
        user_id=user.id,
        chat_id="chat_dup",
        chat_name="Dup Chat",
        chat_type="group",
        is_active=True,
    )
    db_session.add(chat)
    db_session.commit()
    db_session.refresh(chat)

    payload = {
        "userId": str(user.id),
        "chatId": "chat_dup",
        "chatName": "Dup Chat",
        "chatType": "group",
        "messageId": "msg_dup_123",
        "sender": "Bob",
        "content": "Duplicate test",
        "timestamp": "2024-01-01T12:00:00Z",
        "importance": 3,
        "hasMedia": False,
    }

    first = client.post("/webhook/whatsapp/message", json=payload)
    assert first.status_code == 200
    assert first.json().get("status") == "success"

    second = client.post("/webhook/whatsapp/message", json=payload)
    assert second.status_code == 200
    data = second.json()
    assert data.get("status") == "skipped"
    assert "already processed" in data.get("message", "").lower()


@pytest.mark.e2e
def test_get_active_users(client, db_session):
    """Create users with whatsapp_connected=True, GET active-users returns them."""
    from app.auth.security import get_password_hash

    user1 = User(
        username="active_user1",
        email="active1@example.com",
        hashed_password=get_password_hash("testpass"),
        whatsapp_connected=True,
        is_active=True,
    )
    user2 = User(
        username="active_user2",
        email="active2@example.com",
        hashed_password=get_password_hash("testpass"),
        whatsapp_connected=True,
        is_active=True,
    )
    db_session.add_all([user1, user2])
    db_session.commit()

    response = client.get("/webhook/whatsapp/active-users")
    assert response.status_code == 200
    data = response.json()
    active = data.get("active_users", [])
    usernames = [u["username"] for u in active]
    assert "active_user1" in usernames
    assert "active_user2" in usernames


@pytest.mark.e2e
def test_whatsapp_connected_webhook(client, db_session, mock_telegram_service):
    """POST /webhook/whatsapp/connected updates user status."""
    from app.auth.security import get_password_hash

    user = User(
        username="connect_testuser",
        email="connect_test@example.com",
        hashed_password=get_password_hash("testpass"),
        whatsapp_connected=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    payload = {
        "userId": str(user.id),
        "timestamp": datetime.utcnow().isoformat(),
    }

    response = client.post("/webhook/whatsapp/connected", json=payload)
    assert response.status_code == 200
    assert response.json().get("status") == "success"

    db_session.refresh(user)
    assert user.whatsapp_connected is True


@pytest.mark.e2e
def test_whatsapp_disconnected_webhook(client, db_session, mock_telegram_service):
    """POST /webhook/whatsapp/disconnected updates user status."""
    from app.auth.security import get_password_hash

    user = User(
        username="disconnect_testuser",
        email="disconnect_test@example.com",
        hashed_password=get_password_hash("testpass"),
        whatsapp_connected=True,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    payload = {
        "userId": str(user.id),
        "timestamp": datetime.utcnow().isoformat(),
    }

    response = client.post("/webhook/whatsapp/disconnected", json=payload)
    assert response.status_code == 200
    assert response.json().get("status") == "success"

    db_session.refresh(user)
    assert user.whatsapp_connected is False
