"""
Report API routes for HireFlow AI.

Provides:
    GET /report/{user_id}/latest
        Returns the most recent WeeklyReport for the user, sourced
        from the database (not from disk). The HTML/JSON files on disk
        are auxiliary artifacts only.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.models.report import WeeklyReport
from src.models.user import User

router = APIRouter(prefix="/report", tags=["reports"])


def _serialise_report(report: WeeklyReport) -> dict[str, Any]:
    """Convert a WeeklyReport ORM object into a JSON-safe response dict.

    The ``top_matches`` column stores the full cross-application insights
    structure built by the report generator, so it is surfaced directly.
    """
    top_matches = report.top_matches or []
    insights: dict[str, Any] = {}
    top_applications: list[dict[str, Any]] = []

    if top_matches and isinstance(top_matches, list) and top_matches:
        first = top_matches[0]
        if isinstance(first, dict):
            insights = first.get("insights", {})
            top_applications = first.get("top_applications", [])

    return {
        "id": str(report.id),
        "user_id": str(report.user_id),
        "week_start": report.week_start.isoformat(),
        "week_end": report.week_end.isoformat(),
        "applications_sent": report.applications_sent,
        "responses_received": report.responses_received,
        "summary": report.summary,
        "report_path": report.report_path,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "top_applications": top_applications,
        "insights": insights,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/{user_id}/latest")
def get_latest_report(
    user_id: str,
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """Return the most recent weekly report for a user.

    The response is sourced entirely from the ``weekly_reports`` database
    table. HTML and JSON files on disk are auxiliary artifacts and are not
    read by this endpoint.

    Args:
        user_id: UUID of the user whose latest report to retrieve.
        db: Injected SQLAlchemy session.

    Returns:
        A dict containing report metadata plus cross-application insights
        extracted from ``top_matches``.

    Raises:
        400: If ``user_id`` is not a valid UUID.
        404: If the user does not exist or has no reports.
    """
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format — expected a UUID.",
        )

    # Verify user exists
    user = db.query(User).filter(User.id == uid).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id!r} not found.",
        )

    # Fetch the report for the most recent week
    report = (
        db.query(WeeklyReport)
        .filter(WeeklyReport.user_id == uid)
        .order_by(WeeklyReport.week_start.desc())
        .first()
    )

    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No weekly report found for user {user_id!r}.",
        )

    return _serialise_report(report)
