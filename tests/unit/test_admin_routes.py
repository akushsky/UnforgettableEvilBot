"""Unit tests for admin routes in app/api/admin_routes.py."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

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
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@patch("app.api.admin_routes.get_whatsapp_service")
@patch("app.api.admin_routes.repository_factory")
@patch("app.api.admin_routes.require_admin_auth")
def test_get_available_chats_success(
    mock_auth, mock_repo_factory, mock_whatsapp, client
):
    """Test GET /admin/users/{user_id}/chats returns chats when connected."""
    mock_auth.return_value = True
    mock_user = Mock()
    mock_user.id = 1
    mock_user.whatsapp_connected = True

    mock_user_repo = Mock()
    mock_user_repo.get_by_id_or_404.return_value = mock_user
    mock_repo_factory.get_user_repository.return_value = mock_user_repo

    mock_whatsapp_svc = AsyncMock()
    mock_whatsapp_svc.get_chats = AsyncMock(
        return_value=[{"id": "chat1", "name": "Test Chat"}]
    )
    mock_whatsapp.return_value = mock_whatsapp_svc

    response = client.get("/admin/users/1/chats")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "chats" in data
    assert len(data["chats"]) == 1


@patch("app.api.admin_routes.repository_factory")
@patch("app.api.admin_routes.require_admin_auth")
def test_get_available_chats_not_connected(mock_auth, mock_repo_factory, client):
    """Test GET /admin/users/{user_id}/chats returns error when not connected."""
    mock_auth.return_value = True
    mock_user = Mock()
    mock_user.id = 1
    mock_user.whatsapp_connected = False

    mock_user_repo = Mock()
    mock_user_repo.get_by_id_or_404.return_value = mock_user
    mock_repo_factory.get_user_repository.return_value = mock_user_repo

    response = client.get("/admin/users/1/chats")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert "WhatsApp not connected" in data["message"]


@patch("app.api.admin_routes.repository_factory")
@patch("app.api.admin_routes.require_admin_auth")
def test_add_monitored_chat_success(mock_auth, mock_repo_factory, client, mock_db):
    """Test POST /admin/users/{user_id}/chats/add adds new chat."""
    mock_auth.return_value = True
    mock_user_repo = Mock()
    mock_user_repo.get_by_id_or_404.return_value = Mock()
    mock_repo_factory.get_user_repository.return_value = mock_user_repo

    mock_chat_repo = Mock()
    mock_chat_repo.get_by_user_and_chat_id.return_value = None
    mock_repo_factory.get_monitored_chat_repository.return_value = mock_chat_repo

    response = client.post(
        "/admin/users/1/chats/add",
        data={"chat_id": "wa_chat_123", "chat_name": "My Chat", "chat_type": "group"},
    )

    assert response.status_code == 303
    assert response.headers.get("location") == "/admin/users/1"
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called()


@patch("app.api.admin_routes.repository_factory")
@patch("app.api.admin_routes.require_admin_auth")
def test_add_monitored_chat_already_exists(mock_auth, mock_repo_factory, client):
    """Test POST /admin/users/{user_id}/chats/add reactivates existing inactive chat."""
    mock_auth.return_value = True
    mock_user_repo = Mock()
    mock_user_repo.get_by_id_or_404.return_value = Mock()
    mock_repo_factory.get_user_repository.return_value = mock_user_repo

    existing_chat = Mock()
    existing_chat.is_active = False
    mock_chat_repo = Mock()
    mock_chat_repo.get_by_user_and_chat_id.return_value = existing_chat
    mock_repo_factory.get_monitored_chat_repository.return_value = mock_chat_repo

    response = client.post(
        "/admin/users/1/chats/add",
        data={"chat_id": "wa_chat_123", "chat_name": "My Chat", "chat_type": "group"},
    )

    assert response.status_code == 303
    assert existing_chat.is_active is True


@patch("app.api.admin_routes.repository_factory")
@patch("app.api.admin_routes.require_admin_auth")
def test_remove_chat_success(mock_auth, mock_repo_factory, client):
    """Test POST /admin/users/{user_id}/chats/{chat_id}/remove deactivates chat."""
    mock_auth.return_value = True
    mock_chat = Mock()
    mock_chat.id = 10
    mock_chat.user_id = 1
    mock_chat.is_active = True

    mock_chat_repo = Mock()
    mock_chat_repo.get_by_id.return_value = mock_chat
    mock_repo_factory.get_monitored_chat_repository.return_value = mock_chat_repo

    response = client.post("/admin/users/1/chats/10/remove")

    assert response.status_code == 303
    assert mock_chat.is_active is False


@patch("app.api.admin_routes.repository_factory")
@patch("app.api.admin_routes.require_admin_auth")
def test_rename_chat_success(mock_auth, mock_repo_factory, client):
    """Test POST /admin/users/{user_id}/chats/{chat_id}/rename updates custom name."""
    mock_auth.return_value = True
    mock_chat = Mock()
    mock_chat.id = 10
    mock_chat.user_id = 1
    mock_chat.custom_name = None

    mock_chat_repo = Mock()
    mock_chat_repo.get_by_id.return_value = mock_chat
    mock_repo_factory.get_monitored_chat_repository.return_value = mock_chat_repo

    response = client.post(
        "/admin/users/1/chats/10/rename",
        data={"custom_name": "My Custom Name"},
    )

    assert response.status_code == 303
    assert mock_chat.custom_name == "My Custom Name"


@patch("app.api.admin_routes.httpx")
@patch("app.api.admin_routes.repository_factory")
@patch("app.api.admin_routes.require_admin_auth")
def test_get_qr_code(mock_auth, mock_repo_factory, mock_httpx, client):
    """Test GET /admin/users/{user_id}/qr returns QR code data."""
    mock_auth.return_value = True
    mock_user_repo = Mock()
    mock_user_repo.get_by_id_or_404.return_value = Mock()
    mock_repo_factory.get_user_repository.return_value = mock_user_repo

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "qrCode": "data:image/png;base64,xxx",
        "timestamp": "123",
    }
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=None)

    response = client.get("/admin/users/1/qr")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "qr_code" in data


@patch("app.api.admin_routes.httpx")
@patch("app.api.admin_routes.require_admin_auth")
def test_check_qr_status(mock_auth, mock_httpx, client):
    """Test GET /admin/users/{user_id}/qr/check returns QR status."""
    mock_auth.return_value = True

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"qrCode": "xxx", "timestamp": "123"}
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=None)

    response = client.get("/admin/users/1/qr/check")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"


@patch("app.api.admin_routes.httpx")
@patch("app.api.admin_routes.repository_factory")
@patch("app.api.admin_routes.require_admin_auth")
def test_get_whatsapp_status(mock_auth, mock_repo_factory, mock_httpx, client):
    """Test GET /admin/users/{user_id}/whatsapp/status returns status."""
    mock_auth.return_value = True
    mock_user = Mock()
    mock_user.id = 1
    mock_user.whatsapp_connected = True

    mock_user_repo = Mock()
    mock_user_repo.get_by_id_or_404.return_value = mock_user
    mock_repo_factory.get_user_repository.return_value = mock_user_repo

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"connected": True}
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=None)

    response = client.get("/admin/users/1/whatsapp/status")

    assert response.status_code == 200
    data = response.json()
    assert "whatsapp_connected" in data
    assert "status" in data


@patch("app.api.admin_routes.repository_factory")
@patch("app.api.admin_routes.require_admin_auth")
def test_update_whatsapp_status(mock_auth, mock_repo_factory, client):
    """Test POST /admin/users/{user_id}/whatsapp/update-status updates status."""
    mock_auth.return_value = True
    mock_user = Mock()
    mock_user.id = 1
    mock_user.whatsapp_connected = False

    mock_user_repo = Mock()
    mock_user_repo.get_by_id_or_404.return_value = mock_user
    mock_repo_factory.get_user_repository.return_value = mock_user_repo

    response = client.post(
        "/admin/users/1/whatsapp/update-status",
        json={"connected": True},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert mock_user.whatsapp_connected is True


@patch("app.scheduler.digest_scheduler.DigestScheduler")
@patch("app.api.admin_routes.repository_factory")
@patch("app.api.admin_routes.require_admin_auth")
def test_generate_digest(mock_auth, mock_repo_factory, mock_scheduler_cls, client):
    """Test POST /admin/users/{user_id}/digest/generate creates digest."""
    mock_auth.return_value = True
    mock_user = Mock()
    mock_user.id = 1
    mock_user.is_active = True
    mock_user.whatsapp_connected = True
    mock_user.telegram_channel_id = "-100123"

    mock_user_repo = Mock()
    mock_user_repo.get_by_id_or_404.return_value = mock_user
    mock_repo_factory.get_user_repository.return_value = mock_user_repo

    mock_scheduler = AsyncMock()
    mock_scheduler.create_and_send_digest = AsyncMock()
    mock_scheduler_cls.return_value = mock_scheduler

    response = client.post("/admin/users/1/digest/generate")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"


@patch("app.api.admin_routes.repository_factory")
@patch("app.api.admin_routes.require_admin_auth")
def test_get_messages(mock_auth, mock_repo_factory, client):
    """Test GET /admin/users/{user_id}/messages returns messages."""
    mock_auth.return_value = True
    mock_user_repo = Mock()
    mock_user_repo.get_by_id_or_404.return_value = Mock()
    mock_repo_factory.get_user_repository.return_value = mock_user_repo

    mock_chat_repo = Mock()
    mock_chat_repo.get_active_chats_for_user.return_value = []
    mock_repo_factory.get_monitored_chat_repository.return_value = mock_chat_repo

    response = client.get("/admin/users/1/messages")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "messages" in data
    assert data["total"] == 0


@patch("app.api.admin_routes.repository_factory")
@patch("app.api.admin_routes.require_admin_auth")
def test_get_digests(mock_auth, mock_repo_factory, client):
    """Test GET /admin/users/{user_id}/digests returns digest logs."""
    mock_auth.return_value = True
    mock_user_repo = Mock()
    mock_user_repo.get_by_id_or_404.return_value = Mock()
    mock_repo_factory.get_user_repository.return_value = mock_user_repo

    mock_digest_repo = Mock()
    mock_digest_repo.get_digests_for_period.return_value = []
    mock_repo_factory.get_digest_log_repository.return_value = mock_digest_repo

    response = client.get("/admin/users/1/digests")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "digests" in data


@patch("app.core.data_cleanup.cleanup_service")
@patch("app.api.admin_routes.repository_factory")
@patch("app.api.admin_routes.require_admin_auth")
def test_storage_stats(mock_auth, mock_repo_factory, mock_cleanup, client):
    """Test GET /admin/storage/stats returns storage statistics."""
    mock_auth.return_value = True
    mock_cleanup.get_storage_stats = AsyncMock(
        return_value={"total_messages": 100, "storage_mb": 50}
    )

    response = client.get("/admin/storage/stats")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "storage_stats" in data


@patch("app.core.data_cleanup.cleanup_service")
@patch("app.api.admin_routes.require_admin_auth")
def test_storage_cleanup(mock_auth, mock_cleanup, client):
    """Test POST /admin/storage/cleanup runs cleanup."""
    mock_auth.return_value = True
    mock_cleanup.run_full_cleanup = AsyncMock(
        return_value={"deleted": 10, "freed_mb": 5}
    )

    response = client.post("/admin/storage/cleanup")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "cleanup_results" in data


@patch("app.core.resource_savings.resource_savings_service")
@patch("app.api.admin_routes.require_admin_auth")
def test_resource_savings(mock_auth, mock_savings, client):
    """Test GET /admin/resource-savings returns savings metrics."""
    mock_auth.return_value = True
    mock_savings.get_total_savings.return_value = {
        "total_whatsapp_connections_saved": 5,
        "total_memory_mb_saved": 100,
    }
    mock_savings.get_current_system_savings.return_value = {
        "current_memory_usage_mb": 50,
    }

    response = client.get("/admin/resource-savings")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "total_savings" in data


@patch("app.api.admin_routes.httpx")
@patch("app.api.admin_routes.require_admin_auth")
def test_system_status(mock_auth, mock_httpx, client):
    """Test GET /admin/system/status returns system status."""
    mock_auth.return_value = True

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "ok"}
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=None)

    response = client.get("/admin/system/status")

    assert response.status_code == 200
    data = response.json()
    assert "fastapi" in data
    assert "bridge" in data
