"""drop_unused_user_settings_columns

Revision ID: drop_unused_user_settings_cols
Revises: drop_resource_savings
Create Date: 2026-03-31 01:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "drop_unused_user_settings_cols"
down_revision: str | None = "drop_resource_savings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("user_settings") as batch_op:
        batch_op.drop_column("include_media_messages")
        batch_op.drop_column("daily_summary")
        batch_op.drop_column("auto_add_new_chats")
        batch_op.drop_column("auto_add_group_chats_only")


def downgrade() -> None:
    with op.batch_alter_table("user_settings") as batch_op:
        batch_op.add_column(
            sa.Column("include_media_messages", sa.Boolean(), nullable=True)
        )
        batch_op.add_column(sa.Column("daily_summary", sa.Boolean(), nullable=True))
        batch_op.add_column(
            sa.Column("auto_add_new_chats", sa.Boolean(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("auto_add_group_chats_only", sa.Boolean(), nullable=True)
        )
