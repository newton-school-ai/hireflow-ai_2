import csv
import logging
import re
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from src.config.database import SessionLocal
from src.models.job import Job
from src.models.shortlist import Shortlist
from src.pipelines.embedding_pipeline import EmbeddingPipeline
from src.pipelines.match_scorer import score_job

logger = logging.getLogger(__name__)


def _extract_jd_info(jd_text: str) -> dict[str, Any]:
    """Small deterministic helper to extract info from JD text if not provided."""
    info = {
        "skills_required": [],
        "experience_required": None,
        "role_title": None,
    }
    if not jd_text:
        return info

    # Simple heuristic for skills (looks for common keywords in a naive way)
    # We avoid a huge dictionary, just looking for common ones if explicitly mentioned
    # A better approach is to rely on embedding similarity for the whole JD
    # But since the scorer needs exact skills for the skill score, we extract a few
    common_skills = [
        "python",
        "java",
        "c++",
        "javascript",
        "react",
        "node",
        "sql",
        "aws",
        "docker",
        "kubernetes",
        "machine learning",
        "ai",
        "langchain",
        "rag",
        "fastapi",
        "spring",
        "multi-agent",
    ]

    jd_lower = jd_text.lower()
    found_skills = []
    for skill in common_skills:
        # Simple word boundary check
        if re.search(rf"\b{re.escape(skill)}\b", jd_lower):
            # preserve original casing if possible, or just use capitalized
            if skill == "rag":
                found_skills.append("RAG")
            elif skill == "ai":
                found_skills.append("AI")
            elif skill == "fastapi":
                found_skills.append("FastAPI")
            else:
                found_skills.append(skill.title())

    info["skills_required"] = found_skills

    # Simple heuristic for experience
    exp_match = re.search(
        r"(\d+)\+?\s*(?:years?|yrs?)\s+(?:of\s+)?experience", jd_lower
    )
    if exp_match:
        info["experience_required"] = float(exp_match.group(1))

    # Simple heuristic for role title if it's the first line
    lines = [line.strip() for line in jd_text.split("\n") if line.strip()]
    if lines and len(lines[0]) < 100:
        info["role_title"] = lines[0]

    return info


def _normalize_applicant(app: dict[str, Any]) -> dict[str, Any]:
    """Normalizes applicant dict to the format expected by score_job."""
    name = app.get("name", "Unknown Applicant")

    # Parse skills
    raw_skills = app.get("skills", [])
    if isinstance(raw_skills, str):
        # CSV format usually separates by semicolon or comma
        if ";" in raw_skills:
            skills = [s.strip() for s in raw_skills.split(";")]
        else:
            skills = [s.strip() for s in raw_skills.split(",")]
    else:
        skills = raw_skills

    # Experience
    raw_exp = app.get("experience_years", app.get("experience", 0.0))
    try:
        experience = float(raw_exp)
    except (ValueError, TypeError):
        experience = 0.0

    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "master_profile": {
            "skills": skills,
            "experience": experience,
            # Education is intentionally ignored here because the Issue 10
            # matching engine does not use it. This intrinsically fulfills
            # the fairness requirement to not penalize non-traditional backgrounds.
        },
    }


class HiringShortlistAgent:
    def __init__(
        self,
        embedding_pipeline: EmbeddingPipeline | None = None,
        db: Session | None = None,
    ):
        self.embedding_pipeline = embedding_pipeline
        self.db = db

    def shortlist(
        self,
        jd_text: str,
        applicants: list[dict[str, Any]] | None = None,
        applicants_csv: str | Path | None = None,
        shortlist_size: int = 10,
        company_name: str | None = None,
        role_title: str | None = None,
    ) -> dict[str, Any]:
        if not jd_text or not jd_text.strip():
            raise ValueError("jd_text must not be empty.")
        if shortlist_size <= 0:
            raise ValueError("shortlist_size must be a positive integer.")
        if applicants is None and applicants_csv is None:
            raise ValueError("Must provide either applicants or applicants_csv.")

        parsed_applicants = []
        if applicants_csv:
            path = Path(applicants_csv)
            if not path.exists():
                raise FileNotFoundError(f"CSV file not found: {path}")

            with open(path, "r", encoding="utf-8") as f:
                parsed_applicants = list(csv.DictReader(f))
        else:
            parsed_applicants = applicants or []

        if not parsed_applicants:
            return {
                "total_applicants": 0,
                "shortlist_size": shortlist_size,
                "shortlist": [],
            }

        # Normalize JD
        extracted = _extract_jd_info(jd_text)
        final_role = role_title or extracted.get("role_title") or "Unknown Role"

        # Ephemeral Job for scoring (DO NOT PERSIST to jobs table)
        ephemeral_job = Job(
            id=uuid.uuid4(),
            jd_text=jd_text,
            role_title=final_role,
            company_name=company_name or "Unknown Company",
            skills_required=extracted.get("skills_required", []),
            experience_required=extracted.get("experience_required"),
            location=None,
            stipend_salary=None,
            source="hiring_shortlist",
            is_spam=False,
        )

        scored_candidates = []
        for raw_app in parsed_applicants:
            norm_app = _normalize_applicant(raw_app)

            # Use Issue #10 Match Scorer
            result = score_job(
                user=norm_app,
                job=ephemeral_job,
                embedding_pipeline=self.embedding_pipeline,
            )

            match_score = result.get("match_score", 0.0)
            matched_skills = result.get("skill_matches", [])
            skill_gaps = result.get("skill_gaps", [])

            # Generate deterministic summary
            if matched_skills:
                skills_str = ", ".join(matched_skills[:3])
                if len(matched_skills) > 3:
                    summary = f"Strong match with {skills_str}, and {len(matched_skills)-3} other relevant skills."
                else:
                    summary = f"Strong match with {skills_str} experience."
            else:
                summary = (
                    "Candidate has relevant profile but few explicit skill matches."
                )

            scored_candidates.append(
                {
                    "name": norm_app["name"],
                    "score": match_score,
                    "strengths": matched_skills,
                    "matched_skills": matched_skills,
                    "skill_gaps": skill_gaps,
                    "summary": summary,
                }
            )

        # Deterministic sorting: score DESC, name ASC
        scored_candidates.sort(key=lambda x: (-x["score"], x["name"]))

        # Slice the shortlist
        final_shortlist = scored_candidates[:shortlist_size]

        # Add rank
        for i, c in enumerate(final_shortlist, start=1):
            c["rank"] = i

        response = {
            "total_applicants": len(parsed_applicants),
            "shortlist_size": shortlist_size,
            "shortlist": final_shortlist,
        }

        # Persist to DB using minimal Shortlist model
        session = self.db if self.db is not None else SessionLocal()
        owns_session = self.db is None
        try:
            sl_record = Shortlist(
                company_name=company_name,
                role_title=final_role,
                total_applicants=len(parsed_applicants),
                shortlist_size=shortlist_size,
                candidates=final_shortlist,
            )
            session.add(sl_record)
            session.commit()
        except Exception as e:  # noqa: BLE001
            session.rollback()
            logger.error(f"Failed to persist shortlist to DB: {e}")
        finally:
            if owns_session:
                session.close()

        return response
