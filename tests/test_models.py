"""
Tests for HireFlow AI database models.

Uses an in-memory SQLite database so tests run in CI without PostgreSQL.
Validates table structure, column constraints, relationships, and CRUD.
"""

import uuid
from datetime import date

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from src.config.database import Base
from src.models.application import Application
from src.models.job import Job
from src.models.prep_guide import PrepGuide
from src.models.report import WeeklyReport
from src.models.user import User

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="module")
def engine():
    """Create an in-memory SQLite engine for the test module."""
    eng = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def db(engine):
    """Yield a transactional session that rolls back after each test.

    Uses a nested transaction so IntegrityError tests don't leave
    the connection in a broken state.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    yield session
    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(**overrides) -> User:
    """Create a User instance with sensible defaults."""
    defaults = {
        "id": uuid.uuid4(),
        "name": "Test User",
        "email": f"test-{uuid.uuid4().hex[:8]}@example.com",
        "mode": "internship",
        "weekly_quota": 5,
        "confirmation_mode": "batch",
    }
    defaults.update(overrides)
    return User(**defaults)


def _make_job(**overrides) -> Job:
    """Create a Job instance with sensible defaults."""
    defaults = {
        "id": uuid.uuid4(),
        "company_name": "Acme Corp",
        "role_title": "AI Engineer Intern",
        "jd_text": "We are looking for an AI engineer intern...",
        "application_url": f"https://jobs.lever.co/acme/{uuid.uuid4().hex}",
        "listing_type": "internship",
        "is_spam": False,
        "spam_confidence": 0.0,
    }
    defaults.update(overrides)
    return Job(**defaults)


# ===========================================================================
# Table Existence Tests
# ===========================================================================


class TestTableExistence:
    """Verify all expected tables exist in the metadata."""

    EXPECTED_TABLES = {
        "users",
        "jobs",
        "applications",
        "prep_guides",
        "weekly_reports",
    }

    def test_all_tables_created(self, engine):
        """All 5 core tables should be present."""
        inspector = inspect(engine)
        actual_tables = set(inspector.get_table_names())
        assert self.EXPECTED_TABLES.issubset(
            actual_tables
        ), f"Missing tables: {self.EXPECTED_TABLES - actual_tables}"


# ===========================================================================
# Column Presence Tests
# ===========================================================================


class TestUsersColumns:
    """Verify the users table has every required column."""

    EXPECTED_COLUMNS = {
        "id",
        "name",
        "email",
        "mode",
        "master_profile",
        "weekly_quota",
        "confirmation_mode",
        "created_at",
        "updated_at",
    }

    def test_users_columns(self, engine):
        inspector = inspect(engine)
        actual = {col["name"] for col in inspector.get_columns("users")}
        assert self.EXPECTED_COLUMNS.issubset(
            actual
        ), f"Missing columns in users: {self.EXPECTED_COLUMNS - actual}"


class TestJobsColumns:
    """Verify the jobs table has every required column."""

    EXPECTED_COLUMNS = {
        "id",
        "company_name",
        "role_title",
        "jd_text",
        "location",
        "application_url",
        "posting_date",
        "listing_type",
        "skills_required",
        "salary_range",
        "experience_required",
        "source_platform",
        "is_spam",
        "spam_confidence",
        "scraped_at",
        "created_at",
    }

    def test_jobs_columns(self, engine):
        inspector = inspect(engine)
        actual = {col["name"] for col in inspector.get_columns("jobs")}
        assert self.EXPECTED_COLUMNS.issubset(
            actual
        ), f"Missing columns in jobs: {self.EXPECTED_COLUMNS - actual}"


class TestApplicationsColumns:
    """Verify the applications table has every required column."""

    EXPECTED_COLUMNS = {
        "id",
        "user_id",
        "job_id",
        "match_score",
        "skill_matches",
        "skill_gaps",
        "resume_path",
        "resume_version",
        "status",
        "applied_at",
        "created_at",
    }

    def test_applications_columns(self, engine):
        inspector = inspect(engine)
        actual = {col["name"] for col in inspector.get_columns("applications")}
        assert self.EXPECTED_COLUMNS.issubset(actual), (
            f"Missing columns in applications: " f"{self.EXPECTED_COLUMNS - actual}"
        )


class TestPrepGuidesColumns:
    """Verify the prep_guides table has every required column."""

    EXPECTED_COLUMNS = {
        "id",
        "user_id",
        "job_id",
        "skill_gaps",
        "resources",
        "mock_questions",
        "created_at",
    }

    def test_prep_guides_columns(self, engine):
        inspector = inspect(engine)
        actual = {col["name"] for col in inspector.get_columns("prep_guides")}
        assert self.EXPECTED_COLUMNS.issubset(actual), (
            f"Missing columns in prep_guides: " f"{self.EXPECTED_COLUMNS - actual}"
        )


class TestWeeklyReportsColumns:
    """Verify the weekly_reports table has every required column."""

    EXPECTED_COLUMNS = {
        "id",
        "user_id",
        "week_start",
        "week_end",
        "applications_sent",
        "responses_received",
        "top_matches",
        "summary",
        "created_at",
    }

    def test_weekly_reports_columns(self, engine):
        inspector = inspect(engine)
        actual = {col["name"] for col in inspector.get_columns("weekly_reports")}
        assert self.EXPECTED_COLUMNS.issubset(actual), (
            f"Missing columns in weekly_reports: " f"{self.EXPECTED_COLUMNS - actual}"
        )


# ===========================================================================
# CRUD Tests
# ===========================================================================


class TestUserCRUD:
    """Test basic CRUD operations on the User model."""

    def test_create_user(self, db: Session):
        user = _make_user()
        db.add(user)
        db.flush()

        fetched = db.get(User, user.id)
        assert fetched is not None
        assert fetched.name == "Test User"
        assert fetched.mode == "internship"
        assert fetched.weekly_quota == 5
        assert fetched.confirmation_mode == "batch"

    def test_create_user_job_mode(self, db: Session):
        user = _make_user(mode="job")
        db.add(user)
        db.flush()

        fetched = db.get(User, user.id)
        assert fetched is not None
        assert fetched.mode == "job"

    def test_user_with_jsonb_profile(self, db: Session):
        profile = {
            "skills": ["Python", "FastAPI", "LangChain"],
            "projects": [{"name": "HireFlow", "description": "AI job app"}],
            "experience_years": 1,
        }
        user = _make_user(master_profile=profile)
        db.add(user)
        db.flush()

        fetched = db.get(User, user.id)
        assert fetched is not None
        assert fetched.master_profile["skills"] == [
            "Python",
            "FastAPI",
            "LangChain",
        ]

    def test_duplicate_email_rejected(self, db: Session):
        email = "duplicate@example.com"
        db.add(_make_user(email=email))
        db.flush()

        db.add(_make_user(email=email))
        with pytest.raises(IntegrityError):
            db.flush()


class TestJobCRUD:
    """Test basic CRUD operations on the Job model."""

    def test_create_job(self, db: Session):
        job = _make_job()
        db.add(job)
        db.flush()

        fetched = db.get(Job, job.id)
        assert fetched is not None
        assert fetched.company_name == "Acme Corp"
        assert fetched.listing_type == "internship"
        assert fetched.is_spam is False
        assert fetched.spam_confidence == 0.0

    def test_duplicate_application_url_rejected(self, db: Session):
        url = "https://jobs.lever.co/acme/unique-job-123"
        db.add(_make_job(application_url=url))
        db.flush()

        db.add(_make_job(application_url=url))
        with pytest.raises(IntegrityError):
            db.flush()


class TestApplicationCRUD:
    """Test Application model CRUD and constraints."""

    def test_create_application(self, db: Session):
        user = _make_user()
        job = _make_job()
        db.add_all([user, job])
        db.flush()

        app = Application(
            id=uuid.uuid4(),
            user_id=user.id,
            job_id=job.id,
            match_score=0.85,
            skill_gaps=["Docker", "Kubernetes"],
            status="matched",
        )
        db.add(app)
        db.flush()

        fetched = db.get(Application, app.id)
        assert fetched is not None
        assert fetched.match_score == 0.85
        assert fetched.status == "matched"

    def test_unique_user_job_constraint(self, db: Session):
        user = _make_user()
        job = _make_job()
        db.add_all([user, job])
        db.flush()

        app1 = Application(
            id=uuid.uuid4(),
            user_id=user.id,
            job_id=job.id,
            status="matched",
        )
        db.add(app1)
        db.flush()

        app2 = Application(
            id=uuid.uuid4(),
            user_id=user.id,
            job_id=job.id,
            status="applied",
        )
        db.add(app2)
        with pytest.raises(IntegrityError):
            db.flush()


class TestPrepGuideCRUD:
    """Test PrepGuide model CRUD."""

    def test_create_prep_guide_with_job(self, db: Session):
        user = _make_user()
        job = _make_job()
        db.add_all([user, job])
        db.flush()

        guide = PrepGuide(
            id=uuid.uuid4(),
            user_id=user.id,
            job_id=job.id,
            skill_gaps=["React", "TypeScript"],
            resources=[{"url": "https://react.dev", "title": "React Docs"}],
            mock_questions=["Explain virtual DOM"],
        )
        db.add(guide)
        db.flush()

        fetched = db.get(PrepGuide, guide.id)
        assert fetched is not None
        assert fetched.skill_gaps == ["React", "TypeScript"]

    def test_create_general_prep_guide(self, db: Session):
        """PrepGuide without a job_id (general guide)."""
        user = _make_user()
        db.add(user)
        db.flush()

        guide = PrepGuide(
            id=uuid.uuid4(),
            user_id=user.id,
            job_id=None,
            skill_gaps=["System Design"],
            resources=[],
            mock_questions=[],
        )
        db.add(guide)
        db.flush()

        fetched = db.get(PrepGuide, guide.id)
        assert fetched is not None
        assert fetched.job_id is None


class TestWeeklyReportCRUD:
    """Test WeeklyReport model CRUD."""

    def test_create_weekly_report(self, db: Session):
        user = _make_user()
        db.add(user)
        db.flush()

        report = WeeklyReport(
            id=uuid.uuid4(),
            user_id=user.id,
            week_start=date(2025, 6, 30),
            week_end=date(2025, 7, 6),
            applications_sent=5,
            responses_received=2,
            top_matches=[{"job_id": str(uuid.uuid4()), "score": 0.92}],
            summary="Good week - 2 interview invites received.",
        )
        db.add(report)
        db.flush()

        fetched = db.get(WeeklyReport, report.id)
        assert fetched is not None
        assert fetched.applications_sent == 5
        assert fetched.responses_received == 2


# ===========================================================================
# Relationship Tests
# ===========================================================================


class TestRelationships:
    """Verify ORM relationships between models."""

    def test_user_has_applications(self, db: Session):
        user = _make_user()
        job = _make_job()
        db.add_all([user, job])
        db.flush()

        app = Application(
            id=uuid.uuid4(),
            user_id=user.id,
            job_id=job.id,
            status="matched",
        )
        db.add(app)
        db.flush()

        db.refresh(user)
        assert len(user.applications) == 1
        assert user.applications[0].job_id == job.id

    def test_application_has_user_and_job(self, db: Session):
        user = _make_user()
        job = _make_job()
        db.add_all([user, job])
        db.flush()

        app = Application(
            id=uuid.uuid4(),
            user_id=user.id,
            job_id=job.id,
            status="shortlisted",
        )
        db.add(app)
        db.flush()

        db.refresh(app)
        assert app.user.name == "Test User"
        assert app.job.company_name == "Acme Corp"

    def test_user_has_prep_guides(self, db: Session):
        user = _make_user()
        db.add(user)
        db.flush()

        guide = PrepGuide(
            id=uuid.uuid4(),
            user_id=user.id,
            skill_gaps=[],
            resources=[],
            mock_questions=[],
        )
        db.add(guide)
        db.flush()

        db.refresh(user)
        assert len(user.prep_guides) == 1

    def test_user_has_weekly_reports(self, db: Session):
        user = _make_user()
        db.add(user)
        db.flush()

        report = WeeklyReport(
            id=uuid.uuid4(),
            user_id=user.id,
            week_start=date(2025, 7, 1),
            week_end=date(2025, 7, 7),
        )
        db.add(report)
        db.flush()

        db.refresh(user)
        assert len(user.weekly_reports) == 1


# ===========================================================================
# Model Repr Tests
# ===========================================================================


class TestModelRepr:
    """Verify __repr__ methods return useful strings."""

    def test_user_repr(self, db: Session):
        user = _make_user(email="repr@test.com")
        assert "repr@test.com" in repr(user)

    def test_job_repr(self, db: Session):
        job = _make_job(company_name="TestCo", role_title="SWE")
        assert "TestCo" in repr(job)
        assert "SWE" in repr(job)

    def test_application_repr(self, db: Session):
        app = Application(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            status="applied",
        )
        assert "applied" in repr(app)
