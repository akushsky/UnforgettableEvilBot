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
from app.core.repository_factory import RepositoryFactory, repository_factory


class TestRepositoryFactory:
    """Test RepositoryFactory functionality"""

    def setup_method(self):
        """Setup test method"""
        self.factory = RepositoryFactory()

    def test_get_user_repository(self):
        """Test get_user_repository returns user repository"""
        result = self.factory.get_user_repository()
        assert result == user_repository

    def test_get_monitored_chat_repository(self):
        """Test get_monitored_chat_repository returns monitored chat repository"""
        result = self.factory.get_monitored_chat_repository()
        assert result == monitored_chat_repository

    def test_get_whatsapp_message_repository(self):
        """Test get_whatsapp_message_repository returns whatsapp message repository"""
        result = self.factory.get_whatsapp_message_repository()
        assert result == whatsapp_message_repository

    def test_get_digest_log_repository(self):
        """Test get_digest_log_repository returns digest log repository"""
        result = self.factory.get_digest_log_repository()
        assert result == digest_log_repository

    def test_get_system_log_repository(self):
        """Test get_system_log_repository returns system log repository"""
        result = self.factory.get_system_log_repository()
        assert result == system_log_repository

    def test_get_user_settings_repository(self):
        """Test get_user_settings_repository returns user settings repository"""
        result = self.factory.get_user_settings_repository()
        assert result == user_settings_repository

    def test_get_resource_savings_repository(self):
        """Test get_resource_savings_repository returns resource savings repository"""
        result = self.factory.get_resource_savings_repository()
        assert result == resource_savings_repository

    def test_get_openai_metrics_repository(self):
        """Test get_openai_metrics_repository returns openai metrics repository"""
        result = self.factory.get_openai_metrics_repository()
        assert result == openai_metrics_repository

    def test_factory_is_available(self):
        """Test that repository_factory is available"""
        assert repository_factory is not None
        assert isinstance(repository_factory, RepositoryFactory)

    def test_all_repository_methods_return_repositories(self):
        """Test that all factory methods return repository instances"""
        assert self.factory.get_user_repository() is not None
        assert self.factory.get_monitored_chat_repository() is not None
        assert self.factory.get_whatsapp_message_repository() is not None
        assert self.factory.get_digest_log_repository() is not None
        assert self.factory.get_system_log_repository() is not None
        assert self.factory.get_user_settings_repository() is not None
        assert self.factory.get_resource_savings_repository() is not None
        assert self.factory.get_openai_metrics_repository() is not None

    def test_factory_methods_are_static(self):
        """Test that factory methods are static methods"""
        assert hasattr(RepositoryFactory, "get_user_repository")
        assert callable(RepositoryFactory.get_user_repository)
        assert hasattr(RepositoryFactory, "get_monitored_chat_repository")
        assert callable(RepositoryFactory.get_monitored_chat_repository)
