"""
Resume Tailoring Engine (RAG Pipeline) for HireFlow AI.

RAG pipeline that takes a user profile and job description, selects the most
relevant skills and projects, and generates tailored, grounded resume content
without introducing hallucinated data.
"""

import argparse
import json
import logging
import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from src.config.database import SessionLocal
from src.models.job import Job
from src.models.user import User
from src.pipelines.embedding_pipeline import EmbeddingPipeline
from src.utils.llm_client import BaseLLMClient, LLMConfigError, get_llm_client

logger = logging.getLogger(__name__)


class ResumeError(Exception):
    """Base exception for resume tailoring engine errors."""


class UserNotFoundError(ResumeError, ValueError):
    """Raised when a specified user ID is not found."""


class JobNotFoundError(ResumeError, ValueError):
    """Raised when a specified job ID is not found."""


class EmptyProfileError(ResumeError, ValueError):
    """Raised when candidate profile data is missing or empty."""


class EmptyJobError(ResumeError, ValueError):
    """Raised when job description text is missing or empty."""


def _clean_str(text: Any) -> str:
    """Helper to convert any input to clean string."""
    if text is None:
        return ""
    return str(text).strip()


class ResumeTailoringEngine:
    """Trustworthy Resume Tailoring Engine using Retrieval-Augmented Generation (RAG).

    Selects, reorders, and rewrites candidate profile information to align with a
    target Job Description (JD) without hallucinating unverified skills or experience.
    """

    def __init__(
        self,
        llm_client: BaseLLMClient | None = None,
        embedding_pipeline: EmbeddingPipeline | None = None,
    ) -> None:
        """Initialize engine with optional dependency injection.

        Args:
            llm_client: Optional LLM client instance for text generation.
            embedding_pipeline: Optional embedding pipeline instance for semantic search.
        """
        self._llm_client = llm_client
        self._embedding_pipeline = embedding_pipeline

    @property
    def llm_client(self) -> BaseLLMClient | None:
        """Lazily load LLM client if not injected."""
        if self._llm_client is None:
            try:
                self._llm_client = get_llm_client()
            except (LLMConfigError, ValueError) as e:
                logger.warning(f"LLM client unavailable, using template fallbacks: {e}")
                self._llm_client = None
        return self._llm_client

    @property
    def embedding_pipeline(self) -> EmbeddingPipeline | None:
        """Lazily load EmbeddingPipeline if not injected."""
        if self._embedding_pipeline is None:
            try:
                self._embedding_pipeline = EmbeddingPipeline()
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    f"Embedding pipeline unavailable, using text fallback: {e}"
                )
                self._embedding_pipeline = None
        return self._embedding_pipeline

    def retrieval(
        self,
        user_id: str | uuid.UUID,
        job_id: str | uuid.UUID,
        db: Session | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Retrieve user profile and job listing data from database or raw inputs.

        Args:
            user_id: User identifier (UUID or string).
            job_id: Job identifier (UUID or string).
            db: Optional SQLAlchemy Session.

        Returns:
            Tuple of (user_profile_dict, job_data_dict).

        Raises:
            UserNotFoundError: If user is not found.
            JobNotFoundError: If job is not found.
            EmptyProfileError: If user profile contains no data.
            EmptyJobError: If job description text is empty.
        """
        if db is None:
            with SessionLocal() as session:
                return self.retrieval(user_id, job_id, db=session)

        # Query User
        try:
            parsed_user_id = (
                uuid.UUID(str(user_id))
                if isinstance(user_id, str) and len(str(user_id)) == 36
                else user_id
            )
            user = db.query(User).filter(User.id == parsed_user_id).first()
        except Exception:  # noqa: BLE001
            user = db.query(User).filter(User.id == user_id).first()

        if not user:
            raise UserNotFoundError(f"User with ID '{user_id}' not found.")

        # Query Job
        try:
            parsed_job_id = (
                uuid.UUID(str(job_id))
                if isinstance(job_id, str) and len(str(job_id)) == 36
                else job_id
            )
            job = db.query(Job).filter(Job.id == parsed_job_id).first()
        except Exception:  # noqa: BLE001
            job = db.query(Job).filter(Job.id == job_id).first()

        if not job:
            raise JobNotFoundError(f"Job with ID '{job_id}' not found.")

        master_profile = user.master_profile or {}
        if not master_profile and not user.name:
            raise EmptyProfileError(f"Profile for user '{user_id}' is empty.")

        user_profile = {
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "mode": user.mode or "internship",
            "skills": master_profile.get("skills", []),
            "target_roles": master_profile.get("target_roles", []),
            "experience": master_profile.get("experience", []),
            "education": master_profile.get("education", []),
            "projects": master_profile.get("projects", []),
        }

        jd_text = _clean_str(job.jd_text)
        if not jd_text and not job.role_title:
            raise EmptyJobError(f"Job description for job '{job_id}' is empty.")

        job_data = {
            "id": str(job.id),
            "company_name": job.company_name,
            "role_title": job.role_title,
            "jd_text": jd_text,
            "skills_required": job.skills_required or [],
            "listing_type": job.listing_type or "internship",
        }

        return user_profile, job_data

    def prioritize_skills(
        self,
        user_skills: list[str] | None,
        jd_skills: list[str] | None,
        jd_text: str | None = None,
    ) -> list[str]:
        """Reorder user skills based on Job Description priority.

        Skills mentioned earlier in the JD or required skills list appear first.
        NEVER introduces skills not possessed by the user.

        Args:
            user_skills: Candidate's skills list.
            jd_skills: Job description required skills.
            jd_text: Full JD text for contextual priority.

        Returns:
            Reordered list of candidate's skills.
        """
        if not user_skills:
            return []

        # Map lowercased skill to original casing
        user_map: dict[str, str] = {}
        for s in user_skills:
            clean_s = _clean_str(s)
            if clean_s:
                lower = clean_s.lower()
                if lower not in user_map:
                    user_map[lower] = clean_s

        if not user_map:
            return []

        # Build priority order from JD skills & JD text
        jd_priority: list[str] = []
        seen_jd: set[str] = set()

        if jd_skills:
            for s in jd_skills:
                clean_s = _clean_str(s).lower()
                if clean_s and clean_s not in seen_jd:
                    jd_priority.append(clean_s)
                    seen_jd.add(clean_s)

        if jd_text:
            cleaned_text = jd_text.lower()
            # Check for occurrences of candidate skills in JD text in order of appearance
            skill_positions: list[tuple[int, str]] = []
            for skill_lower in user_map:
                pos = cleaned_text.find(skill_lower)
                if pos != -1:
                    skill_positions.append((pos, skill_lower))

            skill_positions.sort(key=lambda x: x[0])
            for _, skill_lower in skill_positions:
                if skill_lower not in seen_jd:
                    jd_priority.append(skill_lower)
                    seen_jd.add(skill_lower)

        # Assemble prioritized skills
        result: list[str] = []
        added: set[str] = set()

        # 1. User skills that match JD priority, in JD priority order
        for priority_skill in jd_priority:
            if priority_skill in user_map and priority_skill not in added:
                result.append(user_map[priority_skill])
                added.add(priority_skill)

        # 2. Remaining user skills in original order
        for orig_skill in user_skills:
            clean_s = _clean_str(orig_skill)
            lower = clean_s.lower()
            if lower in user_map and lower not in added:
                result.append(user_map[lower])
                added.add(lower)

        return result

    def select_projects(
        self,
        projects: list[dict[str, Any]] | None,
        jd_skills: list[str] | None,
        jd_text: str | None = None,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """Select the most relevant 2 to 3 projects from candidate profile.

        Ranks projects based on skill overlap, keyword match, and semantic similarity.

        Args:
            projects: Candidate projects list.
            jd_skills: Required skills from JD.
            jd_text: Full JD text.
            top_k: Maximum projects to return (default 3).

        Returns:
            List of top relevant project dictionaries.
        """
        if not projects:
            return []

        if len(projects) <= 1:
            return list(projects)

        jd_skills_lower = {
            _clean_str(s).lower() for s in (jd_skills or []) if _clean_str(s)
        }
        clean_jd_text = _clean_str(jd_text).lower()

        # Use injected embedding pipeline if provided
        jd_embedding = None
        if self._embedding_pipeline and clean_jd_text:
            try:
                jd_embedding = self._embedding_pipeline.embed_text(clean_jd_text)
            except Exception as e:  # noqa: BLE001
                logger.debug(
                    f"Failed to generate JD embedding for project selection: {e}"
                )
                jd_embedding = None

        scored_projects: list[tuple[float, int, dict[str, Any]]] = []

        for idx, proj in enumerate(projects):
            proj_name = _clean_str(proj.get("name") or proj.get("title"))
            proj_desc = _clean_str(proj.get("description"))

            proj_tech_raw = proj.get("technologies") or proj.get("skills") or []
            if isinstance(proj_tech_raw, str):
                proj_tech = [t.strip() for t in proj_tech_raw.split(",") if t.strip()]
            else:
                proj_tech = [_clean_str(t) for t in proj_tech_raw if _clean_str(t)]

            proj_tech_lower = {t.lower() for t in proj_tech}

            # 1. Skill overlap score
            if jd_skills_lower:
                overlap = len(proj_tech_lower.intersection(jd_skills_lower))
                skill_score = overlap / max(1, len(jd_skills_lower))
            else:
                skill_score = 0.0

            # 2. Text keyword / semantic similarity score
            proj_full_text = f"{proj_name} {proj_desc} {' '.join(proj_tech)}"
            proj_text_lower = proj_full_text.lower()

            semantic_score = 0.0
            if jd_embedding is not None and self._embedding_pipeline:
                try:
                    proj_emb = self._embedding_pipeline.embed_text(proj_full_text)
                    if proj_emb is not None:
                        semantic_score = float((proj_emb * jd_embedding).sum())
                except Exception:  # noqa: BLE001
                    semantic_score = 0.0

            # Keyword matching fallback/boost
            keyword_score = 0.0
            if clean_jd_text:
                matched_words = 0
                proj_words = set(re.findall(r"\w+", proj_text_lower))
                for word in proj_words:
                    if len(word) > 3 and word in clean_jd_text:
                        matched_words += 1
                keyword_score = matched_words / max(1, len(proj_words))

            text_score = (
                max(semantic_score, keyword_score)
                if semantic_score > 0
                else keyword_score
            )

            # Combined score
            composite_score = (0.5 * skill_score) + (0.5 * text_score)
            scored_projects.append((composite_score, -idx, proj))

        # Sort descending by score, tie-break by original order
        scored_projects.sort(key=lambda x: (x[0], x[1]), reverse=True)

        target_count = min(len(projects), max(2, top_k))
        return [p[2] for p in scored_projects[:target_count]]

    def generate_summary(
        self,
        user_profile: dict[str, Any],
        job_data: dict[str, Any],
        mode: str = "internship",
    ) -> str:
        """Generate a tailored summary for candidate profile grounded in real data.

        Supports 'internship' mode (learning mindset, projects, technical foundations)
        and 'job' mode (professional tone, impact, experience, technical depth).

        Args:
            user_profile: Candidate profile dictionary.
            job_data: Job listing data dictionary.
            mode: 'internship' or 'job'.

        Returns:
            Tailored professional summary string.
        """
        candidate_name = user_profile.get("name", "Candidate")
        skills = user_profile.get("skills", [])
        top_skills = skills[:5] if skills else []
        projects = user_profile.get("projects", [])
        proj_names = [
            _clean_str(p.get("name") or p.get("title"))
            for p in projects
            if _clean_str(p.get("name") or p.get("title"))
        ][:2]

        role_title = job_data.get("role_title", "target role")
        company_name = job_data.get("company_name", "target company")
        jd_skills = job_data.get("skills_required", [])

        # Attempt LLM-based generation with strict grounding prompt
        if self._llm_client:
            mode_instruction = (
                "Highlight learning mindset, hands-on academic/side projects, "
                "and strong technical foundations."
                if mode == "internship"
                else "Highlight professional tone, proven impact, technical experience, "
                "and leadership capabilities."
            )
            prompt = (
                f"Generate a concise 2-sentence professional resume summary for {candidate_name}.\n\n"
                f"Candidate Mode: {mode}\n"
                f"Candidate Verified Skills: {', '.join(top_skills)}\n"
                f"Candidate Verified Projects: {', '.join(proj_names)}\n"
                f"Target Job: {role_title} at {company_name}\n"
                f"Job Required Skills: {', '.join(jd_skills[:5])}\n\n"
                f"Guidelines:\n"
                f"- {mode_instruction}\n"
                f"- ABSOLUTE RULE: Reference ONLY skills and projects listed above. Do NOT invent new skills, experience, or achievements.\n"
                f"- Return only the summary text without markdown quotes."
            )
            try:
                response = self._llm_client.chat(prompt)
                cleaned_summary = _clean_str(response).strip('"').strip("'")
                if cleaned_summary and len(cleaned_summary) > 20:
                    return cleaned_summary
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    f"LLM summary generation failed: {e}. Falling back to template."
                )

        # Grounded template fallbacks
        skills_str = ", ".join(top_skills) if top_skills else "software engineering"
        proj_str = (
            f" featuring projects like {', '.join(proj_names)}" if proj_names else ""
        )

        if mode == "internship":
            return (
                f"Driven candidate with strong foundations in {skills_str}{proj_str}. "
                f"Possesses a quick-learning mindset and eager to contribute to {company_name} "
                f"as a {role_title}."
            )
        else:
            return (
                f"Results-driven software engineering candidate proficient in {skills_str}{proj_str}. "
                f"Brings a track record of delivering technical solutions aligned with the "
                f"{role_title} position at {company_name}."
            )

    def check_hallucination(
        self, resume_dict: dict[str, Any], user_profile: dict[str, Any]
    ) -> list[str]:
        """Validate that all skills, projects, and facts in resume exist in user profile.

        Args:
            resume_dict: Tailored resume dictionary.
            user_profile: Canonical candidate master profile dictionary.

        Returns:
            List of detected hallucination issue strings (empty [] if perfectly grounded).
        """
        hallucinations: list[str] = []

        # 1. Validate skills
        profile_skills_lower = {
            _clean_str(s).lower()
            for s in user_profile.get("skills", [])
            if _clean_str(s)
        }
        for skill in resume_dict.get("skills", []):
            clean_skill = _clean_str(skill)
            if clean_skill and clean_skill.lower() not in profile_skills_lower:
                hallucinations.append(f"Hallucinated skill: '{clean_skill}'")

        # 2. Validate projects
        profile_projects = user_profile.get("projects", [])
        profile_proj_names_lower = {
            _clean_str(p.get("name") or p.get("title")).lower()
            for p in profile_projects
            if _clean_str(p.get("name") or p.get("title"))
        }

        for proj in resume_dict.get("projects", []):
            proj_name = _clean_str(proj.get("name") or proj.get("title"))
            if proj_name and proj_name.lower() not in profile_proj_names_lower:
                hallucinations.append(f"Hallucinated project: '{proj_name}'")

        # 3. Validate experience
        profile_experience = user_profile.get("experience", [])
        profile_companies_lower = {
            _clean_str(e.get("company")).lower()
            for e in profile_experience
            if _clean_str(e.get("company"))
        }

        for exp in resume_dict.get("experience", []):
            company = _clean_str(exp.get("company"))
            if company and company.lower() not in profile_companies_lower:
                hallucinations.append(f"Hallucinated experience company: '{company}'")

        return hallucinations

    def build_resume(
        self,
        user_profile: dict[str, Any],
        job_data: dict[str, Any],
        mode: str | None = None,
    ) -> dict[str, Any]:
        """Assemble structured tailored resume from user profile and job description.

        Args:
            user_profile: Canonical candidate profile.
            job_data: Target job data.
            mode: Optional explicit mode override ('internship' vs 'job').

        Returns:
            Structured dictionary with keys: summary, skills, projects, experience, education.
        """
        selected_mode = (
            mode
            or user_profile.get("mode")
            or job_data.get("listing_type")
            or "internship"
        )

        # Prioritize skills according to JD priority
        prioritized_skills = self.prioritize_skills(
            user_skills=user_profile.get("skills", []),
            jd_skills=job_data.get("skills_required", []),
            jd_text=job_data.get("jd_text", ""),
        )

        # Select top 2 to 3 projects based on JD relevance
        selected_projects = self.select_projects(
            projects=user_profile.get("projects", []),
            jd_skills=job_data.get("skills_required", []),
            jd_text=job_data.get("jd_text", ""),
            top_k=3,
        )

        # Generate mode-specific grounded summary
        summary = self.generate_summary(
            user_profile=user_profile,
            job_data=job_data,
            mode=selected_mode,
        )

        # Format structured output
        resume: dict[str, Any] = {
            "summary": summary,
            "skills": prioritized_skills,
            "projects": selected_projects,
            "experience": user_profile.get("experience", []),
            "education": user_profile.get("education", []),
        }

        # Check for any hallucinations
        hallucinations = self.check_hallucination(resume, user_profile)
        if hallucinations:
            logger.warning(
                f"Detected potential hallucinations during build_resume: {hallucinations}"
            )

        return resume

    def tailor(
        self,
        user_id: str | uuid.UUID,
        job_id: str | uuid.UUID,
        db: Session | None = None,
        mode: str | None = None,
    ) -> dict[str, Any]:
        """End-to-end method to retrieve data and generate a tailored resume.

        Args:
            user_id: User UUID or string.
            job_id: Job UUID or string.
            db: Optional database session.
            mode: Optional mode override.

        Returns:
            Structured resume dictionary.
        """
        user_profile, job_data = self.retrieval(user_id=user_id, job_id=job_id, db=db)
        return self.build_resume(
            user_profile=user_profile, job_data=job_data, mode=mode
        )


def main() -> None:
    """CLI entrypoint for testing and comparing resume generation across jobs."""
    parser = argparse.ArgumentParser(description="HireFlow AI Resume Tailoring Engine")
    parser.add_argument("--user-id", required=True, help="User ID (UUID)")
    parser.add_argument("--job-id", help="Target Job ID (UUID)")
    parser.add_argument(
        "--compare-jobs",
        nargs=2,
        metavar=("JOB_1", "JOB_2"),
        help="Compare generated resumes for two different jobs",
    )
    parser.add_argument(
        "--mode",
        choices=["internship", "job"],
        help="Override application mode",
    )

    args = parser.parse_args()
    engine = ResumeTailoringEngine()

    if args.compare_jobs:
        job1_id, job2_id = args.compare_jobs
        res1 = engine.tailor(user_id=args.user_id, job_id=job1_id, mode=args.mode)
        res2 = engine.tailor(user_id=args.user_id, job_id=job2_id, mode=args.mode)

        print("\n=== RESUME 1 ===")
        print(json.dumps(res1, indent=2))
        print("\n=== RESUME 2 ===")
        print(json.dumps(res2, indent=2))
    elif args.job_id:
        res = engine.tailor(user_id=args.user_id, job_id=args.job_id, mode=args.mode)
        print(json.dumps(res, indent=2))
    else:
        print("Error: Must specify either --job-id or --compare-jobs")


if __name__ == "__main__":
    main()
