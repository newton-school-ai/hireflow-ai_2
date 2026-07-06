"""Initial schema - users, jobs, applications, prep_guides, weekly_reports

Revision ID: 001
Revises: None
Create Date: 2025-07-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all initial tables, indexes, and constraints."""

    # -- Enums --
    user_mode_enum = postgresql.ENUM(
        "internship", "job", name="user_mode_enum", create_type=False
    )
    listing_type_enum = postgresql.ENUM(
        "internship", "job", name="listing_type_enum", create_type=False
    )
    application_status_enum = postgresql.ENUM(
        "planned",
        "matched",
        "shortlisted",
        "resume_generated",
        "applied",
        "failed",
        "withdrawn",
        "needs_action",
        name="application_status_enum",
        create_type=False,
    )

    # Create enum types explicitly before table creation.
    user_mode_enum.create(op.get_bind(), checkfirst=True)
    listing_type_enum.create(op.get_bind(), checkfirst=True)
    application_status_enum.create(op.get_bind(), checkfirst=True)

    # -- users --
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column(
            "mode",
            user_mode_enum,
            server_default="internship",
            nullable=False,
        ),
        sa.Column("master_profile", postgresql.JSONB(), nullable=True),
        sa.Column(
            "weekly_quota",
            sa.Integer(),
            server_default="5",
            nullable=False,
        ),
        sa.Column(
            "confirmation_mode",
            sa.String(length=20),
            server_default="batch",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # -- jobs --
    op.create_table(
        "jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("role_title", sa.String(length=500), nullable=False),
        sa.Column("jd_text", sa.Text(), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("application_url", sa.String(length=2048), nullable=False),
        sa.Column("posting_date", sa.Date(), nullable=True),
        sa.Column("listing_type", listing_type_enum, nullable=False),
        sa.Column(
            "skills_required",
            postgresql.JSONB(),
            server_default="[]",
            nullable=True,
        ),
        sa.Column("stipend_salary", sa.String(length=255), nullable=True),
        sa.Column("experience_required", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("selection_process", sa.Text(), nullable=True),
        sa.Column(
            "is_spam",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column(
            "spam_confidence",
            sa.Float(),
            server_default="0.0",
            nullable=False,
        ),
        sa.Column(
            "scraped_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_url", name="uq_jobs_application_url"),
    )
    op.create_index("ix_jobs_company_name", "jobs", ["company_name"], unique=False)
    op.create_index(
        "ix_jobs_company_listing",
        "jobs",
        ["company_name", "listing_type"],
        unique=False,
    )
    op.create_index("ix_jobs_is_spam", "jobs", ["is_spam"], unique=False)

    # -- applications --
    op.create_table(
        "applications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column(
            "skill_matches",
            postgresql.JSONB(),
            server_default="[]",
            nullable=True,
        ),
        sa.Column(
            "skill_gaps",
            postgresql.JSONB(),
            server_default="[]",
            nullable=True,
        ),
        sa.Column("resume_path", sa.String(length=1024), nullable=True),
        sa.Column("resume_version", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            application_status_enum,
            server_default="matched",
            nullable=False,
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_applications_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name="fk_applications_job_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "job_id", name="uq_user_job"),
    )
    op.create_index(
        "ix_applications_user_id",
        "applications",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_applications_job_id",
        "applications",
        ["job_id"],
        unique=False,
    )

    # -- prep_guides --
    op.create_table(
        "prep_guides",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "skill_gaps",
            postgresql.JSONB(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "resources",
            postgresql.JSONB(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "mock_questions",
            postgresql.JSONB(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("predicted_rounds", sa.Integer(), nullable=True),
        sa.Column("company_intel", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_prep_guides_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name="fk_prep_guides_job_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_prep_guides_user_id",
        "prep_guides",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_prep_guides_job_id",
        "prep_guides",
        ["job_id"],
        unique=False,
    )

    # -- weekly_reports --
    op.create_table(
        "weekly_reports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column(
            "applications_sent",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "responses_received",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "top_matches",
            postgresql.JSONB(),
            server_default="[]",
            nullable=True,
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("report_path", sa.String(length=1024), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_weekly_reports_user_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_weekly_reports_user_id",
        "weekly_reports",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop all tables and enum types in reverse order."""

    # Drop tables (children first to respect FK constraints).
    op.drop_index("ix_weekly_reports_user_id", table_name="weekly_reports")
    op.drop_table("weekly_reports")

    op.drop_index("ix_prep_guides_job_id", table_name="prep_guides")
    op.drop_index("ix_prep_guides_user_id", table_name="prep_guides")
    op.drop_table("prep_guides")

    op.drop_index("ix_applications_job_id", table_name="applications")
    op.drop_index("ix_applications_user_id", table_name="applications")
    op.drop_table("applications")

    op.drop_index("ix_jobs_is_spam", table_name="jobs")
    op.drop_index("ix_jobs_company_listing", table_name="jobs")
    op.drop_index("ix_jobs_company_name", table_name="jobs")
    op.drop_table("jobs")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    # Drop enum types after tables that reference them are gone.
    op.execute("DROP TYPE IF EXISTS application_status_enum")
    op.execute("DROP TYPE IF EXISTS listing_type_enum")
    op.execute("DROP TYPE IF EXISTS user_mode_enum")
