import re
from typing import Optional

from pydantic import BaseModel, field_validator


class SecurityValidators:
    """Class for validating security of input data"""

    @staticmethod
    def validate_username(username: str) -> bool:
        """Validate username"""
        if not username or len(username) < 3 or len(username) > 50:
            return False

        # Only letters, numbers, underscores and hyphens
        if not re.match(r"^[a-zA-Z0-9_-]+$", username):
            return False

        return True

    @staticmethod
    def validate_email(email: str) -> bool:
        """Validate email address"""
        if not email or len(email) > 100:
            return False

        # Simple email format check
        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not re.match(email_pattern, email):
            return False

        return True

    @staticmethod
    def validate_password_strength(password: str) -> bool:
        """Validate password strength"""
        if not password or len(password) < 8:
            return False

        # Check for different types of characters
        has_upper = bool(re.search(r"[A-Z]", password))
        has_lower = bool(re.search(r"[a-z]", password))
        has_digit = bool(re.search(r"\d", password))
        has_special = bool(re.search(r'[!@#$%^&*(),.?":{}|<>]', password))

        # Require minimum 3 out of 4 character types
        strength_score = sum([has_upper, has_lower, has_digit, has_special])
        return strength_score >= 3

    @staticmethod
    def sanitize_input(text: str, max_length: int = 1000) -> str:
        """Clean input text from potentially dangerous characters"""
        if not text:
            return ""

        # Limit length
        if len(text) > max_length:
            text = text[:max_length]

        # Remove potentially dangerous characters
        dangerous_chars = ["<", ">", '"', "'", "&", "script", "javascript"]
        for char in dangerous_chars:
            text = text.replace(char, "")

        return text.strip()


class SecureUserCreate(BaseModel):
    """Secure model for user creation"""

    username: str
    email: str
    password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, v):
        """Validate Username.

        Args:
            v: Description of v.
        """
        if not SecurityValidators.validate_username(v):
            raise ValueError("Invalid username format")
        return v

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        """Validate Email.

        Args:
            v: Description of v.
        """
        if not SecurityValidators.validate_email(v):
            raise ValueError("Invalid email format")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        """Validate Password.

        Args:
            v: Description of v.
        """
        if not SecurityValidators.validate_password_strength(v):
            raise ValueError("Password does not meet security requirements")
        return v


class SecureMessageInput(BaseModel):
    """Secure model for incoming messages"""

    content: str
    chat_name: Optional[str] = None

    @field_validator("content")
    @classmethod
    def sanitize_content(cls, v):
        """Sanitize Content.

        Args:
            v: Description of v.
        """
        return SecurityValidators.sanitize_input(v, max_length=5000)

    @field_validator("chat_name")
    @classmethod
    def sanitize_chat_name(cls, v):
        """Sanitize Chat Name.

        Args:
            v: Description of v.
        """
        if v:
            return SecurityValidators.sanitize_input(v, max_length=100)
        return v


def validate_rate_limit(user_id: str, operation: str) -> bool:
    """Validate rate limit for operations"""
    # Here you can add rate-limit verification logic
    # For now, return True
    return True


def validate_api_key(api_key: str) -> bool:
    """Validate API keys"""
    if not api_key or len(api_key) < 10:
        return False

    # Check the format of the OpenAI API key
    if api_key.startswith("sk-") and len(api_key) > 20:
        return True

    # Check the format of the Telegram Bot Token
    if ":" in api_key and len(api_key) > 30:
        return True

    return False
