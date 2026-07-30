"""
API routes for weekly application plan generation, swapping, and confirmation in HireFlow AI.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.pipelines.quota_selector import (
    InvalidSwapError,
    PlanAlreadyConfirmedError,
    QuotaSelectorPipeline,
    UserNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/weekly-plan", tags=["weekly-plan"])


# =============================================================================
# Request Schemas
# =============================================================================


class SwapRequestSchema(BaseModel):
    """Payload for swapping a selected job with another eligible candidate job."""

    remove_job_id: str = Field(
        ..., description="ID of the job currently selected in plan to remove"
    )
    add_job_id: str = Field(
        ..., description="ID of the eligible replacement job to add"
    )


class ConfirmPlanSchema(BaseModel):
    """Payload for explicitly confirming a weekly plan."""

    confirmed_job_ids: list[str] | None = Field(
        default=None, description="Explicit list of job IDs confirmed by the user"
    )
    removed_job_ids: list[str] | None = Field(
        default=None, description="Explicit list of job IDs removed during confirmation"
    )


# =============================================================================
# API Endpoints
# =============================================================================


@router.get("/{user_id}", response_model=dict[str, Any])
def get_weekly_plan(
    user_id: str,
    index: int = Query(
        0, ge=0, description="Zero-based index for individual confirmation mode"
    ),
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """Retrieves the weekly job application plan for a target user.

    Enforces filtering (expired, blacklisted, already applied, duplicate companies, spam),
    ranks jobs by match score descending, and returns top N jobs matching user's quota.
    Supports both batch and individual confirmation modes.
    """
    pipeline = QuotaSelectorPipeline()
    try:
        plan_result = pipeline.generate_weekly_plan(user_id=user_id, db=db)
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.error(f"Error generating weekly plan for user {user_id}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate weekly plan.",
        ) from exc

    plan_dict = plan_result.to_dict()

    # Handle individual mode vs batch mode formatting
    if plan_result.confirmation_mode == "individual":
        selected = plan_dict.get("selected_jobs", [])
        if selected:
            safe_index = min(max(0, index), len(selected) - 1)
            plan_dict["current_recommendation"] = selected[safe_index]
            plan_dict["current_index"] = safe_index
            plan_dict["total_recommendations"] = len(selected)
        else:
            plan_dict["current_recommendation"] = None
            plan_dict["current_index"] = 0
            plan_dict["total_recommendations"] = 0

    return plan_dict


@router.post("/{user_id}/swap", response_model=dict[str, Any])
def swap_job_in_plan(
    user_id: str,
    payload: SwapRequestSchema,
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """Replaces one selected job in the user's weekly plan with another eligible candidate job."""
    pipeline = QuotaSelectorPipeline()
    try:
        updated_plan = pipeline.swap_job(
            user_id=user_id,
            remove_job_id=payload.remove_job_id,
            add_job_id=payload.add_job_id,
            db=db,
        )
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except (InvalidSwapError, PlanAlreadyConfirmedError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.error(f"Error swapping job for user {user_id}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to perform job swap.",
        ) from exc

    return updated_plan.to_dict()


@router.post("/{user_id}/confirm", response_model=dict[str, Any])
def confirm_weekly_plan(
    user_id: str,
    payload: ConfirmPlanSchema | None = None,
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """Explicitly confirms the user's weekly plan, transitioning status to 'confirmed'.

    Only after confirmation will downstream modules be notified that resume generation may begin.
    """
    pipeline = QuotaSelectorPipeline()

    confirmed_ids = payload.confirmed_job_ids if payload else None
    removed_ids = payload.removed_job_ids if payload else None

    try:
        confirmed_plan = pipeline.confirm_weekly_plan(
            user_id=user_id,
            db=db,
            confirmed_job_ids=confirmed_ids,
            removed_job_ids=removed_ids,
        )
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.error(f"Error confirming weekly plan for user {user_id}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to confirm weekly plan.",
        ) from exc

    return confirmed_plan.to_dict()
