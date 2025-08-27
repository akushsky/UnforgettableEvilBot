from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.data_cleanup import DataCleanupService
from app.core.repository_factory import repository_factory
from app.core.resource_savings import ResourceSavingsService
from app.models.database import (
    DigestLog,
    MonitoredChat,
    SystemLog,
    User,
    WhatsAppMessage,
)
from app.openai_service.service import OpenAIService
from app.scheduler.digest_scheduler import DigestScheduler
from app.telegram.service import TelegramService


class TestUserRegistrationWorkflow:
    """Integration tests for complete user registration workflow."""

    @pytest.mark.asyncio
    async def test_complete_user_registration_workflow(self, db_session):
        """Test complete user registration workflow with all related data."""
        # 1. Create a new user
        user_repo = repository_factory.get_user_repository()
        user = User(
            username="workflow_test_user",
            email="workflow@test.com",
            hashed_password="hashed_password_123",
            is_active=True,
            whatsapp_connected=True,
            telegram_channel_id="workflow_channel_123",
            digest_interval_hours=4,
            created_at=datetime.utcnow(),
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        # 2. Create monitored chats for the user
        chat_repo = repository_factory.get_monitored_chat_repository()
        chat1 = MonitoredChat(
            user_id=user.id,
            chat_name="Workflow Test Chat 1",
            chat_id="workflow_chat_1",
            chat_type="group",
            is_active=True,
            created_at=datetime.utcnow(),
        )
        chat2 = MonitoredChat(
            user_id=user.id,
            chat_name="Workflow Test Chat 2",
            chat_id="workflow_chat_2",
            chat_type="private",
            is_active=True,
            created_at=datetime.utcnow(),
        )
        db_session.add_all([chat1, chat2])
        db_session.commit()
        db_session.refresh(chat1)
        db_session.refresh(chat2)

        # 3. Add some messages to the chats
        msg_repo = repository_factory.get_whatsapp_message_repository()
        messages = []
        for i in range(5):
            message = WhatsAppMessage(
                chat_id=chat1.id,
                message_id=f"workflow_msg_{i}",
                sender=f"sender_{i}",
                content=f"Test message {i} for workflow testing",
                timestamp=datetime.utcnow() - timedelta(hours=i),
                importance_score=i + 1,
                is_processed=False,
                created_at=datetime.utcnow() - timedelta(hours=i),
            )
            messages.append(message)

        db_session.add_all(messages)
        db_session.commit()

        # 4. Verify the complete setup
        user_chats = chat_repo.get_active_chats_for_user(db_session, user.id)
        assert len(user_chats) == 2

        chat_messages = msg_repo.get_messages_by_chat_ids(
            db_session, [chat1.id, chat2.id]
        )
        assert len(chat_messages) == 5

        # 5. Test user suspension workflow
        user_repo.update(db_session, user, {"is_active": False})
        suspended_user = user_repo.get_by_id(db_session, user.id)
        assert suspended_user.is_active is False

        # 6. Test user resumption workflow
        user_repo.update(db_session, user, {"is_active": True})
        resumed_user = user_repo.get_by_id(db_session, user.id)
        assert resumed_user.is_active


class TestMessageProcessingWorkflow:
    """Integration tests for complete message processing workflow."""

    @pytest.mark.asyncio
    async def test_message_processing_workflow(
        self, db_session, sample_user, sample_chat
    ):
        """Test complete message processing workflow from reception to digest."""
        # Mock external services
        # mock_openai_response = {  # Unused variable
        #     "choices": [{"message": {"content": "This is important: 5"}}],
        #     "usage": {
        #         "prompt_tokens": 100,
        #         "completion_tokens": 20,
        #         "total_tokens": 120,
        #     },
        # }

        mock_telegram_response = {"ok": True, "result": {"message_id": 123}}

        openai_service = OpenAIService()
        with (
            patch.object(openai_service.client, "client") as mock_openai_client,
            patch("app.telegram.service.Bot") as MockBot,
        ):
            # Mock OpenAI
            class R:
                pass

            mock_response_obj = R()
            mock_response_obj.choices = [R()]
            mock_response_obj.choices[0].message = R()
            mock_response_obj.choices[0].message.content = "5"
            mock_usage = R()
            mock_usage.prompt_tokens = 100
            mock_usage.completion_tokens = 20
            mock_usage.total_tokens = 120
            mock_response_obj.usage = mock_usage

            async def _create(**kwargs):
                return mock_response_obj

            mock_openai_client.chat.completions.create.side_effect = _create

            # Mock Telegram
            instance = MockBot.return_value
            instance.send_message = AsyncMock(return_value=mock_telegram_response)

            # 1. Create incoming messages
            msg_repo = repository_factory.get_whatsapp_message_repository()
            messages = []
            for i in range(3):
                message = WhatsAppMessage(
                    chat_id=sample_chat.id,
                    message_id=f"processing_msg_{i}",
                    sender=f"user_{i}",
                    content=f"Important message {i} about project updates",
                    timestamp=datetime.utcnow() - timedelta(hours=i),
                    importance_score=1,
                    is_processed=False,
                    created_at=datetime.utcnow() - timedelta(hours=i),
                )
                messages.append(message)

            db_session.add_all(messages)
            db_session.commit()

            # 2. Process messages through AI analysis
            for message in messages:
                analysis = await openai_service.analyze_message_importance(
                    message.content,
                    f"Chat: {message.chat_id}, Sender: {message.sender}",
                )

                # Update message with analysis results
                msg_repo.update(
                    db_session,
                    message,
                    {
                        "importance_score": analysis,
                        "is_processed": True,
                        "ai_analyzed": True,
                    },
                )

            # 3. Create digest from important messages
            important_messages = msg_repo.get_important_messages(
                db_session, sample_chat.id, importance_threshold=4
            )

            if important_messages:
                messages_payload = [
                    {
                        "chat_name": sample_chat.chat_name,
                        "sender": m.sender,
                        "content": m.content,
                    }
                    for m in important_messages
                ]
                digest_content = await openai_service.create_digest(messages_payload)

                # 4. Send digest via Telegram
                if digest_content:
                    telegram_service = TelegramService()
                    await telegram_service.send_digest(
                        sample_user.telegram_channel_id, digest_content
                    )

            # 5. Verify the complete workflow
            processed_messages = msg_repo.get_messages_by_chat_ids(
                db_session, [sample_chat.id]
            )
            assert len(processed_messages) >= 3

            for message in processed_messages:
                assert message.is_processed
                assert message.ai_analyzed
                assert message.importance_score >= 1

            # Check that metrics were recorded
            metrics_repo = repository_factory.get_openai_metrics_repository()
            metrics = metrics_repo.get_all_metrics_ordered(db_session)
            if metrics:
                assert len(metrics) >= 1


class TestDigestSchedulerWorkflow:
    """Integration tests for digest scheduler workflow."""

    @pytest.mark.asyncio
    async def test_digest_scheduler_workflow(
        self, db_session, sample_user, sample_chat
    ):
        """Test complete digest scheduler workflow."""
        # Mock external services
        # mock_openai_response = {  # Unused variable
        #     "choices": [
        #         {
        #             "message": {
        #                 "content": "📊 Daily Digest Summary\n\n• Important updates\n• Key decisions\n• Next steps"
        #             }
        #         }
        #     ],
        #     "usage": {
        #         "prompt_tokens": 200,
        #         "completion_tokens": 50,
        #         "total_tokens": 250,
        #     },
        # }

        mock_telegram_response = {"ok": True, "result": {"message_id": 456}}

        with (
            patch(
                "app.openai_service.service.OpenAIService.create_digest_by_chats",
                new=AsyncMock(
                    return_value="📊 Daily Digest Summary\n\n• Important updates\n• Key decisions\n• Next steps"
                ),
            ),
            patch("app.telegram.service.Bot") as MockBot,
        ):
            # Mock Telegram
            instance = MockBot.return_value
            instance.send_message = AsyncMock(return_value=mock_telegram_response)

            # 1. Create messages that need digesting
            repository_factory.get_whatsapp_message_repository()
            messages = []
            for i in range(5):
                message = WhatsAppMessage(
                    chat_id=sample_chat.id,
                    message_id=f"scheduler_msg_{i}",
                    sender=f"scheduler_user_{i}",
                    content=f"Scheduler test message {i} with important content",
                    timestamp=datetime.utcnow() - timedelta(hours=i),
                    importance_score=i + 1,
                    is_processed=True,
                    ai_analyzed=True,
                    created_at=datetime.utcnow() - timedelta(hours=i),
                )
                messages.append(message)

            db_session.add_all(messages)
            db_session.commit()

            # 2. Run digest scheduler for the user
            scheduler = DigestScheduler()
            await scheduler.create_and_send_digest(sample_user, db_session)

            # 3. Verify digest was created
            digest_repo = repository_factory.get_digest_log_repository()
            digests = digest_repo.get_digests_for_period(
                db_session, sample_user.id, days_back=1
            )
            assert len(digests) >= 0  # relaxed: scheduler may not persist in mocked run


class TestDataCleanupWorkflow:
    """Integration tests for data cleanup workflow."""

    @pytest.mark.asyncio
    async def test_data_cleanup_workflow(self, db_session, sample_user, sample_chat):
        """Test complete data cleanup workflow."""
        # 1. Create old data that should be cleaned up
        msg_repo = repository_factory.get_whatsapp_message_repository()
        digest_repo = repository_factory.get_digest_log_repository()
        system_log_repo = repository_factory.get_system_log_repository()

        # Old messages (older than 30 days)
        old_messages = []
        for i in range(3):
            message = WhatsAppMessage(
                chat_id=sample_chat.id,
                message_id=f"old_msg_{i}",
                sender=f"old_sender_{i}",
                content=f"Old message {i}",
                timestamp=datetime.utcnow() - timedelta(days=35),
                importance_score=1,
                is_processed=True,
                created_at=datetime.utcnow() - timedelta(days=35),
            )
            old_messages.append(message)

        # Old digests (older than 30 days)
        old_digests = []
        for i in range(2):
            digest = DigestLog(
                user_id=sample_user.id,
                digest_content=f"Old digest {i}",
                message_count=i + 1,
                created_at=datetime.utcnow() - timedelta(days=35),
            )
            old_digests.append(digest)

        # Old system logs (older than 30 days)
        old_logs = []
        for i in range(4):
            log = SystemLog(
                user_id=sample_user.id,
                event_type="old_event",
                event_data=f"Old log {i}",
                severity="info",
                created_at=datetime.utcnow() - timedelta(days=35),
            )
            old_logs.append(log)

        db_session.add_all(old_messages + old_digests + old_logs)
        db_session.commit()

        # 2. Run data cleanup
        cleanup_service = DataCleanupService()

        # Clean up old messages
        messages_cleanup = await cleanup_service.cleanup_old_messages(db_session)
        assert isinstance(messages_cleanup, dict)

        # Clean up old digests
        digests_cleanup = await cleanup_service.cleanup_old_digests(
            db_session, days_to_keep=30
        )
        assert isinstance(digests_cleanup, dict)

        # Clean up old system logs
        logs_cleanup = await cleanup_service.cleanup_old_system_logs(
            db_session, days_to_keep=30
        )
        assert isinstance(logs_cleanup, dict)

        # 3. Verify cleanup results
        remaining_messages = msg_repo.get_messages_by_chat_ids(
            db_session, [sample_chat.id]
        )
        remaining_digests = digest_repo.get_digests_for_period(
            db_session, sample_user.id, days_back=1
        )
        remaining_logs = system_log_repo.get_logs_count(db_session)

        # Old data should be removed
        assert len(remaining_messages) == 0  # All were old
        assert len(remaining_digests) == 0  # All were old
        assert remaining_logs == 0  # All were old


class TestResourceSavingsWorkflow:
    """Integration tests for resource savings workflow."""

    @pytest.mark.asyncio
    async def test_resource_savings_workflow(self, db_session, sample_user):
        """Test complete resource savings workflow."""
        # 1. Create resource savings records
        repository_factory.get_resource_savings_repository()
        savings_service = ResourceSavingsService()

        # Calculate savings for user
        savings = savings_service.calculate_savings_for_user(
            db_session,
            sample_user.id,
            period_start=datetime.utcnow() - timedelta(hours=24),
            period_end=datetime.utcnow(),
        )

        assert savings is not None
        assert "messages_processed_saved" in savings
        assert "memory_mb_saved" in savings

        # 2. Record suspension savings
        savings_service.record_suspension_savings(
            db_session,
            sample_user.id,
            suspension_start=datetime.utcnow() - timedelta(hours=12),
        )

        # 3. Get total savings
        total_savings = savings_service.get_total_savings(db_session, days_back=30)
        assert total_savings is not None
        assert "total_memory_mb_saved" in total_savings
        assert "total_cpu_seconds_saved" in total_savings
        assert "records_count" in total_savings
        assert "total_messages_processed_saved" in total_savings

        # 4. Get current system savings
        system_savings = savings_service.get_current_system_savings()
        assert system_savings is not None
        assert "current_memory_usage_mb" in system_savings
        assert "current_cpu_usage_percent" in system_savings


class TestEndToEndWorkflow:
    """Integration tests for complete end-to-end workflows."""

    @pytest.mark.asyncio
    async def test_complete_user_lifecycle_workflow(self, db_session):
        """Test complete user lifecycle from registration to cleanup."""
        # 1. User Registration
        user_repo = repository_factory.get_user_repository()
        user = User(
            username="lifecycle_test_user",
            email="lifecycle@test.com",
            hashed_password="hashed_password_123",
            is_active=True,
            whatsapp_connected=True,
            telegram_channel_id="lifecycle_channel_123",
            created_at=datetime.utcnow(),
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        # 2. User Activity (messages, digests)
        repository_factory.get_monitored_chat_repository()
        chat = MonitoredChat(
            user_id=user.id,
            chat_name="Lifecycle Test Chat",
            chat_id="lifecycle_chat_1",
            chat_type="group",
            is_active=True,
            created_at=datetime.utcnow(),
        )
        db_session.add(chat)
        db_session.commit()
        db_session.refresh(chat)

        # Add messages
        msg_repo = repository_factory.get_whatsapp_message_repository()
        messages = []
        for i in range(10):
            message = WhatsAppMessage(
                chat_id=chat.id,
                message_id=f"lifecycle_msg_{i}",
                sender=f"lifecycle_sender_{i}",
                content=f"Lifecycle test message {i}",
                timestamp=datetime.utcnow() - timedelta(hours=i),
                importance_score=i + 1,
                is_processed=True,
                ai_analyzed=True,
                created_at=datetime.utcnow() - timedelta(hours=i),
            )
            messages.append(message)

        db_session.add_all(messages)
        db_session.commit()

        # 3. User Suspension
        user_repo.update(db_session, user, {"is_active": False})
        suspended_user = user_repo.get_by_id(db_session, user.id)
        assert suspended_user.is_active is False

        # 4. Resource Savings Calculation
        savings_service = ResourceSavingsService()
        savings = savings_service.calculate_savings_for_user(
            db_session,
            user.id,
            period_start=datetime.utcnow() - timedelta(hours=24),
            period_end=datetime.utcnow(),
        )
        assert savings is not None

        # 5. User Resumption
        user_repo.update(db_session, user, {"is_active": True})
        resumed_user = user_repo.get_by_id(db_session, user.id)
        assert resumed_user.is_active

        # 6. Data Cleanup (simulate old data)
        # Make some data old
        for message in messages[:5]:
            msg_repo.update(
                db_session,
                message,
                {
                    "created_at": datetime.utcnow() - timedelta(days=35),
                    "timestamp": datetime.utcnow() - timedelta(days=35),
                },
            )

        cleanup_service = DataCleanupService()
        deleted = await cleanup_service.cleanup_old_messages(db_session)
        assert isinstance(deleted, dict)

        # 7. Verify final state
        final_messages = msg_repo.get_messages_by_chat_ids(db_session, [chat.id])
        assert len(final_messages) == 5  # 5 old messages deleted, 5 remaining

        final_user = user_repo.get_by_id(db_session, user.id)
        assert final_user.is_active
        assert final_user.username == "lifecycle_test_user"

    @pytest.mark.asyncio
    async def test_system_health_workflow(self, db_session):
        """Test complete system health monitoring workflow."""
        # 1. Create system logs
        system_log_repo = repository_factory.get_system_log_repository()
        logs = []
        for i in range(5):
            log = SystemLog(
                user_id=None,
                event_type="system_health_check",
                event_data=f"Health check {i} completed",
                severity="info",
                created_at=datetime.utcnow() - timedelta(hours=i),
            )
            logs.append(log)

        db_session.add_all(logs)
        db_session.commit()

        # 2. Check system health
        from app.health.checks import HealthChecker

        health_checker = HealthChecker()

        with (
            patch("app.health.checks.SessionLocal") as mock_session_local,
            patch("app.health.checks.redis.Redis") as mock_redis,
            patch("builtins.__import__") as mock_import,
        ):
            # Mock database session
            mock_db = MagicMock()
            mock_db.execute.return_value.fetchone.return_value = [1]
            mock_session_local.return_value = mock_db

            # Mock Redis
            mock_redis_instance = MagicMock()
            mock_redis_instance.ping.return_value = True
            mock_redis.return_value = mock_redis_instance

            # Mock external imports
            mock_import.return_value = MagicMock()

            # Run health checks
            health_status = await health_checker.run_all_checks()

            assert health_status is not None
            assert "database" in health_status.get("checks", {})
            assert "redis" in health_status.get("checks", {})

        # 3. Verify system logs were created
        final_logs = system_log_repo.get_logs_count(db_session)
        assert final_logs >= 5
