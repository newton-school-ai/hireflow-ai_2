import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.config.database import Base
from datetime import datetime


class WeeklyReport(Base):
    __tablename__ = "weekly_reports"

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

    report_data: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )

    total_applications: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    interviews: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    offers: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    user = relationship("User")
