"""
Profile routes for HireFlow AI.

Provides the endpoints:
- POST /profile: Handles JSON inputs and multipart PDF uploads (parsing text via LLM).
- GET /profile/{user_id}: Retrieves the complete user profile.
"""

from datetime import datetime
import io
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from pypdf import PdfReader
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from src.config.database import get_db
from src.models.user import User
from src.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class ProfileCreate(BaseModel):
    """Schema for validating profile creation inputs."""

    name: str = Field(..., max_length=255, description="Full name of the user")
    email: EmailStr = Field(..., description="Unique email address")
    skills: List[str] = Field(
        default_factory=list, description="List of technical/soft skills"
    )
    mode: str = Field(
        default="internship", description="Target mode: 'internship' or 'job'"
    )
    weekly_quota: int = Field(default=5, ge=0, description="Weekly application limit")
    target_roles: List[str] = Field(
        default_factory=list, description="Target job titles/roles"
    )
    preferred_locations: List[str] = Field(
        default_factory=list, description="Preferred locations"
    )
    min_stipend: Optional[Any] = Field(
        default=None, description="Minimum expected stipend/salary"
    )

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        """Validates that mode is either 'internship' or 'job'."""
        if v not in ("internship", "job"):
            raise ValueError("mode must be either 'internship' or 'job'")
        return v


class UserProfileResponse(BaseModel):
    """Schema for returning complete user profile details."""

    id: UUID
    name: str
    email: EmailStr
    mode: str
    weekly_quota: int
    confirmation_mode: str
    master_profile: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {
        "from_attributes": True,
    }


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extracts plain text content from PDF binary bytes.

    Args:
        pdf_bytes: Binary contents of a PDF file.

    Returns:
        The extracted text content.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"
    return text


RESUME_PARSE_SCHEMA_PROMPT = """
You must parse the candidate's resume text and extract the details in the following JSON format.
Strictly output JSON only.

Required JSON Structure:
{
  "name": "Candidate's Full Name (string)",
  "email": "Candidate's Email Address (string)",
  "skills": ["List of skills extracted from the resume (array of strings)"],
  "mode": "Target mode - output either 'internship' or 'job'. Inferred from the resume context, or default to 'internship' if unclear (string)",
  "weekly_quota": 5,
  "target_roles": ["List of target job titles or roles the candidate is seeking or has experience in (array of strings)"],
  "preferred_locations": ["List of locations mentioned as preferred, or list of candidate's locations/past work locations (array of strings)"],
  "min_stipend": null
}
"""


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------


@router.post(
    "/profile",
    response_model=UserProfileResponse,
    status_code=status.HTTP_201_CREATED,
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {"schema": ProfileCreate.model_json_schema()},
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "file": {
                                "type": "string",
                                "format": "binary",
                                "description": "PDF Resume file to parse",
                            }
                        },
                        "required": ["file"],
                    }
                },
            }
        }
    },
)
async def create_profile(request: Request, db: Session = Depends(get_db)):
    """Creates a user profile.

    Supports two media types:
    1. application/json: Creates a profile directly using the provided JSON details.
    2. multipart/form-data: Accepts a PDF resume, parses its text using an LLM,
       and builds the profile.
    """
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        try:
            body = await request.json()
            profile_data = ProfileCreate(**body)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid JSON payload or validation error: {str(e)}",
            )

    elif "multipart/form-data" in content_type:
        form = await request.form()
        file = form.get("file")
        if not file or not isinstance(file, UploadFile):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Resume file must be provided under the form-data key 'file'",
            )

        pdf_bytes = await file.read()
        if not pdf_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded PDF file is empty",
            )

        try:
            resume_text = extract_text_from_pdf(pdf_bytes)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to extract text from PDF: {str(e)}",
            )

        if not resume_text.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not extract any text from the PDF file",
            )

        try:
            llm = LLMClient()
            parsed_data = llm.generate_json(
                prompt=f"Resume Text:\n{resume_text}",
                schema_prompt=RESUME_PARSE_SCHEMA_PROMPT,
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"LLM parsing failed: {str(e)}",
            )

        try:
            profile_data = ProfileCreate(**parsed_data)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"LLM generated JSON did not validate: {str(e)}",
            )

    else:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported media type. Must be application/json or multipart/form-data",
        )

    # Check if a user with the same email already exists
    existing_user = db.query(User).filter(User.email == profile_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists",
        )

    # Map profile_data fields to User model
    new_user = User(
        name=profile_data.name,
        email=profile_data.email,
        mode=profile_data.mode,
        weekly_quota=profile_data.weekly_quota,
        master_profile={
            "skills": profile_data.skills,
            "target_roles": profile_data.target_roles,
            "preferred_locations": profile_data.preferred_locations,
            "min_stipend": profile_data.min_stipend,
        },
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return new_user


@router.get(
    "/profile/{user_id}",
    response_model=UserProfileResponse,
    status_code=status.HTTP_200_OK,
)
def get_profile(user_id: UUID, db: Session = Depends(get_db)):
    """Retrieves a complete user profile by their unique ID."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return user
