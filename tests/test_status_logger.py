"""
Unit and integration tests for status logger and applications API endpoints.
"""

import os
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
from src.utils.status_logger import log_status_change

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


def test_log_status_change_local_file():
    """Verify that log_status_change correctly appends logs with timestamps to data/logs/status_changes.log."""
    app_id = str(uuid.uuid4())
    log_file = "data/logs/status_changes.log"

    # Remove log file if it exists prior to test
    if os.path.exists(log_file):
        os.remove(log_file)

    log_status_change(app_id, "planned", "confirmed", "User accepted swap")

    assert os.path.exists(log_file)
    with open(log_file, "r", encoding="utf-8") as f:
        content = f.read()

    assert app_id in content
    assert "Transition: planned -> confirmed" in content
    assert "Reason: User accepted swap" in content

    # Clean up log file
    if os.path.exists(log_file):
        os.remove(log_file)


@pytest.mark.asyncio
async def test_api_get_applications_status_filter_and_pagination(client, db_session):
    """Test applications listing, pagination, status filtering, and custom response keys."""
    # 1. Create a test user
    user = User(
        name="Test Candidate",
        email="candidate@test.com",
        mode="internship",
        master_profile={},
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    # 2. Create jobs
    job_applied = Job(
        company_name="Google",
        role_title="Software Engineer",
        jd_text="Backend engineer role",
        application_url="https://google.com/apply",
        listing_type="job",
    )
    job_failed = Job(
        company_name="Netflix",
        role_title="Infrastructure Developer",
        jd_text="Platform engineer role",
        application_url="https://netflix.com/apply",
        listing_type="job",
    )
    job_needs_action = Job(
        company_name="Meta",
        role_title="Research Engineer",
        jd_text="ML developer role",
        application_url="https://meta.com/apply",
        listing_type="job",
    )
    db_session.add_all([job_applied, job_failed, job_needs_action])
    db_session.commit()
    db_session.refresh(job_applied)
    db_session.refresh(job_failed)
    db_session.refresh(job_needs_action)

    # 3. Create applications with different statuses
    app1 = Application(
        user_id=user.id,
        job_id=job_applied.id,
        status="applied",
        resume_path="/resumes/google.pdf",
    )
    app2 = Application(
        user_id=user.id,
        job_id=job_failed.id,
        status="failed",
        resume_path="/resumes/netflix.pdf",
        failure_reason="Timeout during form submission",
    )
    app3 = Application(
        user_id=user.id,
        job_id=job_needs_action.id,
        status="needs_action",
        resume_path="/resumes/meta.pdf",
        failure_reason="CAPTCHA challenge encountered",
    )
    db_session.add_all([app1, app2, app3])
    db_session.commit()

    # 4. Fetch all applications
    response = await client.get(f"/applications/{user.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert len(data["applications"]) == 3

    # Check that failed contains failure_reason
    failed_apps = [a for a in data["applications"] if a["status"] == "failed"]
    assert len(failed_apps) == 1
    assert failed_apps[0]["failure_reason"] == "Timeout during form submission"

    # Check needs_action includes specific reason and manual action URL
    needs_action_apps = [
        a for a in data["applications"] if a["status"] == "needs_action"
    ]
    assert len(needs_action_apps) == 1
    assert needs_action_apps[0]["failure_reason"] == "CAPTCHA challenge encountered"
    assert needs_action_apps[0]["manual_apply_url"] == "https://meta.com/apply"

    # 5. Fetch with status filter
    response_filter = await client.get(f"/applications/{user.id}?status=applied")
    assert response_filter.status_code == 200
    data_filter = response_filter.json()
    assert data_filter["total"] == 1
    assert len(data_filter["applications"]) == 1
    assert data_filter["applications"][0]["company_name"] == "Google"

    # 6. Fetch with pagination
    response_paginated = await client.get(f"/applications/{user.id}?limit=2&offset=0")
    assert response_paginated.status_code == 200
    data_paginated = response_paginated.json()
    assert data_paginated["total"] == 3
    assert len(data_paginated["applications"]) == 2


@pytest.mark.asyncio
async def test_api_applications_validation_and_errors(client, db_session):
    """Test GET /applications/{user_id} error handling for missing user and invalid UUID formats."""
    # Non-existent user UUID
    non_existent_uuid = str(uuid.uuid4())
    response = await client.get(f"/applications/{non_existent_uuid}")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]

    # Invalid UUID format
    response_invalid = await client.get("/applications/invalid_id_format")
    assert response_invalid.status_code == 400
    assert "Invalid user ID format" in response_invalid.json()["detail"]
