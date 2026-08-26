"""
Application history API routes for HireFlow AI.

Provides:
    GET /applications/{user_id}
        Returns a paginated list of the user's applications enriched with
        job metadata (company name, role title, application URL) and the
        current status, failure reason, resume link, and timestamps.

    Query parameters:
        status  (optional) – filter by a single ApplicationStatus value.
        page    (optional, default 1)  – 1-indexed page number.
        limit   (optional, default 20) – results per page (max 100).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.models.application import Application
from src.models.job import Job
from src.models.user import User
from src.utils.status_logger import VALID_STATUSES as _VALID_STATUSES

router = APIRouter(prefix="/applications", tags=["applications"])


def _serialise_application(app: Application, job: Job | None) -> dict[str, Any]:
    """Convert an Application + its related Job into a JSON-safe dict.

    For ``needs_action`` applications, ``manual_application_url`` is explicitly
    included so the caller (dashboard / email delivery) can surface the link
    the user must visit to apply manually.
    """
    application_url = job.application_url if job else None
    payload: dict[str, Any] = {
        "id": str(app.id),
        "job_id": str(app.job_id),
        "company_name": job.company_name if job else None,
        "role_title": job.role_title if job else None,
        "application_url": application_url,
        "status": app.status,
        "failure_reason": app.failure_reason,
        "resume_path": app.resume_path,
        "match_score": app.match_score,
        "applied_at": app.applied_at.isoformat() if app.applied_at else None,
        "created_at": app.created_at.isoformat() if app.created_at else None,
    }
    # Acceptance criterion: needs_action items expose the manual apply URL
    # under an explicit key so consumers never have to infer it.
    if app.status == "needs_action":
        payload["manual_application_url"] = application_url
    return payload


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/{user_id}")
def list_applications(
    user_id: str,
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="Filter by application status (e.g. 'applied', 'failed').",
    ),
    page: int = Query(default=1, ge=1, description="1-indexed page number."),
    limit: int = Query(
        default=20, ge=1, le=100, description="Results per page (max 100)."
    ),
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """Return a paginated application history for a user.

    Enriches each application with the matching job's ``company_name``,
    ``role_title``, and ``application_url`` so the caller does not need a
    separate jobs lookup.

    Args:
        user_id: UUID of the user whose applications to list.
        status_filter: Optional status to filter by.
        page: 1-indexed page number.
        limit: Maximum results per page (capped at 100).
        db: Injected SQLAlchemy session.

    Returns:
        A dict with ``total``, ``page``, ``limit``, and ``items`` keys.

    Raises:
        400: If ``user_id`` is not a valid UUID or ``status`` is not recognised.
        404: If no user with that ID exists.
    """
    # Validate user_id
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format — expected a UUID.",
        )

    # Validate status filter
    if status_filter is not None and status_filter not in _VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unknown status {status_filter!r}. "
                f"Valid values: {sorted(_VALID_STATUSES)}"
            ),
        )

    # Verify user exists
    user = db.query(User).filter(User.id == uid).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id!r} not found.",
        )

    # Build query
    query = db.query(Application).filter(Application.user_id == uid)
    if status_filter is not None:
        query = query.filter(Application.status == status_filter)

    # Order newest-created first so the dashboard shows recent activity at top.
    query = query.order_by(Application.created_at.desc())

    total = query.count()
    offset = (page - 1) * limit
    applications = query.offset(offset).limit(limit).all()

    # Batch-load jobs to avoid N+1.
    job_ids = {app.job_id for app in applications}
    jobs_by_id: dict[uuid.UUID, Job] = {}
    if job_ids:
        jobs = db.query(Job).filter(Job.id.in_(job_ids)).all()
        jobs_by_id = {j.id: j for j in jobs}

    items = [
        _serialise_application(app, jobs_by_id.get(app.job_id)) for app in applications
    ]

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "items": items,
    }
