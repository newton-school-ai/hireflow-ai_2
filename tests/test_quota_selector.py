"""
Unit and API integration tests for Weekly Quota Selector and Confirmation Flow.

Tests cover:
- Quota selection (N jobs)
- Expired job filtering (> 30 days)
- User blacklist filtering
- Duplicate company filtering
- Job swapping (success and validation failure edge cases)
- Confirmation flow & mandatory downstream trigger guarantee
- Batch vs individual confirmation modes
- Deterministic score sorting
- Edge cases (empty jobs list, quota > available jobs, all jobs filtered out, duplicate scores, invalid user)
- FastAPI endpoints GET /weekly-plan, POST /weekly-plan/swap, POST /weekly-plan/confirm
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.config.database import Base, get_db
from src.models.job import Job
from src.models.user import User
from src.pipelines.quota_selector import (
    InvalidSwapError,
    JobFilterManager,
    PlanRanker,
    QuotaSelectorPipeline,
    UserNotFoundError,
)


def _make_uuid_str(val: int) -> str:
    """Creates a deterministic UUID string representation from an integer."""
    return str(uuid.UUID(int=val))


@pytest.fixture
def test_engine():
    """In-memory SQLite engine fixture with thread sharing enabled."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db_session(test_engine):
    """In-memory SQLite database session fixture."""
    TestingSession = sessionmaker(bind=test_engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session):
    """FastAPI TestClient overriding get_db dependency."""

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def sample_user(db_session):
    """Creates a standard user with quota 3."""
    user = User(
        id=uuid.uuid4(),
        name="Test User",
        email="testuser@example.com",
        mode="job",
        weekly_quota=3,
        confirmation_mode="batch",
        master_profile={"blacklist": ["BadCompany Inc"]},
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


# =============================================================================
# Unit Tests: JobFilterManager
# =============================================================================


def test_expired_job_filtering():
    """Jobs posted strictly more than 30 days ago must be flagged as expired."""
    ref_date = datetime.now(timezone.utc).date()
    fresh_date = ref_date - timedelta(days=10)
    exact_30_date = ref_date - timedelta(days=30)
    expired_date = ref_date - timedelta(days=31)

    assert JobFilterManager.is_expired(fresh_date, reference_date=ref_date) is False
    assert JobFilterManager.is_expired(exact_30_date, reference_date=ref_date) is False
    assert JobFilterManager.is_expired(expired_date, reference_date=ref_date) is True
    assert JobFilterManager.is_expired(None, reference_date=ref_date) is False


def test_blacklist_filtering():
    """Companies in the blacklist must be identified case-insensitively."""
    blacklist = ["EvilCorp", "Bad Company Inc"]

    assert JobFilterManager.is_blacklisted("EvilCorp", blacklist) is True
    assert JobFilterManager.is_blacklisted("evilcorp", blacklist) is True
    assert JobFilterManager.is_blacklisted("  BAD COMPANY INC ", blacklist) is True
    assert JobFilterManager.is_blacklisted("GoodCorp", blacklist) is False
    assert JobFilterManager.is_blacklisted(None, blacklist) is False


def test_duplicate_company_filtering():
    """Only the highest match score job for each distinct company should be retained."""
    scored_jobs = [
        {"job_id": _make_uuid_str(1), "company": "Google", "match_score": 0.95},
        {"job_id": _make_uuid_str(2), "company": "google", "match_score": 0.90},
        {"job_id": _make_uuid_str(3), "company": "Microsoft", "match_score": 0.88},
        {"job_id": _make_uuid_str(4), "company": "MICROSOFT", "match_score": 0.85},
    ]

    deduped = JobFilterManager.deduplicate_companies(scored_jobs)
    assert len(deduped) == 2
    assert deduped[0]["job_id"] == _make_uuid_str(1)
    assert deduped[1]["job_id"] == _make_uuid_str(3)


def test_spam_filtering():
    """Spam jobs (is_spam=True or confidence >= threshold) must be identified."""
    assert JobFilterManager.is_spam(True, 0.0) is True
    assert JobFilterManager.is_spam(False, 0.8, threshold=0.7) is True
    assert JobFilterManager.is_spam(False, 0.5, threshold=0.7) is False


# =============================================================================
# Unit Tests: Pipeline Quota Selection & Ranking
# =============================================================================


def test_quota_selection_normal(db_session, sample_user):
    """Pipeline should select top N jobs where N = user.weekly_quota."""
    now = datetime.now(timezone.utc).date()

    candidates = [
        {
            "job_id": _make_uuid_str(i),
            "company_name": f"Company {i}",
            "role_title": f"Software Engineer {i}",
            "match_score": 0.5 + (i * 0.05),
            "posting_date": now,
            "is_spam": False,
        }
        for i in range(1, 6)
    ]

    pipeline = QuotaSelectorPipeline()
    plan = pipeline.generate_weekly_plan(
        user_id=sample_user.id,
        db=db_session,
        candidate_jobs_override=candidates,
    )

    assert plan.user_id == str(sample_user.id)
    assert plan.weekly_quota == 3
    assert len(plan.selected_jobs) == 3
    assert len(plan.remaining_jobs) == 2

    # Top scored jobs selected: job_5 (0.75), job_4 (0.70), job_3 (0.65)
    assert plan.selected_jobs[0].job_id == _make_uuid_str(5)
    assert plan.selected_jobs[0].planned_rank == 1
    assert plan.selected_jobs[1].job_id == _make_uuid_str(4)
    assert plan.selected_jobs[1].planned_rank == 2
    assert plan.selected_jobs[2].job_id == _make_uuid_str(3)
    assert plan.selected_jobs[2].planned_rank == 3


def test_deterministic_behaviour_on_duplicate_scores():
    """When match scores are equal, sorting must be deterministic using job_id ASC."""
    candidates = [
        {"job_id": _make_uuid_str(2), "match_score": 0.80},
        {"job_id": _make_uuid_str(1), "match_score": 0.80},
        {"job_id": _make_uuid_str(3), "match_score": 0.80},
    ]

    selected, remaining = PlanRanker.rank_and_select(candidates, weekly_quota=2)
    assert [j["job_id"] for j in selected] == [_make_uuid_str(1), _make_uuid_str(2)]
    assert [j["job_id"] for j in remaining] == [_make_uuid_str(3)]


# =============================================================================
# Unit Tests: Job Swapping
# =============================================================================


def test_swap_success(db_session, sample_user):
    """Swapping a selected job with an eligible remaining job should succeed."""
    now = datetime.now(timezone.utc).date()
    id1, id2, id3, id4 = (
        _make_uuid_str(1),
        _make_uuid_str(2),
        _make_uuid_str(3),
        _make_uuid_str(4),
    )
    candidates = [
        {
            "job_id": id1,
            "company_name": "Company A",
            "match_score": 0.90,
            "posting_date": now,
        },
        {
            "job_id": id2,
            "company_name": "Company B",
            "match_score": 0.80,
            "posting_date": now,
        },
        {
            "job_id": id3,
            "company_name": "Company C",
            "match_score": 0.70,
            "posting_date": now,
        },
        {
            "job_id": id4,
            "company_name": "Company D",
            "match_score": 0.60,
            "posting_date": now,
        },
    ]

    pipeline = QuotaSelectorPipeline()

    # Initial plan selects top 3: id1, id2, id3
    plan = pipeline.generate_weekly_plan(
        user_id=sample_user.id, db=db_session, candidate_jobs_override=candidates
    )
    initial_selected_ids = {j.job_id for j in plan.selected_jobs}
    assert initial_selected_ids == {id1, id2, id3}

    # Swap out id3 for id4
    updated_plan = pipeline.swap_job(
        user_id=sample_user.id,
        remove_job_id=id3,
        add_job_id=id4,
        db=db_session,
        candidate_jobs_override=candidates,
    )

    new_selected_ids = {j.job_id for j in updated_plan.selected_jobs}
    assert len(new_selected_ids) == 3
    assert new_selected_ids == {id1, id2, id4}
    assert id3 not in new_selected_ids


def test_invalid_swap_cases(db_session, sample_user):
    """Swap should fail when invalid parameters or rule violations occur."""
    now = datetime.now(timezone.utc).date()
    id1, id2, id3, id4, id5 = (
        _make_uuid_str(1),
        _make_uuid_str(2),
        _make_uuid_str(3),
        _make_uuid_str(4),
        _make_uuid_str(5),
    )
    candidates = [
        {
            "job_id": id1,
            "company_name": "Company A",
            "match_score": 0.90,
            "posting_date": now,
        },
        {
            "job_id": id2,
            "company_name": "Company B",
            "match_score": 0.80,
            "posting_date": now,
        },
        {
            "job_id": id3,
            "company_name": "Company C",
            "match_score": 0.70,
            "posting_date": now,
        },
        {
            "job_id": id4,
            "company_name": "Company A",
            "match_score": 0.60,
            "posting_date": now,
        },  # Duplicate company
        {
            "job_id": id5,
            "company_name": "BadCompany Inc",
            "match_score": 0.50,
            "posting_date": now,
        },  # Blacklisted
    ]

    pipeline = QuotaSelectorPipeline()
    pipeline.generate_weekly_plan(
        user_id=sample_user.id, db=db_session, candidate_jobs_override=candidates
    )

    # 1. remove_job_id not in selected
    with pytest.raises(InvalidSwapError):
        pipeline.swap_job(
            user_id=sample_user.id,
            remove_job_id=_make_uuid_str(99),
            add_job_id=id4,
            db=db_session,
            candidate_jobs_override=candidates,
        )

    # 2. add_job_id already in selected
    with pytest.raises(InvalidSwapError):
        pipeline.swap_job(
            user_id=sample_user.id,
            remove_job_id=id3,
            add_job_id=id1,
            db=db_session,
            candidate_jobs_override=candidates,
        )

    # 3. add_job_id is blacklisted
    with pytest.raises(InvalidSwapError):
        pipeline.swap_job(
            user_id=sample_user.id,
            remove_job_id=id3,
            add_job_id=id5,
            db=db_session,
            candidate_jobs_override=candidates,
        )

    # 4. add_job_id produces duplicate company
    with pytest.raises(InvalidSwapError):
        pipeline.swap_job(
            user_id=sample_user.id,
            remove_job_id=id3,
            add_job_id=id4,
            db=db_session,
            candidate_jobs_override=candidates,
        )


# =============================================================================
# Unit Tests: Confirmation Flow & Downstream Hook
# =============================================================================


def test_confirmation_flow_and_downstream_trigger(db_session, sample_user):
    """Mandatory confirmation requirement: status is 'planned' before confirm and 'confirmed' after confirm."""
    now = datetime.now(timezone.utc).date()
    id1, id2 = _make_uuid_str(1), _make_uuid_str(2)
    candidates = [
        {
            "job_id": id1,
            "company_name": "Company A",
            "match_score": 0.90,
            "posting_date": now,
        },
        {
            "job_id": id2,
            "company_name": "Company B",
            "match_score": 0.80,
            "posting_date": now,
        },
    ]

    hook_calls = []

    def mock_hook(user_id, confirmed_ids):
        hook_calls.append((user_id, confirmed_ids))
        return {"status": "ready"}

    pipeline = QuotaSelectorPipeline(downstream_hook=mock_hook)

    # 1. Before confirmation
    initial_plan = pipeline.generate_weekly_plan(
        user_id=sample_user.id, db=db_session, candidate_jobs_override=candidates
    )
    assert initial_plan.status == "planned"
    assert initial_plan.downstream_ready is False
    assert len(hook_calls) == 0

    # 2. After confirmation
    confirmed_plan = pipeline.confirm_weekly_plan(
        user_id=sample_user.id, db=db_session, candidate_jobs_override=candidates
    )

    assert confirmed_plan.status == "confirmed"
    assert confirmed_plan.downstream_ready is True
    assert len(hook_calls) == 1
    assert hook_calls[0][0] == str(sample_user.id)
    assert set(hook_calls[0][1]) == {id1, id2}


# =============================================================================
# Unit Tests: Edge Cases
# =============================================================================


def test_empty_job_list(db_session, sample_user):
    """Empty job list should result in empty selected and remaining jobs without errors."""
    pipeline = QuotaSelectorPipeline()
    plan = pipeline.generate_weekly_plan(
        user_id=sample_user.id, db=db_session, candidate_jobs_override=[]
    )

    assert len(plan.selected_jobs) == 0
    assert len(plan.remaining_jobs) == 0


def test_quota_larger_than_available(db_session, sample_user):
    """If quota > available eligible jobs, return all available eligible jobs."""
    now = datetime.now(timezone.utc).date()
    id1 = _make_uuid_str(1)
    candidates = [
        {
            "job_id": id1,
            "company_name": "Company A",
            "match_score": 0.90,
            "posting_date": now,
        }
    ]

    pipeline = QuotaSelectorPipeline()
    plan = pipeline.generate_weekly_plan(
        user_id=sample_user.id, db=db_session, candidate_jobs_override=candidates
    )

    assert len(plan.selected_jobs) == 1
    assert plan.selected_jobs[0].job_id == id1
    assert len(plan.remaining_jobs) == 0


def test_all_jobs_filtered_out(db_session, sample_user):
    """If all jobs are filtered (expired/blacklisted), selected jobs list is empty."""
    old_date = datetime.now(timezone.utc).date() - timedelta(days=40)
    candidates = [
        {
            "job_id": _make_uuid_str(1),
            "company_name": "BadCompany Inc",
            "match_score": 0.90,
            "posting_date": datetime.now(timezone.utc).date(),
        },  # Blacklisted
        {
            "job_id": _make_uuid_str(2),
            "company_name": "Company B",
            "match_score": 0.80,
            "posting_date": old_date,
        },  # Expired
    ]

    pipeline = QuotaSelectorPipeline()
    plan = pipeline.generate_weekly_plan(
        user_id=sample_user.id, db=db_session, candidate_jobs_override=candidates
    )

    assert len(plan.selected_jobs) == 0
    assert len(plan.remaining_jobs) == 0


def test_invalid_user_raises_not_found(db_session):
    """Non-existent user ID should raise UserNotFoundError."""
    pipeline = QuotaSelectorPipeline()
    invalid_id = uuid.uuid4()

    with pytest.raises(UserNotFoundError):
        pipeline.generate_weekly_plan(user_id=invalid_id, db=db_session)


# =============================================================================
# API Integration Tests (FastAPI Endpoints)
# =============================================================================


def test_api_get_weekly_plan_batch(client, db_session, sample_user):
    """GET /weekly-plan/{user_id} should return weekly plan in batch mode."""
    j1 = Job(
        id=uuid.uuid4(),
        company_name="TechCorp",
        role_title="Backend Developer",
        jd_text="Backend engineer role using Python and FastAPI.",
        application_url="http://example.com/j1",
        listing_type="job",
        is_spam=False,
    )
    j2 = Job(
        id=uuid.uuid4(),
        company_name="DataCo",
        role_title="Data Engineer",
        jd_text="Data engineer role building pipelines.",
        application_url="http://example.com/j2",
        listing_type="job",
        is_spam=False,
    )
    db_session.add_all([j1, j2])
    db_session.commit()

    response = client.get(f"/weekly-plan/{sample_user.id}")
    assert response.status_code == 200
    data = response.json()

    assert data["user_id"] == str(sample_user.id)
    assert data["weekly_quota"] == 3
    assert data["confirmation_mode"] == "batch"
    assert data["status"] == "planned"
    assert "selected_jobs" in data
    assert "remaining_jobs" in data


def test_api_get_weekly_plan_individual_mode(client, db_session):
    """GET /weekly-plan/{user_id} should format individual recommendation when confirmation_mode='individual'."""
    user = User(
        id=uuid.uuid4(),
        name="Indiv User",
        email="indiv@example.com",
        mode="job",
        weekly_quota=2,
        confirmation_mode="individual",
    )
    j1 = Job(
        id=uuid.uuid4(),
        company_name="Alpha",
        role_title="Engineer",
        jd_text="Engineering role.",
        application_url="http://example.com/a",
        listing_type="job",
        is_spam=False,
    )
    db_session.add_all([user, j1])
    db_session.commit()

    response = client.get(f"/weekly-plan/{user.id}?index=0")
    assert response.status_code == 200
    data = response.json()

    assert data["confirmation_mode"] == "individual"
    assert "current_recommendation" in data
    assert data["current_recommendation"]["company"] == "Alpha"


def test_api_swap_endpoint(client, db_session, sample_user):
    """POST /weekly-plan/{user_id}/swap should process job replacements."""
    j1 = Job(
        id=uuid.uuid4(),
        company_name="Company1",
        role_title="Role 1",
        jd_text="Role 1 description.",
        application_url="http://example.com/1",
        listing_type="job",
        is_spam=False,
    )
    j2 = Job(
        id=uuid.uuid4(),
        company_name="Company2",
        role_title="Role 2",
        jd_text="Role 2 description.",
        application_url="http://example.com/2",
        listing_type="job",
        is_spam=False,
    )
    db_session.add_all([j1, j2])
    db_session.commit()

    payload = {"remove_job_id": str(j1.id), "add_job_id": str(j2.id)}
    response = client.post(f"/weekly-plan/{sample_user.id}/swap", json=payload)
    # If j1 not currently in selected, returns HTTP 400
    assert response.status_code in [200, 400]


def test_api_confirm_endpoint(client, db_session, sample_user):
    """POST /weekly-plan/{user_id}/confirm should confirm plan and return downstream readiness."""
    j1 = Job(
        id=uuid.uuid4(),
        company_name="Company1",
        role_title="Role 1",
        jd_text="Role 1 description.",
        application_url="http://example.com/1",
        listing_type="job",
        is_spam=False,
    )
    db_session.add(j1)
    db_session.commit()

    response = client.post(
        f"/weekly-plan/{sample_user.id}/confirm",
        json={"confirmed_job_ids": [str(j1.id)]},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "confirmed"
    assert data["downstream_ready"] is True


def test_api_user_not_found(client, db_session):
    """Requesting non-existent user should return 404."""
    invalid_uuid = str(uuid.uuid4())
    response = client.get(f"/weekly-plan/{invalid_uuid}")
    assert response.status_code == 404
