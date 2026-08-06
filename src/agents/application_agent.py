"""
Application Agent for HireFlow AI.

Orchestrates job application execution by loading application records,
generating grounded responses to free-text questions, executing Playwright
browser automation via FormFiller, and updating application status in DB.
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from playwright.sync_api import sync_playwright
from sqlalchemy.orm import Session

from src.automation.captcha_handler import CaptchaHandler
from src.automation.form_filler import FormFiller
from src.config.database import SessionLocal
from src.models.application import Application
from src.models.job import Job
from src.models.user import User
from src.utils.llm_client import get_llm_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exception hierarchy (Issue #15)
# ---------------------------------------------------------------------------


class ApplicationError(Exception):
    """Base class for application agent errors."""


class CaptchaDetectedError(ApplicationError):
    """Raised when a CAPTCHA challenge is detected on the page.

    This is a *permanent* failure.  The application is flagged for manual
    action; the agent must never attempt to solve CAPTCHAs.
    """


class PermanentApplicationError(ApplicationError):
    """Raised for failures that should not be retried.

    Examples:
        - Required form selector not found.
        - Unsupported or unrecognised form type.
        - Validation errors from the career portal.
        - Malformed page.
    """


class TemporaryApplicationError(ApplicationError):
    """Raised for failures that may succeed on a subsequent attempt.

    Examples:
        - Network timeout or connection reset.
        - Playwright navigation timeout.
        - Transient HTTP 5xx response.
    """


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
    """Orchestrates job application form filling, LLM integration, and status updates.

    Also implements retry logic and CAPTCHA-aware error recovery (Issue #15).

    Args:
        form_filler: Optional custom FormFiller instance.
        max_retries: Max retry attempts for temporary failures (default 3).
        retry_delay: Base sleep in seconds; actual = ``retry_delay * 2^attempt``
            (default 1).
    """

    def __init__(
        self,
        form_filler: FormFiller | None = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if retry_delay < 0:
            raise ValueError("retry_delay must be >= 0")
        self.form_filler = form_filler or FormFiller()
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.captcha_handler = CaptchaHandler()

    # ------------------------------------------------------------------
    # Issue #15: Retry + CAPTCHA-aware apply()
    # ------------------------------------------------------------------

    def apply(
        self,
        application_url: str,
        resume_path: str,
        user_profile: dict[str, Any],
        application_id: str | uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Submit a job application with exponential-backoff retry.

        Classifies failures as *temporary* (retry) or *permanent* (fail-fast).
        Never crashes the outer application run — always returns a structured
        dict regardless of outcome.

        Args:
            application_url: URL of the job application form.
            resume_path: Path to the tailored resume PDF.
            user_profile: Dict with at minimum ``name`` and ``email``.
            application_id: Optional ``Application.id`` to update in the DB.

        Returns:
            ::

                {
                    "status": "applied" | "failed" | "needs_action",
                    "failure_reason": str | None,
                    "attempts": int,
                }
        """
        logger.info(
            "ApplicationAgent.apply: starting — url=%s max_retries=%d",
            application_url,
            self.max_retries,
        )
        result = self._execute_with_retry(
            application_url=application_url,
            resume_path=resume_path,
            user_profile=user_profile,
        )
        if application_id is not None:
            self._persist_result(application_id, result)
        logger.info(
            "ApplicationAgent.apply: finished — status=%s attempts=%d",
            result["status"],
            result["attempts"],
        )
        return result

    def _execute_with_retry(
        self,
        application_url: str,
        resume_path: str,
        user_profile: dict[str, Any],
    ) -> dict[str, Any]:
        """Attempt the application with exponential-backoff retries.

        Permanent failures bypass retries immediately.  Temporary failures
        are retried up to ``self.max_retries`` times.

        Returns:
            Structured result dict (see :meth:`apply`).
        """
        last_reason: str = "Unknown error"
        total_attempts = self.max_retries + 1  # initial attempt + retries

        for attempt in range(1, total_attempts + 1):
            logger.info(
                "ApplicationAgent: attempt %d/%d for %s",
                attempt,
                total_attempts,
                application_url,
            )
            try:
                self._submit_application(
                    application_url=application_url,
                    resume_path=resume_path,
                    user_profile=user_profile,
                )
                logger.info("ApplicationAgent: application submitted successfully")
                return {
                    "status": "applied",
                    "failure_reason": None,
                    "attempts": attempt,
                }

            except CaptchaDetectedError as exc:
                reason = str(exc) or "CAPTCHA detected"
                logger.warning(
                    "ApplicationAgent: CAPTCHA detected on attempt %d — "
                    "flagging for manual action",
                    attempt,
                )
                return {
                    "status": "needs_action",
                    "failure_reason": reason,
                    "attempts": attempt,
                }

            except PermanentApplicationError as exc:
                reason = str(exc) or "Permanent failure"
                logger.error(
                    "ApplicationAgent: permanent failure on attempt %d — "
                    "not retrying: %s",
                    attempt,
                    reason,
                )
                return {
                    "status": "failed",
                    "failure_reason": reason,
                    "attempts": attempt,
                }

            except TemporaryApplicationError as exc:
                last_reason = str(exc) or "Temporary failure"
                logger.warning(
                    "ApplicationAgent: temporary failure on attempt %d: %s",
                    attempt,
                    last_reason,
                )
                if attempt < total_attempts:
                    sleep_time = self.retry_delay * (2 ** (attempt - 1))
                    logger.info(
                        "ApplicationAgent: sleeping %.1fs before retry %d/%d",
                        sleep_time,
                        attempt + 1,
                        total_attempts,
                    )
                    time.sleep(sleep_time)
                else:
                    logger.error(
                        "ApplicationAgent: exhausted all %d attempts — marking failed",
                        total_attempts,
                    )

            except Exception as exc:  # noqa: BLE001
                # Unexpected exception (e.g. NotImplementedError when Playwright
                # integration is not yet wired).  Treat as a permanent failure so
                # apply() always returns a structured result and never crashes the
                # outer application run.
                reason = f"Unexpected error: {type(exc).__name__}: {exc}"
                logger.error(
                    "ApplicationAgent: unexpected exception on attempt %d — "
                    "treating as permanent failure: %s",
                    attempt,
                    reason,
                )
                return {
                    "status": "failed",
                    "failure_reason": reason,
                    "attempts": attempt,
                }

        return {
            "status": "failed",
            "failure_reason": f"Failed after {total_attempts} attempt(s): {last_reason}",
            "attempts": total_attempts,
        }

    def _submit_application(
        self,
        application_url: str,
        resume_path: str,
        user_profile: dict[str, Any],
    ) -> None:
        """Single submission attempt — integration point for Playwright.

        Raises typed exceptions so :meth:`_execute_with_retry` can classify
        failures without inspecting strings.

        Raises:
            CaptchaDetectedError: CAPTCHA present on the page.
            PermanentApplicationError: Selector missing / unsupported form.
            TemporaryApplicationError: Timeout or transient network error.
        """
        try:
            if self.captcha_handler.detect(application_url):
                raise CaptchaDetectedError("CAPTCHA detected")
        except CaptchaDetectedError:
            raise
        except RuntimeError as exc:
            raise TemporaryApplicationError(
                f"Could not load page for CAPTCHA check: {exc}"
            ) from exc

        # Playwright form interaction (wired in Issue #14 via FormFiller).
        # Until Playwright is integrated, this raises NotImplementedError —
        # which is a known, permanent state, not an unexpected error.
        try:
            self._fill_and_submit_form(
                application_url=application_url,
                resume_path=resume_path,
                user_profile=user_profile,
            )
        except NotImplementedError as exc:
            raise PermanentApplicationError(str(exc)) from exc

    def _fill_and_submit_form(
        self,
        application_url: str,
        resume_path: str,
        user_profile: dict[str, Any],
    ) -> None:
        """Fill and submit the form via Playwright.

        Subclasses or tests override this method to inject behaviour.

        Raises:
            PermanentApplicationError: If a required selector is missing.
            TemporaryApplicationError: On Playwright/network timeouts.
        """
        raise NotImplementedError(
            "_fill_and_submit_form must be overridden by a Playwright "
            "subclass or mocked in tests."
        )

    def _persist_result(
        self,
        application_id: str | uuid.UUID,
        result: dict[str, Any],
    ) -> None:
        """Persist the terminal application status to the database.

        Args:
            application_id: The ``Application.id`` to update.
            result: Structured result dict from :meth:`_execute_with_retry`.
        """
        db = SessionLocal()
        try:
            app = (
                db.query(Application)
                .filter(Application.id == str(application_id))
                .first()
            )
            if app is None:
                logger.warning(
                    "ApplicationAgent: Application %s not found — skipping DB update",
                    application_id,
                )
                return
            old_status = app.status
            new_status = result["status"]
            reason = result.get("failure_reason")

            app.status = new_status
            if hasattr(app, "failure_reason"):
                app.failure_reason = reason
            db.commit()

            from src.utils.status_logger import log_status_change
            log_status_change(str(app.id), old_status, new_status, reason)

            logger.info(
                "ApplicationAgent: DB updated — id=%s status=%s",
                application_id,
                result["status"],
            )
        except Exception as exc:
            db.rollback()
            logger.error(
                "ApplicationAgent: DB update failed for %s: %s", application_id, exc
            )
            raise
        finally:
            db.close()

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

            # Transition to 'applying'
            old_status = application.status
            application.status = "applying"
            db.commit()
            from src.utils.status_logger import log_status_change
            log_status_change(str(application.id), old_status, "applying")

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
            old_status = application.status
            new_status = fill_result.status
            application.status = new_status
            if fill_result.status == "applied":
                application.applied_at = datetime.now(timezone.utc)
            if hasattr(application, "failure_reason"):
                application.failure_reason = fill_result.failure_reason

            db.commit()
            from src.utils.status_logger import log_status_change
            log_status_change(str(application.id), old_status, new_status, fill_result.failure_reason)

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
            # Try to persist failed state
            try:
                application = db.query(Application).filter_by(id=app_uuid).first()
                if application:
                    old_status = application.status
                    application.status = "failed"
                    application.failure_reason = f"Application orchestration exception: {e}"
                    db.commit()
                    from src.utils.status_logger import log_status_change
                    log_status_change(str(application.id), old_status, "failed", application.failure_reason)
            except Exception as persist_exc:
                logger.error(f"Failed to persist failure status on exception: {persist_exc}")

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
