"""
API routes for user profile and onboarding in HireFlow AI.
"""

import io
import re
import uuid

import pypdf
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, EmailStr, Field, ValidationError
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.models.user import User
from src.utils.llm_client import get_llm_client

router = APIRouter(prefix="/profile", tags=["profile"])


class ProfileCreateSchema(BaseModel):
    name: str
    email: EmailStr
    mode: str = Field("internship", pattern="^(internship|job)$")
    weekly_quota: int = Field(5, ge=1)
    confirmation_mode: str = "batch"
    skills: list[str] = []
    target_roles: list[str] = []
    preferred_locations: list[str] = []
    min_stipend: int | None = None
    min_salary: int | None = None
    experience: list[dict] = []
    education: list[dict] = []
    projects: list[dict] = []


@router.post("")
async def create_profile(request: Request, db: Session = Depends(get_db)):
    """Creates a user profile either from JSON payload or a PDF resume upload."""
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload",
            )

        try:
            data = ProfileCreateSchema(**body)
        except ValidationError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=e.errors(),
            )

        # Check for duplicate email
        existing_user = db.query(User).filter(User.email == data.email).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            )

        # Store extra details in master_profile
        master_profile = {
            "skills": data.skills,
            "target_roles": data.target_roles,
            "preferred_locations": data.preferred_locations,
            "min_stipend": data.min_stipend,
            "min_salary": data.min_salary,
            "experience": data.experience,
            "education": data.education,
            "projects": data.projects,
        }

        user = User(
            name=data.name,
            email=data.email,
            mode=data.mode,
            weekly_quota=data.weekly_quota,
            confirmation_mode=data.confirmation_mode,
            master_profile=master_profile,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    elif "multipart/form-data" in content_type:
        form = await request.form()
        file = form.get("file")
        from starlette.datastructures import UploadFile as StarletteUploadFile

        if not file or not (
            isinstance(file, UploadFile) or isinstance(file, StarletteUploadFile)
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Resume PDF file is required",
            )

        # Extract other fields from Form
        name = form.get("name")
        email = form.get("email")
        mode = form.get("mode", "internship")
        weekly_quota_str = form.get("weekly_quota", "5")
        confirmation_mode = form.get("confirmation_mode", "batch")

        # Helpers to parse lists/integers from form fields
        def parse_form_list(value) -> list[str]:
            if not value:
                return []
            if isinstance(value, list):
                return [str(v).strip() for v in value]
            val_str = str(value).strip()
            if val_str.startswith("[") and val_str.endswith("]"):
                try:
                    import json

                    parsed = json.loads(val_str)
                    if isinstance(parsed, list):
                        return [str(v).strip() for v in parsed]
                except Exception:
                    pass
            return [v.strip() for v in val_str.split(",") if v.strip()]

        def parse_form_int(value) -> int | None:
            if value is None or str(value).strip() == "":
                return None
            try:
                return int(str(value).strip())
            except ValueError:
                return None

        target_roles = parse_form_list(form.get("target_roles"))
        preferred_locations = parse_form_list(form.get("preferred_locations"))
        min_stipend = parse_form_int(form.get("min_stipend"))
        min_salary = parse_form_int(form.get("min_salary"))

        # Validate mode
        if mode not in ["internship", "job"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="mode field validated: only 'internship' or 'job' accepted",
            )

        # Validate weekly quota
        try:
            weekly_quota = int(weekly_quota_str)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="weekly_quota must be an integer",
            )

        # Read and parse PDF
        try:
            pdf_bytes = await file.read()
            pdf_file = io.BytesIO(pdf_bytes)
            reader = pypdf.PdfReader(pdf_file)
            text = ""
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to parse PDF resume: {e}",
            )

        if not text.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not extract text from the uploaded PDF resume",
            )

        # Query LLM to extract structured data
        try:
            llm = get_llm_client()
            prompt = (
                "You are an expert resume parser. Extract the structured fields listed below in JSON format from the following resume text. "
                "Ensure the response is a single valid JSON object containing exactly these keys:\n"
                "- name (str or null if not found)\n"
                "- email (str or null if not found)\n"
                "- skills (list of strings)\n"
                "- experience (list of objects with company, role, duration, description)\n"
                "- education (list of objects with institution, degree, year)\n"
                "- projects (list of objects with title, description, technologies)\n\n"
                f"Resume Text:\n{text}\n"
            )
            extracted = llm.extract(prompt)
            if isinstance(extracted, str):
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="LLM failed to return structured JSON data",
                )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"LLM extraction failed: {e}",
            )

        # Fallback fields if not provided in Form
        if not name:
            name = extracted.get("name")
        if not email:
            email = extracted.get("email")

        if not name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Name is required but could not be extracted from resume. Please specify name.",
            )
        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is required but could not be extracted from resume. Please specify email.",
            )

        # Clean email and simple regex validate
        email = email.strip()
        if not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid email format",
            )

        # Check for duplicate email
        existing_user = db.query(User).filter(User.email == email).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            )

        # Build master profile
        master_profile = {
            "skills": extracted.get("skills", []),
            "target_roles": target_roles,
            "preferred_locations": preferred_locations,
            "min_stipend": min_stipend,
            "min_salary": min_salary,
            "experience": extracted.get("experience", []),
            "education": extracted.get("education", []),
            "projects": extracted.get("projects", []),
        }

        user = User(
            name=name,
            email=email,
            mode=mode,
            weekly_quota=weekly_quota,
            confirmation_mode=confirmation_mode,
            master_profile=master_profile,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    else:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported Content-Type. Use application/json or multipart/form-data.",
        )


@router.get("/{user_id}")
def get_profile(user_id: str, db: Session = Depends(get_db)):
    """Retrieves the full profile of a user by UUID."""
    try:
        u_id = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format",
        )

    user = db.query(User).filter(User.id == u_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user
