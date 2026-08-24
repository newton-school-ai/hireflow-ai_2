"""
WeeklyReport model for HireFlow AI.

Stores weekly summary reports for users including application counts,
response tracking, and top match highlights.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import JSON, Uuid

from src.config.database import Base

# JSONB on PostgreSQL, falls back to JSON on SQLite (for tests).
JSONBCompat = JSONB().with_variant(JSON, "sqlite")


class WeeklyReport(Base):
    """Represents a weekly activity report for a user.

    Generated at the end of each application cycle to summarize
    what was sent, what responses came back, and which matches
    performed best.

    Attributes:
        id: Unique identifier (UUID).
        user_id: FK to the user this report belongs to.
        week_start: Start date of the reporting period.
        week_end: End date of the reporting period.
        applications_sent: Number of applications submitted this week.
        responses_received: Number of responses received.
        top_matches: JSONB array of best-performing matches.
        summary: LLM-generated narrative summary of the week.
        report_path: Path to the generated report file.
        created_at: When the report was generated.
    """

    __tablename__ = "weekly_reports"

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
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    week_end: Mapped[date] = mapped_column(Date, nullable=False)
    applications_sent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    responses_received: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    top_matches: Mapped[list | None] = mapped_column(
        JSONBCompat, nullable=True, default=list
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # -- Relationships --
    user: Mapped["User"] = relationship(  # noqa: F821
        "User", back_populates="weekly_reports"
    )

    def __repr__(self) -> str:
        return (
            f"<WeeklyReport(id={self.id!r}, user_id={self.user_id!r}, "
            f"week={self.week_start} to {self.week_end})>"
        )
