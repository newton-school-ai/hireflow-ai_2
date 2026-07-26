"""
Multi-Factor Match Scorer and Skill Gap Extractor for HireFlow AI.

Combines embedding similarity with skill match, role fit, experience fit,
location match, compensation fit, and company signals to compute a deterministic
composite match score for candidate job listings. Also extracts skill gaps.
"""

import argparse
import json
import logging
import re
import uuid
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from src.config.database import SessionLocal
from src.models.application import Application
from src.models.job import Job
from src.models.user import User

logger = logging.getLogger(__name__)

# Configurable scoring weights (must sum to 1.00)
WEIGHT_SKILL: float = 0.40
WEIGHT_ROLE: float = 0.20
WEIGHT_EXPERIENCE: float = 0.15
WEIGHT_LOCATION: float = 0.10
WEIGHT_COMPENSATION: float = 0.10
WEIGHT_COMPANY_SIGNAL: float = 0.05


def extract_skill_gaps(
    user_skills: list[str] | None, jd_skills: list[str] | None
) -> list[str]:
    """Identifies skills required by JD that are missing from user profile.

    Deduplicates skills while preserving order of appearance in JD.
    Performs case-insensitive comparisons and handles missing data gracefully.

    Args:
        user_skills: List of skills possessed by the user.
        jd_skills: List of skills required by the job description.

    Returns:
        List of missing skill strings in order of appearance in jd_skills.
    """
    if not jd_skills or not isinstance(jd_skills, list):
        return []

    if user_skills is None or not isinstance(user_skills, list):
        user_skills_set: set[str] = set()
    else:
        user_skills_set = {
            str(s).strip().lower()
            for s in user_skills
            if s is not None and str(s).strip()
        }

    gaps: list[str] = []
    seen_gaps_lower: set[str] = set()

    for skill in jd_skills:
        if skill is None:
            continue
        skill_str = str(skill).strip()
        if not skill_str:
            continue
        skill_lower = skill_str.lower()
        if skill_lower not in user_skills_set and skill_lower not in seen_gaps_lower:
            gaps.append(skill_str)
            seen_gaps_lower.add(skill_lower)

    return gaps


def calculate_skill_score(
    user_skills: list[str] | None, jd_skills: list[str] | None
) -> float:
    """Calculates skill match ratio (0.0 to 1.0) between user and job skills.

    Args:
        user_skills: List of skills possessed by the user.
        jd_skills: List of skills required by the job description.

    Returns:
        Float score between 0.0 and 1.0. Returns 1.0 if no skills required.
    """
    if not jd_skills or not isinstance(jd_skills, list):
        return 1.0

    jd_clean = {
        str(s).strip().lower() for s in jd_skills if s is not None and str(s).strip()
    }
    if not jd_clean:
        return 1.0

    if not user_skills or not isinstance(user_skills, list):
        return 0.0

    user_clean = {
        str(s).strip().lower() for s in user_skills if s is not None and str(s).strip()
    }

    matched = jd_clean.intersection(user_clean)
    return float(len(matched)) / float(len(jd_clean))


def calculate_role_score(
    target_roles: list[str] | str | None,
    role_title: str | None,
    embedding_similarity: float | None = None,
) -> float:
    """Calculates role fit score combining title matching and embedding similarity.

    Args:
        target_roles: Target roles specified by user (list or string).
        role_title: Role title from job posting.
        embedding_similarity: Optional embedding similarity score (0.0 to 1.0).

    Returns:
        Float score between 0.0 and 1.0.
    """
    title_fit = 0.0
    if role_title and isinstance(role_title, str) and role_title.strip():
        role_clean = role_title.strip().lower()
        roles_list: list[str] = []
        if isinstance(target_roles, list):
            roles_list = [
                str(r).strip().lower()
                for r in target_roles
                if r is not None and str(r).strip()
            ]
        elif isinstance(target_roles, str) and target_roles.strip():
            roles_list = [target_roles.strip().lower()]

        if roles_list:
            best_match = 0.0
            role_words = set(re.findall(r"\w+", role_clean))
            for tr in roles_list:
                if tr == role_clean:
                    best_match = 1.0
                    break
                elif tr in role_clean or role_clean in tr:
                    best_match = max(best_match, 0.85)
                else:
                    tr_words = set(re.findall(r"\w+", tr))
                    if tr_words:
                        overlap = len(tr_words.intersection(role_words))
                        if overlap > 0:
                            ratio = float(overlap) / float(len(tr_words))
                            best_match = max(best_match, ratio * 0.75)
            title_fit = best_match

    if embedding_similarity is not None:
        emb_sim_clamped = max(0.0, min(1.0, float(embedding_similarity)))
        if title_fit > 0.0:
            return 0.5 * title_fit + 0.5 * emb_sim_clamped
        return emb_sim_clamped

    if title_fit > 0.0:
        return title_fit
    return 0.5 if target_roles is None else 0.0


def _extract_user_years(user_exp: Any) -> float:
    """Helper to extract total experience years from various profile formats."""
    if user_exp is None:
        return 0.0

    if isinstance(user_exp, (int, float)):
        return float(user_exp)

    if isinstance(user_exp, str):
        match = re.search(r"(\d+(?:\.\d+)?)", user_exp)
        if match:
            return float(match.group(1))
        return 0.0

    if isinstance(user_exp, list):
        total_years = 0.0
        for item in user_exp:
            if isinstance(item, (int, float)):
                total_years += float(item)
            elif isinstance(item, dict):
                y = item.get("years") or item.get("duration_years")
                if isinstance(y, (int, float)):
                    total_years += float(y)
                elif isinstance(y, str):
                    m = re.search(r"(\d+(?:\.\d+)?)", y)
                    if m:
                        total_years += float(m.group(1))
                else:
                    dur = item.get("duration")
                    if isinstance(dur, str):
                        m = re.search(r"(\d+(?:\.\d+)?)", dur)
                        if m:
                            total_years += float(m.group(1))
        return total_years

    return 0.0


def _parse_job_experience_req(job_exp_req: Any) -> float | None:
    """Helper to parse required experience years from job requirements string."""
    if job_exp_req is None:
        return None

    if isinstance(job_exp_req, (int, float)):
        return float(job_exp_req)

    if not isinstance(job_exp_req, str) or not job_exp_req.strip():
        return None

    text = job_exp_req.strip().lower()

    if any(k in text for k in ["fresher", "entry", "junior", "intern"]):
        return 0.0

    match_plus = re.search(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)?", text)
    if match_plus:
        return float(match_plus.group(1))

    if "senior" in text or "lead" in text:
        return 5.0

    if "mid" in text:
        return 3.0

    return None


def calculate_experience_score(user_exp: Any, job_exp_req: Any) -> float:
    """Calculates experience fit score (0.0 to 1.0).

    Args:
        user_exp: User experience data (list, int, float, or str).
        job_exp_req: Job experience requirement string or numeric.

    Returns:
        Float score between 0.0 and 1.0.
    """
    min_req = _parse_job_experience_req(job_exp_req)
    if min_req is None or min_req <= 0.0:
        return 1.0

    user_years = _extract_user_years(user_exp)
    if user_years >= min_req:
        return 1.0

    return max(0.0, min(1.0, user_years / min_req))


def calculate_location_score(
    user_locations: list[str] | str | None, job_location: str | None
) -> float:
    """Calculates location match score (0.0 to 1.0).

    Args:
        user_locations: User preferred locations (list or string).
        job_location: Job location string.

    Returns:
        Float score: 1.0 for match, 0.5 for unspecified, 0.0 for mismatch.
    """
    if not user_locations:
        return 1.0

    if (
        not job_location
        or not isinstance(job_location, str)
        or not job_location.strip()
    ):
        return 0.5

    job_loc_clean = job_location.strip().lower()
    user_locs: list[str] = []

    if isinstance(user_locations, list):
        user_locs = [
            str(loc).strip().lower()
            for loc in user_locations
            if loc is not None and str(loc).strip()
        ]
    elif isinstance(user_locations, str) and user_locations.strip():
        user_locs = [user_locations.strip().lower()]

    if not user_locs:
        return 1.0

    is_job_remote = "remote" in job_loc_clean

    for u_loc in user_locs:
        if u_loc == "remote" and is_job_remote:
            return 1.0
        if is_job_remote or u_loc == "remote":
            return 1.0
        if u_loc in job_loc_clean or job_loc_clean in u_loc:
            return 1.0

    return 0.0


def _parse_compensation(value: Any) -> float | None:
    """Helper to extract numerical compensation value from string or numeric types."""
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if not isinstance(value, str) or not value.strip():
        return None

    text = value.strip().lower()
    # Remove commas between digits (e.g., 5,000 -> 5000)
    text = re.sub(r"(?<=\d),(?=\d)", "", text)

    # Find numbers with optional k/K suffix
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*(k)?", text)
    if not matches:
        return None

    values: list[float] = []
    for num_str, k_suffix in matches:
        num = float(num_str)
        if k_suffix == "k":
            num *= 1000.0
        values.append(num)

    if not values:
        return None

    return max(values)


def calculate_compensation_score(
    user_min_comp: Any, job_comp_str: Any, mode: str = "job"
) -> float:
    """Calculates compensation score (0.0 to 1.0) comparing target to offering.

    Args:
        user_min_comp: Minimum stipend (internship) or salary (job).
        job_comp_str: Job compensation text or numeric amount.
        mode: Candidate mode ('internship' or 'job').

    Returns:
        Float score between 0.0 and 1.0.
    """
    user_min = _parse_compensation(user_min_comp)
    if user_min is None or user_min <= 0.0:
        return 1.0

    job_comp = _parse_compensation(job_comp_str)
    if job_comp is None or job_comp <= 0.0:
        return 0.5

    if job_comp >= user_min:
        return 1.0

    return max(0.0, min(1.0, job_comp / user_min))


def calculate_company_signal(
    company_name: str | None, job_source: str | None = None
) -> float:
    """Calculates company signal score (0.0 to 1.0).

    Args:
        company_name: Name of hiring company.
        job_source: ATS source (e.g. 'lever', 'greenhouse').

    Returns:
        Float score: 1.0 for top ATS source, 0.8 for valid name, 0.0 if missing.
    """
    if (
        not company_name
        or not isinstance(company_name, str)
        or not company_name.strip()
    ):
        return 0.0

    clean_name = company_name.strip().lower()
    if clean_name in ["unknown", "n/a", "none"]:
        return 0.0

    if job_source and isinstance(job_source, str):
        clean_source = job_source.strip().lower()
        if clean_source in ["lever", "greenhouse", "workday", "ashby"]:
            return 1.0

    return 0.8


def compute_final_score(
    skill_score: float,
    role_score: float,
    exp_score: float,
    loc_score: float,
    comp_score: float,
    company_score: float,
) -> float:
    """Calculates composite match score normalized between 0.0 and 1.0.

    Weights: Skill (40%), Role (20%), Experience (15%), Location (10%),
             Compensation (10%), Company Signal (5%).
    """
    total = (
        WEIGHT_SKILL * skill_score
        + WEIGHT_ROLE * role_score
        + WEIGHT_EXPERIENCE * exp_score
        + WEIGHT_LOCATION * loc_score
        + WEIGHT_COMPENSATION * comp_score
        + WEIGHT_COMPANY_SIGNAL * company_score
    )
    clamped = max(0.0, min(1.0, float(total)))
    return round(clamped, 4)


def score_job(
    user: User | dict[str, Any],
    job: Job,
    embedding_pipeline: Any = None,
) -> dict[str, Any]:
    """Scores a single Job model against a User model or profile dict.

    Args:
        user: User instance or profile dict.
        job: Job instance.
        embedding_pipeline: Optional EmbeddingPipeline instance.

    Returns:
        Dict with job_id, user_id, match_score, skill_matches, skill_gaps, sub_scores.
    """
    if isinstance(user, User):
        user_id = user.id
        mode = user.mode or "internship"
        mp = user.master_profile or {}
    elif isinstance(user, dict):
        user_id = user.get("id")
        mode = user.get("mode", "internship")
        mp = (
            user.get("master_profile")
            if isinstance(user.get("master_profile"), dict)
            else user
        )
    else:
        user_id = None
        mode = "internship"
        mp = {}

    user_skills = mp.get("skills", [])
    target_roles = mp.get("target_roles", [])
    preferred_locations = mp.get("preferred_locations", [])
    user_exp = mp.get("experience", mp.get("years_of_experience"))

    if mode == "internship":
        user_min_comp = mp.get("min_stipend")
    else:
        user_min_comp = mp.get("min_salary")

    jd_skills = job.skills_required or []

    # Semantic similarity calculation using embedding pipeline if provided
    embedding_similarity: float | None = None
    if embedding_pipeline is not None:
        try:
            profile_summary_parts = []
            if target_roles:
                roles_str = (
                    ", ".join(target_roles)
                    if isinstance(target_roles, list)
                    else str(target_roles)
                )
                profile_summary_parts.append(f"Roles: {roles_str}")
            if user_skills:
                skills_str = (
                    ", ".join(user_skills)
                    if isinstance(user_skills, list)
                    else str(user_skills)
                )
                profile_summary_parts.append(f"Skills: {skills_str}")

            profile_text = "\n".join(profile_summary_parts)
            if profile_text.strip():
                u_emb = embedding_pipeline.embed_text(profile_text)
                job_text = (
                    f"Role: {job.role_title or ''}\n"
                    f"Company: {job.company_name or ''}\n"
                    f"Description: {job.jd_text or ''}"
                )
                j_emb = embedding_pipeline.embed_text(job_text)

                if u_emb is not None and j_emb is not None:
                    sim = float(np.dot(u_emb, j_emb))
                    embedding_similarity = max(0.0, min(1.0, sim))
        except Exception as e:
            logger.warning(f"Error computing embedding similarity: {e}")
            embedding_similarity = None

    # Calculate sub-factor scores
    skill_score = calculate_skill_score(user_skills, jd_skills)
    role_score = calculate_role_score(
        target_roles, job.role_title, embedding_similarity
    )
    exp_score = calculate_experience_score(user_exp, job.experience_required)
    loc_score = calculate_location_score(preferred_locations, job.location)
    comp_score = calculate_compensation_score(
        user_min_comp, job.stipend_salary, mode=mode
    )
    company_score = calculate_company_signal(job.company_name, job.source)

    # Extract gaps and matches
    gaps = extract_skill_gaps(user_skills, jd_skills)

    gaps_lower = {g.lower() for g in gaps}
    matched_skills = [
        str(s).strip()
        for s in (jd_skills or [])
        if s is not None and str(s).strip() and str(s).strip().lower() not in gaps_lower
    ]

    final_score = compute_final_score(
        skill_score=skill_score,
        role_score=role_score,
        exp_score=exp_score,
        loc_score=loc_score,
        comp_score=comp_score,
        company_score=company_score,
    )

    return {
        "job_id": job.id,
        "user_id": user_id,
        "match_score": final_score,
        "skill_matches": matched_skills,
        "skill_gaps": gaps,
        "sub_scores": {
            "skill": skill_score,
            "role": role_score,
            "experience": exp_score,
            "location": loc_score,
            "compensation": comp_score,
            "company": company_score,
        },
    }


def score_all_jobs(
    user_id: uuid.UUID | str,
    db: Session,
    save_to_db: bool = True,
    dry_run: bool = False,
    embedding_pipeline: Any = None,
) -> list[dict[str, Any]]:
    """Scores non-spam jobs for a target user and saves applications.

    Args:
        user_id: User UUID or string identifier.
        db: Active SQLAlchemy Session.
        save_to_db: Whether to write application records to database.
        dry_run: If True, skips database writes regardless of save_to_db.
        embedding_pipeline: Optional EmbeddingPipeline instance.

    Returns:
        List of score dicts sorted deterministically by match_score DESC, job_id ASC.
    """
    if isinstance(user_id, str):
        try:
            u_id = uuid.UUID(user_id)
        except ValueError as e:
            raise ValueError(f"Invalid user_id UUID format: {user_id}") from e
    else:
        u_id = user_id

    user = db.query(User).filter(User.id == u_id).first()
    if not user:
        raise ValueError(f"User with ID {user_id} not found.")

    jobs = db.query(Job).filter(Job.is_spam == False).all()  # noqa: E712

    results: list[dict[str, Any]] = []
    for job in jobs:
        res = score_job(user=user, job=job, embedding_pipeline=embedding_pipeline)
        results.append(res)

    results.sort(key=lambda x: (-x["match_score"], str(x["job_id"])))

    if save_to_db and not dry_run:
        for item in results:
            j_id = item["job_id"]
            app = (
                db.query(Application)
                .filter(Application.user_id == u_id, Application.job_id == j_id)
                .first()
            )
            if app:
                app.match_score = item["match_score"]
                app.skill_matches = item["skill_matches"]
                app.skill_gaps = item["skill_gaps"]
            else:
                app = Application(
                    user_id=u_id,
                    job_id=j_id,
                    match_score=item["match_score"],
                    skill_matches=item["skill_matches"],
                    skill_gaps=item["skill_gaps"],
                    status="matched",
                )
                db.add(app)
        db.commit()

    return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="HireFlow AI CLI match scorer pipeline."
    )
    parser.add_argument(
        "--user-id",
        type=str,
        required=True,
        help="UUID string of the target user to score jobs against.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform scoring calculations without saving results to the database.",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Do not save scored application results to database.",
    )

    args = parser.parse_args()

    session = SessionLocal()
    try:
        should_save = not args.dry_run and not args.no_save
        scored = score_all_jobs(
            user_id=args.user_id,
            db=session,
            save_to_db=should_save,
            dry_run=args.dry_run,
        )

        formatted_results = [
            {
                "job_id": str(r["job_id"]),
                "user_id": str(r["user_id"]) if r["user_id"] else None,
                "match_score": r["match_score"],
                "skill_matches": r["skill_matches"],
                "skill_gaps": r["skill_gaps"],
                "sub_scores": r["sub_scores"],
            }
            for r in scored
        ]

        print(json.dumps(formatted_results, indent=2))
    except Exception as exc:
        logger.error(f"Error during match scorer CLI execution: {exc}")
        raise
    finally:
        session.close()
