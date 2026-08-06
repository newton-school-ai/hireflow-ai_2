"""
API routes for application status tracking and history retrieval in HireFlow AI.
"""

import math
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, joinedload, selectinload

from src.config.database import get_db
from src.models.application import Application
from src.models.user import User

router = APIRouter(prefix="/applications", tags=["applications"])


# =============================================================================
# Response Schemas
# =============================================================================


class JobInfoSchema(BaseModel):
    """Job information associated with an application."""

    id: uuid.UUID
    company_name: str
    role_title: str
    application_url: str
    location: str | None = None
    listing_type: str | None = None

    model_config = ConfigDict(from_attributes=True)


class StatusLogSchema(BaseModel):
    """Audit trail record of a status transition."""

    id: uuid.UUID
    application_id: uuid.UUID
    previous_status: str | None = None
    new_status: str
    failure_reason: str | None = None
    manual_apply_url: str | None = None
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)


class ApplicationItemSchema(BaseModel):
    """Detailed response schema for an application record."""

    id: uuid.UUID
    user_id: uuid.UUID
    job_id: uuid.UUID
    company: str
    role: str
    status: str
    applied_at: datetime | None = None
    resume_path: str | None = None
    resume_version: int | None = None
    failure_reason: str | None = None
    manual_apply_url: str | None = None
    match_score: float | None = None
    created_at: datetime
    job: JobInfoSchema
    status_history: list[StatusLogSchema] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class PaginatedApplicationsResponse(BaseModel):
    """Paginated response wrapper containing application items and metadata."""

    items: list[ApplicationItemSchema]
    total: int
    total_pages: int
    current_page: int
    page_size: int


# =============================================================================
# API Endpoints
# =============================================================================


@router.get(
    "/{user_id}",
    response_model=PaginatedApplicationsResponse,
    status_code=status.HTTP_200_OK,
)
def get_user_applications(
    user_id: uuid.UUID,
    status_param: str | None = Query(
        default=None, alias="status", description="Filter applications by status"
    ),
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(
        default=10, ge=1, le=100, description="Number of applications per page"
    ),
    db: Session = Depends(get_db),  # noqa: B008
) -> PaginatedApplicationsResponse:
    """Retrieve all applications for a specific user with optional status filtering and pagination.

    Args:
        user_id: UUID of the target user.
        status_param: Optional status filter (e.g., 'applied', 'failed', 'needs_action').
        page: Page number (starts at 1).
        page_size: Maximum records per page.
        db: SQLAlchemy database session dependency.

    Returns:
        Paginated applications list with job details, status history, and pagination metadata.
    """
    # Verify user exists
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID {user_id} not found",
        )

    query = (
        db.query(Application)
        .options(
            joinedload(Application.job),
            selectinload(Application.status_history),
        )
        .filter(Application.user_id == user_id)
    )

    if status_param and status_param.strip():
        clean_status = status_param.strip().lower()
        query = query.filter(Application.status == clean_status)

    total = query.count()

    # Apply ordering and pagination
    query = query.order_by(Application.created_at.desc())
    offset = (page - 1) * page_size
    applications = query.offset(offset).limit(page_size).all()

    items: list[ApplicationItemSchema] = []
    for app in applications:
        company_name = app.job.company_name if app.job else ""
        role_title = app.job.role_title if app.job else ""

        history_items = [
            StatusLogSchema.model_validate(log_entry)
            for log_entry in (app.status_history or [])
        ]

        item = ApplicationItemSchema(
            id=app.id,
            user_id=app.user_id,
            job_id=app.job_id,
            company=company_name,
            role=role_title,
            status=app.status,
            applied_at=app.applied_at,
            resume_path=app.resume_path,
            resume_version=app.resume_version,
            failure_reason=app.failure_reason,
            manual_apply_url=app.manual_apply_url,
            match_score=app.match_score,
            created_at=app.created_at,
            job=JobInfoSchema.model_validate(app.job) if app.job else None,
            status_history=history_items,
        )
        items.append(item)

    total_pages = math.ceil(total / page_size) if total > 0 else 0

    return PaginatedApplicationsResponse(
        items=items,
        total=total,
        total_pages=total_pages,
        current_page=page,
        page_size=page_size,
    )
