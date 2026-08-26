"""Add failure_reason column to applications table.

Revision ID: 002
Revises: 001
Create Date: 2026-08-05

Records why an application could not be submitted automatically
(CAPTCHA detected, selector missing, timeout exhausted, etc.).
Consumed by the weekly report (Issue #20) to surface actionable failures.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add failure_reason column to the applications table."""
    op.add_column(
        "applications",
        sa.Column(
            "failure_reason",
            sa.String(length=2048),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove failure_reason column from the applications table."""
    op.drop_column("applications", "failure_reason")
