"""add_performance_indexes

Revision ID: b2419b8e0ca6
Revises: 49d95ee9b45d
Create Date: 2025-08-21 13:54:17.102671

"""
from typing import Sequence, Union

from alembic import op  # type: ignore[attr-defined]

# revision identifiers, used by Alembic.
revision: str = "b2419b8e0ca6"
down_revision: Union[str, None] = "49d95ee9b45d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Performance optimization indexes

    # Indexes for whatsapp_messages table
    op.create_index(
        "idx_whatsapp_messages_chat_timestamp",
        "whatsapp_messages",
        ["chat_id", "timestamp"],
    )
    op.create_index(
        "idx_whatsapp_messages_importance", "whatsapp_messages", ["importance_score"]
    )
    op.create_index(
        "idx_whatsapp_messages_processed", "whatsapp_messages", ["is_processed"]
    )
    op.create_index(
        "idx_whatsapp_messages_ai_analyzed", "whatsapp_messages", ["ai_analyzed"]
    )

    # Indexes for monitored_chats table
    op.create_index(
        "idx_monitored_chats_user_active", "monitored_chats", ["user_id", "is_active"]
    )
    op.create_index("idx_monitored_chats_auto_added", "monitored_chats", ["auto_added"])

    # Indexes for digest_logs table
    op.create_index(
        "idx_digest_logs_user_created", "digest_logs", ["user_id", "created_at"]
    )
    op.create_index("idx_digest_logs_telegram_sent", "digest_logs", ["telegram_sent"])

    # Indexes for users table
    op.create_index("idx_users_whatsapp_connected", "users", ["whatsapp_connected"])
    op.create_index("idx_users_whatsapp_last_seen", "users", ["whatsapp_last_seen"])

    # Indexes for system logs
    op.create_index(
        "idx_system_logs_user_event", "system_logs", ["user_id", "event_type"]
    )
    op.create_index(
        "idx_system_logs_severity_created", "system_logs", ["severity", "created_at"]
    )


def downgrade() -> None:
    # Remove indexes on rollback

    # whatsapp_messages indexes
    op.drop_index(
        "idx_whatsapp_messages_chat_timestamp", table_name="whatsapp_messages"
    )
    op.drop_index("idx_whatsapp_messages_importance", table_name="whatsapp_messages")
    op.drop_index("idx_whatsapp_messages_processed", table_name="whatsapp_messages")
    op.drop_index("idx_whatsapp_messages_ai_analyzed", table_name="whatsapp_messages")

    # monitored_chats indexes
    op.drop_index("idx_monitored_chats_user_active", table_name="monitored_chats")
    op.drop_index("idx_monitored_chats_auto_added", table_name="monitored_chats")

    # digest_logs indexes
    op.drop_index("idx_digest_logs_user_created", table_name="digest_logs")
    op.drop_index("idx_digest_logs_telegram_sent", table_name="digest_logs")

    # users indexes
    op.drop_index("idx_users_whatsapp_connected", table_name="users")
    op.drop_index("idx_users_whatsapp_last_seen", table_name="users")

    # system_logs indexes
    op.drop_index("idx_system_logs_user_event", table_name="system_logs")
    op.drop_index("idx_system_logs_severity_created", table_name="system_logs")
