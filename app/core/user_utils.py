from sqlalchemy.orm import Session

from app.core.repository_factory import repository_factory
from app.models.database import UserSettings


def create_default_user_settings(user_id: int, db: Session) -> UserSettings:
    """
    Create default settings for a new user

    Args:
        user_id: ID of the user
        db: Database session

    Returns:
        UserSettings: Created settings object
    """
    # Prevent duplicate settings for the same user
    existing = repository_factory.get_user_settings_repository().get_by_user_id(
        db, user_id
    )
    # Only treat as existing if it's a real instance (avoid Mock objects in unit tests)
    if existing is not None and hasattr(existing, "user_id"):
        return existing

    default_settings = UserSettings(
        user_id=user_id,
        max_message_age_hours=24,  # 24 hours default
        min_importance_level=3,
        include_media_messages=True,
        urgent_notifications=True,
        daily_summary=True,
        auto_add_new_chats=False,
        auto_add_group_chats_only=True,
    )

    db.add(default_settings)
    db.commit()
    db.refresh(default_settings)

    return default_settings


def get_user_settings(user_id: int, db: Session) -> UserSettings:
    """
    Get user settings, create default if not exist

    Args:
        user_id: ID of the user
        db: Database session

    Returns:
        UserSettings: User settings object
    """
    settings = repository_factory.get_user_settings_repository().get_by_user_id(
        db, user_id
    )

    if not settings:
        settings = create_default_user_settings(user_id, db)

    return settings
