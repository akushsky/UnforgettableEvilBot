from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.repository_factory import repository_factory
from app.database.connection import SessionLocal
from config.logging_config import get_logger
from config.settings import settings

logger = get_logger(__name__)


class DataCleanupService:
    """Service for automatic cleanup of old data"""

    def __init__(self):
        self.logger = get_logger(__name__)

    async def cleanup_old_messages(self, db: Session) -> Dict[str, int]:
        """Cleanup of old messages based on user settings"""
        try:
            cleanup_stats = {"messages_deleted": 0, "users_processed": 0, "errors": 0}

            # Get settings for all users
            from app.core.user_utils import get_user_settings

            # Get all users
            users = repository_factory.get_user_repository().get_all(db)

            for user in users:
                user_setting = get_user_settings(user.id, db)
                try:
                    # Get maximum message age for the user
                    max_age_hours = int(user_setting.max_message_age_hours)
                    cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)

                    # Find all user chats
                    user_chats = repository_factory.get_monitored_chat_repository().get_active_chats_for_user(
                        db, user_setting.user_id
                    )

                    chat_ids = [chat.id for chat in user_chats]

                    if chat_ids:
                        # Delete old messages
                        deleted_count = repository_factory.get_whatsapp_message_repository().delete_old_messages(
                            db, chat_ids, cutoff_time
                        )

                        cleanup_stats["messages_deleted"] += deleted_count
                        cleanup_stats["users_processed"] += 1

                        self.logger.info(
                            f"Cleaned up {deleted_count} old messages for user {user_setting.user_id} "
                            f"(older than {max_age_hours} hours)"
                        )

                except Exception as e:
                    self.logger.error(
                        f"Error cleaning messages for user {user_setting.user_id}: {e}"
                    )
                    cleanup_stats["errors"] += 1

            db.commit()
            return cleanup_stats

        except Exception as e:
            self.logger.error(f"Error in cleanup_old_messages: {e}")
            db.rollback()
            return {"messages_deleted": 0, "users_processed": 0, "errors": 1}

    async def cleanup_old_digests(
        self, db: Session, days_to_keep: Optional[int] = None
    ) -> Dict[str, int]:
        """Cleanup of old digests"""
        # Use settings default if not provided
        days_to_keep = days_to_keep or settings.CLEANUP_OLD_MESSAGES_DAYS

        try:
            cutoff_time = datetime.utcnow() - timedelta(days=days_to_keep)

            deleted_count = (
                repository_factory.get_digest_log_repository().delete_old_digests(
                    db, cutoff_time
                )
            )

            db.commit()

            self.logger.info(
                f"Cleaned up {deleted_count} old digests (older than {days_to_keep} days)"
            )

            return {"digests_deleted": deleted_count, "days_to_keep": days_to_keep}

        except Exception as e:
            self.logger.error(f"Error in cleanup_old_digests: {e}")
            db.rollback()
            return {"digests_deleted": 0, "errors": 1}

    async def cleanup_old_system_logs(
        self, db: Session, days_to_keep: Optional[int] = None
    ) -> Dict[str, int]:
        """Cleanup of old system logs"""
        # Use settings default if not provided
        days_to_keep = days_to_keep or settings.CLEANUP_OLD_SYSTEM_LOGS_DAYS

        try:
            cutoff_time = datetime.utcnow() - timedelta(days=days_to_keep)

            deleted_count = (
                repository_factory.get_system_log_repository().delete_old_logs(
                    db, cutoff_time
                )
            )

            db.commit()

            self.logger.info(
                f"Cleaned up {deleted_count} old system logs (older than {days_to_keep} days)"
            )

            return {"logs_deleted": deleted_count, "days_to_keep": days_to_keep}

        except Exception as e:
            self.logger.error(f"Error in cleanup_old_system_logs: {e}")
            db.rollback()
            return {"logs_deleted": 0, "errors": 1}

    async def get_storage_stats(self, db: Session) -> Dict[str, Any]:
        """Get storage usage statistics"""
        try:
            # Count messages
            total_messages = (
                repository_factory.get_whatsapp_message_repository().get_messages_count(
                    db
                )
            )

            # Count digests
            total_digests = (
                repository_factory.get_digest_log_repository().get_digests_count(db)
            )

            # Count system logs
            total_system_logs = (
                repository_factory.get_system_log_repository().get_logs_count(db)
            )

            # Old messages (older than 7 days)
            week_ago = datetime.utcnow() - timedelta(days=7)
            old_messages = repository_factory.get_whatsapp_message_repository().get_old_messages_count(
                db, week_ago
            )

            # Old digests (older than 30 days)
            month_ago = datetime.utcnow() - timedelta(days=30)
            old_digests = (
                repository_factory.get_digest_log_repository().get_old_digests_count(
                    db, month_ago
                )
            )

            return {
                "total_messages": total_messages,
                "total_digests": total_digests,
                "total_system_logs": total_system_logs,
                "old_messages_7_days": old_messages,
                "old_digests_30_days": old_digests,
                "estimated_cleanup_potential": {
                    "messages": old_messages,
                    "digests": old_digests,
                },
            }

        except Exception as e:
            self.logger.error(f"Error getting storage stats: {e}")
            return {"error": str(e)}

    async def run_full_cleanup(self) -> Dict[str, Any]:
        """Run full cleanup of all data types"""
        db = SessionLocal()

        try:
            cleanup_results = {
                "messages": await self.cleanup_old_messages(db),
                "digests": await self.cleanup_old_digests(db),
                "system_logs": await self.cleanup_old_system_logs(db),
                "storage_stats": await self.get_storage_stats(db),
            }

            self.logger.info("Full data cleanup completed successfully")
            return cleanup_results

        except Exception as e:
            self.logger.error(f"Error in full cleanup: {e}")
            return {"error": str(e)}
        finally:
            db.close()


# Global service instance
cleanup_service = DataCleanupService()
