from datetime import datetime

from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    """UserCreate class."""

    username: str
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    """UserUpdate class."""

    username: str | None = None
    email: EmailStr | None = None
    digest_interval_hours: int | None = None


class UserResponse(BaseModel):
    """UserResponse class."""

    id: int
    username: str
    email: str
    is_active: bool
    whatsapp_connected: bool
    telegram_channel_id: str | None = None
    digest_interval_hours: int
    created_at: datetime

    class Config:
        """Config class."""

        from_attributes = True

    """UserLogin class."""


class UserLogin(BaseModel):
    username: str
    password: str

    """Token class."""


class Token(BaseModel):
    access_token: str
    token_type: str

    """ChatCreate class."""


class ChatCreate(BaseModel):
    chat_id: str
    chat_name: str
    chat_type: str

    """ChatResponse class."""


class ChatResponse(BaseModel):
    id: int
    chat_id: str
    chat_name: str
    chat_type: str
    is_active: bool
    created_at: datetime

    class Config:
        """Config class."""

        from_attributes = True

    """DigestSettings class."""


class DigestSettings(BaseModel):
    telegram_channel_id: str
    digest_interval_hours: int


class WhatsAppConnectionWebhook(BaseModel):
    """WhatsApp connection webhook schema"""

    userId: str
    timestamp: datetime
    clientInfo: dict | None = None


class WhatsAppMessageWebhook(BaseModel):
    """WhatsApp message webhook schema"""

    userId: str
    messageId: str
    chatId: str
    chatName: str | None = ""
    chatType: str = "unknown"
    sender: str | None = None
    content: str | None = ""
    timestamp: str
    importance: int = 2
    hasMedia: bool = False
    fromMe: bool | None = None
    type: str | None = None
