import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.config.database import Base
from src.models.job import Job
from src.agents.spam_filter import SpamFilter, run_spam_filter

# SQLite memory DB configuration for testing database functionality
TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def clean_db():
    Base.metadata.create_all(bind=engine)
    yield TestingSessionLocal
    Base.metadata.drop_all(bind=engine)


# Standard mock for LLMClient
@pytest.fixture
def mock_llm_client():
    mock_client = MagicMock()
    mock_client.extract.return_value = {
        "spam_confidence": 0.1,
        "reason": "Legitimate job listing",
    }
    return mock_client


# Test 1 (Spam): Missing company name
def test_spam_missing_company(mock_llm_client):
    with patch("src.agents.spam_filter.get_llm_client", return_value=mock_llm_client):
        sf = SpamFilter(threshold=0.7)
        job_data = {
            "company_name": "",
            "role_title": "Software Engineer Intern",
            "jd_text": "We are seeking a Python Intern to help construct modern web applications. Candidate must know Django.",
            "skills_required": ["Python", "Django"],
            "stipend_salary": "$15/hr",
        }
        score = sf.score(job_data)
        assert score == 1.0
        assert sf.is_spam(score) is True


# Test 2 (Spam): JD under 50 words
def test_spam_short_description(mock_llm_client):
    with patch("src.agents.spam_filter.get_llm_client", return_value=mock_llm_client):
        sf = SpamFilter(threshold=0.7)
        job_data = {
            "company_name": "Tech Corp",
            "role_title": "Developer",
            "jd_text": "Apply now for a fast developer job. Good pay.",  # 9 words
            "skills_required": [],
            "stipend_salary": "$20/hr",
        }
        score = sf.score(job_data)
        assert score == 1.0
        assert sf.is_spam(score) is True


# Test 3 (Spam): Unrealistic salary/MLM/get-rich-quick claims
def test_spam_unrealistic_salary(mock_llm_client):
    with patch("src.agents.spam_filter.get_llm_client", return_value=mock_llm_client):
        sf = SpamFilter(threshold=0.7)
        # JD text must be >= 50 words to avoid hitting the "JD under 50 words" rule.
        jd_text = (
            "Get rich quick with our special program! Earn $10,000/week guaranteed from home with no previous "
            "experience needed. Join today and start making passive income immediately. Payout daily to your "
            "account. This is the best opportunity for anyone looking to make money fast on the internet "
            "without any hard work. Apply now."
        )
        job_data = {
            "company_name": "Wealth Creators",
            "role_title": "Work from Home Representative",
            "jd_text": jd_text,
            "skills_required": ["Marketing"],
            "stipend_salary": "$10,000/week",
        }
        score = sf.score(job_data)
        assert score >= 0.7
        assert sf.is_spam(score) is True


# Test 4 (Legitimate): Legitimate short JD (e.g. 60 words)
def test_legitimate_short_jd(mock_llm_client):
    mock_llm_client.extract.return_value = {
        "spam_confidence": 0.15,
        "reason": "Legitimate short listing for an early-stage startup",
    }
    with patch("src.agents.spam_filter.get_llm_client", return_value=mock_llm_client):
        sf = SpamFilter(threshold=0.7)
        # Legitimate 60-word JD
        jd_text = (
            "We are a newly funded AI startup looking for a Python Software Engineering Intern. "
            "In this role, you will assist with building and deploying our FastAPI backend, "
            "writing automated tests, and integrating database pipelines. We use PostgreSQL "
            "and LangChain. This is a part-time remote position with a flexible schedule. "
            "Apply now to join us."
        )
        job_data = {
            "company_name": "DeepMind Labs",
            "role_title": "AI Engineering Intern",
            "jd_text": jd_text,
            "skills_required": ["Python", "FastAPI", "PostgreSQL"],
            "stipend_salary": "$25/hr",
        }
        score = sf.score(job_data)
        assert score < 0.7
        assert sf.is_spam(score) is False


# Test 5 (Legitimate): Legitimate sparse JD with valid company and skill keywords
def test_legitimate_sparse_jd(mock_llm_client):
    mock_llm_client.extract.return_value = {
        "spam_confidence": 0.2,
        "reason": "Legitimate sparse listing",
    }
    with patch("src.agents.spam_filter.get_llm_client", return_value=mock_llm_client):
        sf = SpamFilter(threshold=0.7)
        # Sparse but legitimate JD (> 50 words)
        jd_text = (
            "TechInnovate is hiring a Junior Software Engineer. We need help building our web platform. "
            "Requirements: Python experience, familiarity with HTML/CSS, and standard SQL databases. "
            "This is a full-time position located in Chicago. We offer competitive benefits and "
            "professional growth opportunities. Please submit your application with a copy of your resume."
        )
        job_data = {
            "company_name": "TechInnovate",
            "role_title": "Junior Software Engineer",
            "jd_text": jd_text,
            "skills_required": ["Python", "HTML", "SQL"],
            "stipend_salary": "Competitive",
        }
        score = sf.score(job_data)
        assert score < 0.7
        assert sf.is_spam(score) is False


# Test 6: Bulk processing run_spam_filter database update
def test_run_spam_filter_db_update(clean_db, mock_llm_client):
    mock_llm_client.extract.return_value = {
        "spam_confidence": 0.05,
        "reason": "Good listing",
    }

    with patch(
        "src.agents.spam_filter.get_llm_client", return_value=mock_llm_client
    ), patch("src.agents.spam_filter.SessionLocal", clean_db):

        db = clean_db()

        # Legitimate job
        job_good = Job(
            company_name="Google",
            role_title="Software Engineer",
            jd_text=(
                "A very long job description that will definitely pass the length check as it has more "
                "than fifty words and describes all requirements for a software engineer role in detail. "
                "We need someone who is passionate about coding, willing to learn new technologies, "
                "and works well in a collaborative team environment. You will be responsible for "
                "writing clean, testable, and efficient code for our core microservices and APIs."
            ),
            skills_required=["Python", "Go"],
            stipend_salary="150k",
            application_url="https://careers.google.com/jobs/1",
            listing_type="job",
        )

        # Spam job (missing company name)
        job_spam = Job(
            company_name="",
            role_title="Spam Role",
            jd_text="Earn money fast! Ninja rockstar work from home! Daily payout!",
            skills_required=[],
            stipend_salary="1000/day",
            application_url="https://scam.com/jobs/1",
            listing_type="job",
        )

        db.add(job_good)
        db.add(job_spam)
        db.commit()
        db.close()

        # Run the bulk update
        run_spam_filter()

        # Verify updates in DB
        db = clean_db()
        try:
            db_good = (
                db.query(Job)
                .filter_by(application_url="https://careers.google.com/jobs/1")
                .first()
            )
            assert db_good is not None
            assert db_good.is_spam is False
            assert db_good.spam_confidence < 0.7

            db_spam = (
                db.query(Job)
                .filter_by(application_url="https://scam.com/jobs/1")
                .first()
            )
            assert db_spam is not None
            assert db_spam.is_spam is True
            assert db_spam.spam_confidence == 1.0
        finally:
            db.close()
