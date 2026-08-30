from contextlib import contextmanager
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import BackgroundTasks, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.whatsapp_webhooks import (
    EMPTY_CONTENT_PLACEHOLDER,
    analyze_and_save_message,
    get_active_users,
    receive_whatsapp_message,
    router,
    whatsapp_webhook_health,
)
from app.auth.webhook_auth import verify_bridge_secret
from app.models.database import WhatsAppMessage
from app.models.schemas import WhatsAppMessageWebhook
from tests.unit.conftest import create_test_user


def _build_app():
    """Build a FastAPI app exposing the webhook router."""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    return app


def _make_webhook_message(**overrides) -> WhatsAppMessageWebhook:
    """Build a webhook payload with sane defaults."""
    payload = {
        "userId": "1",
        "messageId": "msg-1",
        "chatId": "123@g.us",
        "chatName": "Test Chat",
        "chatType": "group",
        "sender": "sender@s.whatsapp.net",
        "content": "hello world",
        "timestamp": "2026-01-01T10:00:00Z",
        "importance": 2,
        "hasMedia": False,
    }
    payload.update(overrides)
    return WhatsAppMessageWebhook(**payload)


def _mock_repositories(existing_message=None, chat_db_id=42, user=None):
    """Build a repository_factory mock for a monitored chat of an active user."""
    repo_factory = Mock()

    user_repo = Mock()
    user_repo.get_by_id.return_value = user or create_test_user(id=1, is_active=True)
    repo_factory.get_user_repository.return_value = user_repo

    monitored_chat = Mock()
    monitored_chat.id = chat_db_id
    chat_repo = Mock()
    chat_repo.get_by_user_and_chat_id.return_value = monitored_chat
    repo_factory.get_monitored_chat_repository.return_value = chat_repo

    message_repo = Mock()
    message_repo.get_by_message_id.return_value = existing_message
    repo_factory.get_whatsapp_message_repository.return_value = message_repo

    return repo_factory


@contextmanager
def _fake_db_session(db):
    """Stand in for get_db_session in background tasks."""
    yield db


class TestWhatsAppWebhooks:
    """Test cases for WhatsApp webhooks functionality"""

    @pytest.fixture
    def client(self):
        """Create test client with bridge authentication satisfied"""
        app = _build_app()
        app.dependency_overrides[verify_bridge_secret] = lambda: True
        yield TestClient(app)
        app.dependency_overrides.clear()

    @pytest.fixture
    def mock_db(self):
        """Create mock database session"""
        return Mock(spec=Session)

    @pytest.fixture
    def mock_user_repository(self):
        """Create mock user repository"""
        return Mock()

    @pytest.mark.asyncio
    async def test_whatsapp_webhook_health(self):
        """Test the health check endpoint"""
        response = await whatsapp_webhook_health()

        assert response["status"] == "healthy"
        assert response["service"] == "whatsapp-webhooks"

    @patch("app.api.whatsapp_webhooks.repository_factory")
    @pytest.mark.asyncio
    async def test_get_active_users_success(self, mock_repo_factory, mock_db):
        """Test successful retrieval of active users"""
        # Create mock users
        mock_users = [
            Mock(id=1, username="user1", whatsapp_connected=True, is_active=True),
            Mock(id=2, username="user2", whatsapp_connected=True, is_active=True),
            Mock(
                id=3,
                username="user3",
                whatsapp_connected=False,  # Should be filtered out
                is_active=True,
            ),
        ]

        # Setup mock repository
        mock_user_repo = Mock()
        mock_user_repo.get_active_users_with_whatsapp.return_value = mock_users[:2]
        mock_repo_factory.get_user_repository.return_value = mock_user_repo

        # Call the function
        response = await get_active_users(mock_db)

        # Verify the response
        assert "active_users" in response
        assert len(response["active_users"]) == 2

        user1 = response["active_users"][0]
        assert user1["id"] == 1
        assert user1["username"] == "user1"
        assert user1["whatsapp_connected"] is True
        assert user1["is_active"] is True

        user2 = response["active_users"][1]
        assert user2["id"] == 2
        assert user2["username"] == "user2"
        assert user2["whatsapp_connected"] is True
        assert user2["is_active"] is True

        # Verify repository was called correctly
        mock_user_repo.get_active_users_with_whatsapp.assert_called_once_with(mock_db)

    @patch("app.api.whatsapp_webhooks.repository_factory")
    @pytest.mark.asyncio
    async def test_get_active_users_empty(self, mock_repo_factory, mock_db):
        """Test retrieval when no active users exist"""
        # Setup mock repository to return empty list
        mock_user_repo = Mock()
        mock_user_repo.get_active_users_with_whatsapp.return_value = []
        mock_repo_factory.get_user_repository.return_value = mock_user_repo

        # Call the function
        response = await get_active_users(mock_db)

        # Verify the response
        assert "active_users" in response
        assert len(response["active_users"]) == 0

    @patch("app.api.whatsapp_webhooks.repository_factory")
    @pytest.mark.asyncio
    async def test_get_active_users_database_error(self, mock_repo_factory, mock_db):
        """Test handling of database errors"""
        # Setup mock repository to raise an exception
        mock_user_repo = Mock()
        mock_user_repo.get_active_users_with_whatsapp.side_effect = Exception(
            "Database connection failed"
        )
        mock_repo_factory.get_user_repository.return_value = mock_user_repo

        # Call the function and expect an exception
        with pytest.raises(HTTPException) as exc_info:
            await get_active_users(mock_db)

        assert exc_info.value.status_code == 500
        assert "Database connection failed" in str(exc_info.value.detail)

    def test_active_users_endpoint_integration(self, client, mock_db):
        """Test the /active-users endpoint through the router"""
        with (
            patch("app.api.whatsapp_webhooks.get_db", return_value=mock_db),
            patch("app.api.whatsapp_webhooks.repository_factory") as mock_repo_factory,
        ):
            # Setup mock users
            mock_users = [
                Mock(
                    id=1,
                    username="testuser",
                    whatsapp_connected=True,
                    is_active=True,
                )
            ]

            mock_user_repo = Mock()
            mock_user_repo.get_active_users_with_whatsapp.return_value = mock_users
            mock_repo_factory.get_user_repository.return_value = mock_user_repo

            # Make request to endpoint
            response = client.get("/webhook/whatsapp/active-users")

            # Verify response
            assert response.status_code == 200
            data = response.json()
            assert "active_users" in data
            assert len(data["active_users"]) == 1
            assert data["active_users"][0]["username"] == "testuser"

    def test_health_endpoint_integration(self, client):
        """Test the /health endpoint through the router"""
        response = client.get("/webhook/whatsapp/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "whatsapp-webhooks"

    def test_active_users_endpoint_with_real_user_data(self, client, mock_db):
        """Test with realistic user data structure"""
        with (
            patch("app.api.whatsapp_webhooks.get_db", return_value=mock_db),
            patch("app.api.whatsapp_webhooks.repository_factory") as mock_repo_factory,
        ):
            # Create realistic user objects
            user1 = create_test_user(
                id=1,
                username="john_doe",
                email="john@example.com",
                whatsapp_connected=True,
                is_active=True,
            )
            user2 = create_test_user(
                id=2,
                username="jane_smith",
                email="jane@example.com",
                whatsapp_connected=True,
                is_active=False,  # Should still be included as it has WhatsApp connected
            )

            mock_user_repo = Mock()
            mock_user_repo.get_active_users_with_whatsapp.return_value = [
                user1,
                user2,
            ]
            mock_repo_factory.get_user_repository.return_value = mock_user_repo

            # Make request
            response = client.get("/webhook/whatsapp/active-users")

            # Verify response
            assert response.status_code == 200
            data = response.json()
            assert len(data["active_users"]) == 2

            # Check first user
            assert data["active_users"][0]["id"] == 1
            assert data["active_users"][0]["username"] == "john_doe"
            assert data["active_users"][0]["whatsapp_connected"] is True
            assert data["active_users"][0]["is_active"] is True

            # Check second user
            assert data["active_users"][1]["id"] == 2
            assert data["active_users"][1]["username"] == "jane_smith"
            assert data["active_users"][1]["whatsapp_connected"] is True
            assert data["active_users"][1]["is_active"] is False

    def test_endpoint_error_handling(self, client, mock_db):
        """Test proper error handling in endpoints"""
        with (
            patch("app.api.whatsapp_webhooks.get_db", return_value=mock_db),
            patch("app.api.whatsapp_webhooks.repository_factory") as mock_repo_factory,
        ):
            # Setup repository to raise an exception
            mock_user_repo = Mock()
            mock_user_repo.get_active_users_with_whatsapp.side_effect = Exception(
                "Test error"
            )
            mock_repo_factory.get_user_repository.return_value = mock_user_repo

            # Make request
            response = client.get("/webhook/whatsapp/active-users")

            # Verify error response
            assert response.status_code == 500
            data = response.json()
            assert "detail" in data
            assert "Test error" in data["detail"]


class TestBridgeWebhookSecret:
    """Test cases for the shared-secret guard on the bridge webhook router"""

    @pytest.fixture
    def client(self):
        """Create test client without bypassing bridge authentication"""
        return TestClient(_build_app())

    @staticmethod
    def _configure(secret: str, debug: bool):
        """Patch the settings the bridge secret dependency reads"""
        from config.settings import settings

        return (
            patch.object(settings, "BRIDGE_WEBHOOK_SECRET", secret),
            patch.object(settings, "DEBUG", debug),
        )

    def test_valid_secret_is_accepted(self, client):
        """Test that a matching X-Bridge-Secret header allows the request"""
        secret_patch, debug_patch = self._configure("s3cret-token", False)
        with secret_patch, debug_patch:
            response = client.get(
                "/webhook/whatsapp/health",
                headers={"X-Bridge-Secret": "s3cret-token"},
            )

        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_missing_secret_header_is_rejected(self, client):
        """Test that a configured secret is required on every webhook call"""
        secret_patch, debug_patch = self._configure("s3cret-token", False)
        with secret_patch, debug_patch:
            response = client.get("/webhook/whatsapp/health")

        assert response.status_code == 401

    def test_wrong_secret_is_rejected(self, client):
        """Test that a non-matching secret is rejected"""
        secret_patch, debug_patch = self._configure("s3cret-token", False)
        with secret_patch, debug_patch:
            response = client.get(
                "/webhook/whatsapp/health",
                headers={"X-Bridge-Secret": "wrong-token"},
            )

        assert response.status_code == 401

    def test_secret_prefix_is_rejected(self, client):
        """Test that a prefix of the secret does not authenticate"""
        secret_patch, debug_patch = self._configure("s3cret-token", False)
        with secret_patch, debug_patch:
            response = client.get(
                "/webhook/whatsapp/health",
                headers={"X-Bridge-Secret": "s3cret"},
            )

        assert response.status_code == 401

    def test_secret_enforced_even_in_debug(self, client):
        """Test that DEBUG does not bypass a configured secret"""
        secret_patch, debug_patch = self._configure("s3cret-token", True)
        with secret_patch, debug_patch:
            response = client.get("/webhook/whatsapp/health")

        assert response.status_code == 401

    def test_unconfigured_secret_rejects_outside_debug(self, client):
        """Test that webhooks fail closed when no secret is configured"""
        secret_patch, debug_patch = self._configure("", False)
        with secret_patch, debug_patch:
            response = client.get("/webhook/whatsapp/health")

        assert response.status_code == 401

    def test_unconfigured_secret_allowed_in_debug(self, client):
        """Test that local development without a secret still works"""
        secret_patch, debug_patch = self._configure("", True)
        with secret_patch, debug_patch:
            response = client.get("/webhook/whatsapp/health")

        assert response.status_code == 200

    def test_message_webhook_requires_secret(self, client):
        """Test that the message webhook is guarded before any payload handling"""
        secret_patch, debug_patch = self._configure("s3cret-token", False)
        with secret_patch, debug_patch:
            response = client.post("/webhook/whatsapp/message", json={})

        assert response.status_code == 401

    def test_active_users_webhook_requires_secret(self, client):
        """Test that the active-users webhook is guarded"""
        secret_patch, debug_patch = self._configure("s3cret-token", False)
        with secret_patch, debug_patch:
            response = client.get("/webhook/whatsapp/active-users")

        assert response.status_code == 401


class TestMessagePersistedBeforeAnalysis:
    """Test that the message webhook stores the message before any AI call"""

    @pytest.fixture
    def db(self):
        """Mock request-scoped session"""
        return Mock(spec=Session)

    @staticmethod
    def _added_message(db) -> WhatsAppMessage:
        """The WhatsAppMessage handed to the session"""
        assert db.add.called, "message was not persisted"
        return db.add.call_args[0][0]

    @pytest.mark.asyncio
    async def test_message_is_saved_synchronously(self, db):
        """Test that the row exists before the AI background task is queued"""
        background_tasks = BackgroundTasks()
        message = _make_webhook_message()

        with patch(
            "app.api.whatsapp_webhooks.repository_factory", _mock_repositories()
        ):
            response = await receive_whatsapp_message(message, background_tasks, db)

        stored = self._added_message(db)
        assert stored.message_id == "msg-1"
        assert stored.chat_id == 42
        assert stored.content == "hello world"
        assert stored.importance_score == 2
        assert stored.ai_analyzed is False
        assert db.commit.called
        assert response["status"] == "success"

    @pytest.mark.asyncio
    async def test_analysis_is_queued_for_the_saved_message(self, db):
        """Test that the background task targets the persisted chat row"""
        background_tasks = BackgroundTasks()
        message = _make_webhook_message()

        with patch(
            "app.api.whatsapp_webhooks.repository_factory", _mock_repositories()
        ):
            await receive_whatsapp_message(message, background_tasks, db)

        assert len(background_tasks.tasks) == 1
        task = background_tasks.tasks[0]
        assert task.func is analyze_and_save_message
        assert task.args == (message, 42, "1")

    @pytest.mark.asyncio
    async def test_empty_content_is_persisted_with_placeholder(self, db):
        """Test that a media-only message is stored instead of dropped"""
        background_tasks = BackgroundTasks()
        message = _make_webhook_message(content=None, hasMedia=True)

        with patch(
            "app.api.whatsapp_webhooks.repository_factory", _mock_repositories()
        ):
            response = await receive_whatsapp_message(message, background_tasks, db)

        stored = self._added_message(db)
        assert stored.content == EMPTY_CONTENT_PLACEHOLDER
        assert stored.has_media is True
        assert response["status"] == "success"

    @pytest.mark.asyncio
    async def test_known_duplicate_is_skipped_without_insert(self, db):
        """Test that an already stored message is not written again"""
        background_tasks = BackgroundTasks()
        message = _make_webhook_message()
        repo_factory = _mock_repositories(existing_message=Mock())

        with patch("app.api.whatsapp_webhooks.repository_factory", repo_factory):
            response = await receive_whatsapp_message(message, background_tasks, db)

        assert response["status"] == "skipped"
        assert not db.add.called
        assert background_tasks.tasks == []

    @pytest.mark.asyncio
    async def test_concurrent_duplicate_insert_is_reported_as_skipped(self, db):
        """Test that a racing duplicate insert is absorbed, not a 500"""
        background_tasks = BackgroundTasks()
        message = _make_webhook_message()
        db.commit.side_effect = IntegrityError(
            "INSERT INTO whatsapp_messages", {}, Exception("duplicate message_id")
        )

        repo_factory = _mock_repositories()
        # Not a duplicate on the pre-check, but the racing insert landed first.
        repo_factory.get_whatsapp_message_repository().get_by_message_id.side_effect = [
            None,
            Mock(ai_analyzed=True),
            Mock(ai_analyzed=True),
        ]

        with patch("app.api.whatsapp_webhooks.repository_factory", repo_factory):
            response = await receive_whatsapp_message(message, background_tasks, db)

        assert response["status"] == "skipped"
        assert db.rollback.called
        assert background_tasks.tasks == []

    @pytest.mark.asyncio
    async def test_integrity_error_without_duplicate_row_fails_the_webhook(self, db):
        """A constraint violation that is not a duplicate must return 500

        Swallowing it would tell the bridge the message was handled while
        nothing was ever stored.
        """
        background_tasks = BackgroundTasks()
        message = _make_webhook_message()
        db.commit.side_effect = IntegrityError(
            "INSERT INTO whatsapp_messages", {}, Exception("null value in column")
        )

        repo_factory = _mock_repositories(existing_message=None)

        with (
            patch("app.api.whatsapp_webhooks.repository_factory", repo_factory),
            pytest.raises(HTTPException) as exc_info,
        ):
            await receive_whatsapp_message(message, background_tasks, db)

        assert exc_info.value.status_code == 500
        assert db.rollback.called
        assert background_tasks.tasks == []

    @pytest.mark.asyncio
    async def test_duplicate_never_analyzed_is_requeued(self, db):
        """A stored-but-unscored duplicate gets its analysis queued again"""
        background_tasks = BackgroundTasks()
        message = _make_webhook_message()
        stored = Mock(ai_analyzed=False)
        repo_factory = _mock_repositories(existing_message=stored)

        with patch("app.api.whatsapp_webhooks.repository_factory", repo_factory):
            response = await receive_whatsapp_message(message, background_tasks, db)

        assert response["status"] == "requeued"
        assert not db.add.called
        assert len(background_tasks.tasks) == 1
        task = background_tasks.tasks[0]
        assert task.func is analyze_and_save_message
        assert task.args == (message, 42, "1")

    @pytest.mark.asyncio
    async def test_racing_duplicate_never_analyzed_is_requeued(self, db):
        """The post-insert duplicate path re-queues analysis too"""
        background_tasks = BackgroundTasks()
        message = _make_webhook_message()
        db.commit.side_effect = IntegrityError(
            "INSERT INTO whatsapp_messages", {}, Exception("duplicate message_id")
        )

        repo_factory = _mock_repositories()
        repo_factory.get_whatsapp_message_repository().get_by_message_id.side_effect = [
            None,
            Mock(ai_analyzed=False),
            Mock(ai_analyzed=False),
        ]

        with patch("app.api.whatsapp_webhooks.repository_factory", repo_factory):
            response = await receive_whatsapp_message(message, background_tasks, db)

        assert response["status"] == "requeued"
        assert len(background_tasks.tasks) == 1

    @pytest.mark.asyncio
    async def test_unmonitored_chat_is_not_persisted(self, db):
        """Test that messages from unmonitored chats are still dropped"""
        background_tasks = BackgroundTasks()
        message = _make_webhook_message()
        repo_factory = _mock_repositories()
        repo_factory.get_monitored_chat_repository().get_by_user_and_chat_id.return_value = (
            None
        )

        with patch("app.api.whatsapp_webhooks.repository_factory", repo_factory):
            response = await receive_whatsapp_message(message, background_tasks, db)

        assert response["status"] == "skipped"
        assert not db.add.called


class TestAnalyzeAndSaveMessage:
    """Test the background task that enriches the stored message"""

    @staticmethod
    def _stored_message(importance: int = 2) -> WhatsAppMessage:
        """A message already persisted by the webhook"""
        return WhatsAppMessage(
            chat_id=42,
            message_id="msg-1",
            sender="sender",
            content="hello world",
            timestamp=None,
            importance_score=importance,
            has_media=False,
            is_processed=False,
            ai_analyzed=False,
        )

    @staticmethod
    def _openai(importance: int):
        """Mock OpenAI service returning a fixed importance"""
        service = Mock()
        service.analyze_message_importance = AsyncMock(return_value=importance)
        return service

    @pytest.mark.asyncio
    async def test_existing_message_is_updated_not_reinserted(self):
        """Test that analysis updates the row written by the webhook"""
        db = Mock(spec=Session)
        stored = self._stored_message()
        repo_factory = _mock_repositories(existing_message=stored)

        with (
            patch("app.api.whatsapp_webhooks.repository_factory", repo_factory),
            patch(
                "app.database.connection.get_db_session",
                lambda: _fake_db_session(db),
            ),
            patch(
                "app.api.whatsapp_webhooks.get_openai_service",
                return_value=self._openai(4),
            ),
        ):
            await analyze_and_save_message(_make_webhook_message(), 42, "1")

        assert stored.importance_score == 4
        assert stored.ai_analyzed is True
        assert not db.add.called

    @pytest.mark.asyncio
    async def test_provisional_importance_is_never_lowered(self):
        """Test that the bridge importance wins when AI scores lower"""
        db = Mock(spec=Session)
        stored = self._stored_message(importance=3)
        repo_factory = _mock_repositories(existing_message=stored)

        with (
            patch("app.api.whatsapp_webhooks.repository_factory", repo_factory),
            patch(
                "app.database.connection.get_db_session",
                lambda: _fake_db_session(db),
            ),
            patch(
                "app.api.whatsapp_webhooks.get_openai_service",
                return_value=self._openai(1),
            ),
        ):
            await analyze_and_save_message(_make_webhook_message(importance=3), 42, "1")

        assert stored.importance_score == 3
        assert stored.ai_analyzed is True

    @pytest.mark.asyncio
    async def test_urgent_notification_sent_for_high_importance(self):
        """Test that a high AI score triggers the urgent notification"""
        db = Mock(spec=Session)
        stored = self._stored_message()
        repo_factory = _mock_repositories(existing_message=stored)
        notify = AsyncMock()

        with (
            patch("app.api.whatsapp_webhooks.repository_factory", repo_factory),
            patch(
                "app.database.connection.get_db_session",
                lambda: _fake_db_session(db),
            ),
            patch(
                "app.api.whatsapp_webhooks.get_openai_service",
                return_value=self._openai(5),
            ),
            patch("app.api.whatsapp_webhooks.send_urgent_notification", notify),
        ):
            await analyze_and_save_message(_make_webhook_message(), 42, "1")

        assert stored.importance_score == 5
        notify.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_content_keeps_provisional_importance(self):
        """Test that a media-only message is left alone instead of re-inserted"""
        db = Mock(spec=Session)
        openai_service = self._openai(5)

        with (
            patch(
                "app.database.connection.get_db_session",
                lambda: _fake_db_session(db),
            ),
            patch(
                "app.api.whatsapp_webhooks.get_openai_service",
                return_value=openai_service,
            ),
        ):
            await analyze_and_save_message(
                _make_webhook_message(content=None, hasMedia=True), 42, "1"
            )

        openai_service.analyze_message_importance.assert_not_awaited()
        assert not db.add.called

    @pytest.mark.asyncio
    async def test_missing_row_is_recovered_by_insert(self):
        """Test that a vanished row is re-created rather than lost"""
        db = Mock(spec=Session)
        repo_factory = _mock_repositories(existing_message=None)

        with (
            patch("app.api.whatsapp_webhooks.repository_factory", repo_factory),
            patch(
                "app.database.connection.get_db_session",
                lambda: _fake_db_session(db),
            ),
            patch(
                "app.api.whatsapp_webhooks.get_openai_service",
                return_value=self._openai(4),
            ),
        ):
            await analyze_and_save_message(_make_webhook_message(), 42, "1")

        assert db.add.called
        inserted = db.add.call_args[0][0]
        assert inserted.message_id == "msg-1"
        assert inserted.importance_score == 4
        assert inserted.ai_analyzed is True

    async def _analyze_with_threshold(self, ai_importance, min_importance_level):
        """Run the analysis task against a user with a given digest threshold."""
        db = Mock(spec=Session)
        stored = self._stored_message(importance=1)
        repo_factory = _mock_repositories(existing_message=stored)

        with (
            patch("app.api.whatsapp_webhooks.repository_factory", repo_factory),
            patch(
                "app.database.connection.get_db_session",
                lambda: _fake_db_session(db),
            ),
            patch(
                "app.api.whatsapp_webhooks.get_openai_service",
                return_value=self._openai(ai_importance),
            ),
            patch(
                "app.api.whatsapp_webhooks.get_user_settings",
                return_value=Mock(min_importance_level=min_importance_level),
            ),
        ):
            await analyze_and_save_message(_make_webhook_message(importance=1), 42, "1")

        return stored

    @pytest.mark.asyncio
    async def test_below_threshold_message_is_marked_processed(self):
        """A message that can never reach a digest must not stay unprocessed

        Unprocessed rows are also exempt from cleanup, so they would pile up
        forever.
        """
        stored = await self._analyze_with_threshold(
            ai_importance=2, min_importance_level=3
        )

        assert stored.importance_score == 2
        assert stored.is_processed is True

    @pytest.mark.asyncio
    async def test_digest_eligible_message_stays_unprocessed(self):
        """Anything the digest can still pick up must remain pending"""
        stored = await self._analyze_with_threshold(
            ai_importance=3, min_importance_level=3
        )

        assert stored.importance_score == 3
        assert stored.is_processed is False

    @pytest.mark.asyncio
    async def test_user_threshold_is_respected_over_the_default(self):
        """A user who wants low-importance messages still gets them"""
        stored = await self._analyze_with_threshold(
            ai_importance=2, min_importance_level=1
        )

        assert stored.is_processed is False


class TestUrgentNotificationSettings:
    """Urgent alerts respect the user's urgent_notifications setting"""

    @staticmethod
    async def _send(urgent_notifications):
        """Run send_urgent_notification with a given setting; return the telegram mock."""
        db = Mock(spec=Session)
        telegram = Mock()
        telegram.send_notification = AsyncMock()

        user = create_test_user(id=1, username="testuser", is_active=True)
        user.telegram_channel_id = "channel-1"
        openai_service = Mock()
        openai_service.translate_to_russian = AsyncMock(return_value="перевод")

        repo_factory = _mock_repositories(user=user)
        repo_factory.get_monitored_chat_repository().get_by_user_and_chat_id.return_value.custom_name = (
            "Школа"
        )

        from app.api.whatsapp_webhooks import send_urgent_notification

        with (
            patch("app.api.whatsapp_webhooks.repository_factory", repo_factory),
            patch(
                "app.database.connection.get_db_session",
                lambda: _fake_db_session(db),
            ),
            patch(
                "app.api.whatsapp_webhooks.get_telegram_service", return_value=telegram
            ),
            patch(
                "app.api.whatsapp_webhooks.get_openai_service",
                return_value=openai_service,
            ),
            patch(
                "app.api.whatsapp_webhooks.get_user_settings",
                return_value=Mock(urgent_notifications=urgent_notifications),
            ),
        ):
            await send_urgent_notification(_make_webhook_message(), "1")

        return telegram

    @pytest.mark.asyncio
    async def test_disabled_setting_suppresses_alert(self):
        telegram = await self._send(urgent_notifications=False)

        telegram.send_notification.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_enabled_setting_sends_alert(self):
        telegram = await self._send(urgent_notifications=True)

        telegram.send_notification.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_missing_setting_defaults_to_enabled(self):
        """Urgent alerts are opt-out, so an unset value keeps them on"""
        telegram = await self._send(urgent_notifications=None)

        telegram.send_notification.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_settings_lookup_failure_defaults_to_enabled(self):
        from app.api.whatsapp_webhooks import _urgent_notifications_enabled

        with patch(
            "app.api.whatsapp_webhooks.get_user_settings",
            side_effect=Exception("no settings"),
        ):
            assert _urgent_notifications_enabled(1, Mock(spec=Session)) is True


class TestConnectionRestoredTask:
    """Test the /connected background task session handling"""

    @pytest.mark.asyncio
    async def test_opens_its_own_session(self):
        """Test that the task does not reuse the closed request session"""
        from app.api.whatsapp_webhooks import reconnection_service

        db = Mock(spec=Session)
        user = create_test_user(id=1, username="testuser")
        user.telegram_channel_id = "channel-1"
        repo_factory = _mock_repositories(user=user)
        telegram = Mock()
        telegram.send_notification = AsyncMock()
        opened = []

        @contextmanager
        def tracking_session():
            opened.append(db)
            yield db

        with (
            patch("app.api.whatsapp_webhooks.repository_factory", repo_factory),
            patch("app.database.connection.get_db_session", tracking_session),
            patch(
                "app.api.whatsapp_webhooks.get_telegram_service", return_value=telegram
            ),
        ):
            await reconnection_service.handle_connection_restored("1")

        assert opened == [db]
        telegram.send_notification.assert_awaited_once()
        assert telegram.send_notification.await_args[0][0] == "channel-1"

    @pytest.mark.asyncio
    async def test_connected_endpoint_queues_task_without_request_session(self):
        """Test that the request-scoped session is not handed to the task"""
        from app.api.whatsapp_webhooks import (
            WhatsAppConnectionWebhook,
            reconnection_service,
            whatsapp_connected,
        )

        db = Mock(spec=Session)
        background_tasks = BackgroundTasks()
        connection = WhatsAppConnectionWebhook(
            userId="1", timestamp="2026-01-01T10:00:00Z"
        )

        with patch(
            "app.api.whatsapp_webhooks.repository_factory", _mock_repositories()
        ):
            await whatsapp_connected(connection, background_tasks, db)

        assert len(background_tasks.tasks) == 1
        task = background_tasks.tasks[0]
        assert task.func == reconnection_service.handle_connection_restored
        assert task.args == ("1",)
