"""
Status Logger utility for HireFlow AI.

Provides reusable tracking and audit logging for application status transitions,
ensuring a complete immutable history of application state progression.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import ClassVar

from sqlalchemy.orm import Session

from src.models.application import Application, ApplicationStatusLog

logger = logging.getLogger(__name__)


class StatusLogger:
    """Utility for recording and retrieving application status transitions.

    Supported application statuses:
        - planned: Initial state when application is created/queued.
        - confirmed: User or system confirmed application readiness.
        - applying: Application processing / browser submission in progress.
        - applied: Successfully submitted to target platform.
        - failed: Submission failed due to automated error or retry exhaustion.
        - needs_action: Flagged for manual user action (e.g., CAPTCHA).
        - matched, shortlisted, resume_generated, withdrawn: Supplementary statuses.
    """

    SUPPORTED_STATUSES: ClassVar[set[str]] = {
        "planned",
        "matched",
        "shortlisted",
        "confirmed",
        "resume_generated",
        "applying",
        "applied",
        "failed",
        "withdrawn",
        "needs_action",
    }

    @classmethod
    def log_transition(
        cls,
        db: Session,
        application_id: uuid.UUID | str,
        new_status: str,
        failure_reason: str | None = None,
        manual_apply_url: str | None = None,
    ) -> Application | None:
        """Record an application status transition and maintain audit trail history.

        Args:
            db: Active SQLAlchemy database session.
            application_id: Unique UUID identifier of the application.
            new_status: The target status string.
            failure_reason: Optional failure details if new_status is 'failed' or 'needs_action'.
            manual_apply_url: Optional URL if manual intervention is required.

        Returns:
            Updated Application model instance, or None if validation fails or application is missing.
        """
        # Validate status parameter
        if not new_status or not isinstance(new_status, str):
            logger.warning(
                "StatusLogger: invalid status type or empty string: %r", new_status
            )
            return None

        status_clean = new_status.strip().lower()
        if status_clean not in cls.SUPPORTED_STATUSES:
            logger.warning(
                "StatusLogger: unsupported status '%s' for application %s",
                new_status,
                application_id,
            )
            return None

        # Parse application_id
        try:
            app_uuid = (
                application_id
                if isinstance(application_id, uuid.UUID)
                else uuid.UUID(str(application_id))
            )
        except ValueError:
            logger.warning(
                "StatusLogger: invalid UUID string provided: %r", application_id
            )
            return None

        app = db.query(Application).filter(Application.id == app_uuid).first()
        if app is None:
            logger.warning(
                "StatusLogger: application %s not found in database", app_uuid
            )
            return None

        previous_status = app.status
        now = datetime.now(timezone.utc)

        # Update application state
        app.status = status_clean
        if failure_reason is not None:
            app.failure_reason = failure_reason
        if manual_apply_url is not None:
            app.manual_apply_url = manual_apply_url
        if status_clean == "applied" and app.applied_at is None:
            app.applied_at = now

        # Append to audit trail
        log_entry = ApplicationStatusLog(
            application_id=app.id,
            previous_status=previous_status,
            new_status=status_clean,
            failure_reason=failure_reason,
            manual_apply_url=manual_apply_url,
            timestamp=now,
        )
        db.add(log_entry)
        db.flush()

        logger.info(
            "StatusLogger: application %s transitioned status [%s -> %s]",
            app.id,
            previous_status,
            status_clean,
        )

        return app

    @classmethod
    def get_status_history(
        cls,
        db: Session,
        application_id: uuid.UUID | str,
    ) -> list[ApplicationStatusLog]:
        """Retrieve the complete audit history for a specific application.

        Args:
            db: Active SQLAlchemy database session.
            application_id: Unique UUID identifier of the application.

        Returns:
            List of ApplicationStatusLog records ordered chronologically by timestamp.
        """
        try:
            app_uuid = (
                application_id
                if isinstance(application_id, uuid.UUID)
                else uuid.UUID(str(application_id))
            )
        except ValueError:
            logger.warning(
                "StatusLogger: invalid UUID for get_status_history: %r", application_id
            )
            return []

        return (
            db.query(ApplicationStatusLog)
            .filter(ApplicationStatusLog.application_id == app_uuid)
            .order_by(ApplicationStatusLog.timestamp.asc())
            .all()
        )
