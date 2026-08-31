"""drop_resource_savings

Revision ID: drop_resource_savings
Revises: add_digest_prefs_phones
Create Date: 2026-03-31 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "drop_resource_savings"
down_revision: str | None = "add_digest_prefs_phones"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(op.f("ix_resource_savings_id"), table_name="resource_savings")
    op.drop_table("resource_savings")


def downgrade() -> None:
    op.create_table(
        "resource_savings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("whatsapp_connections_saved", sa.Integer(), nullable=True),
        sa.Column("messages_processed_saved", sa.Integer(), nullable=True),
        sa.Column("openai_requests_saved", sa.Integer(), nullable=True),
        sa.Column("memory_mb_saved", sa.Float(), nullable=True),
        sa.Column("cpu_seconds_saved", sa.Float(), nullable=True),
        sa.Column("openai_cost_saved_usd", sa.Float(), nullable=True),
        sa.Column("period_start", sa.DateTime(), nullable=False),
        sa.Column("period_end", sa.DateTime(), nullable=False),
        sa.Column("reason", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_resource_savings_id"), "resource_savings", ["id"], unique=False
    )
