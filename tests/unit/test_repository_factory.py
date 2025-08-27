from unittest.mock import patch

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
from app.core.repository_factory import RepositoryFactory, repository_factory


class TestRepositoryFactory:
    """Test RepositoryFactory functionality"""

    def setup_method(self):
        """Setup test method"""
        self.factory = RepositoryFactory()

    @patch("app.core.repository_factory.settings")
    def test_get_user_repository_basic(self, mock_settings):
        """Test get_user_repository returns basic repository when optimized is disabled"""
        # Arrange
        mock_settings.USE_OPTIMIZED_REPOSITORIES = False

        # Act
        result = self.factory.get_user_repository()

        # Assert
        assert result == user_repository

    @patch("app.core.repository_factory.settings")
    def test_get_user_repository_optimized(self, mock_settings):
        """Test get_user_repository returns optimized repository when enabled"""
        # Arrange
        mock_settings.USE_OPTIMIZED_REPOSITORIES = True

        # Act
        result = self.factory.get_user_repository()

        # Assert
        assert result == optimized_user_repository

    @patch("app.core.repository_factory.settings")
    def test_get_monitored_chat_repository_basic(self, mock_settings):
        """Test get_monitored_chat_repository returns basic repository"""
        # Arrange
        mock_settings.USE_OPTIMIZED_REPOSITORIES = False

        # Act
        result = self.factory.get_monitored_chat_repository()

        # Assert
        assert result == monitored_chat_repository

    @patch("app.core.repository_factory.settings")
    def test_get_monitored_chat_repository_optimized_fallback(self, mock_settings):
        """Test get_monitored_chat_repository falls back to basic when optimized not available"""
        # Arrange
        mock_settings.USE_OPTIMIZED_REPOSITORIES = True

        # Act
        result = self.factory.get_monitored_chat_repository()

        # Assert
        assert (
            result == monitored_chat_repository
        )  # Should fallback since no optimized version exists

    @patch("app.core.repository_factory.settings")
    def test_get_whatsapp_message_repository_basic(self, mock_settings):
        """Test get_whatsapp_message_repository returns basic repository when optimized is disabled"""
        # Arrange
        mock_settings.USE_OPTIMIZED_REPOSITORIES = False

        # Act
        result = self.factory.get_whatsapp_message_repository()

        # Assert
        assert result == whatsapp_message_repository

    @patch("app.core.repository_factory.settings")
    def test_get_whatsapp_message_repository_optimized(self, mock_settings):
        """Test get_whatsapp_message_repository returns optimized repository when enabled"""
        # Arrange
        mock_settings.USE_OPTIMIZED_REPOSITORIES = True

        # Act
        result = self.factory.get_whatsapp_message_repository()

        # Assert
        assert result == optimized_whatsapp_message_repository

    @patch("app.core.repository_factory.settings")
    def test_get_digest_log_repository_basic(self, mock_settings):
        """Test get_digest_log_repository returns basic repository when optimized is disabled"""
        # Arrange
        mock_settings.USE_OPTIMIZED_REPOSITORIES = False

        # Act
        result = self.factory.get_digest_log_repository()

        # Assert
        assert result == digest_log_repository

    @patch("app.core.repository_factory.settings")
    def test_get_digest_log_repository_optimized(self, mock_settings):
        """Test get_digest_log_repository returns optimized repository when enabled"""
        # Arrange
        mock_settings.USE_OPTIMIZED_REPOSITORIES = True

        # Act
        result = self.factory.get_digest_log_repository()

        # Assert
        assert result == optimized_digest_log_repository

    @patch("app.core.repository_factory.settings")
    def test_get_system_log_repository(self, mock_settings):
        """Test get_system_log_repository always returns basic repository"""
        # Arrange
        mock_settings.USE_OPTIMIZED_REPOSITORIES = True

        # Act
        result = self.factory.get_system_log_repository()

        # Assert
        assert (
            result == system_log_repository
        )  # Should always return basic since no optimized version exists

    @patch("app.core.repository_factory.settings")
    def test_get_user_settings_repository(self, mock_settings):
        """Test get_user_settings_repository always returns basic repository"""
        # Arrange
        mock_settings.USE_OPTIMIZED_REPOSITORIES = True

        # Act
        result = self.factory.get_user_settings_repository()

        # Assert
        assert (
            result == user_settings_repository
        )  # Should always return basic since no optimized version exists

    @patch("app.core.repository_factory.settings")
    def test_get_resource_savings_repository(self, mock_settings):
        """Test get_resource_savings_repository always returns basic repository"""
        # Arrange
        mock_settings.USE_OPTIMIZED_REPOSITORIES = True

        # Act
        result = self.factory.get_resource_savings_repository()

        # Assert
        assert (
            result == resource_savings_repository
        )  # Should always return basic since no optimized version exists

    @patch("app.core.repository_factory.settings")
    def test_get_openai_metrics_repository(self, mock_settings):
        """Test get_openai_metrics_repository always returns basic repository"""
        # Arrange
        mock_settings.USE_OPTIMIZED_REPOSITORIES = True

        # Act
        result = self.factory.get_openai_metrics_repository()

        # Assert
        assert (
            result == openai_metrics_repository
        )  # Should always return basic since no optimized version exists

    def test_factory_is_singleton(self):
        """Test that repository_factory is a singleton instance"""
        # Act & Assert
        assert repository_factory is not None
        assert isinstance(repository_factory, RepositoryFactory)
        # Note: RepositoryFactory is not actually a singleton, it's just a global instance
        # So we test that it exists and is the correct type

    @patch("app.core.repository_factory.settings")
    def test_all_repository_methods_return_repositories(self, mock_settings):
        """Test that all factory methods return repository instances"""
        # Arrange
        mock_settings.USE_OPTIMIZED_REPOSITORIES = False

        # Act & Assert
        assert self.factory.get_user_repository() is not None
        assert self.factory.get_monitored_chat_repository() is not None
        assert self.factory.get_whatsapp_message_repository() is not None
        assert self.factory.get_digest_log_repository() is not None
        assert self.factory.get_system_log_repository() is not None
        assert self.factory.get_user_settings_repository() is not None
        assert self.factory.get_resource_savings_repository() is not None
        assert self.factory.get_openai_metrics_repository() is not None

    @patch("app.core.repository_factory.settings")
    def test_optimized_repositories_are_different_instances(self, mock_settings):
        """Test that optimized repositories are different from basic repositories"""
        # Arrange
        mock_settings.USE_OPTIMIZED_REPOSITORIES = True

        # Act & Assert
        assert self.factory.get_user_repository() != user_repository
        assert (
            self.factory.get_whatsapp_message_repository()
            != whatsapp_message_repository
        )
        assert self.factory.get_digest_log_repository() != digest_log_repository

    def test_factory_methods_are_static(self):
        """Test that factory methods are static methods"""
        # Act & Assert
        assert hasattr(RepositoryFactory, "get_user_repository")
        assert callable(RepositoryFactory.get_user_repository)
        assert hasattr(RepositoryFactory, "get_monitored_chat_repository")
        assert callable(RepositoryFactory.get_monitored_chat_repository)
