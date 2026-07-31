"""
Unit tests for Multi-Factor Match Scorer and Skill Gap Extractor.

Tests skill gap extraction, sub-factor calculations, mode switching (internship vs job),
score determinism, edge cases, and SQLite database persistence.
"""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config.database import Base
from src.models.application import Application
from src.models.job import Job
from src.models.user import User
from src.pipelines.match_scorer import (
    WEIGHT_COMPANY_SIGNAL,
    WEIGHT_COMPENSATION,
    WEIGHT_EXPERIENCE,
    WEIGHT_LOCATION,
    WEIGHT_ROLE,
    WEIGHT_SKILL,
    calculate_company_signal,
    calculate_compensation_score,
    calculate_experience_score,
    calculate_location_score,
    calculate_role_score,
    calculate_skill_score,
    compute_final_score,
    extract_skill_gaps,
    score_all_jobs,
    score_job,
)


@pytest.fixture
def db_session():
    """In-memory SQLite session fixture for matcher testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


def test_extract_skill_gaps_normal():
    user_skills = ["Python", "FastAPI", "PostgreSQL"]
    jd_skills = ["Python", "FastAPI", "Docker", "AWS", "PostgreSQL"]

    gaps = extract_skill_gaps(user_skills, jd_skills)
    assert gaps == ["Docker", "AWS"]


def test_extract_skill_gaps_deduplication_and_order():
    user_skills = ["python"]
    jd_skills = ["Docker", "AWS", "docker", "Kubernetes", "aws"]

    gaps = extract_skill_gaps(user_skills, jd_skills)
    assert gaps == ["Docker", "AWS", "Kubernetes"]


def test_extract_skill_gaps_empty_or_missing_data():
    assert extract_skill_gaps(None, ["Python"]) == ["Python"]
    assert extract_skill_gaps(["Python"], None) == []
    assert extract_skill_gaps([], []) == []
    assert extract_skill_gaps(None, None) == []
    assert extract_skill_gaps("invalid_type", ["Python"]) == ["Python"]


def test_calculate_skill_score():
    # Full match
    assert calculate_skill_score(["Python", "React"], ["Python", "React"]) == 1.0
    # Partial match (1 out of 2)
    assert calculate_skill_score(["Python"], ["Python", "React"]) == 0.5
    # No match
    assert calculate_skill_score(["Java"], ["Python", "React"]) == 0.0
    # Empty JD requirements -> perfect score 1.0
    assert calculate_skill_score(["Python"], []) == 1.0
    assert calculate_skill_score([], []) == 1.0
    assert calculate_skill_score(None, None) == 1.0


def test_calculate_role_score():
    # Exact title match
    assert calculate_role_score(["Backend Engineer"], "Backend Engineer") == 1.0
    # Substring match
    assert (
        calculate_role_score(["Software Engineer"], "Senior Software Engineer") == 0.85
    )
    # Role title missing
    assert calculate_role_score(["Backend Engineer"], None) == 0.0
    # Embedding similarity integration
    score_with_emb = calculate_role_score(
        ["Backend Engineer"], "Senior Software Developer", embedding_similarity=0.8
    )
    assert 0.0 <= score_with_emb <= 1.0


def test_calculate_experience_score():
    # Candidate meets required experience
    assert calculate_experience_score(3, "3+ years") == 1.0
    assert calculate_experience_score(5, "3+ years") == 1.0
    # Candidate under-qualified
    assert calculate_experience_score(1, "2 years") == 0.5
    # Entry level requirement
    assert calculate_experience_score(0, "Entry level") == 1.0
    assert calculate_experience_score(0, "Fresher") == 1.0
    # Missing job requirement
    assert calculate_experience_score(0, None) == 1.0
    # Malformed experience data
    assert calculate_experience_score(None, "3 years") == 0.0


def test_calculate_location_score():
    # Exact location match
    assert calculate_location_score(["San Francisco"], "San Francisco, CA") == 1.0
    # Remote match
    assert calculate_location_score(["Remote"], "Remote - USA") == 1.0
    assert calculate_location_score(["San Francisco"], "Remote") == 1.0
    # No preference -> 1.0
    assert calculate_location_score([], "San Francisco") == 1.0
    # Job location missing -> 0.5
    assert calculate_location_score(["San Francisco"], None) == 0.5
    # Mismatch
    assert calculate_location_score(["New York"], "San Francisco, CA") == 0.0


def test_calculate_compensation_score_internship_mode():
    # Meets stipend expectation
    assert (
        calculate_compensation_score(3000, "$5,000 / month", mode="internship") == 1.0
    )
    # Below stipend expectation
    assert (
        calculate_compensation_score(5000, "$2,500 / month", mode="internship") == 0.5
    )
    # Unstated job stipend -> neutral 0.5
    assert calculate_compensation_score(3000, None, mode="internship") == 0.5
    # Candidate no min expectation -> 1.0
    assert (
        calculate_compensation_score(None, "$2,000 / month", mode="internship") == 1.0
    )


def test_calculate_compensation_score_job_mode():
    # Meets salary expectation
    assert (
        calculate_compensation_score(100000, "$120,000 - $150,000", mode="job") == 1.0
    )
    # Below salary expectation
    assert calculate_compensation_score(100000, "80k", mode="job") == 0.8
    # Unstated salary -> 0.5
    assert calculate_compensation_score(100000, None, mode="job") == 0.5


def test_calculate_company_signal():
    assert calculate_company_signal("Google", "greenhouse") == 1.0
    assert calculate_company_signal("Startup Inc", "generic") == 0.8
    assert calculate_company_signal(None, "lever") == 0.0
    assert calculate_company_signal("Unknown", "lever") == 0.0


def test_compute_final_score_weights():
    # All sub-scores 1.0 -> final score 1.0
    score = compute_final_score(1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
    assert score == 1.0

    # Weight verification: only skill match 1.0 -> 0.40
    skill_only = compute_final_score(1.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    assert skill_only == round(WEIGHT_SKILL, 4)

    # Weight verification: only role fit 1.0 -> 0.20
    role_only = compute_final_score(0.0, 1.0, 0.0, 0.0, 0.0, 0.0)
    assert role_only == round(WEIGHT_ROLE, 4)

    # Weight verification: only experience fit 1.0 -> 0.15
    exp_only = compute_final_score(0.0, 0.0, 1.0, 0.0, 0.0, 0.0)
    assert exp_only == round(WEIGHT_EXPERIENCE, 4)

    # Weight verification: only location 1.0 -> 0.10
    loc_only = compute_final_score(0.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    assert loc_only == round(WEIGHT_LOCATION, 4)

    # Weight verification: only compensation 1.0 -> 0.10
    comp_only = compute_final_score(0.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    assert comp_only == round(WEIGHT_COMPENSATION, 4)

    # Weight verification: only company signal 1.0 -> 0.05
    company_only = compute_final_score(0.0, 0.0, 0.0, 0.0, 0.0, 1.0)
    assert company_only == round(WEIGHT_COMPANY_SIGNAL, 4)


def test_score_job_determinism():
    user = {
        "id": str(uuid.uuid4()),
        "mode": "job",
        "master_profile": {
            "skills": ["Python", "FastAPI", "SQL"],
            "target_roles": ["Software Engineer"],
            "preferred_locations": ["Remote"],
            "years_of_experience": 2,
            "min_salary": 90000,
        },
    }

    job = Job(
        id=uuid.uuid4(),
        company_name="Tech Corp",
        role_title="Software Engineer",
        jd_text="Looking for a Python software engineer.",
        location="Remote",
        application_url="https://example.com/job/1",
        listing_type="job",
        skills_required=["Python", "FastAPI", "Docker"],
        stipend_salary="100000",
        experience_required="2 years",
        source="lever",
        is_spam=False,
    )

    res1 = score_job(user, job)
    res2 = score_job(user, job)

    assert res1["match_score"] == res2["match_score"]
    assert res1["skill_gaps"] == res2["skill_gaps"]
    assert res1["skill_matches"] == res2["skill_matches"]
    assert res1["sub_scores"] == res2["sub_scores"]


def test_score_all_jobs_integration(db_session):
    user = User(
        name="Jane Doe",
        email="jane@example.com",
        mode="job",
        master_profile={
            "skills": ["Python", "PostgreSQL"],
            "target_roles": ["Backend Developer"],
            "preferred_locations": ["Remote"],
            "min_salary": 80000,
            "experience": [{"years": 3}],
        },
    )
    db_session.add(user)
    db_session.commit()

    job1 = Job(
        company_name="Acme",
        role_title="Backend Developer",
        jd_text="Python Backend Engineer role",
        location="Remote",
        application_url="https://example.com/job/10",
        listing_type="job",
        skills_required=["Python", "PostgreSQL"],
        stipend_salary="90000",
        experience_required="3 years",
        source="greenhouse",
        is_spam=False,
    )

    job2 = Job(
        company_name="Spam Corp",
        role_title="Spam Role",
        jd_text="Spam description",
        location="Nowhere",
        application_url="https://example.com/job/11",
        listing_type="job",
        skills_required=["Everything"],
        is_spam=True,
    )

    db_session.add_all([job1, job2])
    db_session.commit()

    results = score_all_jobs(user.id, db_session, save_to_db=True)

    # Spam job should be excluded
    assert len(results) == 1
    assert results[0]["job_id"] == job1.id
    assert results[0]["match_score"] > 0.0

    # Application record should be saved in DB
    apps = db_session.query(Application).filter(Application.user_id == user.id).all()
    assert len(apps) == 1
    assert apps[0].job_id == job1.id
    assert apps[0].match_score == results[0]["match_score"]
    assert apps[0].status == "matched"


def test_score_all_jobs_dry_run(db_session):
    user = User(
        name="John Dry",
        email="john@example.com",
        mode="internship",
        master_profile={
            "skills": ["Python"],
            "target_roles": ["Intern"],
            "min_stipend": 2000,
        },
    )
    db_session.add(user)
    db_session.commit()

    job = Job(
        company_name="Intern Hub",
        role_title="Software Intern",
        jd_text="Python internship",
        location="Remote",
        application_url="https://example.com/job/20",
        listing_type="internship",
        skills_required=["Python"],
        stipend_salary="3000",
        is_spam=False,
    )
    db_session.add(job)
    db_session.commit()

    results = score_all_jobs(user.id, db_session, save_to_db=True, dry_run=True)
    assert len(results) == 1

    # Database applications should remain empty due to dry_run
    apps = db_session.query(Application).filter(Application.user_id == user.id).all()
    assert len(apps) == 0
