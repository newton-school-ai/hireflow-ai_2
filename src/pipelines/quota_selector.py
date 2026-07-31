"""
Weekly Quota Selector and Confirmation Pipeline for HireFlow AI.

Selects top N matched jobs for a user based on weekly quota, enforcing strict filtering
(expired jobs, user blacklist, duplicate companies, already-applied companies, spam listings).
Provides job swapping capability and enforces mandatory user confirmation before downstream
resume generation or application submission can begin.
"""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from src.config.settings import settings
from src.models.application import Application
from src.models.job import Job
from src.models.user import User
from src.pipelines.match_scorer import score_all_jobs

logger = logging.getLogger(__name__)


def _safe_uuid(val: Any) -> uuid.UUID | None:
    """Safely converts input to uuid.UUID, returning None on failure."""
    if isinstance(val, uuid.UUID):
        return val
    if not val:
        return None
    try:
        return uuid.UUID(str(val))
    except (ValueError, TypeError, AttributeError):
        return None


# =============================================================================
# Custom Exceptions
# =============================================================================


class QuotaSelectorError(Exception):
    """Base exception for Quota Selector pipeline errors."""


class UserNotFoundError(QuotaSelectorError):
    """Raised when the specified user ID is not found."""


class JobNotFoundError(QuotaSelectorError):
    """Raised when a specified job ID is not found."""


class InvalidSwapError(QuotaSelectorError):
    """Raised when a job swap request fails validation."""


class PlanAlreadyConfirmedError(QuotaSelectorError):
    """Raised when attempting to modify a weekly plan that is already confirmed."""


# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class WeeklyPlanItem:
    """Represents a single job entry within a weekly plan."""

    job_id: str
    company: str
    role: str
    location: str | None
    match_score: float
    skill_gaps: list[str]
    resume_summary_placeholder: str
    application_status: str
    planned_rank: int

    def to_dict(self) -> dict[str, Any]:
        """Converts the plan item to a dictionary representation."""
        return {
            "job_id": self.job_id,
            "company": self.company,
            "role": self.role,
            "location": self.location,
            "match_score": self.match_score,
            "skill_gaps": self.skill_gaps,
            "resume_summary_placeholder": self.resume_summary_placeholder,
            "application_status": self.application_status,
            "planned_rank": self.planned_rank,
        }


@dataclass
class WeeklyPlanResult:
    """Represents the complete weekly plan response."""

    user_id: str
    weekly_quota: int
    confirmation_mode: str
    status: str  # 'planned' or 'confirmed'
    selected_jobs: list[WeeklyPlanItem] = field(default_factory=list)
    remaining_jobs: list[WeeklyPlanItem] = field(default_factory=list)
    match_scores: dict[str, float] = field(default_factory=dict)
    skill_gaps: dict[str, list[str]] = field(default_factory=dict)
    resume_summaries: dict[str, str] = field(default_factory=dict)
    downstream_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Converts the weekly plan result to a dictionary representation."""
        return {
            "user_id": self.user_id,
            "weekly_quota": self.weekly_quota,
            "confirmation_mode": self.confirmation_mode,
            "status": self.status,
            "selected_jobs": [item.to_dict() for item in self.selected_jobs],
            "remaining_jobs": [item.to_dict() for item in self.remaining_jobs],
            "match_scores": self.match_scores,
            "skill_gaps": self.skill_gaps,
            "resume_summaries": self.resume_summaries,
            "downstream_ready": self.downstream_ready,
        }


# =============================================================================
# Helper & Manager Classes
# =============================================================================


class JobFilterManager:
    """Handles filtering criteria for candidate job listings."""

    @staticmethod
    def is_expired(
        posting_date: date | datetime | str | None,
        reference_date: date | datetime | None = None,
        max_age_days: int | None = None,
    ) -> bool:
        """Determines if a job listing is older than max_age_days.

        Args:
            posting_date: Date the job was posted.
            reference_date: Current/reference date for comparison (default: today/now).
            max_age_days: Maximum allowed age in days (default from settings).

        Returns:
            True if the job is strictly older than max_age_days, False otherwise.
        """
        if posting_date is None:
            return False

        if max_age_days is None:
            max_age_days = getattr(settings, "max_job_age_days", 30)

        # Parse string date if needed
        if isinstance(posting_date, str):
            try:
                posting_date = (
                    datetime.strptime(posting_date[:10], "%Y-%m-%d")
                    .replace(tzinfo=timezone.utc)
                    .date()
                )
            except ValueError:
                return False

        if isinstance(posting_date, datetime):
            p_date = posting_date.date()
        else:
            p_date = posting_date

        if reference_date is None:
            ref_date = datetime.now(timezone.utc).date()
        elif isinstance(reference_date, datetime):
            ref_date = reference_date.date()
        else:
            ref_date = reference_date

        age_days = (ref_date - p_date).days
        return age_days > max_age_days

    @staticmethod
    def is_blacklisted(
        company_name: str | None, blacklist: list[str] | set[str] | None
    ) -> bool:
        """Checks if a company name is present in the user's blacklist (case-insensitive)."""
        if not company_name or not blacklist:
            return False

        company_clean = company_name.strip().lower()
        blacklist_clean = {
            str(b).strip().lower() for b in blacklist if b and str(b).strip()
        }
        return company_clean in blacklist_clean

    @staticmethod
    def is_already_applied(
        company_name: str | None, applied_companies: list[str] | set[str] | None
    ) -> bool:
        """Checks if the user has already applied to this company (case-insensitive)."""
        if not company_name or not applied_companies:
            return False

        company_clean = company_name.strip().lower()
        applied_clean = {
            str(a).strip().lower() for a in applied_companies if a and str(a).strip()
        }
        return company_clean in applied_clean

    @staticmethod
    def is_spam(
        is_spam: bool, spam_confidence: float = 0.0, threshold: float | None = None
    ) -> bool:
        """Checks if a job is classified as spam."""
        if threshold is None:
            threshold = getattr(settings, "spam_threshold", 0.7)
        return is_spam or (spam_confidence >= threshold)

    @classmethod
    def filter_candidate_jobs(
        cls,
        scored_jobs: list[dict[str, Any]],
        blacklist: list[str] | set[str] | None = None,
        applied_companies: list[str] | set[str] | None = None,
        reference_date: date | datetime | None = None,
        max_age_days: int | None = None,
    ) -> list[dict[str, Any]]:
        """Filters candidate jobs by removing expired, blacklisted, applied, and spam jobs.

        Args:
            scored_jobs: List of scored job objects or dictionary representations.
            blacklist: List of company names blacklisted by user.
            applied_companies: List of company names user has already applied to.
            reference_date: Reference date for age calculation.
            max_age_days: Maximum job age threshold in days.

        Returns:
            Filtered list of candidate job dicts.
        """
        filtered: list[dict[str, Any]] = []

        for item in scored_jobs:
            company = item.get("company_name") or item.get("company") or ""
            posting_date = item.get("posting_date")
            is_spam = item.get("is_spam", False)
            spam_conf = item.get("spam_confidence", 0.0)

            if cls.is_spam(is_spam, spam_conf):
                logger.debug(f"Filtering out spam job: {item.get('job_id')}")
                continue

            if cls.is_blacklisted(company, blacklist):
                logger.debug(
                    f"Filtering out blacklisted company job: {company} ({item.get('job_id')})"
                )
                continue

            if cls.is_already_applied(company, applied_companies):
                logger.debug(
                    f"Filtering out already applied company job: {company} ({item.get('job_id')})"
                )
                continue

            if cls.is_expired(posting_date, reference_date, max_age_days):
                logger.debug(
                    f"Filtering out expired job: {posting_date} ({item.get('job_id')})"
                )
                continue

            filtered.append(item)

        return filtered

    @staticmethod
    def deduplicate_companies(
        scored_jobs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Deduplicates candidate jobs so that each company appears at most once.

        Assumes input is sorted by match_score DESC, retaining the highest-scoring job
        per company.

        Args:
            scored_jobs: List of job dicts sorted by match_score descending.

        Returns:
            List of job dicts with distinct company names.
        """
        seen_companies: set[str] = set()
        deduped: list[dict[str, Any]] = []

        for item in scored_jobs:
            company = (item.get("company_name") or item.get("company") or "").strip()
            company_lower = company.lower()

            if company_lower and company_lower in seen_companies:
                logger.debug(
                    f"Filtering duplicate company job: {company} ({item.get('job_id')})"
                )
                continue

            if company_lower:
                seen_companies.add(company_lower)
            deduped.append(item)

        return deduped


class PlanRanker:
    """Handles ranking and quota selection of candidate jobs."""

    @staticmethod
    def rank_and_select(
        candidate_jobs: list[dict[str, Any]], weekly_quota: int
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Ranks jobs by match_score descending and selects the top N jobs.

        Sorts deterministically by (-match_score, job_id_string).

        Args:
            candidate_jobs: List of candidate job dicts.
            weekly_quota: Target number of jobs to select (N).

        Returns:
            Tuple of (selected_jobs, remaining_jobs).
        """
        sorted_jobs = sorted(
            candidate_jobs,
            key=lambda x: (-float(x.get("match_score", 0.0)), str(x.get("job_id"))),
        )

        selected = sorted_jobs[:weekly_quota]
        remaining = sorted_jobs[weekly_quota:]

        return selected, remaining


class PlanSwapper:
    """Handles replacing a selected job in a weekly plan with an eligible candidate job."""

    @staticmethod
    def swap_job(
        selected_jobs: list[dict[str, Any]],
        remaining_jobs: list[dict[str, Any]],
        remove_job_id: str | uuid.UUID,
        add_job_id: str | uuid.UUID,
        blacklist: list[str] | set[str] | None = None,
        applied_companies: list[str] | set[str] | None = None,
        reference_date: date | datetime | None = None,
        max_age_days: int | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Swaps remove_job_id out of selected_jobs with add_job_id from candidate pool.

        Validates that replacement exists, passes filters, is not already selected,
        and does not create a duplicate company entry among selected jobs.

        Args:
            selected_jobs: Currently selected job dicts.
            remaining_jobs: Candidate remaining job dicts.
            remove_job_id: ID of the job to remove.
            add_job_id: ID of the replacement job.
            blacklist: Optional user blacklist.
            applied_companies: Optional list of already applied companies.
            reference_date: Optional reference date for age filtering.
            max_age_days: Optional maximum age threshold.

        Returns:
            Updated tuple of (selected_jobs, remaining_jobs).

        Raises:
            InvalidSwapError: If swap validation fails.
        """
        remove_id_str = str(remove_job_id)
        add_id_str = str(add_job_id)

        # 1. Verify remove_job_id is currently selected
        target_remove_idx = None
        for idx, item in enumerate(selected_jobs):
            if str(item.get("job_id")) == remove_id_str:
                target_remove_idx = idx
                break

        if target_remove_idx is None:
            raise InvalidSwapError(
                f"Job {remove_id_str} is not currently in the selected weekly plan."
            )

        # 2. Verify add_job_id is NOT already selected
        for item in selected_jobs:
            if str(item.get("job_id")) == add_id_str:
                raise InvalidSwapError(
                    f"Job {add_id_str} is already selected in the weekly plan."
                )

        # 3. Find replacement job in remaining pool (or overall candidates)
        replacement_item = None
        replacement_idx = None
        for idx, item in enumerate(remaining_jobs):
            if str(item.get("job_id")) == add_id_str:
                replacement_item = item
                replacement_idx = idx
                break

        if replacement_item is None:
            raise InvalidSwapError(
                f"Replacement job {add_id_str} not found in available eligible jobs pool."
            )

        # 4. Validate replacement job against filters
        company = (
            replacement_item.get("company_name")
            or replacement_item.get("company")
            or ""
        )
        posting_date = replacement_item.get("posting_date")
        is_spam = replacement_item.get("is_spam", False)
        spam_conf = replacement_item.get("spam_confidence", 0.0)

        if JobFilterManager.is_spam(is_spam, spam_conf):
            raise InvalidSwapError(f"Replacement job {add_id_str} is flagged as spam.")

        if JobFilterManager.is_blacklisted(company, blacklist):
            raise InvalidSwapError(
                f"Replacement job company '{company}' is in user blacklist."
            )

        if JobFilterManager.is_already_applied(company, applied_companies):
            raise InvalidSwapError(f"User has already applied to company '{company}'.")

        if JobFilterManager.is_expired(posting_date, reference_date, max_age_days):
            raise InvalidSwapError(
                f"Replacement job {add_id_str} is older than {max_age_days or 30} days."
            )

        # 5. Validate duplicate company rule among remaining selected jobs
        company_lower = company.strip().lower()
        for idx, item in enumerate(selected_jobs):
            if idx == target_remove_idx:
                continue
            cur_company = (
                (item.get("company_name") or item.get("company") or "").strip().lower()
            )
            if company_lower and cur_company == company_lower:
                raise InvalidSwapError(
                    f"Selected plan already contains a job from company '{company}'."
                )

        # Execute Swap
        new_selected = list(selected_jobs)
        removed_job = new_selected.pop(target_remove_idx)

        new_remaining = list(remaining_jobs)
        if replacement_idx is not None:
            new_remaining.pop(replacement_idx)

        new_selected.append(replacement_item)
        new_remaining.append(removed_job)

        # Sort updated lists
        new_selected = sorted(
            new_selected,
            key=lambda x: (-float(x.get("match_score", 0.0)), str(x.get("job_id"))),
        )
        new_remaining = sorted(
            new_remaining,
            key=lambda x: (-float(x.get("match_score", 0.0)), str(x.get("job_id"))),
        )

        return new_selected, new_remaining


class DownstreamTriggerHook:
    """Interface/hook for triggering downstream processing (resume generation) after plan confirmation."""

    @staticmethod
    def on_plan_confirmed(
        user_id: str | uuid.UUID, confirmed_job_ids: list[str]
    ) -> dict[str, Any]:
        """Triggered strictly after user plan confirmation.

        Note: Does not actually generate resumes, but provides a clean hook interface
        for downstream resume tailoring & submission modules.

        Args:
            user_id: User identifier.
            confirmed_job_ids: List of confirmed job IDs ready for resume tailoring.

        Returns:
            Dictionary indicating downstream readiness state.
        """
        logger.info(
            f"Downstream hook invoked: Plan confirmed for user {user_id} "
            f"with {len(confirmed_job_ids)} jobs. Ready for resume generation."
        )
        return {
            "status": "ready",
            "user_id": str(user_id),
            "confirmed_job_ids": confirmed_job_ids,
            "resume_generation_ready": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# =============================================================================
# Main Pipeline Orchestrator
# =============================================================================


class QuotaSelectorPipeline:
    """Orchestrates weekly quota selection, job swapping, and plan confirmation."""

    def __init__(
        self,
        downstream_hook: (
            Callable[[str | uuid.UUID, list[str]], dict[str, Any]] | None
        ) = None,
    ) -> None:
        self.downstream_hook = (
            downstream_hook or DownstreamTriggerHook.on_plan_confirmed
        )

    def _get_user_blacklist(self, user: User) -> list[str]:
        """Extracts blacklist from user's master_profile dictionary."""
        if not user.master_profile or not isinstance(user.master_profile, dict):
            return []

        blacklist = user.master_profile.get("blacklist") or user.master_profile.get(
            "company_blacklist"
        )
        if isinstance(blacklist, list):
            return [str(b).strip() for b in blacklist if b]
        return []

    def _get_applied_companies(self, user_id: uuid.UUID, db: Session) -> set[str]:
        """Fetches company names user has already applied to or confirmed."""
        apps = (
            db.query(Application)
            .join(Job, Application.job_id == Job.id)
            .filter(
                Application.user_id == user_id,
                Application.status.in_(["applied", "confirmed", "resume_generated"]),
            )
            .all()
        )
        return {
            app.job.company_name.strip()
            for app in apps
            if app.job and app.job.company_name
        }

    def _build_plan_item(
        self, job_dict: dict[str, Any], rank: int, status: str = "planned"
    ) -> WeeklyPlanItem:
        """Helper to create a WeeklyPlanItem from a job dict."""
        j_id = str(job_dict.get("job_id") or job_dict.get("id"))
        company = job_dict.get("company_name") or job_dict.get("company") or "Unknown"
        role = job_dict.get("role_title") or job_dict.get("role") or "Unknown"
        location = job_dict.get("location")
        match_score = round(float(job_dict.get("match_score", 0.0)), 4)
        skill_gaps = job_dict.get("skill_gaps") or []

        resume_summary = (
            f"Tailored resume placeholder for {role} at {company} (Pending generation)"
        )

        return WeeklyPlanItem(
            job_id=j_id,
            company=company,
            role=role,
            location=location,
            match_score=match_score,
            skill_gaps=skill_gaps,
            resume_summary_placeholder=resume_summary,
            application_status=status,
            planned_rank=rank,
        )

    def generate_weekly_plan(
        self,
        user_id: str | uuid.UUID,
        db: Session,
        reference_date: date | datetime | None = None,
        candidate_jobs_override: list[dict[str, Any]] | None = None,
    ) -> WeeklyPlanResult:
        """Generates a weekly plan for the specified user.

        Args:
            user_id: User UUID or string representation.
            db: SQLAlchemy Session.
            reference_date: Optional reference date for age calculations.
            candidate_jobs_override: Optional explicit scored jobs pool (useful in unit tests).

        Returns:
            WeeklyPlanResult instance.

        Raises:
            UserNotFoundError: If user is not found.
        """
        if isinstance(user_id, str):
            try:
                u_id = uuid.UUID(user_id)
            except ValueError as e:
                raise UserNotFoundError(f"Invalid user_id format: {user_id}") from e
        else:
            u_id = user_id

        user = db.query(User).filter(User.id == u_id).first()
        if not user:
            raise UserNotFoundError(f"User with ID {user_id} not found.")

        quota = user.weekly_quota or 5
        conf_mode = user.confirmation_mode or "batch"
        blacklist = self._get_user_blacklist(user)
        applied_companies = self._get_applied_companies(u_id, db)

        # Check existing applications in DB to see if plan is already confirmed
        existing_confirmed_apps = (
            db.query(Application)
            .filter(Application.user_id == u_id, Application.status == "confirmed")
            .all()
        )
        plan_is_confirmed = len(existing_confirmed_apps) > 0

        if candidate_jobs_override is not None:
            all_scored = candidate_jobs_override
        else:
            # Score non-spam jobs using match_scorer
            all_scored = score_all_jobs(
                user_id=u_id, db=db, save_to_db=False, dry_run=True
            )
            # Decorate scored jobs with full job details
            job_map = {
                j.id: j for j in db.query(Job).filter(Job.is_spam.is_(False)).all()
            }
            for item in all_scored:
                j_obj = job_map.get(item["job_id"])
                if j_obj:
                    item["company_name"] = j_obj.company_name
                    item["role_title"] = j_obj.role_title
                    item["location"] = j_obj.location
                    item["posting_date"] = j_obj.posting_date
                    item["is_spam"] = j_obj.is_spam
                    item["spam_confidence"] = j_obj.spam_confidence

        # Filter candidate jobs
        filtered = JobFilterManager.filter_candidate_jobs(
            scored_jobs=all_scored,
            blacklist=blacklist,
            applied_companies=applied_companies,
            reference_date=reference_date,
        )

        # Deduplicate companies
        deduped = JobFilterManager.deduplicate_companies(filtered)

        # Rank and select top N
        selected_dicts, remaining_dicts = PlanRanker.rank_and_select(deduped, quota)

        current_status = "confirmed" if plan_is_confirmed else "planned"

        selected_items = [
            self._build_plan_item(item, idx + 1, status=current_status)
            for idx, item in enumerate(selected_dicts)
        ]
        remaining_items = [
            self._build_plan_item(item, len(selected_items) + idx + 1, status="matched")
            for idx, item in enumerate(remaining_dicts)
        ]

        # Sync application records to DB with status='planned' if not yet confirmed
        if not plan_is_confirmed:
            for s_item in selected_items:
                j_id_uuid = _safe_uuid(s_item.job_id)
                if j_id_uuid is None:
                    continue
                app = (
                    db.query(Application)
                    .filter(
                        Application.user_id == u_id, Application.job_id == j_id_uuid
                    )
                    .first()
                )
                if app:
                    if app.status != "confirmed":
                        app.status = "planned"
                        app.match_score = s_item.match_score
                        app.skill_gaps = s_item.skill_gaps
                else:
                    app = Application(
                        user_id=u_id,
                        job_id=j_id_uuid,
                        match_score=s_item.match_score,
                        skill_gaps=s_item.skill_gaps,
                        status="planned",
                    )
                    db.add(app)
            db.commit()

        # Build metadata maps
        match_scores = {
            item.job_id: item.match_score for item in selected_items + remaining_items
        }
        skill_gaps_map = {
            item.job_id: item.skill_gaps for item in selected_items + remaining_items
        }
        summaries_map = {
            item.job_id: item.resume_summary_placeholder
            for item in selected_items + remaining_items
        }

        return WeeklyPlanResult(
            user_id=str(u_id),
            weekly_quota=quota,
            confirmation_mode=conf_mode,
            status=current_status,
            selected_jobs=selected_items,
            remaining_jobs=remaining_items,
            match_scores=match_scores,
            skill_gaps=skill_gaps_map,
            resume_summaries=summaries_map,
            downstream_ready=plan_is_confirmed,
        )

    def swap_job(
        self,
        user_id: str | uuid.UUID,
        remove_job_id: str | uuid.UUID,
        add_job_id: str | uuid.UUID,
        db: Session,
        reference_date: date | datetime | None = None,
        candidate_jobs_override: list[dict[str, Any]] | None = None,
    ) -> WeeklyPlanResult:
        """Replaces one selected job in the user's plan with another eligible job.

        Args:
            user_id: Target user ID.
            remove_job_id: ID of job to remove.
            add_job_id: ID of replacement job.
            db: SQLAlchemy Session.
            reference_date: Optional reference date.
            candidate_jobs_override: Optional candidate pool override.

        Returns:
            Updated WeeklyPlanResult.

        Raises:
            UserNotFoundError, InvalidSwapError, PlanAlreadyConfirmedError
        """
        current_plan = self.generate_weekly_plan(
            user_id=user_id,
            db=db,
            reference_date=reference_date,
            candidate_jobs_override=candidate_jobs_override,
        )

        if current_plan.status == "confirmed":
            raise PlanAlreadyConfirmedError(
                "Cannot swap jobs on an already confirmed weekly plan."
            )

        u_id = uuid.UUID(str(user_id))
        user = db.query(User).filter(User.id == u_id).first()
        if not user:
            raise UserNotFoundError(f"User with ID {user_id} not found.")

        blacklist = self._get_user_blacklist(user)
        applied_companies = self._get_applied_companies(u_id, db)

        selected_dicts = [item.to_dict() for item in current_plan.selected_jobs]
        remaining_dicts = [item.to_dict() for item in current_plan.remaining_jobs]

        # Preserve posting_date and is_spam metadata if override or DB jobs present
        job_metadata: dict[str, dict[str, Any]] = {}
        if candidate_jobs_override:
            for item in candidate_jobs_override:
                j_id = str(item.get("job_id") or item.get("id"))
                job_metadata[j_id] = item
        else:
            all_jobs = db.query(Job).all()
            for j in all_jobs:
                job_metadata[str(j.id)] = {
                    "posting_date": j.posting_date,
                    "is_spam": j.is_spam,
                    "spam_confidence": j.spam_confidence,
                    "company_name": j.company_name,
                    "role_title": j.role_title,
                    "location": j.location,
                }

        for item in selected_dicts + remaining_dicts:
            j_id = item["job_id"]
            if j_id in job_metadata:
                item.update(job_metadata[j_id])

        new_selected_dicts, new_remaining_dicts = PlanSwapper.swap_job(
            selected_jobs=selected_dicts,
            remaining_jobs=remaining_dicts,
            remove_job_id=remove_job_id,
            add_job_id=add_job_id,
            blacklist=blacklist,
            applied_companies=applied_companies,
            reference_date=reference_date,
        )

        # Update DB application records
        rem_uuid = _safe_uuid(remove_job_id)
        if rem_uuid:
            rem_app = (
                db.query(Application)
                .filter(
                    Application.user_id == u_id,
                    Application.job_id == rem_uuid,
                )
                .first()
            )
            if rem_app and rem_app.status == "planned":
                rem_app.status = "matched"

        # Set added app to 'planned'
        add_uuid = _safe_uuid(add_job_id)
        if add_uuid:
            add_app = (
                db.query(Application)
                .filter(Application.user_id == u_id, Application.job_id == add_uuid)
                .first()
            )
            if add_app:
                add_app.status = "planned"
            else:
                # find match score from new_selected_dicts
                add_score = 0.0
                add_gaps = []
                for item in new_selected_dicts:
                    if str(item.get("job_id")) == str(add_job_id):
                        add_score = item.get("match_score", 0.0)
                        add_gaps = item.get("skill_gaps", [])
                        break
                add_app = Application(
                    user_id=u_id,
                    job_id=add_uuid,
                    match_score=add_score,
                    skill_gaps=add_gaps,
                    status="planned",
                )
                db.add(add_app)

        db.commit()

        # Build items
        selected_items = [
            self._build_plan_item(item, idx + 1, status="planned")
            for idx, item in enumerate(new_selected_dicts)
        ]
        remaining_items = [
            self._build_plan_item(item, len(selected_items) + idx + 1, status="matched")
            for idx, item in enumerate(new_remaining_dicts)
        ]

        match_scores = {
            item.job_id: item.match_score for item in selected_items + remaining_items
        }
        skill_gaps_map = {
            item.job_id: item.skill_gaps for item in selected_items + remaining_items
        }
        summaries_map = {
            item.job_id: item.resume_summary_placeholder
            for item in selected_items + remaining_items
        }

        return WeeklyPlanResult(
            user_id=str(u_id),
            weekly_quota=user.weekly_quota or 5,
            confirmation_mode=user.confirmation_mode or "batch",
            status="planned",
            selected_jobs=selected_items,
            remaining_jobs=remaining_items,
            match_scores=match_scores,
            skill_gaps=skill_gaps_map,
            resume_summaries=summaries_map,
            downstream_ready=False,
        )

    def confirm_weekly_plan(
        self,
        user_id: str | uuid.UUID,
        db: Session,
        confirmed_job_ids: list[str] | None = None,
        removed_job_ids: list[str] | None = None,
        candidate_jobs_override: list[dict[str, Any]] | None = None,
    ) -> WeeklyPlanResult:
        """Confirms the weekly plan for a user and triggers downstream process readiness.

        Args:
            user_id: Target user ID.
            db: SQLAlchemy Session.
            confirmed_job_ids: Optional explicit subset of job IDs to confirm.
            removed_job_ids: Optional explicit subset of job IDs to remove.
            candidate_jobs_override: Optional candidate pool override.

        Returns:
            Confirmed WeeklyPlanResult.
        """
        current_plan = self.generate_weekly_plan(
            user_id=user_id,
            db=db,
            candidate_jobs_override=candidate_jobs_override,
        )

        u_id = uuid.UUID(str(user_id))

        if confirmed_job_ids is None or len(confirmed_job_ids) == 0:
            target_confirm_ids = [item.job_id for item in current_plan.selected_jobs]
        else:
            target_confirm_ids = [str(j) for j in confirmed_job_ids]

        if removed_job_ids:
            removed_set = {str(j) for j in removed_job_ids}
            target_confirm_ids = [j for j in target_confirm_ids if j not in removed_set]

        # Update DB application status to 'confirmed'
        for j_id_str in target_confirm_ids:
            try:
                j_uuid = uuid.UUID(j_id_str)
                app = (
                    db.query(Application)
                    .filter(Application.user_id == u_id, Application.job_id == j_uuid)
                    .first()
                )
                if app:
                    app.status = "confirmed"
                else:
                    app = Application(
                        user_id=u_id,
                        job_id=j_uuid,
                        status="confirmed",
                    )
                    db.add(app)
            except ValueError:
                continue

        db.commit()

        # Execute downstream hook
        self.downstream_hook(str(u_id), target_confirm_ids)

        # Build response
        confirmed_selected_items: list[WeeklyPlanItem] = []
        for item in current_plan.selected_jobs:
            if item.job_id in target_confirm_ids:
                item.application_status = "confirmed"
                confirmed_selected_items.append(item)

        current_plan.status = "confirmed"
        current_plan.selected_jobs = confirmed_selected_items
        current_plan.downstream_ready = True

        return current_plan
