"""Unit tests for digest delivery channel helpers."""

from unittest.mock import Mock, patch

from app.core.digest_delivery import (
    can_generate_immediate_digest,
    has_digest_delivery_channel,
)


def _user(*, preference=None, telegram_channel_id="-1001", is_active=True, wa=True):
    user = Mock()
    user.id = 1
    user.is_active = is_active
    user.whatsapp_connected = wa
    user.telegram_channel_id = telegram_channel_id
    if preference is None:
        user.digest_preference = None
    else:
        pref = Mock()
        pref.name = preference
        user.digest_preference = pref
    return user


@patch("app.core.digest_delivery.repository_factory")
def test_whatsapp_pref_requires_phones_even_with_telegram(mock_repo_factory):
    """WhatsApp preference must not fall through to Telegram."""
    mock_phone_repo = Mock()
    mock_phone_repo.get_phone_numbers_for_user.return_value = []
    mock_repo_factory.get_whatsapp_phone_repository.return_value = mock_phone_repo

    user = _user(preference="whatsapp", telegram_channel_id="-100123")
    assert has_digest_delivery_channel(user, Mock()) is False


@patch("app.core.digest_delivery.repository_factory")
def test_whatsapp_pref_with_phones(mock_repo_factory):
    mock_phone_repo = Mock()
    mock_phone_repo.get_phone_numbers_for_user.return_value = ["+972500000000"]
    mock_repo_factory.get_whatsapp_phone_repository.return_value = mock_phone_repo

    user = _user(preference="whatsapp", telegram_channel_id=None)
    assert has_digest_delivery_channel(user, Mock()) is True


def test_telegram_pref_requires_channel():
    assert (
        has_digest_delivery_channel(
            _user(preference="telegram", telegram_channel_id=None), Mock()
        )
        is False
    )
    assert (
        has_digest_delivery_channel(
            _user(preference="telegram", telegram_channel_id="-1001"), Mock()
        )
        is True
    )


def test_no_preference_uses_telegram_channel():
    assert has_digest_delivery_channel(_user(preference=None), Mock()) is True
    assert (
        has_digest_delivery_channel(
            _user(preference=None, telegram_channel_id=None), Mock()
        )
        is False
    )


@patch("app.core.digest_delivery.repository_factory")
def test_can_generate_requires_active_and_connected(mock_repo_factory):
    mock_phone_repo = Mock()
    mock_phone_repo.get_phone_numbers_for_user.return_value = ["+972500000000"]
    mock_repo_factory.get_whatsapp_phone_repository.return_value = mock_phone_repo
    db = Mock()

    assert (
        can_generate_immediate_digest(_user(preference="whatsapp", is_active=False), db)
        is False
    )
    assert (
        can_generate_immediate_digest(_user(preference="whatsapp", wa=False), db)
        is False
    )
    assert can_generate_immediate_digest(_user(preference="whatsapp"), db) is True
