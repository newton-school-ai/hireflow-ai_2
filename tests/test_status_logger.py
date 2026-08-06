"""
Comprehensive tests for StatusLogger utility and Applications API endpoints.

Validates normal status progression, error handling, audit logging, status filtering,
pagination, and API responses.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.config.database import Base, get_db
from src.models.application import Application
from src.models.job import Job
from src.models.user import User
from src.utils.status_logger import StatusLogger

TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="module")
def test_engine():
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def db_session(test_engine):
    connection = test_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()

    yield session

    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


@pytest.fixture()
def client(db_session):
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.fixture()
def sample_user(db_session):
    user = User(
        name="Jane Doe",
        email=f"jane_{uuid.uuid4()}@example.com",
        mode="internship",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def sample_job(db_session):
    job = Job(
        company_name="Acme Corp",
        role_title="Software Engineer Intern",
        jd_text="Python, SQL, Algorithms",
        application_url=f"https://acme.example.com/jobs/{uuid.uuid4()}",
        listing_type="internship",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


@pytest.fixture()
def sample_application(db_session, sample_user, sample_job):
    application = Application(
        user_id=sample_user.id,
        job_id=sample_job.id,
        status="planned",
        resume_path="/resumes/jane_v1.pdf",
    )
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)
    return application


# =============================================================================
# StatusLogger Unit Tests
# =============================================================================


def test_normal_status_progression(db_session, sample_application):
    """Test full normal lifecycle: planned -> confirmed -> applying -> applied."""
    app_id = sample_application.id

    # 1. planned -> confirmed
    res1 = StatusLogger.log_transition(db_session, app_id, "confirmed")
    assert res1 is not None
    assert res1.status == "confirmed"

    # 2. confirmed -> applying
    res2 = StatusLogger.log_transition(db_session, app_id, "applying")
    assert res2 is not None
    assert res2.status == "applying"

    # 3. applying -> applied
    res3 = StatusLogger.log_transition(db_session, app_id, "applied")
    assert res3 is not None
    assert res3.status == "applied"
    assert res3.applied_at is not None

    # Verify complete audit trail
    history = StatusLogger.get_status_history(db_session, app_id)
    assert len(history) == 3

    assert history[0].previous_status == "planned"
    assert history[0].new_status == "confirmed"

    assert history[1].previous_status == "confirmed"
    assert history[1].new_status == "applying"

    assert history[2].previous_status == "applying"
    assert history[2].new_status == "applied"


def test_failed_application_logging(db_session, sample_application):
    """Test transitioning to failed with a failure reason."""
    app_id = sample_application.id
    reason = "Timeout waiting for submit button selector"

    result = StatusLogger.log_transition(
        db_session,
        app_id,
        "failed",
        failure_reason=reason,
    )

    assert result is not None
    assert result.status == "failed"
    assert result.failure_reason == reason

    history = StatusLogger.get_status_history(db_session, app_id)
    assert len(history) == 1
    assert history[0].new_status == "failed"
    assert history[0].failure_reason == reason


def test_needs_action_logging(db_session, sample_application):
    """Test transitioning to needs_action with failure reason and manual apply URL."""
    app_id = sample_application.id
    reason = "Cloudflare CAPTCHA challenge detected"
    manual_url = "https://acme.example.com/apply/direct"

    result = StatusLogger.log_transition(
        db_session,
        app_id,
        "needs_action",
        failure_reason=reason,
        manual_apply_url=manual_url,
    )

    assert result is not None
    assert result.status == "needs_action"
    assert result.failure_reason == reason
    assert result.manual_apply_url == manual_url

    history = StatusLogger.get_status_history(db_session, app_id)
    assert len(history) == 1
    assert history[0].new_status == "needs_action"
    assert history[0].failure_reason == reason
    assert history[0].manual_apply_url == manual_url


def test_invalid_status_handling(db_session, sample_application):
    """Test that invalid statuses or malformed arguments fail gracefully without exceptions."""
    app_id = sample_application.id

    # Invalid status name
    res1 = StatusLogger.log_transition(db_session, app_id, "unknown_status_xyz")
    assert res1 is None

    # Empty status
    res2 = StatusLogger.log_transition(db_session, app_id, "")
    assert res2 is None

    # Non-existent application UUID
    random_uuid = uuid.uuid4()
    res3 = StatusLogger.log_transition(db_session, random_uuid, "applied")
    assert res3 is None

    # Malformed application ID
    res4 = StatusLogger.log_transition(db_session, "not-a-uuid", "applied")
    assert res4 is None

    # Verify history is empty
    history = StatusLogger.get_status_history(db_session, app_id)
    assert len(history) == 0


def test_get_status_history_invalid_id(db_session):
    """Test history lookup with invalid UUID returns empty list."""
    assert StatusLogger.get_status_history(db_session, "invalid-uuid") == []


# =============================================================================
# Applications API Integration Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_applications_empty_history(client, sample_user):
    """Test GET /applications/{user_id} for user with no applications."""
    response = await client.get(f"/applications/{sample_user.id}")
    assert response.status_code == 200

    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["total_pages"] == 0
    assert data["current_page"] == 1
    assert data["page_size"] == 10


@pytest.mark.asyncio
async def test_get_applications_user_not_found(client):
    """Test GET /applications/{user_id} with non-existent user returns 404."""
    random_user_id = uuid.uuid4()
    response = await client.get(f"/applications/{random_user_id}")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_applications_filtering(client, db_session, sample_user):
    """Test GET /applications/{user_id}?status=... filtering."""
    # Create 3 jobs and applications with different statuses
    statuses = ["applied", "failed", "needs_action"]
    for idx, st in enumerate(statuses):
        job = Job(
            company_name=f"Company {idx}",
            role_title=f"Role {idx}",
            jd_text="Job Description",
            application_url=f"https://company{idx}.example.com/apply",
            listing_type="job",
        )
        db_session.add(job)
        db_session.commit()

        app_obj = Application(
            user_id=sample_user.id,
            job_id=job.id,
            status="planned",
            resume_path=f"/resumes/ver_{idx}.pdf",
        )
        db_session.add(app_obj)
        db_session.commit()

        # Update status via StatusLogger
        StatusLogger.log_transition(
            db_session,
            app_obj.id,
            st,
            failure_reason="Test reason" if st != "applied" else None,
            manual_apply_url="https://manual.url" if st == "needs_action" else None,
        )

    # 1. Filter status=applied
    res_applied = await client.get(f"/applications/{sample_user.id}?status=applied")
    assert res_applied.status_code == 200
    data_applied = res_applied.json()
    assert data_applied["total"] == 1
    assert data_applied["items"][0]["status"] == "applied"

    # 2. Filter status=failed
    res_failed = await client.get(f"/applications/{sample_user.id}?status=failed")
    assert res_failed.status_code == 200
    data_failed = res_failed.json()
    assert data_failed["total"] == 1
    assert data_failed["items"][0]["status"] == "failed"
    assert data_failed["items"][0]["failure_reason"] == "Test reason"

    # 3. Filter status=needs_action
    res_action = await client.get(f"/applications/{sample_user.id}?status=needs_action")
    assert res_action.status_code == 200
    data_action = res_action.json()
    assert data_action["total"] == 1
    assert data_action["items"][0]["status"] == "needs_action"
    assert data_action["items"][0]["manual_apply_url"] == "https://manual.url"


@pytest.mark.asyncio
async def test_get_applications_pagination(client, db_session, sample_user):
    """Test pagination metadata and slicing for applications API."""
    # Create 5 applications
    for i in range(5):
        job = Job(
            company_name=f"Paginated Co {i}",
            role_title=f"Engineer {i}",
            jd_text="Description",
            application_url=f"https://paginated{i}.example.com/apply",
            listing_type="job",
        )
        db_session.add(job)
        db_session.commit()

        app_obj = Application(
            user_id=sample_user.id,
            job_id=job.id,
            status="planned",
        )
        db_session.add(app_obj)
        db_session.commit()

    # Page 1, size 2 -> should return 2 items out of 5, total_pages 3
    res_p1 = await client.get(f"/applications/{sample_user.id}?page=1&page_size=2")
    assert res_p1.status_code == 200
    d1 = res_p1.json()
    assert d1["total"] == 5
    assert d1["total_pages"] == 3
    assert d1["current_page"] == 1
    assert d1["page_size"] == 2
    assert len(d1["items"]) == 2

    # Page 3, size 2 -> should return 1 item (last page)
    res_p3 = await client.get(f"/applications/{sample_user.id}?page=3&page_size=2")
    assert res_p3.status_code == 200
    d3 = res_p3.json()
    assert d3["total"] == 5
    assert d3["total_pages"] == 3
    assert d3["current_page"] == 3
    assert len(d3["items"]) == 1
