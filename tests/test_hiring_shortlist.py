from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from src.agents.hiring_shortlist_agent import HiringShortlistAgent
from src.api.main import app
from src.config.database import Base
from src.models.shortlist import Shortlist

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
    """Yield a transactional session that rolls back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    yield session
    session.close()
    transaction.rollback()
    connection.close()


client = TestClient(app)


@pytest.fixture(scope="module")
def mock_embedding_pipeline():
    """A lightweight mock that avoids loading the real sentence-transformers model."""
    mock = MagicMock()
    mock.embed_text.return_value = None  # score_job gracefully handles None embeddings
    return mock


def test_fairness_no_education_penalty(mock_embedding_pipeline):
    """
    Test that a traditional candidate and a non-traditional candidate
    with the exact same practical skills receive the same or very similar score,
    proving no education penalty exists.
    """
    jd_text = "Looking for a Python developer with LangChain and RAG experience. 2 years of experience."

    traditional_candidate = {
        "name": "Alice (CS Degree)",
        "skills": ["Python", "LangChain", "RAG"],
        "experience": 2,
        "education": "BS Computer Science",
    }

    nontraditional_candidate = {
        "name": "Bob (Bootcamp)",
        "skills": ["Python", "LangChain", "RAG"],
        "experience": 2,
        "education": "Self-Taught / Bootcamp",
    }

    agent = HiringShortlistAgent(embedding_pipeline=mock_embedding_pipeline)
    result = agent.shortlist(
        jd_text=jd_text,
        applicants=[traditional_candidate, nontraditional_candidate],
        shortlist_size=2,
    )

    shortlist = result["shortlist"]
    assert len(shortlist) == 2

    score_alice = next(c["score"] for c in shortlist if "Alice" in c["name"])
    score_bob = next(c["score"] for c in shortlist if "Bob" in c["name"])

    # Since education is not a factor in Issue #10 Match Scorer, they should be exactly equal
    assert (
        score_alice == score_bob
    ), f"Fairness violation: Alice ({score_alice}) != Bob ({score_bob})"


def test_agent_json_parsing(mock_embedding_pipeline):
    agent = HiringShortlistAgent(embedding_pipeline=mock_embedding_pipeline)

    applicants = [
        {"name": "Bad Match", "skills": ["Java"], "experience": 0},
        {"name": "Good Match", "skills": ["Python", "FastAPI"], "experience": 3},
    ]

    jd = "Python backend developer with FastAPI and 3 years experience."

    result = agent.shortlist(jd_text=jd, applicants=applicants, shortlist_size=1)

    assert result["total_applicants"] == 2
    assert result["shortlist_size"] == 1
    assert len(result["shortlist"]) == 1
    assert result["shortlist"][0]["name"] == "Good Match"
    assert result["shortlist"][0]["rank"] == 1


def test_agent_csv_parsing(mock_embedding_pipeline):
    csv_path = Path(__file__).parent / "fixtures" / "sample_applicants.csv"
    agent = HiringShortlistAgent(embedding_pipeline=mock_embedding_pipeline)

    jd = "We need a Python AI engineer with LangChain and RAG experience."
    result = agent.shortlist(jd_text=jd, applicants_csv=csv_path, shortlist_size=2)

    assert result["total_applicants"] == 4
    assert len(result["shortlist"]) == 2
    # Ensure students with Python, LangChain, RAG are at the top
    top_name = result["shortlist"][0]["name"]
    assert top_name in ["Student A", "Student C", "Student D"]


def test_db_persistence(mock_embedding_pipeline, db):
    agent = HiringShortlistAgent(embedding_pipeline=mock_embedding_pipeline, db=db)
    applicants = [{"name": "Test User", "skills": ["Python"], "experience": 1}]

    agent.shortlist(
        jd_text="Python",
        applicants=applicants,
        shortlist_size=5,
        company_name="TestCorp",
        role_title="TestRole",
    )

    # Get latest
    record = db.query(Shortlist).order_by(Shortlist.created_at.desc()).first()
    assert record is not None
    assert record.company_name == "TestCorp"
    assert record.total_applicants == 1
    assert record.shortlist_size == 5
    assert len(record.candidates) == 1


def test_api_json_endpoint():
    applicants = [
        {"name": "A", "skills": ["Python"]},
        {"name": "B", "skills": ["Java"]},
    ]

    response = client.post(
        "/hiring/shortlist",
        json={
            "jd_text": "Python developer",
            "shortlist_size": 1,
            "applicants": applicants,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_applicants"] == 2
    assert len(data["shortlist"]) == 1
    assert data["shortlist"][0]["name"] == "A"


def test_api_csv_endpoint():
    csv_path = Path(__file__).parent / "fixtures" / "sample_applicants.csv"

    with open(csv_path, "rb") as f:
        response = client.post(
            "/hiring/shortlist",
            data={"jd_text": "Python LangChain", "shortlist_size": 2},
            files={"applicants_csv": ("sample.csv", f, "text/csv")},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["total_applicants"] == 4
    assert len(data["shortlist"]) == 2


def test_fewer_applicants_than_shortlist_size(mock_embedding_pipeline):
    """Edge case: shortlist_size is larger than the applicant pool."""
    agent = HiringShortlistAgent(embedding_pipeline=mock_embedding_pipeline)
    applicants = [
        {"name": "Solo Candidate", "skills": ["Python"], "experience": 1},
    ]

    result = agent.shortlist(
        jd_text="Python developer needed",
        applicants=applicants,
        shortlist_size=10,
    )

    assert result["total_applicants"] == 1
    assert result["shortlist_size"] == 10
    # Should return only the 1 applicant, not error
    assert len(result["shortlist"]) == 1
    assert result["shortlist"][0]["name"] == "Solo Candidate"
    assert result["shortlist"][0]["rank"] == 1


def test_all_low_scoring_applicants(mock_embedding_pipeline):
    """Edge case: all applicants have very low or no skill overlap with the JD."""
    agent = HiringShortlistAgent(embedding_pipeline=mock_embedding_pipeline)
    applicants = [
        {"name": "Mismatch A", "skills": ["Cooking", "Painting"], "experience": 0},
        {"name": "Mismatch B", "skills": ["Gardening"], "experience": 0},
    ]

    result = agent.shortlist(
        jd_text="Senior Kubernetes and Rust systems engineer, 10 years experience",
        applicants=applicants,
        shortlist_size=2,
    )

    assert result["total_applicants"] == 2
    assert len(result["shortlist"]) == 2
    # Both should still appear, just with low scores
    for candidate in result["shortlist"]:
        assert candidate["score"] < 0.5
        assert "name" in candidate
        assert "summary" in candidate
