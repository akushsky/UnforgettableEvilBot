"""
Lightweight application state registry.

Holds references to long-lived objects (scheduler, etc.) that multiple
modules need without importing main.py, avoiding circular imports.
"""

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.scheduler.digest_scheduler import DigestScheduler

scheduler: Optional["DigestScheduler"] = None
