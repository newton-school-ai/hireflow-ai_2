"""
Unit tests for PrepGuideAgent - Interview Round Predictor and Topic Analyzer.

Tests explicit round extraction from JD text, fallback heuristic predictions
across different listing types (internship vs. full-time) and company stages,
skill topic categorization (strong, moderate, gaps), and resilience edge cases.
"""

from unittest.mock import MagicMock

import pytest

from src.agents.prep_guide_agent import PrepGuideAgent


@pytest.fixture
def agent():
    """PrepGuideAgent fixture without external LLM dependency."""
    return PrepGuideAgent(llm_client=MagicMock())


# ===========================================================================
# 1. Round Prediction Tests - Explicit Process in JD
# ===========================================================================


def test_predict_rounds_explicit_two_rounds(agent):
    """Verify explicit '2 rounds: technical and HR' is extracted correctly."""
    jd_text = (
        "We are looking for a Software Engineer Intern. "
        "Our interview process has 2 rounds: technical and HR. "
        "Must be proficient in Python and SQL."
    )
    result = agent.predict_rounds(
        jd_text=jd_text,
        company_stage="startup",
        listing_type="internship",
        company_name="TechVentures",
    )

    assert result["round_count"] == 2
    rounds = result["rounds"]
    assert len(rounds) == 2

    assert rounds[0]["number"] == 1
    assert rounds[0]["type"] == "technical"
    assert "problem solving" in rounds[0]["focus"].lower() or "programming" in rounds[0]["focus"].lower()
    assert rounds[0]["duration"]

    assert rounds[1]["number"] == 2
    assert rounds[1]["type"] in ["screening", "hr", "hr_and_fit"]
    assert "TechVentures" in rounds[1]["tips"] or "excites you" in rounds[1]["tips"]


def test_predict_rounds_explicit_numbered_rounds(agent):
    """Verify explicit numbered rounds (Round 1, Round 2, Round 3) are extracted."""
    jd_text = """
    Hiring Process:
    Round 1: Online Coding Assessment
    Round 2: Technical Deep Dive & System Design
    Round 3: Founder & Leadership Round
    """
    result = agent.predict_rounds(
        jd_text=jd_text,
        company_stage="startup",
        listing_type="job",
        company_name="Acme AI",
    )

    assert result["round_count"] == 3
    rounds = result["rounds"]
    assert len(rounds) == 3

    assert rounds[0]["number"] == 1
    assert rounds[0]["type"] == "assignment"

    assert rounds[1]["number"] == 2
    assert rounds[1]["type"] in ["technical", "system_design"]

    assert rounds[2]["number"] == 3
    assert rounds[2]["type"] == "founder"


def test_predict_rounds_explicit_assignment_process(agent):
    """Verify JDs specifying take-home assignments are classified appropriately."""
    jd_text = (
        "Process: 2 rounds: take-home assignment and founder chat. "
        "Looking for an autonomous builder."
    )
    result = agent.predict_rounds(jd_text=jd_text, company_stage="early-stage")
    assert result["round_count"] == 2
    assert result["rounds"][0]["type"] == "assignment"
    assert result["rounds"][1]["type"] == "founder"


# ===========================================================================
# 2. Round Prediction Tests - Fallback / Implicit Process (No process in JD)
# ===========================================================================


def test_predict_rounds_fallback_internship(agent):
    """Verify internship listings without explicit process default to 1-2 rounds."""
    jd_text = (
        "Looking for an enthusiastic Backend Developer Intern to join our team. "
        "You will build APIs in FastAPI and manage PostgreSQL databases."
    )
    result = agent.predict_rounds(
        jd_text=jd_text,
        company_stage="startup",
        listing_type="internship",
    )

    # Acceptance criteria: Internship predictions default to 1 to 2 rounds
    assert 1 <= result["round_count"] <= 2
    assert len(result["rounds"]) == result["round_count"]
    # Check structure
    for r in result["rounds"]:
        assert "number" in r
        assert "type" in r
        assert "focus" in r
        assert "duration" in r
        assert "tips" in r


def test_predict_rounds_fallback_full_time_job(agent):
    """Verify full-time job listings default to 3 rounds."""
    jd_text = (
        "Senior Backend Engineer needed to scale our distributed microservices architecture. "
        "Must have extensive experience with Go, Kubernetes, Kafka, and cloud platforms."
    )
    result = agent.predict_rounds(
        jd_text=jd_text,
        company_stage="growth",
        listing_type="job",
    )

    assert result["round_count"] == 3
    rounds = result["rounds"]
    assert len(rounds) == 3
    assert rounds[0]["number"] == 1
    assert rounds[1]["number"] == 2
    assert rounds[2]["number"] == 3


def test_predict_rounds_fallback_enterprise_vs_startup(agent):
    """Verify company stage variations produce tailored focus and structure."""
    jd_text = "Software Engineer position."

    # Startup job
    startup_res = agent.predict_rounds(
        jd_text=jd_text, company_stage="early-stage", listing_type="job"
    )
    assert startup_res["round_count"] == 3
    assert any("founder" in r["type"].lower() for r in startup_res["rounds"])

    # Enterprise job
    enterprise_res = agent.predict_rounds(
        jd_text=jd_text, company_stage="enterprise", listing_type="job"
    )
    assert enterprise_res["round_count"] == 3
    assert any(
        "recruiter" in r["type"].lower() or "screening" in r["type"].lower()
        for r in enterprise_res["rounds"]
    )


# ===========================================================================
# 3. Topic Analysis Tests - Categorization into Strong, Moderate, Gaps
# ===========================================================================


def test_analyze_topics_exact_and_clusters(agent):
    """Verify topic analysis accurately categorizes direct match, related, and gaps."""
    user_skills = ["Python", "FastAPI", "LangChain"]
    jd_skills = ["Python", "LangChain", "TypeScript", "Docker", "RAG"]
    skill_gaps = ["TypeScript", "Docker"]

    topics = agent.analyze_topics(
        user_skills=user_skills,
        jd_skills=jd_skills,
        skill_gaps=skill_gaps,
    )

    # Python & LangChain are exact matches
    assert "Python" in topics["strong"]
    assert "LangChain" in topics["strong"]

    # RAG is in the same AI/LLM cluster as LangChain -> moderate
    assert "RAG" in topics["moderate"]

    # TypeScript & Docker have no representation in user_skills -> gaps
    assert "TypeScript" in topics["gaps"]
    assert "Docker" in topics["gaps"]

    # Ensure no skill is duplicated across categories
    all_categorized = topics["strong"] + topics["moderate"] + topics["gaps"]
    assert len(all_categorized) == len(set(all_categorized))


def test_analyze_topics_equivalent_aliases(agent):
    """Verify technology aliases (e.g. React vs React.js, PostgreSQL vs Postgres) are strong."""
    user_skills = ["React.js", "PostgreSQL", "Node.js"]
    jd_skills = ["React", "Postgres", "Node", "AWS"]

    topics = agent.analyze_topics(
        user_skills=user_skills,
        jd_skills=jd_skills,
    )

    assert "React" in topics["strong"]
    assert "Postgres" in topics["strong"]
    assert "Node" in topics["strong"]
    assert "AWS" in topics["gaps"]


def test_analyze_topics_related_ecosystem(agent):
    """Verify related ecosystem skills (e.g., PostgreSQL -> MySQL, Docker -> Kubernetes) become moderate."""
    user_skills = ["PostgreSQL", "Docker", "JavaScript"]
    jd_skills = ["MySQL", "Kubernetes", "TypeScript", "Rust"]

    topics = agent.analyze_topics(
        user_skills=user_skills,
        jd_skills=jd_skills,
    )

    # MySQL related to PostgreSQL (Relational DB cluster)
    assert "MySQL" in topics["moderate"]
    # Kubernetes related to Docker (Cloud & DevOps cluster)
    assert "Kubernetes" in topics["moderate"]
    # TypeScript related to JavaScript (JS ecosystem cluster)
    assert "TypeScript" in topics["moderate"]
    # Rust is unrelated -> Gap
    assert "Rust" in topics["gaps"]


# ===========================================================================
# 4. Resilience and Edge Case Tests
# ===========================================================================


def test_prep_guide_empty_inputs(agent):
    """Verify methods handle None, empty strings, and empty lists gracefully without crashing."""
    # Round prediction with empty JD
    res = agent.predict_rounds(jd_text="", company_stage="", listing_type="")
    assert res["round_count"] >= 1
    assert len(res["rounds"]) == res["round_count"]

    res_none = agent.predict_rounds(jd_text=None)
    assert res_none["round_count"] >= 1

    # Topic analysis with None / empty
    topics_none = agent.analyze_topics(
        user_skills=None, jd_skills=None, skill_gaps=None
    )
    assert topics_none["strong"] == []
    assert topics_none["moderate"] == []
    assert topics_none["gaps"] == []

    topics_empty = agent.analyze_topics(
        user_skills=[], jd_skills=["Python"], skill_gaps=[]
    )
    assert topics_empty["strong"] == []
    assert topics_empty["moderate"] == []
    assert topics_empty["gaps"] == ["Python"]


def test_prep_guide_case_insensitivity(agent):
    """Verify skill case insensitivity works for matching."""
    topics = agent.analyze_topics(
        user_skills=["PYTHON", "fastapi"],
        jd_skills=["python", "FastAPI"],
    )
    assert "python" in topics["strong"]
    assert "FastAPI" in topics["strong"]
    assert topics["gaps"] == []
