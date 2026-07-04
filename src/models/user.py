"""
User model for HireFlow AI.

Stores user profiles including mode (internship/job), master profile data
(as JSON/JSONB), weekly application quota, and confirmation preferences.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, Uuid

from src.config.database import Base


class User(Base):
    """Represents a HireFlow user.

    Attributes:
        id: Unique identifier (UUID).
        name: Full name.
        email: Email address (unique, indexed).
        mode: Target mode - 'internship' or 'job'.
        master_profile: JSON blob storing skills, projects, experience, etc.
        weekly_quota: Maximum applications per week.
        confirmation_mode: How the user confirms weekly plans ('batch' or 'individual').
        created_at: Timestamp of account creation.
        updated_at: Timestamp of last profile update.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    mode: Mapped[str] = mapped_column(
        Enum("internship", "job", name="user_mode_enum", create_constraint=True),
        nullable=False,
        default="internship",
        server_default="internship",
    )
    master_profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    weekly_quota: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default="5"
    )
    confirmation_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="batch", server_default="batch"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # -- Relationships --
    applications: Mapped[list["Application"]] = relationship(  # noqa: F821
        "Application", back_populates="user", cascade="all, delete-orphan"
    )
    prep_guides: Mapped[list["PrepGuide"]] = relationship(  # noqa: F821
        "PrepGuide", back_populates="user", cascade="all, delete-orphan"
    )
    weekly_reports: Mapped[list["WeeklyReport"]] = relationship(  # noqa: F821
        "WeeklyReport", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id!r}, email={self.email!r}, mode={self.mode!r})>"
