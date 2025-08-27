from app.core.optimized_repositories import (
    optimized_digest_log_repository,
    optimized_user_repository,
    optimized_whatsapp_message_repository,
)
from app.core.repositories import (
    digest_log_repository,
    monitored_chat_repository,
    openai_metrics_repository,
    resource_savings_repository,
    system_log_repository,
    user_repository,
    user_settings_repository,
    whatsapp_message_repository,
)
from config.settings import settings


class RepositoryFactory:
    """Factory for choosing between basic and optimized repositories based on configuration"""

    @staticmethod
    def get_user_repository():
        """Get user repository based on configuration"""
        if settings.USE_OPTIMIZED_REPOSITORIES:
            return optimized_user_repository
        return user_repository

    @staticmethod
    def get_monitored_chat_repository():
        """Get monitored chat repository based on configuration"""
        if settings.USE_OPTIMIZED_REPOSITORIES:
            # Note: No optimized version exists yet, fallback to basic
            return monitored_chat_repository
        return monitored_chat_repository

    @staticmethod
    def get_whatsapp_message_repository():
        """Get WhatsApp message repository based on configuration"""
        if settings.USE_OPTIMIZED_REPOSITORIES:
            return optimized_whatsapp_message_repository
        return whatsapp_message_repository

    @staticmethod
    def get_digest_log_repository():
        """Get digest log repository based on configuration"""
        if settings.USE_OPTIMIZED_REPOSITORIES:
            return optimized_digest_log_repository
        return digest_log_repository

    @staticmethod
    def get_system_log_repository():
        """Get system log repository based on configuration"""
        # Note: No optimized version exists yet, fallback to basic
        return system_log_repository

    @staticmethod
    def get_user_settings_repository():
        """Get user settings repository based on configuration"""
        # Note: No optimized version exists yet, fallback to basic
        return user_settings_repository

    @staticmethod
    def get_resource_savings_repository():
        """Get resource savings repository based on configuration"""
        # Note: No optimized version exists yet, fallback to basic
        return resource_savings_repository

    @staticmethod
    def get_openai_metrics_repository():
        """Get OpenAI metrics repository based on configuration"""
        # Note: No optimized version exists yet, fallback to basic
        return openai_metrics_repository


# Global factory instance
repository_factory = RepositoryFactory()
