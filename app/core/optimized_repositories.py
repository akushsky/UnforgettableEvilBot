# mypy: disable-error-code="no-any-return"
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import asc, desc, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from app.core.cache import cached, invalidate_cache
from app.core.repositories import BaseRepository
from app.models.database import DigestLog, User, WhatsAppMessage
from config.logging_config import get_logger

logger = get_logger(__name__)


class OptimizedUserRepository(BaseRepository):
    """Optimized repository for working with users"""

    def __init__(self):
        """Init  ."""
        super().__init__(User)

    @cached(prefix="user", ttl=300)  # cache for 5 minutes
    def get_by_username(self, db: Session, username: str) -> Optional[User]:
        """Get a user by username with caching"""
        return db.query(User).filter(User.username == username).first()

    @cached(prefix="user_email", ttl=300)
    def get_by_email(self, db: Session, email: str) -> Optional[User]:
        """Get a user by email with caching"""
        return db.query(User).filter(User.email == email).first()

    @cached(prefix="active_users", ttl=60)  # cache for 1 minute
    def get_active_users(self, db: Session) -> List[User]:
        """Get active users with caching"""
        return db.query(User).filter(User.is_active, User.whatsapp_connected).all()

    @cached(prefix="active_users_with_telegram", ttl=60)
    def get_active_users_with_telegram(self, db: Session) -> List[User]:
        """Get active users with configured Telegram channels"""
        return (
            db.query(User)
            .filter(User.is_active, User.telegram_channel_id.isnot(None))
            .all()
        )

    @cached(prefix="users_with_chats", ttl=120)
    def get_users_with_chats(self, db: Session) -> List[User]:
        """Get users with their chats (eager loading)"""
        return (
            db.query(User)
            .options(joinedload(User.monitored_chats))
            .filter(User.is_active)
            .all()
        )

    @cached(prefix="user_full_data", ttl=180)
    def get_user_with_full_data(self, db: Session, user_id: int) -> Optional[User]:
        """Get a user with all related data"""
        return (
            db.query(User)
            .options(joinedload(User.monitored_chats), joinedload(User.digest_logs))
            .filter(User.id == user_id)
            .first()
        )

    @invalidate_cache(pattern="user*")  # Invalidate cache on update
    def update_whatsapp_status(
        self, db: Session, user_id: int, connected: bool
    ) -> User:
        """Update WhatsApp connection status"""
        user = self.get_by_id_or_404(db, user_id)
        user.whatsapp_connected = connected
        user.whatsapp_last_seen = datetime.utcnow()
        db.commit()
        db.refresh(user)
        return user

    def get_users_batch(self, db: Session, user_ids: List[int]) -> List[User]:
        """Get users in batches for optimization"""
        if not user_ids:
            return []

        return db.query(User).filter(User.id.in_(user_ids)).all()

    def update_users_batch(self, db: Session, updates: List[Tuple[int, Dict]]) -> int:
        """Batch update users"""
        if not updates:
            return 0

        updated_count = 0
        for user_id, update_data in updates:
            try:
                user = self.get_by_id(db, user_id)
                if user:
                    for field, value in update_data.items():
                        if hasattr(user, field):
                            setattr(user, field, value)
                    updated_count += 1
            except Exception as e:
                logger.error(f"Error updating user {user_id}: {e}")

        db.commit()
        return updated_count


class OptimizedWhatsAppMessageRepository(BaseRepository):
    """Optimized repository for WhatsApp messages"""

    def __init__(self):
        """Init  ."""
        super().__init__(WhatsAppMessage)

    @cached(prefix="message_by_id", ttl=600)  # cache for 10 minutes
    def get_by_message_id(
        self, db: Session, message_id: str
    ) -> Optional[WhatsAppMessage]:
        """Get a message by ID with caching"""
        return (
            db.query(WhatsAppMessage)
            .filter(WhatsAppMessage.message_id == message_id)
            .first()
        )

    def get_unprocessed_messages(
        self, db: Session, chat_id: int, limit: int = 100
    ) -> List[WhatsAppMessage]:
        """Get unprocessed messages with a limit"""
        return (
            db.query(WhatsAppMessage)
            .filter(
                WhatsAppMessage.chat_id == chat_id,
                WhatsAppMessage.is_processed.is_(False),
            )
            .order_by(WhatsAppMessage.timestamp.asc())
            .limit(limit)
            .all()
        )

    @cached(prefix="important_messages", ttl=300)
    def get_important_messages(
        self, db: Session, chat_id: int, importance_threshold: int = 3, limit: int = 50
    ) -> List[WhatsAppMessage]:
        """Get important messages with caching"""
        return (
            db.query(WhatsAppMessage)
            .filter(
                WhatsAppMessage.chat_id == chat_id,
                WhatsAppMessage.importance_score >= importance_threshold,
            )
            .order_by(desc(WhatsAppMessage.timestamp))
            .limit(limit)
            .all()
        )

    def get_messages_for_digest(
        self, db: Session, chat_id: int, hours_back: int = 24
    ) -> List[WhatsAppMessage]:
        """Get messages for a digest with optimization"""
        cutoff_time = datetime.utcnow() - timedelta(hours=hours_back)

        # Use an index by timestamp for optimization
        return (
            db.query(WhatsAppMessage)
            .filter(
                WhatsAppMessage.chat_id == chat_id,
                WhatsAppMessage.timestamp >= cutoff_time,
                WhatsAppMessage.is_processed.is_(False),
            )
            .order_by(asc(WhatsAppMessage.timestamp))
            .all()
        )

    def mark_as_processed_batch(self, db: Session, message_ids: List[int]) -> int:
        """Batch mark messages as processed"""
        if not message_ids:
            return 0

        try:
            # Use bulk update for optimization
            result = (
                db.query(WhatsAppMessage)
                .filter(WhatsAppMessage.id.in_(message_ids))
                .update({"is_processed": True}, synchronize_session=False)
            )

            db.commit()
            return result
        except SQLAlchemyError as e:
            logger.error(f"Error in batch mark as processed: {e}")
            db.rollback()
            return 0

    def get_message_stats(
        self, db: Session, chat_id: int, days_back: int = 7
    ) -> Dict[str, Any]:
        """Get message statistics"""
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)

        stats = (
            db.query(
                func.count(WhatsAppMessage.id).label("total_messages"),
                func.avg(WhatsAppMessage.importance_score).label("avg_importance"),
                func.max(WhatsAppMessage.importance_score).label("max_importance"),
                func.count(WhatsAppMessage.id)
                .filter(WhatsAppMessage.is_processed.is_(False))
                .label("unprocessed_messages"),
            )
            .filter(
                WhatsAppMessage.chat_id == chat_id,
                WhatsAppMessage.timestamp >= cutoff_date,
            )
            .first()
        )

        return {
            "total_messages": stats.total_messages or 0,
            "avg_importance": float(stats.avg_importance or 0),
            "max_importance": stats.max_importance or 0,
            "unprocessed_messages": stats.unprocessed_messages or 0,
            "period_days": days_back,
        }

    def cleanup_old_messages(self, db: Session, days_to_keep: int = 30) -> int:
        """Cleanup old messages to optimize the DB"""
        cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)

        try:
            # Delete old processed messages
            result = (
                db.query(WhatsAppMessage)
                .filter(
                    WhatsAppMessage.timestamp < cutoff_date,
                    WhatsAppMessage.is_processed,
                )
                .delete(synchronize_session=False)
            )

            db.commit()
            logger.info(f"Cleaned up {result} old messages")
            return result
        except SQLAlchemyError as e:
            logger.error(f"Error cleaning up old messages: {e}")
            db.rollback()
            return 0

    def get_messages_by_chat_ids(
        self, db: Session, chat_ids: List[int], limit: int = 100
    ) -> List[WhatsAppMessage]:
        """Get messages by chat IDs for integration tests"""
        if not chat_ids:
            return []

        return (
            db.query(WhatsAppMessage)
            .filter(WhatsAppMessage.chat_id.in_(chat_ids))
            .order_by(desc(WhatsAppMessage.timestamp))
            .limit(limit)
            .all()
        )

    def delete_old_messages(
        self, db: Session, chat_ids: List[int], cutoff_time: datetime
    ) -> int:
        """Delete old messages for specified chats"""
        try:
            result = (
                db.query(WhatsAppMessage)
                .filter(
                    WhatsAppMessage.chat_id.in_(chat_ids),
                    WhatsAppMessage.timestamp < cutoff_time,
                )
                .delete(synchronize_session=False)
            )
            db.commit()
            return result
        except SQLAlchemyError as e:
            logger.error(f"Error deleting old messages: {e}")
            db.rollback()
            return 0


class OptimizedDigestLogRepository(BaseRepository):
    """Optimized repository for digest logs"""

    def __init__(self):
        """Init  ."""
        super().__init__(DigestLog)

    @cached(prefix="last_digest", ttl=300)
    def get_last_digest_for_user(
        self, db: Session, user_id: int
    ) -> Optional[DigestLog]:
        """Get the latest digest with caching"""
        return (
            db.query(DigestLog)
            .filter(DigestLog.user_id == user_id)
            .order_by(desc(DigestLog.created_at))
            .first()
        )

    @cached(prefix="digests_period", ttl=600)
    def get_digests_for_period(
        self, db: Session, user_id: int, days_back: int = 7
    ) -> List[DigestLog]:
        """Get digests over a period with caching"""
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)
        return (
            db.query(DigestLog)
            .filter(DigestLog.user_id == user_id, DigestLog.created_at >= cutoff_date)
            .order_by(desc(DigestLog.created_at))
            .all()
        )

    def should_create_digest(
        self, db: Session, user_id: int, interval_hours: int
    ) -> bool:
        """Check the need to create a digest"""
        last_digest = self.get_last_digest_for_user(db, user_id)
        if not last_digest:
            return True

        time_since_last = datetime.utcnow() - last_digest.created_at
        return time_since_last >= timedelta(hours=interval_hours)

    def get_digest_stats(
        self, db: Session, user_id: int, days_back: int = 30
    ) -> Dict[str, Any]:
        """Get digest statistics"""
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)

        stats = (
            db.query(
                func.count(DigestLog.id).label("total_digests"),
                func.avg(
                    func.extract(
                        "epoch",
                        DigestLog.created_at
                        - func.lag(DigestLog.created_at).over(
                            partition_by=DigestLog.user_id,
                            order_by=DigestLog.created_at,
                        ),
                    )
                ).label("avg_interval_hours"),
            )
            .filter(DigestLog.user_id == user_id, DigestLog.created_at >= cutoff_date)
            .first()
        )

        return {
            "total_digests": stats.total_digests or 0,
            "avg_interval_hours": float(stats.avg_interval_hours or 0) / 3600,
            "period_days": days_back,
        }

    def delete_old_digests(self, db: Session, cutoff_time: datetime) -> int:
        """Delete old digests"""
        try:
            result = (
                db.query(DigestLog)
                .filter(DigestLog.created_at < cutoff_time)
                .delete(synchronize_session=False)
            )
            db.commit()
            return result
        except SQLAlchemyError as e:
            logger.error(f"Error deleting old digests: {e}")
            db.rollback()
            return 0


# Global instances of optimized repositories
optimized_user_repository = OptimizedUserRepository()
optimized_whatsapp_message_repository = OptimizedWhatsAppMessageRepository()
optimized_digest_log_repository = OptimizedDigestLogRepository()
