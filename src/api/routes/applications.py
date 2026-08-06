"""
API routes for querying and tracking user applications in HireFlow AI.
"""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.models.application import Application
from src.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/applications", tags=["applications"])


@router.get("/{user_id}", response_model=dict[str, Any])
def get_user_applications(
    user_id: str,
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """Retrieves all applications for a target user.

    Supports status filtering (?status=applied) and pagination (limit and offset).
    Includes current status, resume paths, failure reasons, and manual application URLs where needed.
    """
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format. Must be a valid UUID.",
        ) from exc

    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID {user_id} not found.",
        )

    query = db.query(Application).filter(Application.user_id == user_uuid)
    if status_filter:
        query = query.filter(Application.status == status_filter)

    total_count = query.count()
    applications = (
        query.order_by(Application.created_at.desc()).offset(offset).limit(limit).all()
    )

    results = []
    for app in applications:
        app_dict = {
            "id": str(app.id),
            "user_id": str(app.user_id),
            "job_id": str(app.job_id),
            "company_name": app.job.company_name,
            "role_title": app.job.role_title,
            "status": app.status,
            "resume_path": app.resume_path,
            "resume_link": app.resume_path,  # Backwards compatibility key
            "applied_at": app.applied_at.isoformat() if app.applied_at else None,
            "created_at": app.created_at.isoformat() if app.created_at else None,
            "failure_reason": app.failure_reason,
        }

        # Handle specific criteria for "failed" and "needs_action" statuses
        if app.status == "failed":
            app_dict["failure_reason"] = app.failure_reason or "Unknown failure"
        elif app.status == "needs_action":
            app_dict["failure_reason"] = (
                app.failure_reason or "Manual intervention required"
            )
            app_dict["reason"] = app_dict["failure_reason"]
            app_dict["manual_application_url"] = app.job.application_url
            app_dict["manual_apply_url"] = app.job.application_url

        results.append(app_dict)

    return {
        "total": total_count,
        "limit": limit,
        "offset": offset,
        "applications": results,
        "results": results,  # Backwards compatibility key for tests expecting direct lookup
    }
