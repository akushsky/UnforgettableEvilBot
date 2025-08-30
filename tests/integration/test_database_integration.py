from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.repositories import (
    DigestLogRepository,
    UserRepository,
    WhatsAppMessageRepository,
)
from app.core.repository_factory import repository_factory
from app.models.database import (
    DigestLog,
    MonitoredChat,
    OpenAIMetrics,
    ResourceSavings,
    SystemLog,
    User,
    WhatsAppMessage,
)


class TestDatabaseIntegration:
    """Integration tests for database operations with real database."""

    def test_user_creation_and_retrieval(self, db_session: Session, clean_database):
        """Test creating and retrieving users from the database."""
        # Create a user
        user = User(
            username="integration_test_user",
            email="integration@test.com",
            hashed_password="hashed_password_123",
            is_active=True,
            whatsapp_connected=True,
            created_at=datetime.utcnow(),
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        # Verify user was created
        assert user.id is not None
        assert user.username == "integration_test_user"
        assert user.email == "integration@test.com"

        # Retrieve user from database
        retrieved_user = (
            db_session.query(User)
            .filter(User.username == "integration_test_user")
            .first()
        )
        assert retrieved_user is not None
        assert retrieved_user.id == user.id
        assert retrieved_user.email == "integration@test.com"

    def test_user_repository_integration(self, db_session: Session, clean_database):
        """Test user repository with real database operations."""
        user_repo = UserRepository()

        # Create user via repository
        user = User(
            username="repo_test_user",
            email="repo@test.com",
            hashed_password="hashed_password_123",
            is_active=True,
            whatsapp_connected=True,
            created_at=datetime.utcnow(),
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        # Verify user was created
        assert user.id is not None
        assert user.username == "repo_test_user"

        # Retrieve user via repository
        retrieved_user = user_repo.get_by_username(db_session, "repo_test_user")
        assert retrieved_user is not None
        assert retrieved_user.email == "repo@test.com"

        # Update user via repository
        updated_user = user_repo.update(db_session, user, {"is_active": False})
        assert updated_user.is_active is False

        # Verify update persisted
        retrieved_user = user_repo.get_by_id(db_session, user.id)
        assert retrieved_user is not None
        assert retrieved_user.is_active is False

    def test_chat_and_messages_integration(self, db_session: Session, clean_database):
        """Test creating chats and messages with relationships."""
        # Create user
        user = User(
            username="chat_test_user",
            email="chat@test.com",
            hashed_password="hashed_password_123",
            is_active=True,
            created_at=datetime.utcnow(),
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        # Create chat
        chat = MonitoredChat(
            user_id=user.id,
            chat_name="Test Chat",
            chat_id="test_chat_123",
            chat_type="group",  # Required field
            is_active=True,
            created_at=datetime.utcnow(),
        )
        db_session.add(chat)
        db_session.commit()
        db_session.refresh(chat)

        # Create messages
        messages = []
        for i in range(3):
            message = WhatsAppMessage(
                chat_id=chat.id,
                message_id=f"msg_{i}",
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

        # Verify relationships
        retrieved_chat = (
            db_session.query(MonitoredChat).filter(MonitoredChat.id == chat.id).first()
        )
        assert retrieved_chat is not None
        assert retrieved_chat.user_id == user.id

        retrieved_messages = (
            db_session.query(WhatsAppMessage)
            .filter(WhatsAppMessage.chat_id == chat.id)
            .all()
        )
        assert len(retrieved_messages) == 3

        # Test message repository
        msg_repo = WhatsAppMessageRepository()
        chat_messages = msg_repo.get_messages_by_chat_ids(db_session, [chat.id])
        assert len(chat_messages) == 3

    def test_digest_logs_integration(
        self, db_session: Session, clean_database, sample_user
    ):
        """Test digest logs with real database operations."""
        digest_repo = DigestLogRepository()

        # Create digest logs
        digests = []
        for i in range(3):
            digest = DigestLog(
                user_id=sample_user.id,
                digest_content=f"Test digest content {i}",
                message_count=i + 1,
                created_at=datetime.utcnow() - timedelta(days=i),
            )
            digests.append(digest)

        db_session.add_all(digests)
        db_session.commit()

        # Test repository methods
        user_digests = digest_repo.get_digests_for_period(
            db_session, sample_user.id, days_back=7
        )
        assert len(user_digests) == 3

        last_digest = digest_repo.get_last_digest_for_user(db_session, sample_user.id)
        assert last_digest is not None
        assert (
            "Test digest content 0" in last_digest.digest_content
        )  # Most recent (day 0)

    def test_system_logs_integration(self, db_session: Session, clean_database):
        """Test system logs with real database operations."""
        # Create system logs
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

        # Verify logs were created
        retrieved_logs = db_session.query(SystemLog).all()
        assert len(retrieved_logs) == 5

        # Test filtering
        recent_logs = (
            db_session.query(SystemLog)
            .filter(SystemLog.created_at >= datetime.utcnow() - timedelta(hours=2))
            .all()
        )
        assert len(recent_logs) == 2  # Logs from last 2 hours (0 and 1 hour ago)

    def test_resource_savings_integration(
        self, db_session: Session, clean_database, sample_user
    ):
        """Test resource savings with real database operations."""
        # Create resource savings
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

        # Verify savings were created
        retrieved_savings = (
            db_session.query(ResourceSavings)
            .filter(ResourceSavings.user_id == sample_user.id)
            .all()
        )
        assert len(retrieved_savings) == 3

        # Test calculations
        total_messages = sum(s.messages_processed_saved for s in retrieved_savings)
        assert total_messages == 30  # 0 + 10 + 20

        total_storage = sum(s.memory_mb_saved for s in retrieved_savings)
        assert total_storage == 16.5  # 0 + 5.5 + 11.0

    def test_openai_metrics_integration(self, db_session: Session, clean_database):
        """Test OpenAI metrics with real database operations."""
        # Create metrics
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

        # Verify metrics were created
        retrieved_metrics = db_session.query(OpenAIMetrics).all()
        assert len(retrieved_metrics) == 5

        # Test aggregations
        total_cost = sum(m.cost_usd for m in retrieved_metrics)
        assert total_cost == 0.10  # 0 + 0.01 + 0.02 + 0.03 + 0.04

        total_input_tokens = sum(m.input_tokens for m in retrieved_metrics)
        assert total_input_tokens == 1000  # 0 + 100 + 200 + 300 + 400

    def test_database_constraints(self, db_session: Session, clean_database):
        """Test database constraints and integrity."""
        # Test unique username constraint
        user1 = User(
            username="unique_test_user",
            email="unique1@test.com",
            hashed_password="hashed_password_123",
            is_active=True,
            created_at=datetime.utcnow(),
        )
        db_session.add(user1)
        db_session.commit()

        # Try to create another user with same username
        user2 = User(
            username="unique_test_user",  # Same username
            email="unique2@test.com",
            hashed_password="hashed_password_123",
            is_active=True,
            created_at=datetime.utcnow(),
        )
        db_session.add(user2)

        with pytest.raises(IntegrityError):
            db_session.commit()

        db_session.rollback()

    def test_transaction_rollback(self, db_session: Session, clean_database):
        """Test transaction rollback functionality."""
        # Start transaction
        user = User(
            username="rollback_test_user",
            email="rollback@test.com",
            hashed_password="hashed_password_123",
            is_active=True,
            created_at=datetime.utcnow(),
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        # Verify user exists
        assert user.id is not None

        # Simulate error and rollback
        try:
            # Try to create invalid data
            invalid_user = User(
                username=None,  # Invalid - should cause error
                email="invalid@test.com",
                hashed_password="hashed_password_123",
                is_active=True,
                created_at=datetime.utcnow(),
            )
            db_session.add(invalid_user)
            db_session.commit()
        except BaseException:
            db_session.rollback()

        # Verify original user still exists
        retrieved_user = (
            db_session.query(User).filter(User.username == "rollback_test_user").first()
        )
        assert retrieved_user is not None
        assert retrieved_user.email == "rollback@test.com"

    def test_repository_factory_integration(self, db_session: Session, clean_database):
        """Test repository factory with real database operations."""
        # Create test data
        user = User(
            username="factory_test_user",
            email="factory@test.com",
            hashed_password="hashed_password_123",
            is_active=True,
            created_at=datetime.utcnow(),
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        # Test repository factory
        user_repo = repository_factory.get_user_repository()
        retrieved_user = user_repo.get_by_username(db_session, "factory_test_user")
        assert retrieved_user is not None
        assert retrieved_user.email == "factory@test.com"

        # Test optimized repository factory
        optimized_user_repo = (
            repository_factory.get_user_repository()
        )  # Use regular repository for now
        retrieved_user = optimized_user_repo.get_by_username(
            db_session, "factory_test_user"
        )
        assert retrieved_user is not None
        assert retrieved_user.email == "factory@test.com"
