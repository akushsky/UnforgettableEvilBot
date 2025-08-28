from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import asc, desc
from sqlalchemy.orm import Session, joinedload

from app.core.base_service import BaseService
from app.models.database import (
    DigestLog,
    MonitoredChat,
    OpenAIMetrics,
    ResourceSavings,
    SystemLog,
    User,
    UserSettings,
    WhatsAppMessage,
)
from config.logging_config import get_logger

logger = get_logger(__name__)


class BaseRepository(BaseService):
    """Base repository with common database methods"""

    def __init__(self, model_class):
        """Init  .

        Args:
            model_class: Description of model_class.
        """
        super().__init__()
        self.model = model_class

    def get_by_id(self, db: Session, id: int) -> Optional[Any]:
        """Get a record by ID"""
        return db.query(self.model).filter(self.model.id == id).first()

    def get_by_id_or_404(self, db: Session, id: int) -> Any:
        """Get a record by ID, raising 404 if not found"""
        result = self.get_by_id(db, id)
        if not result:
            raise HTTPException(
                status_code=404, detail=f"{self.model.__name__} not found"
            )
        return result

    def get_all(self, db: Session, skip: int = 0, limit: int = 100) -> List[Any]:
        """Get all records with pagination"""
        return db.query(self.model).offset(skip).limit(limit).all()

    def create(self, db: Session, obj_in: Dict[str, Any]) -> Any:
        """Create a new record"""
        db_obj = self.model(**obj_in)
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    def update(self, db: Session, db_obj: Any, obj_in: Dict[str, Any]) -> Any:
        """Update a record"""
        for field, value in obj_in.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    def delete(self, db: Session, id: int) -> bool:
        """Delete a record"""
        obj = self.get_by_id(db, id)
        if obj:
            db.delete(obj)
            db.commit()
            return True
        return False

    async def validate_input(self, data: Any) -> bool:
        """Basic validation — always True"""
        return True


class UserRepository(BaseRepository):
    """Repository for working with users"""

    def __init__(self):
        """Init  ."""
        super().__init__(User)

    def get_by_username(self, db: Session, username: str) -> Optional[User]:
        """Get a user by username"""
        return db.query(User).filter(User.username == username).first()

    def get_by_email(self, db: Session, email: str) -> Optional[User]:
        """Get a user by email"""
        return db.query(User).filter(User.email == email).first()

    def get_active_users(self, db: Session) -> List[User]:
        """Get all active users"""
        return db.query(User).filter(User.is_active, User.whatsapp_connected).all()

    def get_active_users_with_telegram(self, db: Session) -> List[User]:
        """Get all active users with configured Telegram channels"""
        return (
            db.query(User)
            .filter(User.is_active, User.telegram_channel_id.isnot(None))
            .all()
        )

    def get_active_users_with_whatsapp(self, db: Session) -> List[User]:
        """Get all active users with WhatsApp connected"""
        return db.query(User).filter(User.is_active, User.whatsapp_connected).all()

    def get_suspended_users_with_whatsapp(self, db: Session) -> List[User]:
        """Get suspended users with active WhatsApp connections"""
        return (
            db.query(User)
            .filter(User.is_active.is_(False), User.whatsapp_connected.is_(True))
            .all()
        )

    def get_users_with_chats(self, db: Session) -> List[User]:
        """Get users with their chats (eager loading)"""
        return (
            db.query(User)
            .options(joinedload(User.monitored_chats))
            .filter(User.is_active.is_(True))
            .all()
        )

    def get_user_with_full_data(self, db: Session, user_id: int) -> Optional[User]:
        """Get a user with all related data"""
        return (
            db.query(User)
            .options(joinedload(User.monitored_chats), joinedload(User.digest_logs))
            .filter(User.id == user_id)
            .first()
        )

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


class MonitoredChatRepository(BaseRepository):
    """Repository for working with monitored chats"""

    def __init__(self):
        """Init  ."""
        super().__init__(MonitoredChat)

    def get_by_user_and_chat_id(
        self, db: Session, user_id: int, chat_id: str
    ) -> Optional[MonitoredChat]:
        """Get a chat by user and chat ID"""
        return (
            db.query(MonitoredChat)
            .filter(MonitoredChat.user_id == user_id, MonitoredChat.chat_id == chat_id)
            .first()
        )

    def get_active_chats_for_user(
        self, db: Session, user_id: int
    ) -> List[MonitoredChat]:
        """Get a user's active chats"""
        return (
            db.query(MonitoredChat)
            .filter(MonitoredChat.user_id == user_id, MonitoredChat.is_active)
            .all()
        )

    def get_chat_with_messages(
        self, db: Session, chat_id: int
    ) -> Optional[MonitoredChat]:
        """Get a chat with messages"""
        return (
            db.query(MonitoredChat)
            .options(joinedload(MonitoredChat.messages))
            .filter(MonitoredChat.id == chat_id)
            .first()
        )


class WhatsAppMessageRepository(BaseRepository):
    """Repository for working with WhatsApp messages"""

    def __init__(self):
        """Init  ."""
        super().__init__(WhatsAppMessage)

    def get_by_message_id(
        self, db: Session, message_id: str
    ) -> Optional[WhatsAppMessage]:
        """Get a message by message ID"""
        return (
            db.query(WhatsAppMessage)
            .filter(WhatsAppMessage.message_id == message_id)
            .first()
        )

    def get_unprocessed_messages(
        self, db: Session, chat_id: int
    ) -> List[WhatsAppMessage]:
        """Get unprocessed messages"""
        return (
            db.query(WhatsAppMessage)
            .filter(
                WhatsAppMessage.chat_id == chat_id,
                WhatsAppMessage.is_processed.is_(False),
            )
            .order_by(WhatsAppMessage.timestamp.asc())
            .all()
        )

    def get_important_messages(
        self, db: Session, chat_id: int, importance_threshold: int = 3
    ) -> List[WhatsAppMessage]:
        """Get important messages"""
        return (
            db.query(WhatsAppMessage)
            .filter(
                WhatsAppMessage.chat_id == chat_id,
                WhatsAppMessage.importance_score >= importance_threshold,
            )
            .order_by(desc(WhatsAppMessage.timestamp))
            .all()
        )

    def get_messages_for_digest(
        self, db: Session, chat_id: int, hours_back: int = 24
    ) -> List[WhatsAppMessage]:
        """Get messages for a digest over the last N hours"""
        cutoff_time = datetime.utcnow() - timedelta(hours=hours_back)
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

    def get_important_messages_for_digest(
        self,
        db: Session,
        chat_id: int,
        hours_back: int = 24,
        importance_threshold: int = 3,
    ) -> List[WhatsAppMessage]:
        """Get important messages for a digest over the last N hours"""
        cutoff_time = datetime.utcnow() - timedelta(hours=hours_back)
        return (
            db.query(WhatsAppMessage)
            .filter(
                WhatsAppMessage.chat_id == chat_id,
                WhatsAppMessage.timestamp >= cutoff_time,
                WhatsAppMessage.importance_score >= importance_threshold,
                WhatsAppMessage.is_processed.is_(False),
            )
            .order_by(desc(WhatsAppMessage.timestamp))
            .all()
        )

    def mark_as_processed(self, db: Session, message_ids: List[int]) -> int:
        """Mark messages as processed"""
        result = (
            db.query(WhatsAppMessage)
            .filter(WhatsAppMessage.id.in_(message_ids))
            .update({"is_processed": True}, synchronize_session=False)
        )
        db.commit()
        return result

    def delete_old_messages(
        self, db: Session, chat_ids: List[int], cutoff_time: datetime
    ) -> int:
        """Delete old messages for specified chats"""
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

    def get_messages_count(self, db: Session) -> int:
        """Get total count of messages"""
        return db.query(WhatsAppMessage).count()

    def get_old_messages_count(self, db: Session, cutoff_time: datetime) -> int:
        """Get count of old messages"""
        return (
            db.query(WhatsAppMessage)
            .filter(WhatsAppMessage.timestamp < cutoff_time)
            .count()
        )

    def get_messages_by_chat_ids(
        self, db: Session, chat_ids: List[int], limit: int = 1000
    ) -> List[WhatsAppMessage]:
        """Get messages by chat IDs"""
        return (
            db.query(WhatsAppMessage)
            .filter(WhatsAppMessage.chat_id.in_(chat_ids))
            .order_by(desc(WhatsAppMessage.timestamp))
            .limit(limit)
            .all()
        )


class DigestLogRepository(BaseRepository):
    """Repository for working with digest logs"""

    def __init__(self):
        """Init  ."""
        super().__init__(DigestLog)

    def get_last_digest_for_user(
        self, db: Session, user_id: int
    ) -> Optional[DigestLog]:
        """Get the user's most recent digest"""
        return (
            db.query(DigestLog)
            .filter(DigestLog.user_id == user_id)
            .order_by(desc(DigestLog.created_at))
            .first()
        )

    def get_digests_for_period(
        self, db: Session, user_id: int, days_back: int = 7
    ) -> List[DigestLog]:
        """Get digests over a period"""
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
        """Check whether a digest should be created"""
        last_digest = self.get_last_digest_for_user(db, user_id)
        if not last_digest:
            return True

        time_since_last = datetime.utcnow() - last_digest.created_at
        return bool(time_since_last >= timedelta(hours=interval_hours))

    def delete_old_digests(self, db: Session, cutoff_time: datetime) -> int:
        """Delete old digests"""
        result = (
            db.query(DigestLog)
            .filter(DigestLog.created_at < cutoff_time)
            .delete(synchronize_session=False)
        )
        db.commit()
        return result

    def get_digests_count(self, db: Session) -> int:
        """Get total count of digests"""
        return db.query(DigestLog).count()

    def get_old_digests_count(self, db: Session, cutoff_time: datetime) -> int:
        """Get count of old digests"""
        return db.query(DigestLog).filter(DigestLog.created_at < cutoff_time).count()


class SystemLogRepository(BaseRepository):
    """Repository for working with system logs"""

    def __init__(self):
        """Init  ."""
        super().__init__(SystemLog)

    def delete_old_logs(self, db: Session, cutoff_time: datetime) -> int:
        """Delete old system logs"""
        result = (
            db.query(SystemLog)
            .filter(SystemLog.created_at < cutoff_time)
            .delete(synchronize_session=False)
        )
        db.commit()
        return result

    def get_logs_count(self, db: Session) -> int:
        """Get total count of system logs"""
        return db.query(SystemLog).count()

    def get_old_logs_count(self, db: Session, cutoff_time: datetime) -> int:
        """Get count of old system logs"""
        return db.query(SystemLog).filter(SystemLog.created_at < cutoff_time).count()


class UserSettingsRepository(BaseRepository):
    """Repository for working with user settings"""

    def __init__(self):
        """Init  ."""
        super().__init__(UserSettings)

    def get_by_user_id(self, db: Session, user_id: int) -> Optional[UserSettings]:
        """Get user settings by user ID"""
        return db.query(UserSettings).filter(UserSettings.user_id == user_id).first()


class ResourceSavingsRepository(BaseRepository):
    """Repository for working with resource savings"""

    def __init__(self):
        """Init  ."""
        super().__init__(ResourceSavings)

    def get_savings_in_period(
        self, db: Session, period_start: datetime, period_end: datetime
    ) -> List[ResourceSavings]:
        """Get savings records in a period"""
        return (
            db.query(ResourceSavings)
            .filter(
                ResourceSavings.period_start >= period_start,
                ResourceSavings.period_end <= period_end,
            )
            .all()
        )

    def get_savings_by_user_in_period(
        self, db: Session, user_id: int, period_start: datetime
    ) -> List[ResourceSavings]:
        """Get savings history for a specific user in a period"""
        return (
            db.query(ResourceSavings)
            .filter(
                ResourceSavings.user_id == user_id,
                ResourceSavings.created_at >= period_start,
            )
            .order_by(desc(ResourceSavings.created_at))
            .all()
        )


class OpenAIMetricsRepository(BaseRepository):
    """Repository for working with OpenAI metrics"""

    def __init__(self):
        """Init  ."""
        super().__init__(OpenAIMetrics)

    def get_all_metrics_ordered(self, db: Session) -> List[OpenAIMetrics]:
        """Get all metrics ordered by request time descending"""
        return db.query(OpenAIMetrics).order_by(desc(OpenAIMetrics.request_time)).all()


# Global repository instances
user_repository = UserRepository()
monitored_chat_repository = MonitoredChatRepository()
whatsapp_message_repository = WhatsAppMessageRepository()
digest_log_repository = DigestLogRepository()
system_log_repository = SystemLogRepository()
user_settings_repository = UserSettingsRepository()
resource_savings_repository = ResourceSavingsRepository()
openai_metrics_repository = OpenAIMetricsRepository()
