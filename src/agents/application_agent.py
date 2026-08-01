"""
Application Agent for HireFlow AI.

Orchestrates job application execution by loading application records,
generating grounded responses to free-text questions, executing Playwright
browser automation via FormFiller, and updating application status in DB.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from playwright.sync_api import sync_playwright
from sqlalchemy.orm import Session

from src.automation.form_filler import FormFiller
from src.config.database import SessionLocal
from src.models.application import Application
from src.models.job import Job
from src.models.user import User
from src.utils.llm_client import get_llm_client

logger = logging.getLogger(__name__)


@dataclass
class ApplicationResult:
    """Outcome of an application submission attempt.

    Attributes:
        application_id: UUID string of the application record.
        status: Final application status ('applied', 'failed', or 'needs_action').
        failure_reason: Explanation if status != 'applied'.
        metadata: Operational details and metrics.
    """

    application_id: str
    status: str
    failure_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ApplicationAgent:
    """Orchestrates job application form filling, LLM integration, and status updates."""

    def __init__(self, form_filler: FormFiller | None = None) -> None:
        self.form_filler = form_filler or FormFiller()

    # ------------------------------------------------------------------
    # LLM Question Answering
    # ------------------------------------------------------------------

    def generate_free_text_answer(
        self,
        question: str,
        user_profile: dict[str, Any],
        job_info: dict[str, Any],
        resume_path: str | None = None,
    ) -> str:
        """Generate a grounded answer to a free-text application question using LLM client.

        Args:
            question: Question string (e.g. 'Why should we hire you?').
            user_profile: Candidate master profile dict.
            job_info: Job metadata (role_title, company_name, jd_text).
            resume_path: Optional path to resume PDF.

        Returns:
            Grounded text response without hallucination.
        """
        role_title = job_info.get("role_title", "the role")
        company_name = job_info.get("company_name", "the company")
        jd_snippet = (job_info.get("jd_text") or "")[:1000]

        prompt = (
            "You are an AI assistant helping a candidate apply for a job.\n"
            "Construct a concise, compelling answer to the application question based STRICTLY "
            "on the candidate profile and job description provided below.\n\n"
            "CRITICAL CONSTRAINTS:\n"
            "1. Do NOT fabricate experience, skills, or achievements not present in the profile.\n"
            "2. Keep response focused and professional (2-4 sentences).\n\n"
            f"Question: {question}\n\n"
            f"Target Role: {role_title}\n"
            f"Target Company: {company_name}\n"
            f"Job Description Snippet: {jd_snippet}\n\n"
            f"Candidate Profile: {user_profile}\n\n"
            "Answer:"
        )

        try:
            llm = get_llm_client()
            answer = llm.chat(prompt)
            if answer and answer.strip():
                return answer.strip()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"LLM answer generation failed or unconfigured: {e}")

        # Fallback grounded answer
        skills = user_profile.get("skills", [])
        skills_str = (
            ", ".join(skills[:5])
            if isinstance(skills, list) and skills
            else "my technical background"
        )
        return (
            f"I am eager to contribute to {company_name} as a {role_title}. "
            f"With my experience in {skills_str}, I bring strong problem-solving skills "
            f"and dedication to delivering high-quality work."
        )

    def prepare_user_data(self, user: User, application: Application) -> dict[str, Any]:
        """Construct user details dictionary for form filling."""
        profile = user.master_profile or {}
        user_data = {
            "name": user.name,
            "full_name": user.name,
            "email": user.email,
            "phone": profile.get("phone") or profile.get("phone_number") or "",
            "location": profile.get("location") or profile.get("city") or "",
            "linkedin": profile.get("linkedin") or profile.get("linkedin_url") or "",
            "github": profile.get("github") or profile.get("github_url") or "",
            "portfolio": profile.get("portfolio") or profile.get("portfolio_url") or "",
            "education": profile.get("education") or profile.get("degree") or "",
            "experience": profile.get("experience")
            or profile.get("years_experience")
            or "",
            "skills": profile.get("skills") or [],
        }
        return user_data

    # ------------------------------------------------------------------
    # Core Application Orchestration
    # ------------------------------------------------------------------

    def apply_for_job(
        self,
        application_id: uuid.UUID | str,
        db_session: Session | None = None,
        custom_page: Any = None,
    ) -> ApplicationResult:
        """Orchestrate form filling and status update for a given application ID.

        Args:
            application_id: UUID of the application record.
            db_session: Optional external SQLAlchemy Session.
            custom_page: Optional pre-configured Playwright Page (for testing).

        Returns:
            ApplicationResult object detailing outcome status and metadata.
        """
        app_uuid = uuid.UUID(str(application_id))
        db = db_session or SessionLocal()
        close_db = db_session is None

        try:
            # 1. Load DB Records
            application = db.query(Application).filter_by(id=app_uuid).first()
            if not application:
                return ApplicationResult(
                    application_id=str(app_uuid),
                    status="failed",
                    failure_reason=f"Application record not found for ID {app_uuid}",
                )

            user = db.query(User).filter_by(id=application.user_id).first()
            job = db.query(Job).filter_by(id=application.job_id).first()

            if not user or not job:
                return ApplicationResult(
                    application_id=str(app_uuid),
                    status="failed",
                    failure_reason="Associated user or job record missing in database.",
                )

            logger.info(
                f"Orchestrating application ID {app_uuid} for job URL: {job.application_url}"
            )

            user_data = self.prepare_user_data(user, application)
            job_info = {
                "role_title": job.role_title,
                "company_name": job.company_name,
                "jd_text": job.jd_text,
                "application_url": job.application_url,
            }

            # 2. Prepare Free Text Answers
            free_text_answers = {
                "why_should_we_hire_you": self.generate_free_text_answer(
                    "Why should we hire you?",
                    user.master_profile or {},
                    job_info,
                    application.resume_path,
                ),
                "tell_us_about_yourself": self.generate_free_text_answer(
                    "Tell us about yourself",
                    user.master_profile or {},
                    job_info,
                    application.resume_path,
                ),
            }

            # 3. Execute Browser Automation
            fill_result = self._run_browser_automation(
                url=job.application_url,
                user_data=user_data,
                resume_path=application.resume_path,
                free_text_answers=free_text_answers,
                custom_page=custom_page,
            )

            # 4. Update DB Application Record
            application.status = fill_result.status
            if fill_result.status == "applied":
                application.applied_at = datetime.now(timezone.utc)

            db.commit()
            logger.info(
                f"Successfully updated application ID {app_uuid} status to '{fill_result.status}'."
            )

            return ApplicationResult(
                application_id=str(app_uuid),
                status=fill_result.status,
                failure_reason=fill_result.failure_reason,
                metadata=fill_result.metadata,
            )

        except Exception as e:
            if db:
                db.rollback()
            logger.exception(
                f"Error during application orchestration for ID {app_uuid}."
            )
            return ApplicationResult(
                application_id=str(app_uuid),
                status="failed",
                failure_reason=f"Application orchestration exception: {e}",
            )
        finally:
            if close_db and db:
                db.close()

    def _run_browser_automation(
        self,
        url: str,
        user_data: dict[str, Any],
        resume_path: str | None,
        free_text_answers: dict[str, str],
        custom_page: Any = None,
    ) -> Any:
        """Run FormFiller on page, closing browser resources when finished."""
        if custom_page:
            # Use injected page (e.g. for unit testing with local HTML fixture)
            if (
                url
                and not custom_page.url.startswith("file://")
                and custom_page.url != url
            ):
                try:
                    custom_page.goto(url)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"Could not navigate custom page to {url}: {e}")
            return self.form_filler.fill_and_submit(
                page=custom_page,
                user_data=user_data,
                resume_path=resume_path,
                free_text_answers=free_text_answers,
            )

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                result = self.form_filler.fill_and_submit(
                    page=page,
                    user_data=user_data,
                    resume_path=resume_path,
                    free_text_answers=free_text_answers,
                )
                return result
            finally:
                context.close()
                browser.close()
