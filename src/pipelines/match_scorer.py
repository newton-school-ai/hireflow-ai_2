"""
Multi-Factor Match Scorer and Skill Gap Extractor for HireFlow AI.

Ranks non-spam job listings against a user profile using a 6-factor weighted scoring algorithm:
- Skill Match: 40%
- Role Fit: 20%
- Experience Fit: 15%
- Location Match: 10%
- Stipend/Salary Fit: 10%
- Company Signal: 5%

Also extracts skill matches and skill gaps for downstream resume tailoring and prep guide modules.
"""

import argparse
import json
import logging
import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from src.config.database import SessionLocal
from src.models.application import Application
from src.models.job import Job
from src.models.user import User
from src.pipelines.embedding_pipeline import EmbeddingPipeline

logger = logging.getLogger(__name__)


class MatchScorer:
    """Multi-factor scoring engine that ranks jobs and extracts skill gaps for a candidate."""

    # Exact factor weights
    WEIGHT_SKILL = 0.40
    WEIGHT_ROLE = 0.20
    WEIGHT_EXPERIENCE = 0.15
    WEIGHT_LOCATION = 0.10
    WEIGHT_SALARY = 0.10
    WEIGHT_COMPANY = 0.05

    def __init__(self, embedding_pipeline: EmbeddingPipeline | None = None) -> None:
        """Initialize MatchScorer.

        Args:
            embedding_pipeline: Optional EmbeddingPipeline instance for semantic role similarity.
        """
        self.embedding_pipeline = embedding_pipeline

    def _get_embedding_pipeline(self) -> EmbeddingPipeline | None:
        if self.embedding_pipeline is None:
            try:
                self.embedding_pipeline = EmbeddingPipeline()
            except Exception as e:
                logger.warning(
                    f"Could not load EmbeddingPipeline for role similarity: {e}"
                )
                self.embedding_pipeline = None
        return self.embedding_pipeline

    def calculate_score(
        self, user_data: dict[str, Any], job_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Calculate factor breakdown, overall match score, and skill gaps for a job against a user profile.

        Args:
            user_data: Dictionary containing user profile information (skills, target_roles, mode, etc.).
            job_data: Dictionary containing job listing information (role_title, company_name, jd_text, etc.).

        Returns:
            dict: Result containing match_score, skill_matches, skill_gaps, and factor breakdown.
        """
        user_skills_raw = user_data.get("skills") or []
        if isinstance(user_skills_raw, str):
            user_skills_raw = [
                s.strip() for s in user_skills_raw.split(",") if s.strip()
            ]

        user_skills_set = {
            s.strip().lower() for s in user_skills_raw if s and s.strip()
        }

        job_skills_raw = job_data.get("skills_required") or []
        if isinstance(job_skills_raw, str):
            job_skills_raw = [s.strip() for s in job_skills_raw.split(",") if s.strip()]

        # 1. Skill Match (40%) & Skill Gaps Extraction
        matched_skills = []
        skill_gaps = []

        if job_skills_raw:
            for s in job_skills_raw:
                s_clean = s.strip()
                if not s_clean:
                    continue
                if s_clean.lower() in user_skills_set:
                    matched_skills.append(s_clean)
                else:
                    skill_gaps.append(s_clean)

            total_job_skills = len(matched_skills) + len(skill_gaps)
            if total_job_skills > 0:
                skill_score = len(matched_skills) / total_job_skills
            else:
                skill_score = 0.5
        else:
            # Fallback when JD doesn't list explicit skills
            jd_text = (job_data.get("jd_text") or "").lower()
            for s in user_skills_raw:
                if s and s.strip().lower() in jd_text:
                    matched_skills.append(s.strip())

            if user_skills_raw:
                skill_score = min(
                    1.0, len(matched_skills) / max(1, len(user_skills_raw))
                )
            else:
                skill_score = 0.5

        # Deduplicate and sort for deterministic output
        skill_matches = sorted(list(dict.fromkeys(matched_skills)))
        skill_gaps = sorted(list(dict.fromkeys(skill_gaps)))

        # 2. Role Fit (20%)
        target_roles = user_data.get("target_roles") or []
        if isinstance(target_roles, str):
            target_roles = [target_roles]
        target_roles_str = " ".join([r for r in target_roles if r]).strip()

        job_title = job_data.get("role_title") or ""
        role_score = self._compute_role_fit(target_roles_str, job_title)

        # 3. Experience Fit (15%)
        user_mode = (user_data.get("mode") or "internship").lower()
        user_exp = user_data.get("experience")
        job_exp_req = job_data.get("experience_required") or ""
        jd_text = job_data.get("jd_text") or ""
        exp_score = self._compute_experience_fit(
            user_mode, user_exp, job_exp_req, jd_text
        )

        # 4. Location Match (10%)
        preferred_locs = user_data.get("preferred_locations") or []
        if isinstance(preferred_locs, str):
            preferred_locs = [preferred_locs]
        job_loc = job_data.get("location") or ""
        loc_score = self._compute_location_match(preferred_locs, job_loc)

        # 5. Stipend / Salary Fit (10%)
        min_stipend = user_data.get("min_stipend")
        min_salary = user_data.get("min_salary")
        stipend_salary_text = job_data.get("stipend_salary") or ""
        salary_score = self._compute_salary_fit(
            user_mode, min_stipend, min_salary, stipend_salary_text
        )

        # 6. Company Signal (5%)
        company_name = job_data.get("company_name") or ""
        source = job_data.get("source") or ""
        company_score = self._compute_company_signal(
            company_name, source, job_skills_raw, job_loc
        )

        # Weighted Total Score
        raw_score = (
            (self.WEIGHT_SKILL * skill_score)
            + (self.WEIGHT_ROLE * role_score)
            + (self.WEIGHT_EXPERIENCE * exp_score)
            + (self.WEIGHT_LOCATION * loc_score)
            + (self.WEIGHT_SALARY * salary_score)
            + (self.WEIGHT_COMPANY * company_score)
        )

        final_match_score = float(round(raw_score, 3))

        return {
            "match_score": final_match_score,
            "skill_matches": skill_matches,
            "skill_gaps": skill_gaps,
            "breakdown": {
                "skill_score": round(skill_score, 3),
                "role_score": round(role_score, 3),
                "experience_score": round(exp_score, 3),
                "location_score": round(loc_score, 3),
                "salary_score": round(salary_score, 3),
                "company_score": round(company_score, 3),
            },
        }

    def _compute_role_fit(self, target_roles_str: str, job_title: str) -> float:
        if not target_roles_str or not job_title:
            return 0.5

        # Check semantic similarity using EmbeddingPipeline if available
        ep = self._get_embedding_pipeline()
        if ep:
            try:
                v1 = ep.embed_text(target_roles_str)
                v2 = ep.embed_text(job_title)
                dot = (
                    float(np.dot(v1, v2))
                    if "np" in globals()
                    else float((v1 * v2).sum())
                )
                sem_sim = max(0.0, min(1.0, dot))
                return sem_sim
            except Exception as e:
                logger.debug(f"Embedding calculation for role fit fallback: {e}")

        # Fallback keyword overlap
        target_words = set(re.findall(r"\w+", target_roles_str.lower()))
        title_words = set(re.findall(r"\w+", job_title.lower()))
        if not target_words or not title_words:
            return 0.5

        overlap = len(target_words.intersection(title_words))
        return min(1.0, overlap / len(target_words))

    def _compute_experience_fit(
        self, user_mode: str, user_exp: Any, job_exp_req: str, jd_text: str
    ) -> float:
        text_to_check = f"{job_exp_req} {jd_text}".lower()

        # For internship mode or entry level / fresher candidates
        if (
            user_mode == "internship"
            or not user_exp
            or str(user_exp).strip() in ["0", "0-1", "fresher", "entry"]
        ):
            if any(
                term in text_to_check
                for term in [
                    "5+ years",
                    "7+ years",
                    "10+ years",
                    "principal",
                    "lead",
                    "director",
                ]
            ):
                return 0.2
            if any(
                term in text_to_check
                for term in ["3+ years", "4+ years", "senior", "sr."]
            ):
                return 0.5
            return 1.0

        # Try to parse experience numbers
        numbers = [int(n) for n in re.findall(r"\d+", str(user_exp))]
        user_years = numbers[0] if numbers else 0

        req_numbers = [int(n) for n in re.findall(r"\d+", job_exp_req)]
        req_years = req_numbers[0] if req_numbers else 0

        if user_years >= req_years:
            return 1.0
        diff = req_years - user_years
        return max(0.0, round(1.0 - (diff * 0.2), 2))

    def _compute_location_match(
        self, preferred_locations: list[str], job_location: str
    ) -> float:
        clean_job_loc = (job_location or "").strip().lower()

        if not clean_job_loc or any(
            remote_kw in clean_job_loc
            for remote_kw in ["remote", "anywhere", "flexible", "work from home"]
        ):
            return 1.0

        if not preferred_locations or any(
            p.strip().lower() in ["any", "remote", "flexible"]
            for p in preferred_locations
            if p
        ):
            return 1.0

        for pref in preferred_locations:
            clean_pref = pref.strip().lower()
            if clean_pref and (
                clean_pref in clean_job_loc or clean_job_loc in clean_pref
            ):
                return 1.0

        return 0.4

    def _compute_salary_fit(
        self,
        user_mode: str,
        min_stipend: Any,
        min_salary: Any,
        stipend_salary_text: str,
    ) -> float:
        if not stipend_salary_text or not stipend_salary_text.strip():
            return 1.0

        min_val = min_stipend if user_mode == "internship" else min_salary
        if min_val is None:
            return 1.0

        try:
            target_min = float(min_val)
        except (ValueError, TypeError):
            return 1.0

        if target_min <= 0:
            return 1.0

        # Parse numeric values from job stipend/salary string
        salary_nums = [
            float(n)
            for n in re.findall(r"\d+(?:\.\d+)?", stipend_salary_text.replace(",", ""))
        ]
        if not salary_nums:
            return 1.0

        max_offered = max(salary_nums)
        if max_offered >= target_min:
            return 1.0

        ratio = max_offered / target_min
        return max(0.2, min(1.0, round(ratio, 2)))

    def _compute_company_signal(
        self,
        company_name: str,
        source: str,
        skills_required: list,
        location: str,
    ) -> float:
        score = 0.5
        if company_name and company_name.strip():
            score += 0.2
        if source and source.lower() in [
            "lever",
            "greenhouse",
            "wellfound",
            "linkedin",
            "workday",
        ]:
            score += 0.2
        if skills_required and location:
            score += 0.1
        return min(1.0, round(score, 2))

    def score_user(
        self,
        user_id: str | uuid.UUID,
        db: Session | None = None,
        dry_run: bool = False,
    ) -> list[dict[str, Any]]:
        """Score all non-spam jobs for a user, optionally saving applications to database.

        Args:
            user_id: Target user UUID or string ID.
            db: Optional database session.
            dry_run: If True, returns scores without saving to database.

        Returns:
            list[dict]: List of scored application result dictionaries sorted by match_score DESC.
        """
        close_session_at_end = False
        if db is None:
            db = SessionLocal()
            close_session_at_end = True

        try:

            user_uuid = uuid.UUID(str(user_id)) if isinstance(user_id, str) else user_id
            user = db.query(User).filter(User.id == user_uuid).first()
            if not user:
                raise ValueError(f"User with id '{user_id}' not found.")

            # Load master profile data
            mp = user.master_profile or {}
            user_data = {
                "user_id": str(user.id),
                "name": user.name,
                "email": user.email,
                "mode": user.mode,
                "skills": mp.get("skills") or [],
                "target_roles": mp.get("target_roles") or [],
                "preferred_locations": mp.get("preferred_locations") or [],
                "min_stipend": mp.get("min_stipend"),
                "min_salary": mp.get("min_salary"),
                "experience": mp.get("experience"),
                "education": mp.get("education"),
            }

            # Fetch non-spam jobs ordered deterministically by id
            jobs = (
                db.query(Job)
                .filter(Job.is_spam == False)  # noqa: E712
                .order_by(Job.id.asc())
                .all()
            )

            results = []
            for job in jobs:
                job_data = {
                    "job_id": str(job.id),
                    "company_name": job.company_name,
                    "role_title": job.role_title,
                    "jd_text": job.jd_text,
                    "location": job.location,
                    "skills_required": job.skills_required or [],
                    "stipend_salary": job.stipend_salary,
                    "experience_required": job.experience_required,
                    "source": job.source,
                }

                scored = self.calculate_score(user_data, job_data)
                result_item = {
                    "job_id": str(job.id),
                    "company_name": job.company_name,
                    "role_title": job.role_title,
                    "match_score": scored["match_score"],
                    "skill_matches": scored["skill_matches"],
                    "skill_gaps": scored["skill_gaps"],
                    "breakdown": scored["breakdown"],
                }
                results.append(result_item)

            # Sort results deterministically by match_score DESC, then job_id ASC
            results.sort(key=lambda x: (-x["match_score"], x["job_id"]))

            if not dry_run:
                # Upsert Application records into DB
                for item in results:
                    job_uuid = uuid.UUID(item["job_id"])
                    app = (
                        db.query(Application)
                        .filter(
                            Application.user_id == user.id,
                            Application.job_id == job_uuid,
                        )
                        .first()
                    )
                    if not app:
                        app = Application(
                            user_id=user.id,
                            job_id=job_uuid,
                            match_score=item["match_score"],
                            skill_matches=item["skill_matches"],
                            skill_gaps=item["skill_gaps"],
                            status="matched",
                        )
                        db.add(app)
                    else:
                        app.match_score = item["match_score"]
                        app.skill_matches = item["skill_matches"]
                        app.skill_gaps = item["skill_gaps"]
                        app.status = "matched"

                db.commit()

            return results

        except Exception as e:
            if not dry_run:
                db.rollback()
            logger.error(f"Error scoring jobs for user {user_id}: {e}", exc_info=True)
            raise e
        finally:
            if close_session_at_end:
                db.close()


def main() -> None:
    """CLI runner for MatchScorer."""
    parser = argparse.ArgumentParser(
        description="HireFlow AI Multi-Factor Match Scorer CLI"
    )
    parser.add_argument(
        "--user-id",
        required=True,
        help="UUID of the user to score jobs against.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute scores and print JSON to stdout without modifying database.",
    )
    args = parser.parse_args()

    scorer = MatchScorer()
    results = scorer.score_user(user_id=args.user_id, dry_run=args.dry_run)

    if args.dry_run:
        print(json.dumps(results, indent=2))
    else:
        print(
            f"Successfully scored {len(results)} non-spam jobs for user '{args.user_id}' and updated database."
        )


if __name__ == "__main__":
    # Import numpy locally if available for matrix math
    try:
        import numpy as np  # noqa: F401
    except ImportError:
        pass
    main()
