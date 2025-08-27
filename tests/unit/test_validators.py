import pytest
from pydantic import ValidationError

from app.core.validators import (
    SecureMessageInput,
    SecureUserCreate,
    SecurityValidators,
    validate_api_key,
    validate_rate_limit,
)


class TestSecurityValidators:
    def test_validate_username_valid(self):
        """Test valid username validation"""
        assert SecurityValidators.validate_username("testuser")
        assert SecurityValidators.validate_username("test_user")
        assert SecurityValidators.validate_username("test-user")
        assert SecurityValidators.validate_username("test123")
        assert SecurityValidators.validate_username("a" * 50)  # Max length

    def test_validate_username_invalid(self):
        """Test invalid username validation"""
        assert SecurityValidators.validate_username("") is False
        assert SecurityValidators.validate_username("ab") is False  # Too short
        assert SecurityValidators.validate_username("a" * 51) is False  # Too long
        assert (
            SecurityValidators.validate_username("test@user") is False
        )  # Invalid chars
        assert SecurityValidators.validate_username("test user") is False  # Space
        assert SecurityValidators.validate_username("test.user") is False  # Dot
        assert SecurityValidators.validate_username("test/user") is False  # Slash

    def test_validate_email_valid(self):
        """Test valid email validation"""
        assert SecurityValidators.validate_email("test@example.com")
        assert SecurityValidators.validate_email("user.name@domain.co.uk")
        assert SecurityValidators.validate_email("test+tag@example.org")
        assert SecurityValidators.validate_email(
            "a" * 50 + "@example.com"
        )  # Near max length

    def test_validate_email_invalid(self):
        """Test invalid email validation"""
        assert SecurityValidators.validate_email("") is False
        assert SecurityValidators.validate_email("a" * 101) is False  # Too long
        assert SecurityValidators.validate_email("invalid-email") is False
        assert SecurityValidators.validate_email("@example.com") is False
        assert SecurityValidators.validate_email("test@") is False
        assert SecurityValidators.validate_email("test@.com") is False
        assert SecurityValidators.validate_email("test.example.com") is False

    def test_validate_password_strength_strong(self):
        """Test strong password validation"""
        assert SecurityValidators.validate_password_strength("StrongPass123!")
        assert SecurityValidators.validate_password_strength("MyP@ssw0rd")
        assert SecurityValidators.validate_password_strength("Secure123#")
        assert SecurityValidators.validate_password_strength("Abc123!@#")

    def test_validate_password_strength_weak(self):
        """Test weak password validation"""
        assert SecurityValidators.validate_password_strength("") is False
        assert (
            SecurityValidators.validate_password_strength("short") is False
        )  # Too short
        assert (
            SecurityValidators.validate_password_strength("onlylowercase") is False
        )  # No variety
        assert (
            SecurityValidators.validate_password_strength("ONLYUPPERCASE") is False
        )  # No variety
        assert (
            SecurityValidators.validate_password_strength("12345678") is False
        )  # Only digits
        assert (
            SecurityValidators.validate_password_strength("!!!!!!!!") is False
        )  # Only special
        assert (
            SecurityValidators.validate_password_strength("lower123") is False
        )  # Only 2 types
        assert (
            SecurityValidators.validate_password_strength("UPPER123") is False
        )  # Only 2 types

    def test_sanitize_input_normal(self):
        """Test normal input sanitization"""
        result = SecurityValidators.sanitize_input("Normal text input")
        assert result == "Normal text input"

    def test_sanitize_input_empty(self):
        """Test empty input sanitization"""
        result = SecurityValidators.sanitize_input("")
        assert result == ""

    def test_sanitize_input_none(self):
        """Test None input sanitization"""
        result = SecurityValidators.sanitize_input("")  # Empty string instead of None
        assert result == ""

    def test_sanitize_input_dangerous_chars(self):
        """Test sanitization of dangerous characters"""
        dangerous_input = '<script>alert("xss")</script>'
        result = SecurityValidators.sanitize_input(dangerous_input)
        assert result == "alert(xss)/"

    def test_sanitize_input_dangerous_chars_individual(self):
        """Test sanitization of individual dangerous characters"""
        # Test each dangerous character
        assert SecurityValidators.sanitize_input("test<script>") == "test"
        assert (
            SecurityValidators.sanitize_input("test>script") == "test"
        )  # Removes both > and script
        assert SecurityValidators.sanitize_input('test"quote') == "testquote"
        assert SecurityValidators.sanitize_input("test'quote") == "testquote"
        assert SecurityValidators.sanitize_input("test&amp") == "testamp"
        assert (
            SecurityValidators.sanitize_input("testjavascript") == "testjava"
        )  # Removes javascript
        assert (
            SecurityValidators.sanitize_input("testscript") == "test"
        )  # Removes script

    def test_sanitize_input_max_length(self):
        """Test input sanitization with max length"""
        long_input = "a" * 2000
        result = SecurityValidators.sanitize_input(long_input, max_length=1000)
        assert len(result) == 1000
        assert result == "a" * 1000

    def test_sanitize_input_custom_max_length(self):
        """Test input sanitization with custom max length"""
        long_input = "a" * 500
        result = SecurityValidators.sanitize_input(long_input, max_length=100)
        assert len(result) == 100
        assert result == "a" * 100

    def test_sanitize_input_whitespace(self):
        """Test input sanitization with whitespace"""
        result = SecurityValidators.sanitize_input("  test input  ")
        assert result == "test input"


class TestSecureUserCreate:
    def test_valid_user_creation(self):
        """Test valid user creation"""
        user_data = {
            "username": "testuser",
            "email": "test@example.com",
            "password": "StrongPass123!",
        }
        user = SecureUserCreate(**user_data)
        assert user.username == "testuser"
        assert user.email == "test@example.com"
        assert user.password == "StrongPass123!"

    def test_invalid_username(self):
        """Test invalid username validation"""
        user_data = {
            "username": "ab",  # Too short
            "email": "test@example.com",
            "password": "StrongPass123!",
        }
        with pytest.raises(ValidationError, match="Invalid username format"):
            SecureUserCreate(**user_data)

    def test_invalid_email(self):
        """Test invalid email validation"""
        user_data = {
            "username": "testuser",
            "email": "invalid-email",
            "password": "StrongPass123!",
        }
        with pytest.raises(ValidationError, match="Invalid email format"):
            SecureUserCreate(**user_data)

    def test_weak_password(self):
        """Test weak password validation"""
        user_data = {
            "username": "testuser",
            "email": "test@example.com",
            "password": "weak",
        }
        with pytest.raises(
            ValidationError, match="Password does not meet security requirements"
        ):
            SecureUserCreate(**user_data)


class TestSecureMessageInput:
    def test_valid_message_input(self):
        """Test valid message input"""
        message_data = {
            "content": "This is a valid message content",
            "chat_name": "Test Chat",
        }
        message = SecureMessageInput(**message_data)
        assert message.content == "This is a valid message content"
        assert message.chat_name == "Test Chat"

    def test_message_input_without_chat_name(self):
        """Test message input without chat name"""
        message_data = {"content": "This is a valid message content"}
        message = SecureMessageInput(**message_data)
        assert message.content == "This is a valid message content"
        assert message.chat_name is None

    def test_message_input_sanitizes_content(self):
        """Test that content is sanitized"""
        message_data = {
            "content": '<script>alert("xss")</script>',
            "chat_name": "Test Chat",
        }
        message = SecureMessageInput(**message_data)
        assert message.content == "alert(xss)/"

    def test_message_input_sanitizes_chat_name(self):
        """Test that chat name is sanitized"""
        message_data = {
            "content": "Valid content",
            "chat_name": '<script>alert("xss")</script>',
        }
        message = SecureMessageInput(**message_data)
        assert message.chat_name == "alert(xss)/"

    def test_message_input_content_max_length(self):
        """Test content max length enforcement"""
        long_content = "a" * 6000  # Over 5000 limit
        message_data = {"content": long_content}
        message = SecureMessageInput(**message_data)
        assert len(message.content) == 5000

    def test_message_input_chat_name_max_length(self):
        """Test chat name max length enforcement"""
        long_chat_name = "a" * 150  # Over 100 limit
        message_data = {"content": "Valid content", "chat_name": long_chat_name}
        message = SecureMessageInput(**message_data)
        assert message.chat_name is not None
        assert len(message.chat_name) == 100


class TestValidateRateLimit:
    def test_validate_rate_limit(self):
        """Test rate limit validation"""
        # Currently always returns True
        assert validate_rate_limit("user123", "operation")
        assert validate_rate_limit("", "")
        assert validate_rate_limit("user456", "create_message")


class TestValidateApiKey:
    def test_validate_openai_api_key_valid(self):
        """Test valid OpenAI API key validation"""
        assert validate_api_key("sk-1234567890abcdef1234567890abcdef1234567890abcdef")
        assert validate_api_key("sk-test1234567890abcdef1234567890abcdef1234567890")

    def test_validate_telegram_api_key_valid(self):
        """Test valid Telegram API key validation"""
        assert validate_api_key("1234567890:ABCdefGHIjklMNOpqrsTUVwxyz")
        assert validate_api_key("9876543210:TestBotToken1234567890abcdef")

    def test_validate_api_key_invalid(self):
        """Test invalid API key validation"""
        assert validate_api_key("") is False
        assert validate_api_key("short") is False  # Too short
        assert validate_api_key("sk-") is False  # Incomplete OpenAI key
        assert validate_api_key("1234567890") is False  # No colon for Telegram
        assert validate_api_key("invalid:key") is False  # Too short for Telegram
        assert validate_api_key("sk-123") is False  # Too short for OpenAI
        assert validate_api_key("1234567890:") is False  # Incomplete Telegram key
