"""
PrepGuide model for HireFlow AI.

Stores interview preparation guides generated for users,
including skill gaps, learning resources, and mock questions.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import JSON, Uuid

from src.config.database import Base


class PrepGuide(Base):
    """Represents an interview prep guide for a user.

    A prep guide can be linked to a specific job (targeted prep) or be
    general (job_id is NULL). It contains skill gaps identified by the
    matcher, curated learning resources, and LLM-generated mock questions.

    Attributes:
        id: Unique identifier (UUID).
        user_id: FK to the user this guide is for.
        job_id: FK to the target job (nullable for general guides).
        skill_gaps: JSON array of skills to improve.
        resources: JSON array of learning resources (URLs, courses, etc.).
        mock_questions: JSON array of practice interview questions.
        created_at: When the guide was generated.
    """

    __tablename__ = "prep_guides"

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
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    skill_gaps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    resources: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    mock_questions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # -- Relationships --
    user: Mapped["User"] = relationship(  # noqa: F821
        "User", back_populates="prep_guides"
    )
    job: Mapped["Job | None"] = relationship(  # noqa: F821
        "Job", back_populates="prep_guides"
    )

    def __repr__(self) -> str:
        return (
            f"<PrepGuide(id={self.id!r}, user_id={self.user_id!r}, "
            f"job_id={self.job_id!r})>"
        )
