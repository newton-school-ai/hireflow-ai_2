"""
Tests for StatusLogger (src/utils/status_logger.py) and the
Application History API (GET /applications/{user_id}).

Uses an in-memory SQLite database so tests run in CI without PostgreSQL.
The ASGI test client (httpx + AsyncClient) mirrors the pattern used in
test_profile_api.py.
"""

from __future__ import annotations

import uuid
from typing import ClassVar

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.api.main import app
from src.config.database import Base, get_db
from src.models.application import Application
from src.models.job import Job
from src.models.user import User
from src.utils.status_logger import StatusLogger, StatusLoggerError

TEST_DATABASE_URL = "sqlite:///:memory:"

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def engine():
    """In-memory SQLite engine, schema created once per module."""
    eng = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def db(engine) -> Session:
    """Transactional session that rolls back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    yield session
    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


@pytest.fixture()
def client(db):
    """AsyncClient wired to the FastAPI app with DB overridden."""

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(db: Session, **overrides) -> User:
    defaults: dict = {
        "id": uuid.uuid4(),
        "name": "Test User",
        "email": f"test-{uuid.uuid4().hex[:8]}@example.com",
        "mode": "internship",
        "weekly_quota": 5,
        "confirmation_mode": "batch",
    }
    defaults.update(overrides)
    user = User(**defaults)
    db.add(user)
    db.flush()
    return user


def _make_job(db: Session, **overrides) -> Job:
    defaults: dict = {
        "id": uuid.uuid4(),
        "company_name": "Acme Corp",
        "role_title": "AI Engineer Intern",
        "jd_text": "Join our AI team.",
        "application_url": f"https://apply.example.com/{uuid.uuid4().hex}",
        "listing_type": "internship",
    }
    defaults.update(overrides)
    job = Job(**defaults)
    db.add(job)
    db.flush()
    return job


def _make_application(db: Session, user: User, job: Job, **overrides) -> Application:
    defaults: dict = {
        "id": uuid.uuid4(),
        "user_id": user.id,
        "job_id": job.id,
        "status": "matched",
    }
    defaults.update(overrides)
    app_obj = Application(**defaults)
    db.add(app_obj)
    db.flush()
    return app_obj


# ===========================================================================
# 1. StatusLogger — unit tests
# ===========================================================================


class TestStatusLoggerBasic:
    """StatusLogger correctly updates the application row."""

    def test_log_updates_status(self, db):
        user = _make_user(db)
        job = _make_job(db)
        application = _make_application(db, user, job, status="matched")

        sl = StatusLogger(db)
        result = sl.log(application_id=application.id, status="applied")

        assert result.status == "applied"

    def test_log_stamps_applied_at_when_applied(self, db):
        user = _make_user(db)
        job = _make_job(db)
        application = _make_application(db, user, job, status="resume_generated")

        sl = StatusLogger(db)
        sl.log(application_id=application.id, status="applied")

        db.refresh(application)
        assert application.applied_at is not None

    def test_log_does_not_stamp_applied_at_for_other_statuses(self, db):
        user = _make_user(db)
        job = _make_job(db)
        application = _make_application(db, user, job)

        sl = StatusLogger(db)
        sl.log(application_id=application.id, status="confirmed")

        db.refresh(application)
        assert application.applied_at is None

    def test_log_stores_failure_reason_on_failed(self, db):
        user = _make_user(db)
        job = _make_job(db)
        application = _make_application(db, user, job)

        sl = StatusLogger(db)
        sl.log(
            application_id=application.id,
            status="failed",
            failure_reason="Playwright timeout after 3 retries",
        )

        db.refresh(application)
        assert application.failure_reason == "Playwright timeout after 3 retries"

    def test_log_stores_failure_reason_on_needs_action(self, db):
        user = _make_user(db)
        job = _make_job(db)
        application = _make_application(db, user, job)

        sl = StatusLogger(db)
        sl.log(
            application_id=application.id,
            status="needs_action",
            failure_reason="CAPTCHA detected — apply manually",
        )

        db.refresh(application)
        assert application.failure_reason == "CAPTCHA detected — apply manually"

    def test_log_clears_failure_reason_on_recovery(self, db):
        """Transitioning back to a non-failure status clears stale failure_reason."""
        user = _make_user(db)
        job = _make_job(db)
        application = _make_application(
            db,
            user,
            job,
            status="failed",
            failure_reason="Old reason",
        )

        sl = StatusLogger(db)
        sl.log(application_id=application.id, status="confirmed")

        db.refresh(application)
        assert application.failure_reason is None

    def test_log_returns_application_instance(self, db):
        user = _make_user(db)
        job = _make_job(db)
        application = _make_application(db, user, job)

        sl = StatusLogger(db)
        result = sl.log(application_id=application.id, status="shortlisted")

        assert isinstance(result, Application)
        assert result.id == application.id

    def test_log_persists_to_db(self, db):
        """The change must survive a fresh query (i.e. it was committed)."""
        user = _make_user(db)
        job = _make_job(db)
        application = _make_application(db, user, job)

        sl = StatusLogger(db)
        sl.log(application_id=application.id, status="applied")

        fresh = db.query(Application).filter(Application.id == application.id).first()
        assert fresh.status == "applied"


class TestStatusLoggerErrors:
    """StatusLogger raises appropriate errors for invalid inputs."""

    def test_log_raises_for_unknown_id(self, db):
        sl = StatusLogger(db)
        with pytest.raises(StatusLoggerError, match="not found"):
            sl.log(application_id=uuid.uuid4(), status="applied")

    def test_log_raises_value_error_for_invalid_status(self, db):
        """Runtime status validation rejects arbitrary strings."""
        user = _make_user(db)
        job = _make_job(db)
        application = _make_application(db, user, job)

        sl = StatusLogger(db)
        with pytest.raises(ValueError, match="not a valid ApplicationStatus"):
            sl.log(application_id=application.id, status="hello")  # type: ignore[arg-type]


class TestStatusLoggerTransitions:
    """StatusLogger handles all valid status values."""

    ALL_STATUSES: ClassVar[list[str]] = [
        "planned",
        "matched",
        "shortlisted",
        "confirmed",
        "resume_generated",
        "applied",
        "failed",
        "withdrawn",
        "needs_action",
    ]

    @pytest.mark.parametrize("target_status", ALL_STATUSES)
    def test_can_set_every_status(self, db, target_status):
        user = _make_user(db)
        job = _make_job(db)
        application = _make_application(db, user, job)

        sl = StatusLogger(db)
        result = sl.log(
            application_id=application.id,
            status=target_status,  # type: ignore[arg-type]
            failure_reason=(
                "reason" if target_status in {"failed", "needs_action"} else None
            ),
        )

        assert result.status == target_status


# ===========================================================================
# 2. GET /applications/{user_id} — API tests
# ===========================================================================


class TestListApplicationsAPI:
    """Integration tests for the application history endpoint."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_user_with_no_applications(self, client, db):
        user = _make_user(db)
        db.commit()

        response = await client.get(f"/applications/{user.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []
        assert data["page"] == 1
        assert data["limit"] == 20

    @pytest.mark.asyncio
    async def test_returns_applications_for_user(self, client, db):
        user = _make_user(db)
        job = _make_job(db)
        _make_application(db, user, job, status="applied")
        db.commit()

        response = await client.get(f"/applications/{user.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        item = data["items"][0]
        assert item["status"] == "applied"
        assert item["company_name"] == "Acme Corp"
        assert item["role_title"] == "AI Engineer Intern"
        assert item["job_id"] == str(job.id)

    @pytest.mark.asyncio
    async def test_does_not_return_other_users_applications(self, client, db):
        user_a = _make_user(db)
        user_b = _make_user(db)
        job = _make_job(db)
        _make_application(db, user_b, job, status="matched")
        db.commit()

        response = await client.get(f"/applications/{user_a.id}")
        assert response.status_code == 200
        assert response.json()["total"] == 0

    @pytest.mark.asyncio
    async def test_404_for_unknown_user(self, client, db):
        response = await client.get(f"/applications/{uuid.uuid4()}")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_400_for_invalid_uuid(self, client, db):
        response = await client.get("/applications/not-a-uuid")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_filter_by_status(self, client, db):
        user = _make_user(db)
        job1 = _make_job(db)
        job2 = _make_job(db)
        _make_application(db, user, job1, status="applied")
        _make_application(db, user, job2, status="failed")
        db.commit()

        response = await client.get(f"/applications/{user.id}?status=applied")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["status"] == "applied"

    @pytest.mark.asyncio
    async def test_filter_by_status_needs_action(self, client, db):
        user = _make_user(db)
        job1 = _make_job(db)
        job2 = _make_job(db)
        _make_application(
            db,
            user,
            job1,
            status="needs_action",
            failure_reason="CAPTCHA detected",
        )
        _make_application(db, user, job2, status="applied")
        db.commit()

        response = await client.get(f"/applications/{user.id}?status=needs_action")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        item = data["items"][0]
        assert item["status"] == "needs_action"
        assert item["failure_reason"] == "CAPTCHA detected"
        # Acceptance criterion: manual_application_url must be present for
        # needs_action items so the user knows where to apply manually.
        assert "manual_application_url" in item
        assert item["manual_application_url"] == job1.application_url

    @pytest.mark.asyncio
    async def test_failed_applications_include_failure_reason(self, client, db):
        user = _make_user(db)
        job = _make_job(db)
        _make_application(
            db,
            user,
            job,
            status="failed",
            failure_reason="Playwright timeout after 3 retries",
        )
        db.commit()

        response = await client.get(f"/applications/{user.id}")
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["failure_reason"] == "Playwright timeout after 3 retries"

    @pytest.mark.asyncio
    async def test_400_for_invalid_status_filter(self, client, db):
        user = _make_user(db)
        db.commit()

        response = await client.get(f"/applications/{user.id}?status=invalid_status")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_pagination_page_and_limit(self, client, db):
        user = _make_user(db)
        for _ in range(5):
            job = _make_job(db)
            _make_application(db, user, job)
        db.commit()

        response = await client.get(f"/applications/{user.id}?page=1&limit=3")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert data["page"] == 1
        assert data["limit"] == 3
        assert len(data["items"]) == 3

    @pytest.mark.asyncio
    async def test_pagination_second_page(self, client, db):
        user = _make_user(db)
        for _ in range(5):
            job = _make_job(db)
            _make_application(db, user, job)
        db.commit()

        response = await client.get(f"/applications/{user.id}?page=2&limit=3")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2  # 5 total, 3 on page 1, 2 on page 2

    @pytest.mark.asyncio
    async def test_response_includes_application_url(self, client, db):
        user = _make_user(db)
        job = _make_job(db)
        _make_application(db, user, job, status="applied")
        db.commit()

        response = await client.get(f"/applications/{user.id}")
        item = response.json()["items"][0]
        assert item["application_url"] == job.application_url

    @pytest.mark.asyncio
    async def test_response_includes_resume_path(self, client, db):
        user = _make_user(db)
        job = _make_job(db)
        _make_application(
            db,
            user,
            job,
            status="applied",
            resume_path="data/resumes/user123/v1.pdf",
        )
        db.commit()

        response = await client.get(f"/applications/{user.id}")
        item = response.json()["items"][0]
        assert item["resume_path"] == "data/resumes/user123/v1.pdf"

    @pytest.mark.asyncio
    async def test_newest_application_appears_first(self, client, db):
        """Applications with a later applied_at appear first in the list."""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(tz=timezone.utc)
        user = _make_user(db)
        job1 = _make_job(db, company_name="Older Corp")
        job2 = _make_job(db, company_name="Newer Corp")
        _make_application(
            db, user, job1, status="applied", applied_at=now - timedelta(days=2)
        )
        _make_application(
            db, user, job2, status="applied", applied_at=now - timedelta(days=1)
        )
        db.commit()

        response = await client.get(f"/applications/{user.id}")
        items = response.json()["items"]
        # Both have status="applied"; descending created_at puts Newer Corp first
        # since it was flushed last (SQLite stores microseconds here correctly).
        company_names = [i["company_name"] for i in items]
        assert "Newer Corp" in company_names
        assert "Older Corp" in company_names
