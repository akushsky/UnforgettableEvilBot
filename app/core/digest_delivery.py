"""Shared helpers for digest delivery channel checks and send outcomes."""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from app.core.repository_factory import repository_factory

DigestOutcome = Literal["sent", "skipped", "failed"]


@dataclass(frozen=True)
class DigestSendResult:
    """Outcome of create_and_send_digest — never claim sent unless delivery succeeded."""

    outcome: DigestOutcome
    reason: str
    telegram_sent: bool = False
    whatsapp_sent: bool = False

    @classmethod
    def sent(
        cls,
        *,
        telegram_sent: bool = False,
        whatsapp_sent: bool = False,
        reason: str = "",
    ) -> "DigestSendResult":
        return cls(
            outcome="sent",
            reason=reason or "Digest delivered",
            telegram_sent=telegram_sent,
            whatsapp_sent=whatsapp_sent,
        )

    @classmethod
    def skipped(cls, reason: str) -> "DigestSendResult":
        return cls(outcome="skipped", reason=reason)

    @classmethod
    def failed(cls, reason: str) -> "DigestSendResult":
        return cls(outcome="failed", reason=reason)


def has_digest_delivery_channel(user, db: Session) -> bool:
    """Whether an immediate digest has a configured delivery channel.

    WhatsApp is used only when preference is explicitly ``whatsapp`` and phone
    numbers exist — there is no Telegram fallthrough for that preference
    (matches DigestScheduler). Otherwise a ``telegram_channel_id`` is required.
    """
    preference = getattr(user.digest_preference, "name", None)

    if preference == "whatsapp":
        phone_numbers = repository_factory.get_whatsapp_phone_repository().get_phone_numbers_for_user(
            db, user.id
        )
        return bool(phone_numbers)

    return bool(user.telegram_channel_id)


def can_generate_immediate_digest(user, db: Session) -> bool:
    """Whether the admin UI/API may trigger an immediate digest for this user."""
    return bool(
        user.is_active and user.whatsapp_connected
    ) and has_digest_delivery_channel(user, db)
