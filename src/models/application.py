"""
Application model for HireFlow AI.

Links a user to a job they are applying to, tracking match score,
skill analysis, resume versioning, and application status.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import JSON, Uuid

from src.config.database import Base

# JSONB on PostgreSQL, falls back to JSON on SQLite (for tests).
JSONBCompat = JSONB().with_variant(JSON, "sqlite")


class Application(Base):
    """Represents a user's application to a specific job.

    Attributes:
        id: Unique identifier (UUID).
        user_id: FK to the applying user.
        job_id: FK to the target job.
        match_score: Composite match score from the scorer (0.0 to 1.0).
        skill_matches: JSON array of skills the user matches.
        skill_gaps: JSON array of skills the user is missing.
        resume_path: Path to the tailored resume PDF.
        resume_version: Version number of the generated resume.
        status: Current application status.
        applied_at: When the application was actually submitted.
        created_at: Record creation timestamp.
    """

    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_user_job"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    skill_matches: Mapped[list | None] = mapped_column(
        JSONBCompat, nullable=True, default=list
    )
    skill_gaps: Mapped[list | None] = mapped_column(
        JSONBCompat, nullable=True, default=list
    )
    resume_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    resume_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(
        String(2048), nullable=True, default=None
    )
    status: Mapped[str] = mapped_column(
        Enum(
            "planned",
            "matched",
            "shortlisted",
            "confirmed",
            "resume_generated",
            "applied",
            "failed",
            "withdrawn",
            "needs_action",
            name="application_status_enum",
            create_constraint=True,
        ),
        nullable=False,
        default="matched",
        server_default="matched",
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # -- Relationships --
    user: Mapped["User"] = relationship(  # noqa: F821
        "User", back_populates="applications"
    )
    job: Mapped["Job"] = relationship(  # noqa: F821
        "Job", back_populates="applications"
    )

    def __repr__(self) -> str:
        return (
            f"<Application(id={self.id!r}, user_id={self.user_id!r}, "
            f"job_id={self.job_id!r}, status={self.status!r})>"
        )
