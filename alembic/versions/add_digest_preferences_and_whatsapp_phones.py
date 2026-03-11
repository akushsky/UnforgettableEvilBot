"""Add digest preferences and WhatsApp phones tables

Revision ID: add_digest_preferences_and_whatsapp_phones
Revises: 4fb32425e140
Create Date: 2024-12-19 10:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "add_digest_prefs_phones"
down_revision = "4fb32425e140"
branch_labels = None
depends_on = None


def upgrade():
    # First, alter the telegram_channel_id column to have sufficient length
    # The initial migration created it as String() which defaults to varchar(32) in PostgreSQL
    # We need it to be at least varchar(100) to match our current model
    op.execute("ALTER TABLE users ALTER COLUMN telegram_channel_id TYPE VARCHAR(100)")

    # Create digest_preferences table
    op.create_table(
        "digest_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_digest_preferences_id"), "digest_preferences", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_digest_preferences_name"), "digest_preferences", ["name"], unique=True
    )

    # Create whatsapp_phones table
    op.create_table(
        "whatsapp_phones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("phone_number", sa.String(length=20), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_whatsapp_phones_id"), "whatsapp_phones", ["id"], unique=False
    )

    # Add digest_preference_id to users table
    op.add_column(
        "users", sa.Column("digest_preference_id", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        "fk_users_digest_preference_id",
        "users",
        "digest_preferences",
        ["digest_preference_id"],
        ["id"],
    )

    # Add WhatsApp delivery fields to digest_logs table
    op.add_column(
        "digest_logs", sa.Column("whatsapp_sent", sa.Boolean(), nullable=True)
    )
    op.add_column("digest_logs", sa.Column("whatsapp_error", sa.Text(), nullable=True))

    # Insert default digest preferences
    op.execute(
        """
        INSERT INTO digest_preferences (name, display_name, description, is_active, created_at, updated_at)
        VALUES
        ('telegram', 'Telegram', 'Send digests only to Telegram channel', true, NOW(), NOW()),
        ('whatsapp', 'WhatsApp', 'Send digests only to WhatsApp phone numbers', true, NOW(), NOW())
    """
    )

    # Set default preference for existing users (telegram if they have telegram_channel_id, otherwise whatsapp)
    op.execute(
        """
        UPDATE users
        SET digest_preference_id = (
            CASE
                WHEN telegram_channel_id IS NOT NULL AND telegram_channel_id != ''
                THEN (SELECT id FROM digest_preferences WHERE name = 'telegram')
                ELSE (SELECT id FROM digest_preferences WHERE name = 'whatsapp')
            END
        )
    """
    )


def downgrade():
    op.drop_constraint("fk_users_digest_preference_id", "users", type_="foreignkey")

    # Remove columns
    op.drop_column("users", "digest_preference_id")
    op.drop_column("digest_logs", "whatsapp_error")
    op.drop_column("digest_logs", "whatsapp_sent")

    # Drop tables
    op.drop_index(op.f("ix_whatsapp_phones_id"), table_name="whatsapp_phones")
    op.drop_table("whatsapp_phones")
    op.drop_index(op.f("ix_digest_preferences_name"), table_name="digest_preferences")
    op.drop_index(op.f("ix_digest_preferences_id"), table_name="digest_preferences")
    op.drop_table("digest_preferences")

    # Revert telegram_channel_id column length change
    op.execute("ALTER TABLE users ALTER COLUMN telegram_channel_id TYPE VARCHAR(32)")
