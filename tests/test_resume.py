"""
Unit tests for Resume Tailoring Engine (RAG Pipeline).

Tests tailoring, project selection, skill prioritization, summary generation (internship vs job),
hallucination detection, JD variation behavior, edge cases, and deterministic execution.
"""

import uuid
from unittest.mock import MagicMock

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config.database import Base
from src.models.job import Job
from src.models.user import User
from src.pipelines.resume_generator import (
    EmptyJobError,
    EmptyProfileError,
    ResumeTailoringEngine,
    UserNotFoundError,
)


@pytest.fixture
def db_session():
    """In-memory SQLite session fixture for testing DB retrieval."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def sample_user_and_jobs(db_session):
    """Fixture providing a sample user profile and two distinct job descriptions in DB."""
    user = User(
        name="Alice Engineer",
        email="alice@example.com",
        mode="internship",
        master_profile={
            "skills": ["Docker", "Python", "SQL", "FastAPI", "React", "AWS"],
            "target_roles": ["Backend Developer", "Fullstack Engineer"],
            "projects": [
                {
                    "name": "E-Commerce API",
                    "description": "High performance REST API built with FastAPI and PostgreSQL",
                    "technologies": ["FastAPI", "Python", "SQL", "Docker"],
                },
                {
                    "name": "React Dashboard",
                    "description": "Interactive web dashboard with React and Tailwind CSS",
                    "technologies": ["React", "JavaScript", "Tailwind"],
                },
                {
                    "name": "Cloud Deployment Automation",
                    "description": "Automated AWS infrastructure with Terraform and Docker",
                    "technologies": ["AWS", "Docker", "Python", "Terraform"],
                },
                {
                    "name": "CLI Task Tracker",
                    "description": "Simple command-line todo tool written in Python",
                    "technologies": ["Python"],
                },
            ],
            "experience": [
                {
                    "company": "Tech Corp",
                    "title": "Software Intern",
                    "duration": "Summer 2025",
                }
            ],
            "education": [
                {
                    "degree": "B.Tech Computer Science",
                    "institution": "State University",
                    "graduation_year": 2026,
                }
            ],
        },
    )
    db_session.add(user)

    job_backend = Job(
        company_name="CloudTech",
        role_title="Backend Engineer",
        jd_text="Looking for a Python developer proficient in FastAPI, Docker, and AWS to build scalable microservices.",
        application_url="https://cloudtech.com/jobs/1",
        listing_type="job",
        skills_required=["Python", "FastAPI", "Docker", "AWS"],
    )
    db_session.add(job_backend)

    job_frontend = Job(
        company_name="WebFront Inc",
        role_title="Frontend Developer",
        jd_text="Seeking a UI developer with expertise in React, JavaScript, and Tailwind CSS to build user interfaces.",
        application_url="https://webfront.com/jobs/2",
        listing_type="internship",
        skills_required=["React", "JavaScript", "Tailwind", "CSS"],
    )
    db_session.add(job_frontend)

    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(job_backend)
    db_session.refresh(job_frontend)

    return user, job_backend, job_frontend


def test_tailor_success(db_session, sample_user_and_jobs):
    """Test successful end-to-end tailoring from DB objects."""
    user, job_backend, _ = sample_user_and_jobs
    engine = ResumeTailoringEngine()

    result = engine.tailor(user_id=user.id, job_id=job_backend.id, db=db_session)

    assert isinstance(result, dict)
    assert "summary" in result
    assert "skills" in result
    assert "projects" in result
    assert "experience" in result
    assert "education" in result

    assert len(result["projects"]) <= 3
    assert result["skills"][0] == "Python"
    assert "FastAPI" in result["skills"]


def test_skill_prioritization():
    """Test reordering of user skills based on JD priority without adding unpossessed skills."""
    engine = ResumeTailoringEngine()
    user_skills = ["Docker", "Python", "SQL", "FastAPI"]
    jd_skills = ["Python", "FastAPI", "Docker", "AWS"]

    prioritized = engine.prioritize_skills(user_skills=user_skills, jd_skills=jd_skills)

    # Expected: Python, FastAPI, Docker (from JD priority in user profile), followed by SQL
    assert prioritized == ["Python", "FastAPI", "Docker", "SQL"]
    # Ensure AWS was NOT added
    assert "AWS" not in prioritized


def test_project_selection():
    """Test ranking and selection of top 2-3 projects matching JD skills."""
    engine = ResumeTailoringEngine()
    projects = [
        {"name": "React UI", "technologies": ["React", "JavaScript"]},
        {
            "name": "Python Microservice",
            "technologies": ["Python", "FastAPI", "Docker"],
        },
        {"name": "Cloud Infra", "technologies": ["AWS", "Docker", "Terraform"]},
        {"name": "Data Analytics Script", "technologies": ["Python", "Pandas"]},
    ]
    jd_skills = ["Python", "FastAPI", "Docker"]

    selected = engine.select_projects(projects=projects, jd_skills=jd_skills, top_k=3)

    assert 2 <= len(selected) <= 3
    assert selected[0]["name"] == "Python Microservice"


def test_project_selection_with_mock_embedding():
    """Test project selection with injected embedding pipeline mock."""
    mock_emb_pipeline = MagicMock()
    # Return normalized mock vectors for JD and projects
    mock_emb_pipeline.embed_text.side_effect = lambda text: (
        np.array([1.0, 0.0], dtype=np.float32)
        if "fastapi" in text.lower()
        else np.array([0.0, 1.0], dtype=np.float32)
    )

    engine = ResumeTailoringEngine(embedding_pipeline=mock_emb_pipeline)
    projects = [
        {"name": "React Dashboard", "technologies": ["React"]},
        {"name": "FastAPI Backend", "technologies": ["FastAPI", "Python"]},
    ]

    selected = engine.select_projects(
        projects=projects,
        jd_skills=["FastAPI"],
        jd_text="Need FastAPI developer",
        top_k=2,
    )

    assert len(selected) == 2
    assert selected[0]["name"] == "FastAPI Backend"


def test_internship_summary():
    """Test summary generation in internship mode focusing on learning mindset and projects."""
    engine = ResumeTailoringEngine()
    user_profile = {
        "name": "Jane Developer",
        "skills": ["Python", "FastAPI"],
        "projects": [{"name": "AI Application"}],
    }
    job_data = {
        "role_title": "Software Engineer Intern",
        "company_name": "Acme Labs",
        "skills_required": ["Python"],
    }

    summary = engine.generate_summary(
        user_profile=user_profile, job_data=job_data, mode="internship"
    )

    assert (
        "Jane" in summary
        or "Driven" in summary
        or "learning" in summary.lower()
        or "intern" in summary.lower()
        or "Acme Labs" in summary
    )
    assert "Python" in summary
    assert "AI Application" in summary


def test_job_summary():
    """Test summary generation in job mode focusing on professional tone and experience."""
    engine = ResumeTailoringEngine()
    user_profile = {
        "name": "John Architect",
        "skills": ["Python", "FastAPI", "Docker"],
        "projects": [{"name": "Enterprise Pipeline"}],
    }
    job_data = {
        "role_title": "Senior Backend Engineer",
        "company_name": "Tech Corp",
        "skills_required": ["Python", "Docker"],
    }

    summary = engine.generate_summary(
        user_profile=user_profile, job_data=job_data, mode="job"
    )

    assert (
        "John" in summary
        or "Results-driven" in summary
        or "professional" in summary.lower()
        or "Tech Corp" in summary
    )
    assert "Python" in summary


def test_hallucination_detection():
    """Test check_hallucination returns [] for valid resume and detects fake skills/projects."""
    engine = ResumeTailoringEngine()
    user_profile = {
        "skills": ["Python", "FastAPI", "Docker"],
        "projects": [{"name": "HireFlow AI"}],
        "experience": [{"company": "Google"}],
    }

    valid_resume = {
        "skills": ["Python", "FastAPI"],
        "projects": [{"name": "HireFlow AI"}],
        "experience": [{"company": "Google"}],
    }
    assert engine.check_hallucination(valid_resume, user_profile) == []

    hallucinated_resume = {
        "skills": ["Python", "QuantumComputing", "FastAPI"],
        "projects": [{"name": "Fake Supercomputer Project"}],
        "experience": [{"company": "NASA"}],
    }
    issues = engine.check_hallucination(hallucinated_resume, user_profile)
    assert len(issues) == 3
    assert any("QuantumComputing" in item for item in issues)
    assert any("Fake Supercomputer Project" in item for item in issues)
    assert any("NASA" in item for item in issues)


def test_different_jds_produce_different_resumes(db_session, sample_user_and_jobs):
    """Test that two different JDs produce meaningfully different resumes for the same user."""
    user, job_backend, job_frontend = sample_user_and_jobs
    engine = ResumeTailoringEngine()

    resume_backend = engine.tailor(
        user_id=user.id, job_id=job_backend.id, db=db_session
    )
    resume_frontend = engine.tailor(
        user_id=user.id, job_id=job_frontend.id, db=db_session
    )

    # Skills order should differ
    assert resume_backend["skills"] != resume_frontend["skills"]
    assert resume_backend["skills"][0] == "Python"
    assert resume_frontend["skills"][0] == "React"

    # Selected projects order/content should differ
    proj_backend_names = [p["name"] for p in resume_backend["projects"]]
    proj_frontend_names = [p["name"] for p in resume_frontend["projects"]]
    assert proj_backend_names != proj_frontend_names
    assert proj_backend_names[0] == "E-Commerce API"
    assert proj_frontend_names[0] == "React Dashboard"

    # Summaries should differ
    assert resume_backend["summary"] != resume_frontend["summary"]


def test_structured_output(db_session, sample_user_and_jobs):
    """Test that output contains all required keys with deterministic structure."""
    user, job_backend, _ = sample_user_and_jobs
    engine = ResumeTailoringEngine()

    resume = engine.tailor(user_id=user.id, job_id=job_backend.id, db=db_session)

    assert isinstance(resume, dict)
    required_keys = {"summary", "skills", "projects", "experience", "education"}
    assert required_keys.issubset(resume.keys())


def test_empty_profile(db_session):
    """Test safe handling of empty user profile."""
    empty_user = User(
        name="",
        email="empty@example.com",
        master_profile={},
    )
    job = Job(
        company_name="Corp",
        role_title="Dev",
        jd_text="Requirements: Python",
        application_url="https://corp.com/1",
        listing_type="job",
    )
    db_session.add(empty_user)
    db_session.add(job)
    db_session.commit()

    engine = ResumeTailoringEngine()
    with pytest.raises(EmptyProfileError):
        engine.tailor(user_id=empty_user.id, job_id=job.id, db=db_session)


def test_empty_jd(db_session):
    """Test safe handling of empty job description."""
    user = User(
        name="Valid User",
        email="valid@example.com",
        master_profile={"skills": ["Python"]},
    )
    empty_job = Job(
        company_name="",
        role_title="",
        jd_text="",
        application_url="https://corp.com/empty",
        listing_type="job",
    )
    db_session.add(user)
    db_session.add(empty_job)
    db_session.commit()

    engine = ResumeTailoringEngine()
    with pytest.raises(EmptyJobError):
        engine.tailor(user_id=user.id, job_id=empty_job.id, db=db_session)


def test_invalid_ids(db_session):
    """Test invalid user and job IDs raise appropriate exceptions."""
    engine = ResumeTailoringEngine()
    random_uuid = str(uuid.uuid4())

    with pytest.raises(UserNotFoundError):
        engine.tailor(user_id=random_uuid, job_id=random_uuid, db=db_session)


def test_deterministic_behaviour(db_session, sample_user_and_jobs):
    """Test that running tailoring multiple times produces identical outputs."""
    user, job_backend, _ = sample_user_and_jobs
    engine = ResumeTailoringEngine()

    run1 = engine.tailor(user_id=user.id, job_id=job_backend.id, db=db_session)
    run2 = engine.tailor(user_id=user.id, job_id=job_backend.id, db=db_session)

    assert run1 == run2


def test_mocked_llm_client():
    """Test dependency injection of mock LLM client."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = "Mocked custom summary for Jane Developer at Acme."

    engine = ResumeTailoringEngine(llm_client=mock_llm)
    user_profile = {"name": "Jane Developer", "skills": ["Python"], "projects": []}
    job_data = {
        "role_title": "Backend Dev",
        "company_name": "Acme",
        "skills_required": [],
    }

    summary = engine.generate_summary(user_profile, job_data, mode="job")
    assert summary == "Mocked custom summary for Jane Developer at Acme."
    mock_llm.chat.assert_called_once()
