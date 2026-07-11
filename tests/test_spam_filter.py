import pytest
from unittest.mock import MagicMock, patch

from src.agents.spam_filter import (
    SpamFilter,
    detect_skills,
)

# ---------------------------------------------------------
# SPAM CASES
# ---------------------------------------------------------


def test_spam_rockstar_ninja():
    """Classic spam: buzzwords, no company, no skills."""
    sf = SpamFilter()
    result = sf.score(
        {
            "jd_text": "We need a rockstar ninja developer. Great pay. Must be passionate.",
            "company_name": "",
            "skills_required": [],
        }
    )
    assert result["is_spam"] is True
    assert result["spam_confidence"] >= 0.7


def test_spam_unrealistic_salary():
    """Unrealistic salary claim with spam language."""
    sf = SpamFilter()
    result = sf.score(
        {
            "jd_text": "Earn $500k guaranteed! Easy money. No experience needed. Be your own boss.",
            "company_name": "",
            "skills_required": [],
        }
    )
    assert result["is_spam"] is True
    assert result["spam_confidence"] >= 0.7


def test_spam_vague_listing():
    """Extremely vague listing with no useful information."""
    sf = SpamFilter()
    result = sf.score(
        {
            "jd_text": "Dream job awaits! Work hard play hard. Unlimited salary potential.",
            "company_name": "",
            "skills_required": [],
        }
    )
    assert result["is_spam"] is True
    assert result["spam_confidence"] >= 0.7


# ---------------------------------------------------------
# LEGITIMATE SPARSE CASES
# ---------------------------------------------------------


def test_legit_sparse_startup():
    """Short but legitimate startup listing should NOT be spam."""
    sf = SpamFilter()
    result = sf.score(
        {
            "jd_text": "Looking for a Python intern to help build our data pipeline.",
            "company_name": "DataFlow Labs",
            "skills_required": ["Python"],
        }
    )
    assert result["is_spam"] is False
    assert result["spam_confidence"] < 0.7


def test_legit_sparse_backend():
    """Short backend listing with real skills should NOT be spam."""
    sf = SpamFilter()
    result = sf.score(
        {
            "jd_text": (
                "Backend engineer needed. Must know SQL, Docker, and FastAPI. "
                "Remote position."
            ),
            "company_name": "TechStartup Inc.",
            "skills_required": [],
        }
    )
    assert result["is_spam"] is False
    assert result["spam_confidence"] < 0.7


# ---------------------------------------------------------
# CONFIDENCE RANGE
# ---------------------------------------------------------


def test_confidence_always_in_range():
    """Confidence must be between 0.0 and 1.0 in all cases."""
    sf = SpamFilter()
    test_cases = [
        {"jd_text": "", "company_name": "", "skills_required": []},
        {"jd_text": "x " * 200, "company_name": "Corp", "skills_required": ["Python"]},
        {
            "jd_text": "rockstar ninja guru quick money easy money must hustle",
            "company_name": "",
            "skills_required": [],
        },
    ]
    for job in test_cases:
        result = sf.score(job)
        assert 0.0 <= result["spam_confidence"] <= 1.0


# ---------------------------------------------------------
# THRESHOLD BEHAVIOR
# ---------------------------------------------------------


def test_custom_threshold():
    """Custom threshold changes the is_spam classification."""
    job = {
        "jd_text": "Short listing.",
        "company_name": "",
        "skills_required": [],
    }

    strict = SpamFilter(threshold=0.3)
    lenient = SpamFilter(threshold=0.99)

    strict_result = strict.score(job)
    lenient_result = lenient.score(job)

    # Same confidence, different classification
    assert strict_result["spam_confidence"] == lenient_result["spam_confidence"]
    assert strict_result["is_spam"] is True
    assert lenient_result["is_spam"] is False


# ---------------------------------------------------------
# MISSING COMPANY
# ---------------------------------------------------------


def test_missing_company_increases_confidence():
    """Missing company name should increase spam confidence."""
    sf = SpamFilter()
    base_job = {
        "jd_text": "We are hiring a software engineer.",
        "skills_required": [],
    }
    with_company = sf.score({**base_job, "company_name": "Acme Corp"})
    without_company = sf.score({**base_job, "company_name": ""})

    assert without_company["spam_confidence"] > with_company["spam_confidence"]


# ---------------------------------------------------------
# SALARY DETECTION
# ---------------------------------------------------------


def test_salary_detection_500k():
    """$500k should trigger unrealistic salary signal."""
    sf = SpamFilter()
    result = sf.score(
        {
            "jd_text": "This role pays $500k per year. Apply now.",
            "company_name": "BigCo",
            "skills_required": ["Python"],
        }
    )
    # Unrealistic salary contributes, but company + skills keep it manageable
    assert result["spam_confidence"] > 0.0


def test_salary_detection_lakh():
    """'10 lakh per month' should trigger unrealistic salary signal."""
    sf = SpamFilter()
    result = sf.score(
        {
            "jd_text": "Earn 10 lakh per month working from home.",
            "company_name": "",
            "skills_required": [],
        }
    )
    assert result["spam_confidence"] >= 0.5


# ---------------------------------------------------------
# SKILLS DETECTION
# ---------------------------------------------------------


def test_detect_skills_finds_matches():
    """detect_skills should find known skills in text."""
    text = "We need experience with Python, Docker, and SQL."
    skills = detect_skills(text)
    assert "python" in skills
    assert "docker" in skills
    assert "sql" in skills


def test_detect_skills_empty_text():
    """detect_skills returns empty list for no skills text."""
    skills = detect_skills("no relevant technical terms here")
    assert skills == []


# ---------------------------------------------------------
# DATABASE RUN
# ---------------------------------------------------------


def test_run_updates_database():
    """run() should read all jobs, score them, and commit."""
    mock_job = MagicMock()
    mock_job.company_name = "TestCo"
    mock_job.jd_text = "Looking for a Python developer with SQL experience."
    mock_job.skills_required = ["Python"]

    mock_db = MagicMock()
    mock_db.query.return_value.all.return_value = [mock_job]

    with patch("src.agents.spam_filter.SessionLocal", return_value=mock_db):
        sf = SpamFilter()
        sf.run()

    # Verify fields were set
    assert mock_job.is_spam is not None
    assert isinstance(mock_job.spam_confidence, float)
    assert 0.0 <= mock_job.spam_confidence <= 1.0

    # Verify commit was called
    mock_db.commit.assert_called_once()
    mock_db.close.assert_called_once()


# ---------------------------------------------------------
# THRESHOLD VALIDATION
# ---------------------------------------------------------


def test_threshold_below_zero_raises():
    """Threshold < 0 should raise ValueError."""
    with pytest.raises(ValueError, match="threshold must be between 0 and 1"):
        SpamFilter(threshold=-0.1)


def test_threshold_above_one_raises():
    """Threshold > 1 should raise ValueError."""
    with pytest.raises(ValueError, match="threshold must be between 0 and 1"):
        SpamFilter(threshold=1.5)


# ---------------------------------------------------------
# SKILLS FALSE POSITIVE PREVENTION
# ---------------------------------------------------------


def test_detect_skills_no_false_positive_go():
    """'go' should not match inside 'going' or 'ago'."""
    skills = detect_skills("We are going to finish this a while ago.")
    assert "go" not in skills


def test_detect_skills_no_false_positive_rust():
    """'rust' should not match inside 'frustrated' or 'trust'."""
    skills = detect_skills("The frustrated engineer lost trust in the system.")
    assert "rust" not in skills
