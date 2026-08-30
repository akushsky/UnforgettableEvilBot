"""Unit tests for config.settings.Settings.validate_required_settings."""

import pytest

from config.settings import Settings


def _settings(**overrides) -> Settings:
    """Build a Settings instance with every required value satisfied."""
    settings = Settings.__new__(Settings)
    settings.DEBUG = False
    settings.OPENAI_API_KEY = "sk-test"
    settings.TELEGRAM_BOT_TOKEN = "123:abc"
    settings.SECRET_KEY = "a-real-secret"
    settings.BRIDGE_WEBHOOK_SECRET = "bridge-secret"
    settings._validated = False

    for key, value in overrides.items():
        setattr(settings, key, value)

    return settings


def test_complete_configuration_validates():
    """A fully configured production instance passes validation."""
    settings = _settings()

    settings.validate_required_settings()

    assert settings._validated is True


@pytest.mark.parametrize("value", ["", "   ", None])
def test_missing_bridge_secret_is_rejected_outside_debug(value):
    """Without the shared secret every inbound webhook fails closed."""
    settings = _settings(BRIDGE_WEBHOOK_SECRET=value)

    with pytest.raises(ValueError) as exc_info:
        settings.validate_required_settings()

    assert "BRIDGE_WEBHOOK_SECRET" in str(exc_info.value)
    assert settings._validated is False


def test_missing_bridge_secret_is_allowed_in_debug():
    """Local development without a bridge secret still starts."""
    settings = _settings(DEBUG=True, BRIDGE_WEBHOOK_SECRET="")

    settings.validate_required_settings()

    assert settings._validated is True


def test_other_missing_variables_are_still_reported():
    """The bridge secret check does not mask the pre-existing checks."""
    settings = _settings(
        OPENAI_API_KEY=None,
        SECRET_KEY="your-secret-key-here",
        BRIDGE_WEBHOOK_SECRET="",
    )

    with pytest.raises(ValueError) as exc_info:
        settings.validate_required_settings()

    detail = str(exc_info.value)
    assert "OPENAI_API_KEY" in detail
    assert "SECRET_KEY" in detail
    assert "BRIDGE_WEBHOOK_SECRET" in detail


def test_validation_is_cached():
    """Repeat calls are a no-op once the configuration validated."""
    settings = _settings()
    settings.validate_required_settings()

    settings.OPENAI_API_KEY = None
    settings.validate_required_settings()
