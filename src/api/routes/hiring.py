import json
import logging
import tempfile

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.agents.hiring_shortlist_agent import HiringShortlistAgent

router = APIRouter(prefix="/hiring", tags=["hiring"])
logger = logging.getLogger(__name__)


class ShortlistedCandidate(BaseModel):
    rank: int
    name: str
    score: float
    strengths: list[str]
    matched_skills: list[str]
    skill_gaps: list[str]
    summary: str


class ShortlistResponse(BaseModel):
    total_applicants: int
    shortlist_size: int
    shortlist: list[ShortlistedCandidate]


@router.post("/shortlist", response_model=ShortlistResponse)
async def generate_shortlist(request: Request):
    """
    Generate a hiring shortlist from a pool of applicants.
    Accepts either `application/json` (with 'applicants' array) or
    `multipart/form-data` (with 'applicants_csv' file).
    """
    content_type = request.headers.get("content-type", "")

    jd_text = None
    shortlist_size = 10
    company_name = None
    role_title = None
    parsed_applicants = None
    tmp_csv_path = None

    try:
        if content_type.startswith("application/json"):
            data = await request.json()
            jd_text = data.get("jd_text")
            shortlist_size = data.get("shortlist_size", 10)
            company_name = data.get("company_name")
            role_title = data.get("role_title")
            parsed_applicants = data.get("applicants")

            if not parsed_applicants or not isinstance(parsed_applicants, list):
                raise HTTPException(
                    status_code=400, detail="'applicants' must be a valid JSON array."
                )

        elif content_type.startswith("multipart/form-data"):
            form = await request.form()
            jd_text = form.get("jd_text")

            # Form fields are strings
            size_str = form.get("shortlist_size", "10")
            try:
                shortlist_size = int(size_str)
            except ValueError:
                shortlist_size = 10

            company_name = form.get("company_name")
            role_title = form.get("role_title")

            applicants_json = form.get("applicants")
            applicants_csv = form.get("applicants_csv")

            if applicants_json:
                try:
                    parsed_applicants = json.loads(applicants_json)
                    if not isinstance(parsed_applicants, list):
                        raise TypeError("Applicants JSON must be a list")
                except (json.JSONDecodeError, TypeError) as exc:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid applicants JSON: {exc}",
                    ) from exc
            elif applicants_csv and hasattr(applicants_csv, "filename"):
                if not applicants_csv.filename.endswith(".csv"):
                    raise HTTPException(
                        status_code=400, detail="Uploaded file must be a CSV."
                    )
                with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
                    content = await applicants_csv.read()
                    tmp.write(content)
                    tmp_csv_path = tmp.name
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Must provide either 'applicants' or 'applicants_csv'.",
                )
        else:
            raise HTTPException(
                status_code=415,
                detail="Unsupported Media Type. Use application/json or multipart/form-data.",
            )

        if not jd_text:
            raise HTTPException(status_code=400, detail="jd_text is required.")
        if shortlist_size <= 0:
            raise HTTPException(status_code=400, detail="shortlist_size must be > 0")

        # Call agent
        agent = HiringShortlistAgent()

        try:
            result = agent.shortlist(
                jd_text=jd_text,
                applicants=parsed_applicants,
                applicants_csv=tmp_csv_path,
                shortlist_size=shortlist_size,
                company_name=company_name,
                role_title=role_title,
            )
            return result
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Error during shortlist generation")
            raise HTTPException(
                status_code=500, detail="Internal server error"
            ) from exc

    finally:
        # Cleanup temp file
        if tmp_csv_path:
            import os

            try:
                os.remove(tmp_csv_path)
            except OSError:
                pass
