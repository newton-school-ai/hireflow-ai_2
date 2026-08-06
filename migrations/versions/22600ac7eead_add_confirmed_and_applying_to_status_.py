"""Add confirmed and applying to status enum

Revision ID: 22600ac7eead
Revises: 002
Create Date: 2026-08-07 01:35:58.141614
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '22600ac7eead'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Adding confirmed and applying to status enum
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("COMMIT")
        op.execute("ALTER TYPE application_status_enum ADD VALUE IF NOT EXISTS 'confirmed'")
        op.execute("ALTER TYPE application_status_enum ADD VALUE IF NOT EXISTS 'applying'")


def downgrade() -> None:
    pass
