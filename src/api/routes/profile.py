"""
Profile API routes for HireFlow AI.

Provides the user onboarding flow:
  - POST /profile  — create a profile from JSON or a PDF resume upload.
  - GET  /profile/{user_id} — retrieve a stored profile.

The POST endpoint supports two content types:
  1. application/json  — direct structured profile submission.
  2. multipart/form-data — PDF resume upload → LLM extraction → profile creation.

Design decisions:
  - master_profile is stored as JSONB so downstream milestones (M3 matcher,
    M4 resume tailoring, M5 form filler, M6 prep guide) can query individual
    fields without schema migrations.
  - LLM output is validated through a Pydantic model before storage to
    guarantee data integrity.
  - Duplicate emails return 409 (not 500) with an actionable error message.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import fitz  # PyMuPDF
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.models.user import User
from src.utils.llm_client import (
    LLMConfigError,
    build_extraction_prompt,
    get_llm_client,
    parse_llm_json,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profile", tags=["Profile"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class ProfileLinks(BaseModel):
    """Structured links extracted from a resume or provided by the user."""

    github: str = ""
    linkedin: str = ""
    portfolio: str = ""


class ProfileCreate(BaseModel):
    """Request body for JSON profile creation.

    All fields beyond name/email/mode are optional so users can fill in
    as much or as little as they have available during onboarding.

    Attributes:
        name: Full name.
        email: Email address (validated format).
        mode: Target mode — must be 'internship' or 'job'.
        skills: List of skill strings.
        weekly_quota: Max applications per week (1-50).
        confirmation_mode: 'batch' or 'individual'.
        target_roles: Desired job titles.
        preferred_locations: Location preferences.
        min_stipend: Minimum acceptable stipend/salary.
        education: Academic background entries.
        experience: Work experience entries.
        projects: Project portfolio entries.
        certifications: Certification strings.
        languages: Spoken/written languages.
        links: Profile links (GitHub, LinkedIn, portfolio).
        phone: Contact phone number.
    """

    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    mode: str = Field(..., pattern=r"^(internship|job)$")
    skills: list[str] = Field(default_factory=list)
    weekly_quota: int = Field(default=5, ge=1, le=50)
    confirmation_mode: str = Field(default="batch")
    target_roles: list[str] = Field(default_factory=list)
    preferred_locations: list[str] = Field(default_factory=list)
    min_stipend: int | None = None
    education: list[dict[str, Any]] = Field(default_factory=list)
    experience: list[dict[str, Any]] = Field(default_factory=list)
    projects: list[dict[str, Any]] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    links: ProfileLinks = Field(default_factory=ProfileLinks)
    phone: str = ""


class ResumeExtractedProfile(BaseModel):
    """Validated shape of LLM-extracted resume data.

    Used to validate the JSON returned by the LLM before storing it.
    If validation fails, the API returns an error instead of persisting
    partial or malformed data.
    """

    name: str = ""
    email: str = ""
    phone: str = ""
    skills: list[str] = Field(default_factory=list)
    education: list[dict[str, Any]] = Field(default_factory=list)
    experience: list[dict[str, Any]] = Field(default_factory=list)
    projects: list[dict[str, Any]] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    links: ProfileLinks = Field(default_factory=ProfileLinks)
    target_roles: list[str] = Field(default_factory=list)
    preferred_locations: list[str] = Field(default_factory=list)


class ProfileResponse(BaseModel):
    """Response body for profile endpoints.

    Serializes the ORM ``User`` object into a clean JSON shape.
    Uses ``model_config`` with ``from_attributes=True`` so SQLAlchemy
    objects can be passed directly.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    email: str
    mode: str
    master_profile: dict[str, Any] | None = None
    weekly_quota: int
    confirmation_mode: str
    created_at: Any = None
    updated_at: Any = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_master_profile(data: ProfileCreate) -> dict[str, Any]:
    """Build the master_profile JSONB payload from validated input.

    Centralises the schema so JSON and PDF paths produce the same shape.
    """
    return {
        "phone": data.phone,
        "skills": data.skills,
        "education": data.education,
        "experience": data.experience,
        "projects": data.projects,
        "certifications": data.certifications,
        "languages": data.languages,
        "links": data.links.model_dump(),
        "target_roles": data.target_roles,
        "preferred_locations": data.preferred_locations,
        "min_stipend": data.min_stipend,
    }


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract plain text from a PDF using PyMuPDF.

    Args:
        pdf_bytes: Raw PDF file content.

    Returns:
        Concatenated text from all pages.

    Raises:
        ValueError: If the PDF is empty or unreadable.
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise ValueError(f"Could not open PDF: {exc}") from exc

    text_parts: list[str] = []
    for page in doc:
        text_parts.append(page.get_text())
    doc.close()

    full_text = "\n".join(text_parts).strip()
    if not full_text:
        raise ValueError("PDF contains no extractable text.")
    return full_text


# ---------------------------------------------------------------------------
# POST /profile — JSON body
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=ProfileResponse,
    status_code=201,
    summary="Create a user profile from JSON",
    responses={
        409: {"description": "Email already registered"},
        422: {"description": "Validation error"},
    },
)
def create_profile_json(
    payload: ProfileCreate,
    db: Session = Depends(get_db),
) -> ProfileResponse:
    """Create a new user profile from a structured JSON body.

    Validates the input, builds the ``master_profile`` JSONB payload,
    creates the ORM object, commits, refreshes, and returns the
    serialised response.
    """
    master_profile = _build_master_profile(payload)

    user = User(
        name=payload.name,
        email=payload.email,
        mode=payload.mode,
        master_profile=master_profile,
        weekly_quota=payload.weekly_quota,
        confirmation_mode=payload.confirmation_mode,
    )

    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"A user with email '{payload.email}' already exists.",
        )

    db.refresh(user)
    return ProfileResponse.model_validate(user)


# ---------------------------------------------------------------------------
# POST /profile/upload — PDF resume
# ---------------------------------------------------------------------------


@router.post(
    "/upload",
    response_model=ProfileResponse,
    status_code=201,
    summary="Create a user profile from a PDF resume",
    responses={
        400: {"description": "Invalid PDF or LLM extraction failure"},
        409: {"description": "Email already registered"},
        422: {"description": "LLM returned invalid data"},
        503: {"description": "LLM provider not configured"},
    },
)
async def create_profile_pdf(
    file: UploadFile = File(..., description="PDF resume file"),
    mode: str = Form("internship"),
    db: Session = Depends(get_db),
) -> ProfileResponse:
    """Create a new user profile by extracting data from a PDF resume.

    Flow:
    1. Read and validate the uploaded PDF.
    2. Extract text using PyMuPDF.
    3. Send text to the configured LLM with the extraction prompt.
    4. Parse and validate the LLM JSON response via Pydantic.
    5. Create the User ORM object, commit, refresh, and return.
    """
    # --- Validate mode ---
    if mode not in ("internship", "job"):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid mode '{mode}'. Must be 'internship' or 'job'.",
        )

    # --- Read PDF ---
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # --- Extract text ---
    try:
        resume_text = _extract_pdf_text(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # --- Call LLM ---
    try:
        llm = get_llm_client()
    except LLMConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    prompt = build_extraction_prompt(resume_text)

    try:
        raw_response = await llm.generate(prompt)
    except Exception as exc:
        logger.exception("LLM call failed")
        raise HTTPException(
            status_code=502,
            detail=f"LLM provider returned an error: {exc}",
        )

    # --- Parse and validate LLM output ---
    try:
        parsed = parse_llm_json(raw_response)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"LLM returned unparseable response: {exc}",
        )

    try:
        extracted = ResumeExtractedProfile.model_validate(parsed)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"LLM output failed validation: {exc}",
        )

    # --- Build master_profile from extracted data ---
    name = extracted.name or "Unknown"
    email = extracted.email or ""
    if not email:
        raise HTTPException(
            status_code=400,
            detail="Could not extract an email address from the resume. "
            "Please provide it manually.",
        )

    master_profile = {
        "phone": extracted.phone,
        "skills": extracted.skills,
        "education": [e if isinstance(e, dict) else {} for e in extracted.education],
        "experience": [e if isinstance(e, dict) else {} for e in extracted.experience],
        "projects": [p if isinstance(p, dict) else {} for p in extracted.projects],
        "certifications": extracted.certifications,
        "languages": extracted.languages,
        "links": extracted.links.model_dump(),
        "target_roles": extracted.target_roles,
        "preferred_locations": extracted.preferred_locations,
        "min_stipend": None,
    }

    user = User(
        name=name,
        email=email,
        mode=mode,
        master_profile=master_profile,
        weekly_quota=5,
        confirmation_mode="batch",
    )

    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"A user with email '{email}' already exists.",
        )

    db.refresh(user)
    return ProfileResponse.model_validate(user)


# ---------------------------------------------------------------------------
# GET /profile/{user_id}
# ---------------------------------------------------------------------------


@router.get(
    "/{user_id}",
    response_model=ProfileResponse,
    summary="Get a user profile by ID",
    responses={404: {"description": "User not found"}},
)
def get_profile(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ProfileResponse:
    """Retrieve a stored user profile by its UUID.

    Returns 404 with a clear message if the user does not exist.
    The response is serialised through ``ProfileResponse`` so the
    shape is consistent with the POST endpoint.
    """
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=404,
            detail=f"User with id '{user_id}' not found.",
        )
    return ProfileResponse.model_validate(user)
