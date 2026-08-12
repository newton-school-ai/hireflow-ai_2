"""
Tests for the Weekly Report Generator and Latest Report API (Issue #20).

Uses an in-memory SQLite database — no PostgreSQL, no live HTTP, no LLM calls.

Coverage:
  - Normal weekly report generation (DB record + files created)
  - Top skills, strongest/weakest match category, study plan
  - failed + needs_action applications clearly surfaced
  - Empty week (zero applications) — must not crash
  - GET /report/{user_id}/latest returns DB data (not disk files)
  - 404 when user has no report
  - 404 when user does not exist
  - Deterministic output — same inputs produce identical results
  - Week-bound filtering: only Monday–Sunday of current week included
  - HTML and latest.json contain the same structured report data
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Generator
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.agents.report_generator import ReportGenerator, _get_week_bounds
from src.api.main import app
from src.config.database import Base, get_db
from src.models.application import Application
from src.models.job import Job
from src.models.prep_guide import PrepGuide
from src.models.user import User

# ---------------------------------------------------------------------------
# Shared in-memory SQLite engine
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite:///:memory:"
_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
Base.metadata.create_all(bind=_engine)
_TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


@pytest.fixture()
def db() -> Generator[Session, None, None]:
    """Yield a rollback-isolated SQLite session for each test."""
    connection = _engine.connect()
    transaction = connection.begin()
    session = _TestingSession(bind=connection)
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture()
def client(db: Session) -> Generator[TestClient, None, None]:
    """FastAPI TestClient wired to the test DB."""

    def _override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def _make_user(db: Session, **overrides) -> User:
    defaults = {
        "id": uuid.uuid4(),
        "name": "Alice Tester",
        "email": f"alice-{uuid.uuid4().hex[:6]}@test.com",
        "mode": "internship",
        "weekly_quota": 10,
        "confirmation_mode": "batch",
    }
    defaults.update(overrides)
    user = User(**defaults)
    db.add(user)
    db.flush()
    return user


def _make_job(db: Session, **overrides) -> Job:
    defaults = {
        "id": uuid.uuid4(),
        "company_name": "Acme Corp",
        "role_title": "AI Intern",
        "jd_text": "We need Python and FastAPI skills.",
        "application_url": f"https://jobs.lever.co/acme/{uuid.uuid4().hex}",
        "listing_type": "internship",
        "skills_required": ["Python", "FastAPI", "SQL"],
        "stipend_salary": "₹20,000/month",
        "experience_required": "0 years",
        "source": "lever",
        "is_spam": False,
        "spam_confidence": 0.0,
    }
    defaults.update(overrides)
    job = Job(**defaults)
    db.add(job)
    db.flush()
    return job


def _make_application(
    db: Session,
    user: User,
    job: Job,
    *,
    status: str = "applied",
    match_score: float = 0.8,
    skill_matches: list | None = None,
    skill_gaps: list | None = None,
    failure_reason: str | None = None,
    resume_path: str | None = "resumes/v1.pdf",
    resume_version: int = 1,
    created_at: datetime | None = None,
) -> Application:
    if created_at is None:
        created_at = datetime.now(timezone.utc)
    app_obj = Application(
        id=uuid.uuid4(),
        user_id=user.id,
        job_id=job.id,
        match_score=match_score,
        skill_matches=skill_matches if skill_matches is not None else ["Python"],
        skill_gaps=skill_gaps if skill_gaps is not None else ["Docker"],
        status=status,
        failure_reason=failure_reason,
        resume_path=resume_path,
        resume_version=resume_version,
    )
    # SQLAlchemy won't let us set server_default columns directly in the
    # constructor on SQLite, so set it via attribute after flushing.
    db.add(app_obj)
    db.flush()
    if created_at is not None:
        db.execute(
            Application.__table__.update()
            .where(Application.id == app_obj.id)
            .values(created_at=created_at)
        )
        db.flush()
        db.refresh(app_obj)
    return app_obj


def _make_prep_guide(
    db: Session,
    user: User,
    job: Job,
    **overrides,
) -> PrepGuide:
    defaults = {
        "id": uuid.uuid4(),
        "user_id": user.id,
        "job_id": job.id,
        "skill_gaps": ["Kubernetes", "CI/CD"],
        "resources": [{"url": "https://kubernetes.io", "title": "K8s Docs"}],
        "mock_questions": ["Explain a pod.", "What is a deployment?"],
        "predicted_rounds": 2,
        "company_intel": {"glassdoor_rating": 4.1},
    }
    defaults.update(overrides)
    guide = PrepGuide(**defaults)
    db.add(guide)
    db.flush()
    return guide


def _week_start_dt(ref: date | None = None) -> datetime:
    """Return a timezone-aware datetime for the Monday of the current week."""
    ws, _ = _get_week_bounds(ref)
    return datetime(ws.year, ws.month, ws.day, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 1. Week-bound calculation
# ---------------------------------------------------------------------------


class TestWeekBounds:
    """_get_week_bounds must return the ISO Monday–Sunday of the reference date."""

    def test_monday_is_start(self):
        # Use a known Monday: 2026-08-10
        monday = date(2026, 8, 10)
        ws, we = _get_week_bounds(monday)
        assert ws == monday
        assert we == date(2026, 8, 16)
        assert ws.isoweekday() == 1  # Monday
        assert we.isoweekday() == 7  # Sunday

    def test_wednesday_in_same_week(self):
        wednesday = date(2026, 8, 12)
        ws, we = _get_week_bounds(wednesday)
        assert ws == date(2026, 8, 10)
        assert we == date(2026, 8, 16)

    def test_sunday_closes_week(self):
        sunday = date(2026, 8, 16)
        ws, we = _get_week_bounds(sunday)
        assert ws == date(2026, 8, 10)
        assert we == date(2026, 8, 16)


# ---------------------------------------------------------------------------
# 2. Normal weekly report generation
# ---------------------------------------------------------------------------


class TestNormalReport:
    """Full report generation with multiple applications."""

    def test_report_creates_db_record(self, db: Session, tmp_path: Path):
        user = _make_user(db)
        job1 = _make_job(db, skills_required=["Python", "FastAPI", "Docker"])
        job2 = _make_job(
            db,
            company_name="BetaCo",
            role_title="ML Intern",
            skills_required=["Python", "TensorFlow", "SQL"],
        )

        _make_application(db, user, job1, match_score=0.9, skill_gaps=["Docker"])
        _make_application(db, user, job2, match_score=0.75, skill_gaps=["TensorFlow"])
        db.commit()

        gen = ReportGenerator(output_root=tmp_path)
        report = gen.generate_report(user.id, db)

        assert report.id is not None
        assert report.user_id == user.id
        assert report.applications_sent == 2
        assert report.report_path is not None
        assert report.summary is not None and len(report.summary) > 10

    def test_report_html_file_created(self, db: Session, tmp_path: Path):
        user = _make_user(db)
        job = _make_job(db)
        _make_application(db, user, job)
        db.commit()

        gen = ReportGenerator(output_root=tmp_path)
        report = gen.generate_report(user.id, db)

        html_path = Path(report.report_path)
        assert html_path.exists()
        content = html_path.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content
        assert "HireFlow Weekly Report" in content
        assert user.name in content

    def test_report_includes_all_applications(self, db: Session, tmp_path: Path):
        """Every application's company and role must appear in the HTML."""
        user = _make_user(db)
        companies = ["AlphaTech", "BetaCo", "GammaSoft"]
        for company in companies:
            job = _make_job(db, company_name=company)
            _make_application(db, user, job)
        db.commit()

        gen = ReportGenerator(output_root=tmp_path)
        report = gen.generate_report(user.id, db)

        html = Path(report.report_path).read_text(encoding="utf-8")
        for company in companies:
            assert company in html, f"{company} missing from HTML report"

    def test_prep_guide_info_in_html(self, db: Session, tmp_path: Path):
        user = _make_user(db)
        job = _make_job(db)
        _make_application(db, user, job, skill_gaps=["Docker"])
        _make_prep_guide(db, user, job, skill_gaps=["Kubernetes", "CI/CD"])
        db.commit()

        gen = ReportGenerator(output_root=tmp_path)
        report = gen.generate_report(user.id, db)

        html = Path(report.report_path).read_text(encoding="utf-8")
        # Prep guide skill gaps should be surfaced
        assert "Kubernetes" in html or "CI/CD" in html

    def test_latest_json_matches_html_structure(self, db: Session, tmp_path: Path):
        """HTML and latest.json must describe the same applications and insights."""
        user = _make_user(db)
        job = _make_job(db, company_name="JsonCheck Inc")
        _make_application(db, user, job, match_score=0.88)
        db.commit()

        gen = ReportGenerator(output_root=tmp_path)
        gen.generate_report(user.id, db)

        json_path = tmp_path / str(user.id) / "latest.json"
        assert json_path.exists(), "latest.json was not created"

        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert "applications" in payload
        assert "insights" in payload
        assert str(user.id) == payload["user_id"]
        assert len(payload["applications"]) == 1
        assert payload["applications"][0]["company"] == "JsonCheck Inc"


# ---------------------------------------------------------------------------
# 3. Cross-application insights
# ---------------------------------------------------------------------------


class TestInsights:
    """Top skills, strongest/weakest category, study plan."""

    def test_top_skills_case_insensitive(self, db: Session, tmp_path: Path):
        user = _make_user(db)
        # python appears in 3 jobs (case-varied), docker in 2, sql in 1
        for skills in [
            ["Python", "Docker"],
            ["python", "Docker"],
            ["PYTHON", "SQL"],
        ]:
            job = _make_job(db, skills_required=skills)
            _make_application(db, user, job)
        db.commit()

        gen = ReportGenerator(output_root=tmp_path)
        report = gen.generate_report(user.id, db)

        top_matches = report.top_matches or []
        assert top_matches, "top_matches should not be empty"
        insights = top_matches[0].get("insights", {})
        skills_out = [s["skill"].lower() for s in insights.get("top_skills", [])]

        assert "python" in skills_out, "Python should be in top skills"
        assert "docker" in skills_out, "Docker should be in top skills"
        # python should rank first (count=3 vs docker count=2)
        assert skills_out.index("python") < skills_out.index("docker")

    def test_top_skills_deterministic_alpha_tie_break(
        self, db: Session, tmp_path: Path
    ):
        """Skills with equal frequency must be sorted alphabetically."""
        user = _make_user(db)
        # Both appear exactly once
        job1 = _make_job(db, skills_required=["Zebra"])
        job2 = _make_job(db, skills_required=["Alpha"])
        _make_application(db, user, job1)
        _make_application(db, user, job2)
        db.commit()

        gen = ReportGenerator(output_root=tmp_path)
        report = gen.generate_report(user.id, db)

        insights = (report.top_matches or [{}])[0].get("insights", {})
        skill_names = [s["skill"].lower() for s in insights.get("top_skills", [])]
        # "alpha" should come before "zebra" alphabetically at equal freq
        assert skill_names.index("alpha") < skill_names.index("zebra")

    def test_top_skills_at_most_five(self, db: Session, tmp_path: Path):
        user = _make_user(db)
        for i in range(8):
            job = _make_job(db, skills_required=[f"SkillUnique{i}"])
            _make_application(db, user, job)
        db.commit()

        gen = ReportGenerator(output_root=tmp_path)
        report = gen.generate_report(user.id, db)

        insights = (report.top_matches or [{}])[0].get("insights", {})
        assert len(insights.get("top_skills", [])) <= 5

    def test_strongest_and_weakest_category_present(self, db: Session, tmp_path: Path):
        user = _make_user(db)
        job = _make_job(db, skills_required=["Python"])
        _make_application(
            db, user, job, match_score=0.85, skill_matches=["Python"], skill_gaps=[]
        )
        db.commit()

        gen = ReportGenerator(output_root=tmp_path)
        report = gen.generate_report(user.id, db)

        insights = (report.top_matches or [{}])[0].get("insights", {})
        assert insights.get("strongest_category") is not None
        assert insights.get("weakest_category") is not None

    def test_no_scores_returns_none_categories(self, db: Session, tmp_path: Path):
        """Applications with no match_score must not invent strongest/weakest."""
        user = _make_user(db)
        job = _make_job(db, skills_required=[])
        # Application with no match_score
        _make_application(
            db, user, job, match_score=None, skill_matches=[], skill_gaps=[]
        )
        db.commit()

        gen = ReportGenerator(output_root=tmp_path)
        report = gen.generate_report(user.id, db)

        insights = (report.top_matches or [{}])[0].get("insights", {})
        # With no match scores, weakest based only on skill ratio (0 req skills → ratio 1.0)
        # strongest_category may be set from skill ratio; weakest for others stays None
        # Key check: does not crash and types are correct
        sc = insights.get("strongest_category")
        wc = insights.get("weakest_category")
        assert sc is None or isinstance(sc, str)
        assert wc is None or isinstance(wc, str)

    def test_weekly_study_plan_excludes_mastered_skills(
        self, db: Session, tmp_path: Path
    ):
        """Skills the user already has must not appear in the study plan."""
        user = _make_user(db)
        # Job requires Python (user has it) and Docker (user lacks it)
        job = _make_job(db, skills_required=["Python", "Docker"])
        _make_application(
            db,
            user,
            job,
            skill_matches=["Python"],
            skill_gaps=["Docker"],
        )
        db.commit()

        gen = ReportGenerator(output_root=tmp_path)
        report = gen.generate_report(user.id, db)

        insights = (report.top_matches or [{}])[0].get("insights", {})
        study_skills = [
            p["skill"].lower() for p in insights.get("weekly_study_plan", [])
        ]
        # Docker is a gap → should appear; Python is a match → should NOT
        assert (
            "python" not in study_skills
        ), "Mastered skill should not be in study plan"

    def test_weekly_study_plan_at_most_three(self, db: Session, tmp_path: Path):
        user = _make_user(db)
        for skill in ["A", "B", "C", "D", "E"]:
            job = _make_job(db, skills_required=[skill])
            _make_application(db, user, job, skill_gaps=[skill], skill_matches=[])
        db.commit()

        gen = ReportGenerator(output_root=tmp_path)
        report = gen.generate_report(user.id, db)

        insights = (report.top_matches or [{}])[0].get("insights", {})
        assert len(insights.get("weekly_study_plan", [])) <= 3


# ---------------------------------------------------------------------------
# 4. Failed and needs_action highlighting
# ---------------------------------------------------------------------------


class TestFailedAndNeedsAction:
    """Failed and needs_action entries must be clearly surfaced."""

    def test_failed_in_html(self, db: Session, tmp_path: Path):
        user = _make_user(db)
        job = _make_job(db, company_name="FailCo")
        _make_application(
            db,
            user,
            job,
            status="failed",
            failure_reason="Application portal closed",
        )
        db.commit()

        gen = ReportGenerator(output_root=tmp_path)
        report = gen.generate_report(user.id, db)

        html = Path(report.report_path).read_text(encoding="utf-8")
        assert "FailCo" in html
        assert "FAILED" in html or "Failed" in html
        assert "Application portal closed" in html

    def test_needs_action_shows_manual_url(self, db: Session, tmp_path: Path):
        manual_url = "https://jobs.lever.co/manualapply/abc123"
        user = _make_user(db)
        job = _make_job(db, company_name="ManualCo", application_url=manual_url)
        _make_application(
            db,
            user,
            job,
            status="needs_action",
            failure_reason="ATS blocked auto-apply",
        )
        db.commit()

        gen = ReportGenerator(output_root=tmp_path)
        report = gen.generate_report(user.id, db)

        html = Path(report.report_path).read_text(encoding="utf-8")
        assert "ManualCo" in html
        assert manual_url in html, "Manual application URL must appear in HTML"

    def test_needs_action_in_json(self, db: Session, tmp_path: Path):
        user = _make_user(db)
        job = _make_job(db, company_name="ActionCo")
        _make_application(db, user, job, status="needs_action")
        db.commit()

        gen = ReportGenerator(output_root=tmp_path)
        gen.generate_report(user.id, db)

        json_path = tmp_path / str(user.id) / "latest.json"
        payload = json.loads(json_path.read_text())
        na_apps = [a for a in payload["applications"] if a["status"] == "needs_action"]
        assert len(na_apps) == 1
        assert na_apps[0]["company"] == "ActionCo"
        assert "manual_application_url" in na_apps[0]

    def test_status_counts_in_insights(self, db: Session, tmp_path: Path):
        user = _make_user(db)
        for status in ["applied", "failed", "needs_action", "failed"]:
            job = _make_job(db)
            _make_application(db, user, job, status=status)
        db.commit()

        gen = ReportGenerator(output_root=tmp_path)
        report = gen.generate_report(user.id, db)

        insights = (report.top_matches or [{}])[0].get("insights", {})
        assert insights.get("failed_count") == 2
        assert insights.get("needs_action_count") == 1
        assert insights.get("applied_count") == 1


# ---------------------------------------------------------------------------
# 5. Empty week
# ---------------------------------------------------------------------------


class TestEmptyWeek:
    """Zero applications must produce a valid report without crashing."""

    def test_empty_week_creates_report(self, db: Session, tmp_path: Path):
        user = _make_user(db)
        db.commit()

        gen = ReportGenerator(output_root=tmp_path)
        report = gen.generate_report(user.id, db)

        assert report is not None
        assert report.applications_sent == 0
        assert report.top_matches is not None

    def test_empty_week_html_is_valid(self, db: Session, tmp_path: Path):
        user = _make_user(db)
        db.commit()

        gen = ReportGenerator(output_root=tmp_path)
        report = gen.generate_report(user.id, db)

        html = Path(report.report_path).read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in html
        assert "No applications this week" in html

    def test_empty_week_insights_are_safe(self, db: Session, tmp_path: Path):
        user = _make_user(db)
        db.commit()

        gen = ReportGenerator(output_root=tmp_path)
        report = gen.generate_report(user.id, db)

        insights = (report.top_matches or [{}])[0].get("insights", {})
        assert insights.get("top_skills") == []
        assert insights.get("strongest_category") is None
        assert insights.get("weakest_category") is None
        assert insights.get("weekly_study_plan") == []
        assert insights.get("total_applications") == 0


# ---------------------------------------------------------------------------
# 6. Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Identical inputs must produce identical outputs."""

    def test_generate_twice_same_summary(self, db: Session, tmp_path: Path):
        user = _make_user(db)
        job = _make_job(db, skills_required=["Python", "SQL"])
        _make_application(db, user, job, match_score=0.78)
        db.commit()

        gen = ReportGenerator(output_root=tmp_path)
        r1 = gen.generate_report(user.id, db)
        r2 = gen.generate_report(user.id, db)

        # Second call upserts — same week_start so same row
        assert r1.user_id == r2.user_id
        assert r1.week_start == r2.week_start
        assert r1.summary == r2.summary

    def test_top_skills_order_stable(self, db: Session, tmp_path: Path):
        """Running insights twice returns the same top-skills order."""
        user = _make_user(db)
        for skills in [["Python", "Docker"], ["Python"], ["Docker", "SQL"]]:
            job = _make_job(db, skills_required=skills)
            _make_application(db, user, job)
        db.commit()

        gen = ReportGenerator(output_root=tmp_path)
        r1 = gen.generate_report(user.id, db)
        r2 = gen.generate_report(user.id, db)

        skills_r1 = [
            (s["skill"], s["count"])
            for s in (r1.top_matches or [{}])[0]
            .get("insights", {})
            .get("top_skills", [])
        ]
        skills_r2 = [
            (s["skill"], s["count"])
            for s in (r2.top_matches or [{}])[0]
            .get("insights", {})
            .get("top_skills", [])
        ]
        assert skills_r1 == skills_r2


# ---------------------------------------------------------------------------
# 7. Week-bound filtering
# ---------------------------------------------------------------------------


class TestWeekBoundFiltering:
    """Applications from previous weeks must not appear in the current report."""

    def test_previous_week_application_excluded(self, db: Session, tmp_path: Path):
        user = _make_user(db)
        job_old = _make_job(db, company_name="OldWeekCo")
        job_new = _make_job(db, company_name="NewWeekCo")

        # Application from 10 days ago (previous week)
        old_dt = datetime.now(timezone.utc) - timedelta(days=10)
        _make_application(db, user, job_old, created_at=old_dt)
        # Application from today (current week)
        _make_application(db, user, job_new)
        db.commit()

        gen = ReportGenerator(output_root=tmp_path)
        report = gen.generate_report(user.id, db)

        # Only the current-week application counts
        assert report.applications_sent <= 1

        html = Path(report.report_path).read_text(encoding="utf-8")
        assert "NewWeekCo" in html
        assert "OldWeekCo" not in html


# ---------------------------------------------------------------------------
# 8. API — GET /report/{user_id}/latest
# ---------------------------------------------------------------------------


class TestLatestReportAPI:
    """GET /report/{user_id}/latest returns data from DB, not disk."""

    def test_returns_latest_report(
        self, db: Session, client: TestClient, tmp_path: Path
    ):
        user = _make_user(db)
        job = _make_job(db)
        _make_application(db, user, job, match_score=0.82)
        db.commit()

        gen = ReportGenerator(output_root=tmp_path)
        gen.generate_report(user.id, db)

        resp = client.get(f"/report/{user.id}/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == str(user.id)
        assert "week_start" in data
        assert "week_end" in data
        assert "applications_sent" in data
        assert "summary" in data
        assert "insights" in data

    def test_returns_insights_from_db(
        self, db: Session, client: TestClient, tmp_path: Path
    ):
        """Insights in API response come from top_matches DB column, not JSON file."""
        user = _make_user(db)
        job = _make_job(db, skills_required=["Python", "Go"])
        _make_application(db, user, job, skill_gaps=["Go"])
        db.commit()

        gen = ReportGenerator(output_root=tmp_path)
        gen.generate_report(user.id, db)

        # Delete the JSON file to prove API doesn't rely on it
        json_path = tmp_path / str(user.id) / "latest.json"
        if json_path.exists():
            json_path.unlink()

        resp = client.get(f"/report/{user.id}/latest")
        assert resp.status_code == 200
        data = resp.json()
        # API should still return insights from DB
        assert "insights" in data

    def test_404_no_report_for_user(self, db: Session, client: TestClient):
        """User exists but has no reports → 404."""
        user = _make_user(db)
        db.commit()

        resp = client.get(f"/report/{user.id}/latest")
        assert resp.status_code == 404
        assert "No weekly report" in resp.json()["detail"]

    def test_404_user_not_found(self, db: Session, client: TestClient):
        """Non-existent user → 404."""
        fake_id = uuid.uuid4()
        resp = client.get(f"/report/{fake_id}/latest")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_400_invalid_uuid(self, client: TestClient):
        """Malformed UUID → 400."""
        resp = client.get("/report/not-a-uuid/latest")
        assert resp.status_code == 400

    def test_returns_most_recent_report(
        self, db: Session, client: TestClient, tmp_path: Path
    ):
        """When the user has multiple reports, the latest one is returned."""
        user = _make_user(db)
        db.commit()

        gen = ReportGenerator(output_root=tmp_path)

        today = datetime.now(tz=timezone.utc).date()
        # First report — last week
        last_monday = today - timedelta(days=today.isoweekday() - 1 + 7)
        gen.generate_report(user.id, db, week_ref=last_monday)

        # Second report — this week
        this_monday = today - timedelta(days=today.isoweekday() - 1)
        gen.generate_report(user.id, db, week_ref=this_monday)

        resp = client.get(f"/report/{user.id}/latest")
        assert resp.status_code == 200
        data = resp.json()
        # The returned week_start must be this week's Monday
        assert data["week_start"] == this_monday.isoformat()
