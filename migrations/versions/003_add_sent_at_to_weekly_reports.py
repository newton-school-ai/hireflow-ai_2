"""Add sent_at to weekly_reports table.

Revision ID: 003
Revises: 002
Create Date: 2026-08-24

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add sent_at column to the weekly_reports table."""
    op.add_column(
        "weekly_reports",
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove sent_at column from the weekly_reports table."""
    op.drop_column("weekly_reports", "sent_at")
