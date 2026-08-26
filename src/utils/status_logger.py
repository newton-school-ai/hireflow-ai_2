"""
Application Status Logger for HireFlow AI.

Provides a reusable ``StatusLogger`` class that persists status changes to the
``applications`` table (and optionally logs them to the Python logging system).

The logger is intentionally thin — it writes only to the columns that already
exist on the ``Application`` model.  No extra audit table is needed for the
current milestone; the single ``status`` + ``failure_reason`` + ``applied_at``
combination is sufficient to answer every question the dashboard needs.

Usage::

    from sqlalchemy.orm import Session
    from src.utils.status_logger import StatusLogger

    logger = StatusLogger(db)
    logger.log(application_id=app.id, status="applied")
    logger.log(
        application_id=app.id,
        status="failed",
        failure_reason="Playwright timeout after 3 retries",
    )
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy.orm import Session

from src.models.application import Application

logger = logging.getLogger(__name__)

# Exhaustive list mirrors the Enum defined in Application.status.
ApplicationStatus = Literal[
    "planned",
    "matched",
    "shortlisted",
    "confirmed",
    "resume_generated",
    "applied",
    "failed",
    "withdrawn",
    "needs_action",
]

# Used for runtime validation — keeps StatusLogger honest even when callers
# bypass the type checker (e.g. values coming from JSON or a DB query).
VALID_STATUSES: frozenset[str] = frozenset(
    {
        "planned",
        "matched",
        "shortlisted",
        "confirmed",
        "resume_generated",
        "applied",
        "failed",
        "withdrawn",
        "needs_action",
    }
)

_FAILURE_STATUSES: frozenset[str] = frozenset({"failed", "needs_action"})


class StatusLoggerError(Exception):
    """Raised when ``StatusLogger`` cannot complete a logging operation."""


class StatusLogger:
    """Persists application status changes to the database.

    Each ``log()`` call updates the ``Application`` row in-place and commits
    the change.  If the application cannot be found the call raises
    ``StatusLoggerError`` so callers always know whether the write succeeded.

    Args:
        db: An active SQLAlchemy ``Session``.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log(
        self,
        application_id: uuid.UUID,
        status: ApplicationStatus,
        failure_reason: str | None = None,
    ) -> Application:
        """Update the status of an application and persist the change.

        When *status* is ``"applied"``, ``applied_at`` is stamped with the
        current UTC time.  When *status* is in ``_FAILURE_STATUSES``,
        *failure_reason* is stored so the history API and weekly report can
        surface it.

        Args:
            application_id: UUID of the ``Application`` row to update.
            status: New application status (must be a valid ``ApplicationStatus``).
            failure_reason: Human-readable reason for failure or needs_action.
                            Ignored (and cleared) for non-failure statuses.

        Returns:
            The updated ``Application`` ORM instance (already committed).

        Raises:
            ValueError: If *status* is not a recognised ``ApplicationStatus``.
            StatusLoggerError: If the application is not found in the database.
        """
        # Runtime validation — type hints alone don't stop callers passing
        # arbitrary strings (e.g. values deserialized from JSON).
        if status not in VALID_STATUSES:
            raise ValueError(
                f"StatusLogger: {status!r} is not a valid ApplicationStatus. "
                f"Valid values: {sorted(VALID_STATUSES)}"
            )

        application = (
            self._db.query(Application).filter(Application.id == application_id).first()
        )

        if application is None:
            raise StatusLoggerError(
                f"StatusLogger: application {application_id!r} not found."
            )

        old_status = application.status
        application.status = status

        if status == "applied":
            application.applied_at = datetime.now(tz=timezone.utc)

        if status in _FAILURE_STATUSES:
            application.failure_reason = failure_reason
        else:
            # Clear any stale failure reason when transitioning to a healthy state.
            application.failure_reason = None

        try:
            self._db.commit()
            self._db.refresh(application)
        except Exception:
            self._db.rollback()
            raise

        logger.info(
            "StatusLogger: application %s transitioned %s → %s%s",
            application_id,
            old_status,
            status,
            f" (reason: {failure_reason})" if failure_reason else "",
        )

        return application
