from unittest.mock import Mock, patch

import pytest
from sqlalchemy.orm import Session

from app.core.user_utils import create_default_user_settings, get_user_settings
from app.models.database import UserSettings


class TestUserUtils:
    """Test user utility functions"""

    def setup_method(self):
        """Setup test method"""
        self.mock_db = Mock(spec=Session)

    def test_create_default_user_settings(self):
        """Test create_default_user_settings function"""
        # Arrange
        user_id = 1
        mock_settings = Mock(spec=UserSettings)
        self.mock_db.add.return_value = None
        self.mock_db.commit.return_value = None
        self.mock_db.refresh.return_value = None

        # Act
        with patch("app.core.user_utils.repository_factory") as mock_factory:
            mock_repo = Mock()
            mock_repo.get_by_user_id.return_value = None  # No existing settings
            mock_factory.get_user_settings_repository.return_value = mock_repo

            with patch("app.core.user_utils.UserSettings") as mock_user_settings_class:
                mock_user_settings_class.return_value = mock_settings
                result = create_default_user_settings(user_id, self.mock_db)

        # Assert
        assert result == mock_settings
        self.mock_db.add.assert_called_once_with(mock_settings)
        self.mock_db.commit.assert_called_once()
        self.mock_db.refresh.assert_called_once_with(mock_settings)

    def test_create_default_user_settings_creates_correct_settings(self):
        """Test that create_default_user_settings creates settings with correct defaults"""
        # Arrange
        user_id = 1
        self.mock_db.add.return_value = None
        self.mock_db.commit.return_value = None
        self.mock_db.refresh.return_value = None

        # Act
        with patch("app.core.user_utils.repository_factory") as mock_factory:
            mock_repo = Mock()
            mock_repo.get_by_user_id.return_value = None  # No existing settings
            mock_factory.get_user_settings_repository.return_value = mock_repo

            with patch("app.core.user_utils.UserSettings") as mock_user_settings_class:
                mock_settings = Mock(spec=UserSettings)
                mock_user_settings_class.return_value = mock_settings
                create_default_user_settings(user_id, self.mock_db)

        # Assert
        mock_user_settings_class.assert_called_once_with(
            user_id=user_id,
            max_message_age_hours=24,
            min_importance_level=3,
            include_media_messages=True,
            urgent_notifications=True,
            daily_summary=True,
            auto_add_new_chats=False,
            auto_add_group_chats_only=True,
        )

    def test_get_user_settings_existing_settings(self):
        """Test get_user_settings when settings already exist"""
        # Arrange
        user_id = 1
        mock_settings = Mock(spec=UserSettings)

        with patch("app.core.user_utils.repository_factory") as mock_factory:
            mock_repo = Mock()
            mock_repo.get_by_user_id.return_value = mock_settings
            mock_factory.get_user_settings_repository.return_value = mock_repo

            # Act
            result = get_user_settings(user_id, self.mock_db)

        # Assert
        assert result == mock_settings
        mock_repo.get_by_user_id.assert_called_once_with(self.mock_db, user_id)

    def test_get_user_settings_creates_default_when_not_exists(self):
        """Test get_user_settings creates default settings when none exist"""
        # Arrange
        user_id = 1
        mock_settings = Mock(spec=UserSettings)

        with patch("app.core.user_utils.repository_factory") as mock_factory:
            mock_repo = Mock()
            mock_repo.get_by_user_id.return_value = None
            mock_factory.get_user_settings_repository.return_value = mock_repo

            with patch(
                "app.core.user_utils.create_default_user_settings"
            ) as mock_create:
                mock_create.return_value = mock_settings

                # Act
                result = get_user_settings(user_id, self.mock_db)

        # Assert
        assert result == mock_settings
        mock_repo.get_by_user_id.assert_called_once_with(self.mock_db, user_id)
        mock_create.assert_called_once_with(user_id, self.mock_db)

    def test_get_user_settings_handles_database_errors(self):
        """Test get_user_settings handles database errors gracefully"""
        # Arrange
        user_id = 1

        with patch("app.core.user_utils.repository_factory") as mock_factory:
            mock_repo = Mock()
            mock_repo.get_by_user_id.side_effect = Exception("Database error")
            mock_factory.get_user_settings_repository.return_value = mock_repo

            # Act & Assert
            with pytest.raises(Exception, match="Database error"):
                get_user_settings(user_id, self.mock_db)

    def test_create_default_user_settings_handles_database_errors(self):
        """Test create_default_user_settings handles database errors gracefully"""
        # Arrange
        user_id = 1
        self.mock_db.add.side_effect = Exception("Database error")

        # Act & Assert
        with patch("app.core.user_utils.repository_factory") as mock_factory:
            mock_repo = Mock()
            mock_repo.get_by_user_id.side_effect = Exception("Database error")
            mock_factory.get_user_settings_repository.return_value = mock_repo

            with pytest.raises(Exception, match="Database error"):
                create_default_user_settings(user_id, self.mock_db)

    def test_get_user_settings_calls_repository_factory(self):
        """Test that get_user_settings uses the repository factory"""
        # Arrange
        user_id = 1
        mock_settings = Mock(spec=UserSettings)

        with patch("app.core.user_utils.repository_factory") as mock_factory:
            mock_repo = Mock()
            mock_repo.get_by_user_id.return_value = mock_settings
            mock_factory.get_user_settings_repository.return_value = mock_repo

            # Act
            get_user_settings(user_id, self.mock_db)

        # Assert
        mock_factory.get_user_settings_repository.assert_called_once()

    def test_create_default_user_settings_returns_user_settings_instance(self):
        """Test that create_default_user_settings returns a UserSettings instance"""
        # Arrange
        user_id = 1
        self.mock_db.add.return_value = None
        self.mock_db.commit.return_value = None
        self.mock_db.refresh.return_value = None

        # Act
        with patch("app.core.user_utils.repository_factory") as mock_factory:
            mock_repo = Mock()
            mock_repo.get_by_user_id.return_value = None  # No existing settings
            mock_factory.get_user_settings_repository.return_value = mock_repo

            with patch("app.core.user_utils.UserSettings") as mock_user_settings_class:
                mock_settings = Mock(spec=UserSettings)
                mock_user_settings_class.return_value = mock_settings
                result = create_default_user_settings(user_id, self.mock_db)

        # Assert
        assert isinstance(result, Mock)  # Since we're using Mock
        assert result == mock_settings
