"""Shared helpers for digest delivery channel checks."""

from sqlalchemy.orm import Session

from app.core.repository_factory import repository_factory


def has_digest_delivery_channel(user, db: Session) -> bool:
    """Whether DigestScheduler would have somewhere to deliver the digest.

    Mirrors create_and_send_digest: WhatsApp is used only when it is the
    explicit preference and phone numbers exist; everything else falls back to
    Telegram.
    """
    preference = getattr(user.digest_preference, "name", None)

    if preference == "whatsapp":
        phone_numbers = repository_factory.get_whatsapp_phone_repository().get_phone_numbers_for_user(
            db, user.id
        )
        if phone_numbers:
            return True

    return bool(user.telegram_channel_id)


def can_generate_immediate_digest(user, db: Session) -> bool:
    """Whether the admin UI/API may trigger an immediate digest for this user."""
    return bool(user.is_active and user.whatsapp_connected) and has_digest_delivery_channel(
        user, db
    )
