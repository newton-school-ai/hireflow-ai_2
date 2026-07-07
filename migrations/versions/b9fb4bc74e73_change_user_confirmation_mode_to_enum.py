"""Change user confirmation_mode to Enum

Revision ID: b9fb4bc74e73
Revises: 001
Create Date: 2026-07-07 22:41:18.430541
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b9fb4bc74e73"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    confirmation_mode_enum = sa.Enum(
        "batch", "individual", name="confirmation_mode_enum", create_constraint=True
    )
    confirmation_mode_enum.create(op.get_bind(), checkfirst=True)

    op.alter_column(
        "users",
        "confirmation_mode",
        existing_type=sa.VARCHAR(length=20),
        type_=confirmation_mode_enum,
        postgresql_using="confirmation_mode::confirmation_mode_enum",
        existing_nullable=False,
        existing_server_default=sa.text("'batch'::character varying"),
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "confirmation_mode",
        existing_type=sa.Enum(
            "batch", "individual", name="confirmation_mode_enum", create_constraint=True
        ),
        type_=sa.VARCHAR(length=20),
        existing_nullable=False,
        existing_server_default=sa.text("'batch'::character varying"),
    )

    confirmation_mode_enum = sa.Enum(
        "batch", "individual", name="confirmation_mode_enum", create_constraint=True
    )
    confirmation_mode_enum.drop(op.get_bind(), checkfirst=True)
