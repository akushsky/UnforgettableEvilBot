"""add_resource_savings_table

Revision ID: 3e7da6056948
Revises: 2bffd4260324
Create Date: 2025-08-24 00:30:25.147521

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op  # type: ignore[attr-defined]

# revision identifiers, used by Alembic.
revision: str = "3e7da6056948"
down_revision: Union[str, None] = "b2419b8e0ca6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add missing columns to resource_savings if not present
    with op.batch_alter_table("resource_savings") as batch_op:
        batch_op.add_column(sa.Column("reason", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("created_at", sa.DateTime(), nullable=True))

    # Backfill nulls with defaults (safe no-op if table empty)
    op.execute(
        """
        UPDATE resource_savings
        SET reason = COALESCE(reason, 'user_suspended'),
            created_at = COALESCE(created_at, NOW())
        """
    )

    # Set NOT NULL on reason after backfill
    with op.batch_alter_table("resource_savings") as batch_op:
        batch_op.alter_column(
            "reason", existing_type=sa.String(length=100), nullable=False
        )


def downgrade() -> None:
    with op.batch_alter_table("resource_savings") as batch_op:
        batch_op.drop_column("created_at")
        batch_op.drop_column("reason")
