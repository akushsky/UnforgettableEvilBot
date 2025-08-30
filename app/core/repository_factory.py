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


class RepositoryFactory:
    """Factory for accessing standard repositories"""

    @staticmethod
    def get_user_repository():
        """Get user repository"""
        return user_repository

    @staticmethod
    def get_monitored_chat_repository():
        """Get monitored chat repository"""
        return monitored_chat_repository

    @staticmethod
    def get_whatsapp_message_repository():
        """Get WhatsApp message repository"""
        return whatsapp_message_repository

    @staticmethod
    def get_digest_log_repository():
        """Get digest log repository"""
        return digest_log_repository

    @staticmethod
    def get_system_log_repository():
        """Get system log repository"""
        return system_log_repository

    @staticmethod
    def get_user_settings_repository():
        """Get user settings repository"""
        return user_settings_repository

    @staticmethod
    def get_resource_savings_repository():
        """Get resource savings repository"""
        return resource_savings_repository

    @staticmethod
    def get_openai_metrics_repository():
        """Get OpenAI metrics repository"""
        return openai_metrics_repository


# Global factory instance
repository_factory = RepositoryFactory()
