"""
Job model for HireFlow AI.

Stores scraped job listings from Lever, Greenhouse, and custom career pages.
Includes spam classification fields and all metadata needed for matching.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, Uuid

from src.config.database import Base

# JSONB on PostgreSQL, falls back to JSON on SQLite (for tests).
JSONBCompat = JSONB().with_variant(JSON, "sqlite")


class Job(Base):
    """Represents a scraped job listing.

    Attributes:
        id: Unique identifier (UUID).
        company_name: Name of the hiring company.
        role_title: Job title from the listing.
        jd_text: Full job description text.
        location: Job location (remote, city, etc.).
        application_url: Direct URL to apply (unique to prevent duplicates).
        posting_date: When the job was posted.
        listing_type: 'internship' or 'job'.
        skills_required: JSONB array of required skills extracted from JD.
        stipend_salary: Stipend or salary range as text.
        experience_required: Experience requirement as text.
        source: Scraper source (e.g., 'lever', 'greenhouse', 'generic').
        selection_process: Description of the selection/interview process.
        is_spam: Whether the listing was flagged as spam.
        spam_confidence: Confidence score from the spam filter (0.0 to 1.0).
        scraped_at: When the listing was scraped.
        created_at: Record creation timestamp.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_company_listing", "company_name", "listing_type"),
        Index("ix_jobs_is_spam", "is_spam"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    company_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role_title: Mapped[str] = mapped_column(String(500), nullable=False)
    jd_text: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    application_url: Mapped[str] = mapped_column(
        String(2048), nullable=False, unique=True
    )
    posting_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    listing_type: Mapped[str] = mapped_column(
        Enum(
            "internship",
            "job",
            name="listing_type_enum",
            create_constraint=True,
        ),
        nullable=False,
    )
    skills_required: Mapped[list | None] = mapped_column(
        JSONBCompat, nullable=True, default=list
    )
    stipend_salary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    experience_required: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    selection_process: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_spam: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    spam_confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # -- Relationships --
    applications: Mapped[list["Application"]] = relationship(  # noqa: F821
        "Application", back_populates="job", cascade="all, delete-orphan"
    )
    prep_guides: Mapped[list["PrepGuide"]] = relationship(  # noqa: F821
        "PrepGuide", back_populates="job", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<Job(id={self.id!r}, company={self.company_name!r}, "
            f"role={self.role_title!r})>"
        )
