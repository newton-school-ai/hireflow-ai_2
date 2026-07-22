from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config.database import Base
from src.models.application import Application
from src.models.job import Job
from src.models.user import User
from src.pipelines.match_scorer import MatchScorer

# In-memory SQLite test database
TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def clean_db():
    Base.metadata.create_all(bind=engine)
    yield TestingSessionLocal
    Base.metadata.drop_all(bind=engine)


def test_multi_factor_scoring_and_skill_gaps():
    scorer = MatchScorer()

    user_data = {
        "skills": ["Python", "FastAPI", "PostgreSQL", "Docker"],
        "target_roles": ["Backend Developer", "Python Engineer"],
        "mode": "job",
        "preferred_locations": ["Remote", "New York"],
        "min_salary": 90000,
        "experience": "2 years",
    }

    job_data = {
        "role_title": "Senior Backend Developer",
        "company_name": "Tech Corp",
        "jd_text": "We are seeking a Backend Developer proficient in Python, FastAPI, and Redis. Requires 3+ years experience.",
        "skills_required": ["Python", "FastAPI", "Redis", "AWS"],
        "location": "Remote",
        "stipend_salary": "$100,000 / year",
        "experience_required": "3 years",
        "source": "lever",
    }

    result = scorer.calculate_score(user_data, job_data)

    assert "match_score" in result
    assert 0.0 <= result["match_score"] <= 1.0

    # Verify skill matches & skill gaps
    assert result["skill_matches"] == ["FastAPI", "Python"]
    assert result["skill_gaps"] == ["AWS", "Redis"]

    # Verify factor breakdown
    breakdown = result["breakdown"]
    assert breakdown["skill_score"] == 0.5  # 2 matched out of 4 required
    assert breakdown["location_score"] == 1.0  # Remote
    assert breakdown["salary_score"] == 1.0  # 100,000 >= 90,000


def test_internship_vs_job_mode():
    scorer = MatchScorer()

    user_internship = {
        "skills": ["Python"],
        "target_roles": ["Software Engineering Intern"],
        "mode": "internship",
        "preferred_locations": ["Remote"],
        "min_stipend": 2000,
        "experience": "0 years",
    }

    job_low_stipend = {
        "role_title": "Software Engineering Intern",
        "company_name": "Startup Inc",
        "jd_text": "Python internship for computer science students.",
        "skills_required": ["Python"],
        "location": "Remote",
        "stipend_salary": "$1,000 / month",
        "experience_required": "0 years",
        "source": "greenhouse",
    }

    res_internship = scorer.calculate_score(user_internship, job_low_stipend)
    assert res_internship["breakdown"]["salary_score"] < 1.0  # 1000 < 2000

    user_job = {
        "skills": ["Python"],
        "target_roles": ["Software Engineer"],
        "mode": "job",
        "preferred_locations": ["Remote"],
        "min_salary": 80000,
        "experience": "2 years",
    }

    job_full_time = {
        "role_title": "Software Engineer",
        "company_name": "Tech Inc",
        "jd_text": "Full-time Python software engineer role.",
        "skills_required": ["Python"],
        "location": "Remote",
        "stipend_salary": "$100,000 / year",
        "experience_required": "2 years",
        "source": "lever",
    }

    res_job = scorer.calculate_score(user_job, job_full_time)
    assert res_job["breakdown"]["salary_score"] == 1.0  # 100,000 >= 80,000


def test_score_user_database_persistence_and_determinism(clean_db):
    with patch("src.pipelines.match_scorer.SessionLocal", clean_db):
        db = clean_db()

        user = User(
            name="Alice Student",
            email="alice@example.com",
            mode="internship",
            master_profile={
                "skills": ["Python", "FastAPI", "SQL"],
                "target_roles": ["AI Engineer Intern"],
                "preferred_locations": ["Remote"],
                "min_stipend": 1500,
            },
        )
        db.add(user)
        db.commit()

        job1 = Job(
            company_name="AI Labs",
            role_title="AI Engineer Intern",
            jd_text="Build LLM applications using Python, FastAPI, and PyTorch.",
            skills_required=["Python", "FastAPI", "PyTorch"],
            location="Remote",
            stipend_salary="$2000 / month",
            application_url="https://example.com/job1",
            listing_type="internship",
            is_spam=False,
        )
        job2 = Job(
            company_name="Dev Corp",
            role_title="Frontend Developer",
            jd_text="React and CSS developer role.",
            skills_required=["React", "CSS"],
            location="New York",
            stipend_salary="$1000 / month",
            application_url="https://example.com/job2",
            listing_type="internship",
            is_spam=False,
        )
        job_spam = Job(
            company_name="Scam Inc",
            role_title="Spam Role",
            jd_text="Earn money fast from home.",
            skills_required=[],
            location="Remote",
            stipend_salary="$10000 / month",
            application_url="https://example.com/job_spam",
            listing_type="internship",
            is_spam=True,
        )

        db.add_all([job1, job2, job_spam])
        db.commit()

        scorer = MatchScorer()

        # 1. Dry run execution twice to verify determinism
        run1 = scorer.score_user(user.id, db=db, dry_run=True)
        run2 = scorer.score_user(user.id, db=db, dry_run=True)

        assert len(run1) == 2  # Only non-spam jobs
        assert run1 == run2  # Exact equality for determinism

        assert run1[0]["role_title"] == "AI Engineer Intern"
        assert run1[0]["match_score"] > run1[1]["match_score"]

        # 2. Real run saving to database
        db_results = scorer.score_user(user.id, db=db, dry_run=False)
        assert len(db_results) == 2

        # Check applications in DB
        apps = db.query(Application).filter(Application.user_id == user.id).all()
        assert len(apps) == 2

        app_ai = (
            db.query(Application)
            .filter(Application.user_id == user.id, Application.job_id == job1.id)
            .first()
        )
        assert app_ai is not None
        assert app_ai.match_score == run1[0]["match_score"]
        assert app_ai.skill_matches == ["FastAPI", "Python"]
        assert app_ai.skill_gaps == ["PyTorch"]
        assert app_ai.status == "matched"
