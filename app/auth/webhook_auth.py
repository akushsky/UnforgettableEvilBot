"""Shared-secret authentication for calls from the Node.js WhatsApp bridge.

The bridge runs in the same container and talks to the API over loopback, but
the API itself is published on a public hostname, so the webhook routes need
their own authentication instead of relying on network isolation.
"""

import hmac

from fastapi import Header, HTTPException, status

from config.logging_config import get_logger
from config.settings import settings

logger = get_logger(__name__)

# Header name only — not a credential value (Bandit B105 / Ruff S105 false positive).
BRIDGE_SECRET_HEADER = "X-Bridge-Secret"  # nosec B105  # noqa: S105


def verify_bridge_secret(
    x_bridge_secret: str | None = Header(default=None, alias=BRIDGE_SECRET_HEADER),
) -> bool:
    """Require a matching shared secret on bridge webhook calls.

    Fails closed: when no secret is configured the webhooks are only reachable
    in DEBUG (local development), never on a deployed instance.
    """
    configured_secret = settings.BRIDGE_WEBHOOK_SECRET

    if not configured_secret:
        if settings.DEBUG:
            return True
        logger.error(
            "BRIDGE_WEBHOOK_SECRET is not configured - rejecting bridge webhook call. "
            "Set BRIDGE_WEBHOOK_SECRET for both the API and the bridge."
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bridge webhook authentication is not configured",
        )

    if not x_bridge_secret or not hmac.compare_digest(
        x_bridge_secret.encode("utf-8"), configured_secret.encode("utf-8")
    ):
        logger.warning("Rejected bridge webhook call with missing or invalid secret")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bridge secret",
        )

    return True
