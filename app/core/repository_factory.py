"""
Repository access layer.

Provides both the legacy RepositoryFactory class (for backward compatibility)
and direct singleton imports for new code.

New code should import repositories directly:
    from app.core.repositories import user_repository

Or use the factory for consistency with existing code:
    from app.core.repository_factory import repository_factory
"""

from app.core.repositories import (
    digest_log_repository,
    digest_preference_repository,
    monitored_chat_repository,
    openai_metrics_repository,
    resource_savings_repository,
    system_log_repository,
    user_repository,
    user_settings_repository,
    whatsapp_message_repository,
    whatsapp_phone_repository,
)


class RepositoryFactory:
    """Factory for accessing standard repositories.

    Thin wrapper that delegates to singleton instances.
    Kept for backward compatibility; prefer direct imports in new code.
    """

    get_user_repository = staticmethod(lambda: user_repository)
    get_monitored_chat_repository = staticmethod(lambda: monitored_chat_repository)
    get_whatsapp_message_repository = staticmethod(lambda: whatsapp_message_repository)
    get_digest_log_repository = staticmethod(lambda: digest_log_repository)
    get_system_log_repository = staticmethod(lambda: system_log_repository)
    get_user_settings_repository = staticmethod(lambda: user_settings_repository)
    get_resource_savings_repository = staticmethod(lambda: resource_savings_repository)
    get_openai_metrics_repository = staticmethod(lambda: openai_metrics_repository)
    get_digest_preference_repository = staticmethod(
        lambda: digest_preference_repository
    )
    get_whatsapp_phone_repository = staticmethod(lambda: whatsapp_phone_repository)


repository_factory = RepositoryFactory()
