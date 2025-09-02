from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class User(Base):  # type: ignore[misc,valid-type]
    """User class."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)

    # WhatsApp connection info
    whatsapp_connected = Column(Boolean, default=False)
    whatsapp_session_id = Column(String(100), nullable=True)
    whatsapp_last_seen = Column(DateTime, nullable=True)  # New field
    whatsapp_auto_reconnect = Column(Boolean, default=True)  # New field

    # Telegram settings
    telegram_channel_id = Column(String(100), nullable=True)

    # Digest settings
    digest_interval_hours = Column(Integer, default=4)

    # User status
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    monitored_chats = relationship("MonitoredChat", back_populates="user")
    digest_logs = relationship("DigestLog", back_populates="user")


class MonitoredChat(Base):  # type: ignore[misc,valid-type]
    """MonitoredChat class."""

    __tablename__ = "monitored_chats"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    chat_id = Column(String(100), nullable=False)
    chat_name = Column(String(200), nullable=False)
    custom_name = Column(String(200), nullable=True)  # Custom Russian name for the chat
    chat_type = Column(String(20), nullable=False)  # 'group' or 'private'
    auto_added = Column(Boolean, default=False)  # New field - automatically added

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="monitored_chats")
    messages = relationship("WhatsAppMessage", back_populates="chat")


class WhatsAppMessage(Base):  # type: ignore[misc,valid-type]
    """WhatsAppMessage class."""

    __tablename__ = "whatsapp_messages"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("monitored_chats.id"), nullable=False)
    message_id = Column(String(200), unique=True, nullable=False)  # WhatsApp message ID
    sender = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)

    timestamp = Column(DateTime, nullable=False)
    importance_score = Column(Integer, default=1)  # 1-5 scale
    has_media = Column(Boolean, default=False)

    is_processed = Column(Boolean, default=False)
    ai_analyzed = Column(Boolean, default=False)  # New field - analyzed by AI
    processing_attempts = Column(Integer, default=0)  # New field - processing attempts

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    chat = relationship("MonitoredChat", back_populates="messages")


class DigestLog(Base):  # type: ignore[misc,valid-type]
    """DigestLog class."""

    __tablename__ = "digest_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    digest_content = Column(Text, nullable=False)
    message_count = Column(Integer, nullable=False)
    telegram_sent = Column(Boolean, default=False)
    telegram_error = Column(Text, nullable=True)  # New field - sending error

    generation_time_seconds = Column(
        Float, nullable=True
    )  # New field - generation time

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="digest_logs")


# New model for logging system events
class SystemLog(Base):  # type: ignore[misc,valid-type]
    """SystemLog class."""

    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    event_type = Column(
        String(50), nullable=False
    )  # 'connection', 'disconnection', 'error', etc.
    event_data = Column(Text, nullable=True)  # JSON string with event details
    severity = Column(
        String(20), default="info"
    )  # 'info', 'warning', 'error', 'critical'

    created_at = Column(DateTime, default=datetime.utcnow)


# New model for storing user configuration
class UserSettings(Base):  # type: ignore[misc,valid-type]
    """UserSettings class."""

    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)

    # Digest settings
    min_importance_level = Column(Integer, default=3)  # Minimum importance level
    include_media_messages = Column(Boolean, default=True)
    max_message_age_hours = Column(Integer, default=24)  # Maximum message age

    # Notification settings
    urgent_notifications = Column(Boolean, default=True)  # Urgent notifications
    daily_summary = Column(Boolean, default=True)  # Daily summary

    # Auto-add chat settings
    auto_add_new_chats = Column(Boolean, default=False)
    auto_add_group_chats_only = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# New model for storing OpenAI metrics
class OpenAIMetrics(Base):  # type: ignore[misc,valid-type]
    """OpenAI metrics storage model."""

    __tablename__ = "openai_metrics"

    id = Column(Integer, primary_key=True, index=True)

    # Request details
    model = Column(String(50), nullable=False)
    input_tokens = Column(Integer, nullable=False)
    output_tokens = Column(Integer, nullable=False)
    total_tokens = Column(Integer, nullable=False)
    cost_usd = Column(Float, nullable=False)
    success = Column(Boolean, nullable=False)
    error_message = Column(Text, nullable=True)

    # Timestamp
    request_time = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ResourceSavings(Base):  # type: ignore[misc,valid-type]
    """ResourceSavings class for tracking resource savings from suspended users."""

    __tablename__ = "resource_savings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Savings metrics
    whatsapp_connections_saved = Column(
        Integer, default=0
    )  # Number of WhatsApp connections saved
    messages_processed_saved = Column(
        Integer, default=0
    )  # Number of messages not processed
    openai_requests_saved = Column(
        Integer, default=0
    )  # Number of OpenAI API calls saved
    memory_mb_saved = Column(Float, default=0.0)  # Memory saved in MB
    cpu_seconds_saved = Column(Float, default=0.0)  # CPU time saved in seconds

    # Cost savings
    openai_cost_saved_usd = Column(Float, default=0.0)  # OpenAI API cost saved in USD

    # Time period
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)

    # Metadata
    reason = Column(
        String(100), nullable=False
    )  # 'user_suspended', 'system_cleanup', etc.
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User")
