import enum
import uuid
from datetime import datetime
from sqlalchemy import DateTime, Enum, Float, ForeignKey, Text, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.config.database import Base


class ApplicationStatus(str, enum.Enum):
    pending = "pending"
    applied = "applied"
    rejected = "rejected"
    interview = "interview"
    accepted = "accepted"


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id"),
        nullable=False,
    )

    match_score: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
    )

    skill_gaps: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )

    resume_path: Mapped[str] = mapped_column(
        String(500),
        nullable=True,
    )

    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus),
        default=ApplicationStatus.pending,
        nullable=False,
    )

    notes: Mapped[str] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    user = relationship("User")
    job = relationship("Job")
