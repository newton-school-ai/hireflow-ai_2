import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.config.database import Base


class UserMode(str, enum.Enum):
    internship = "internship"
    job = "job"


class ConfirmationMode(str, enum.Enum):
    automatic = "automatic"
    manual = "manual"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )

    mode: Mapped[UserMode] = mapped_column(
        Enum(UserMode),
        nullable=False,
    )

    master_profile: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )

    weekly_quota: Mapped[int] = mapped_column(
        Integer,
        default=20,
        nullable=False,
    )

    confirmation_mode: Mapped[ConfirmationMode] = mapped_column(
        Enum(ConfirmationMode),
        default=ConfirmationMode.manual,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )