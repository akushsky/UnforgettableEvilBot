import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.core.data_cleanup import cleanup_service
from app.core.repository_factory import repository_factory
from app.database.connection import SessionLocal
from app.models.database import User
from app.openai_service.service import OpenAIService
from app.telegram.service import TelegramService
from app.whatsapp.service import WhatsAppService
from config.settings import settings

logger = logging.getLogger(__name__)


class DigestScheduler:
    """DigestScheduler class."""

    def __init__(self):
        """Initialize the class."""
        self.whatsapp_service = WhatsAppService(settings.WHATSAPP_SESSION_PATH)
        self.openai_service = OpenAIService()
        self.telegram_service = TelegramService()
        self.is_running = False
        self.last_digest_run = None
        self.last_cleanup_run = None

    async def start_scheduler(self):
        """Start task scheduler"""
        self.is_running = True
        logger.info("Digest scheduler started")

        # Start a separate task for daily cleanup
        asyncio.create_task(self.daily_cleanup_scheduler())

        while self.is_running:
            try:
                await self.process_all_users()
                await asyncio.sleep(300)  # Check every 5 minutes
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                await asyncio.sleep(60)  # Wait a minute on error

    async def daily_cleanup_scheduler(self):
        """Daily data cleanup at 3:00 AM"""
        while self.is_running:
            try:
                now = datetime.utcnow()
                # Calculate time until next run (3:00 AM)
                next_run = now.replace(hour=3, minute=0, second=0, microsecond=0)
                if next_run <= now:
                    next_run += timedelta(days=1)

                wait_seconds = (next_run - now).total_seconds()
                logger.info(
                    f"Next daily cleanup scheduled for {next_run.strftime('%Y-%m-%d %H:%M:%S')} (in {wait_seconds / 3600:.1f} hours)"
                )

                await asyncio.sleep(wait_seconds)

                if self.is_running:
                    await self.run_daily_cleanup()

            except Exception as e:
                logger.error(f"Error in daily cleanup scheduler: {e}")
                await asyncio.sleep(3600)  # Wait an hour on error

    async def run_daily_cleanup(self):
        """Run daily cleanup with notifications"""
        try:
            logger.info("Starting daily data cleanup...")

            # Start cleanup
            cleanup_results = await cleanup_service.run_full_cleanup()

            if "error" not in cleanup_results:
                messages_deleted = cleanup_results.get("messages", {}).get(
                    "messages_deleted", 0
                )
                digests_deleted = cleanup_results.get("digests", {}).get(
                    "digests_deleted", 0
                )
                logs_deleted = cleanup_results.get("system_logs", {}).get(
                    "logs_deleted", 0
                )
                users_processed = cleanup_results.get("messages", {}).get(
                    "users_processed", 0
                )

                # Send notification to administrator
                await self.send_cleanup_notification(
                    messages_deleted, digests_deleted, logs_deleted, users_processed
                )

                logger.info(
                    f"Daily cleanup completed: {messages_deleted} messages, "
                    f"{digests_deleted} digests, {logs_deleted} logs deleted, "
                    f"{users_processed} users processed"
                )
            else:
                logger.error(f"Daily cleanup failed: {cleanup_results['error']}")
                await self.send_cleanup_error_notification(cleanup_results["error"])

        except Exception as e:
            logger.error(f"Error in daily cleanup: {e}")
            await self.send_cleanup_error_notification(str(e))
        finally:
            # Update last cleanup run time
            self.last_cleanup_run = datetime.utcnow()

    async def send_cleanup_notification(
        self,
        messages_deleted: int,
        digests_deleted: int,
        logs_deleted: int,
        users_processed: int,
    ):
        """Send notification about cleanup results"""
        try:
            message = f"""🧹 **Ежедневная очистка данных завершена**

📊 **Результаты:**
• Сообщений удалено: {messages_deleted}
• Дайджестов удалено: {digests_deleted}
• Системных логов удалено: {logs_deleted}
• Пользователей обработано: {users_processed}

⏰ Время: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"""

            # Send to all active users with configured Telegram channels
            db = SessionLocal()
            try:
                users = repository_factory.get_user_repository().get_active_users_with_telegram(
                    db
                )

                for user in users:
                    try:
                        await self.telegram_service.send_notification(
                            user.telegram_channel_id, message
                        )
                    except Exception as e:
                        logger.error(
                            f"Failed to send cleanup notification to user {user.username}: {e}"
                        )

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error sending cleanup notification: {e}")

    async def send_cleanup_error_notification(self, error_message: str):
        """Send notification about cleanup error"""
        try:
            message = f"""❌ **Ошибка ежедневной очистки данных**

🔍 **Детали ошибки:**
{error_message}

⏰ Время: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC

⚠️ Рекомендуется проверить логи системы."""

            # Send to administrator
            db = SessionLocal()
            try:
                admin_user = repository_factory.get_user_repository().get_by_id(
                    db, 1
                )  # Assuming user ID 1 is admin
                if admin_user and admin_user.telegram_channel_id:
                    await self.telegram_service.send_notification(
                        admin_user.telegram_channel_id, message
                    )
            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error sending cleanup error notification: {e}")

    async def process_all_users(self):
        """Processing all users"""
        db = SessionLocal()
        try:
            users = (
                repository_factory.get_user_repository().get_active_users_with_telegram(
                    db
                )
            )

            # Process each user in a separate session
            for user in users:
                try:
                    user_db = SessionLocal()  # New session for each user
                    if await self.should_create_digest(user, user_db):
                        await self.create_and_send_digest(user, user_db)
                    user_db.close()
                except Exception as e:
                    logger.error(f"Error processing user {user.username}: {e}")
                    if "user_db" in locals():
                        user_db.rollback()
                        user_db.close()

            # Update last digest run time
            self.last_digest_run = datetime.utcnow()

        except Exception as e:
            logger.error(f"Error in process_all_users: {e}")
        finally:
            db.close()

    async def should_create_digest(self, user: User, db: Session) -> bool:
        """Check whether a digest should be created for the user"""
        return repository_factory.get_digest_log_repository().should_create_digest(
            db, user.id, user.digest_interval_hours
        )

    async def create_and_send_digest(self, user: User, db: Session):
        """Create and send a digest for the user"""
        try:
            logger.info(f"Creating digest for user {user.username}")

            # Get the user's monitored chats
            monitored_chats = repository_factory.get_monitored_chat_repository().get_active_chats_for_user(
                db, user.id
            )

            if not monitored_chats:
                logger.info(f"No monitored chats for user {user.username}")
                return

            # Get unprocessed messages from the database (arrived via webhook)
            # Group messages by chat
            chat_messages: Dict[str, List[Dict[str, Any]]] = {}
            total_important_messages = 0
            processed_message_ids = []

            for chat in monitored_chats:
                messages = repository_factory.get_whatsapp_message_repository().get_important_messages_for_digest(
                    db, chat.id, user.digest_interval_hours, 3
                )

                if messages:
                    chat_messages[chat.chat_name] = []
                    for msg in messages:
                        msg_data = {
                            "chat_name": chat.chat_name,
                            "sender": msg.sender,
                            "content": msg.content,
                            "importance": msg.importance_score,
                            "timestamp": msg.timestamp,
                        }
                        chat_messages[chat.chat_name].append(msg_data)
                        total_important_messages += 1
                        processed_message_ids.append(msg.id)

            # Mark all processed messages in batch
            if processed_message_ids:
                repository_factory.get_whatsapp_message_repository().mark_as_processed(
                    db, processed_message_ids
                )

            if not chat_messages:
                logger.info(f"No important messages for user {user.username}")
                return

            # Create the digest grouped by chats
            digest_content = await self.openai_service.create_digest_by_chats(
                chat_messages
            )

            # Send to Telegram
            success = await self.telegram_service.send_digest(
                str(user.telegram_channel_id), digest_content
            )

            # Save the digest log
            digest_log_data = {
                "user_id": user.id,
                "digest_content": digest_content,
                "message_count": total_important_messages,
                "telegram_sent": success,
            }
            repository_factory.get_digest_log_repository().create(db, digest_log_data)

            logger.info(
                f"Digest created and sent for user {user.username}. Messages: {total_important_messages}, Chats: {len(chat_messages)}"
            )

        except Exception as e:
            logger.error(f"Error creating digest for user {user.username}: {e}")
            db.rollback()

    def stop_scheduler(self):
        """Stop the scheduler"""
        self.is_running = False
        logger.info("Digest scheduler stopped")

    def get_next_run_time(self):
        """Get information about next scheduled runs"""
        if not self.is_running:
            return {
                "digest_processing": None,
                "daily_cleanup": None,
                "status": "stopped",
            }

        now = datetime.utcnow()

        # Calculate next digest processing (every 5 minutes from last run)
        if self.last_digest_run:
            next_digest = self.last_digest_run + timedelta(minutes=5)
            if next_digest <= now:
                next_digest = now + timedelta(minutes=5)
        else:
            next_digest = now + timedelta(minutes=5)

        # Calculate next daily cleanup (3:00 AM)
        next_cleanup = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if next_cleanup <= now:
            next_cleanup += timedelta(days=1)

        return {
            "digest_processing": next_digest.isoformat(),
            "daily_cleanup": next_cleanup.isoformat(),
            "status": "running",
            "last_digest_run": (
                self.last_digest_run.isoformat() if self.last_digest_run else None
            ),
            "last_cleanup_run": (
                self.last_cleanup_run.isoformat() if self.last_cleanup_run else None
            ),
        }

    async def run_data_cleanup(self):
        """Start data cleanup"""
        try:
            logger.info("Starting scheduled data cleanup...")
            cleanup_results = await cleanup_service.run_full_cleanup()

            if "error" not in cleanup_results:
                messages_deleted = cleanup_results.get("messages", {}).get(
                    "messages_deleted", 0
                )
                digests_deleted = cleanup_results.get("digests", {}).get(
                    "digests_deleted", 0
                )
                logs_deleted = cleanup_results.get("system_logs", {}).get(
                    "logs_deleted", 0
                )

                logger.info(
                    f"Data cleanup completed: {messages_deleted} messages, "
                    f"{digests_deleted} digests, {logs_deleted} logs deleted"
                )
            else:
                logger.error(f"Data cleanup failed: {cleanup_results['error']}")

        except Exception as e:
            logger.error(f"Error in data cleanup: {e}")
