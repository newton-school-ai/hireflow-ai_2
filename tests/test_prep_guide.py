"""
Unit tests for PrepGuideAgent - Interview Round Predictor, Topic Analyzer,
Resource Finder, and Mock Question Generator (Issue #18).
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
    assert (
        "problem solving" in rounds[0]["focus"].lower()
        or "programming" in rounds[0]["focus"].lower()
    )
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


# ===========================================================================
# 5. Resource Finder Tests (Issue #18)
# ===========================================================================


def test_find_resources_multiple_topics(agent, monkeypatch):
    """Verify find_resources returns 2-3 resources per topic with correct structure and no duplicate URLs."""
    # Mock link accessibility check to return True
    monkeypatch.setattr(agent, "_is_url_accessible", lambda url: True)

    topics = ["TypeScript", "Docker", "LangChain"]
    result = agent.find_resources(topics)

    assert isinstance(result, dict)
    assert set(result.keys()) == set(topics)

    all_urls = []
    valid_types = {"docs", "video", "article", "course"}

    for resources in result.values():
        assert 2 <= len(resources) <= 3
        for res in resources:
            assert "title" in res
            assert "url" in res
            assert "type" in res
            assert res["type"] in valid_types
            assert res["url"].startswith("http")
            all_urls.append(res["url"])

    # Ensure no duplicate URLs across resources
    assert len(all_urls) == len(set(all_urls))


def test_find_resources_broken_link_handling(agent, monkeypatch):
    """Verify broken/inaccessible links are skipped and working alternatives returned without crashing."""
    broken_url = "https://docs.typescriptlang.org/broken-page-404"
    working_url_1 = "https://www.typescriptlang.org/docs/"
    working_url_2 = "https://www.freecodecamp.org/news/learn-typescript/"

    def mock_is_accessible(url: str) -> bool:
        return url != broken_url

    monkeypatch.setattr(agent, "_is_url_accessible", mock_is_accessible)

    def mock_fetch(topic: str, seen_urls: set[str]):
        raw_candidates = [
            {"title": "Broken Page", "url": broken_url, "type": "docs"},
            {"title": "TS Docs", "url": working_url_1, "type": "docs"},
            {"title": "TS Course", "url": working_url_2, "type": "course"},
        ]
        return [c for c in raw_candidates if mock_is_accessible(c["url"])]

    monkeypatch.setattr(agent, "_fetch_resources_for_topic", mock_fetch)

    result = agent.find_resources(["TypeScript"])
    ts_resources = result["TypeScript"]

    urls = [r["url"] for r in ts_resources]
    assert broken_url not in urls
    assert working_url_1 in urls
    assert len(ts_resources) >= 2


def test_find_resources_empty_inputs(agent):
    """Verify find_resources handles None and empty lists gracefully."""
    assert agent.find_resources(None) == {}
    assert agent.find_resources([]) == {}
    assert agent.find_resources(["", "  "]) == {}


# ===========================================================================
# 6. Mock Question Generator Tests (Issue #18)
# ===========================================================================


def test_generate_questions_internship():
    """Verify mock question generation for an internship JD produces grounded, lighter-depth questions."""
    jd_text = (
        "We are looking for an AI Engineering Intern to work with Python, LangGraph, "
        "FastAPI, and multi-agent workflows. Experience with LLMs and RAG is a plus."
    )
    mock_llm = MagicMock()
    mock_llm.chat.return_value = """
    [
        {"category": "technical", "question": "In Python and FastAPI, how would you structure a multi-agent workflow using LangGraph for the internship project?"},
        {"category": "behavioral", "question": "Can you describe a time when you learned a new AI framework like LangGraph for a class or side project?"},
        {"category": "design", "question": "How would you design a simple REST endpoint in FastAPI to receive user queries and invoke a LangGraph agent?"}
    ]
    """
    agent_inst = PrepGuideAgent(llm_client=mock_llm)

    questions = agent_inst.generate_questions(
        jd_text=jd_text,
        company_name="AgenticAI",
        listing_type="internship",
        round_types=["technical", "behavioral", "system_design"],
    )

    assert len(questions) == 3
    categories = {q["category"] for q in questions}
    assert "technical" in categories
    assert "behavioral" in categories

    # Verify questions are grounded in JD technologies
    all_text = " ".join(q["question"] for q in questions)
    assert "LangGraph" in all_text or "Python" in all_text or "FastAPI" in all_text


def test_generate_questions_fulltime():
    """Verify mock question generation for a full-time job JD produces deeper technical/design questions."""
    jd_text = (
        "Senior Backend Engineer - Scalable Agentic Systems. "
        "Must have deep expertise in Python, LangChain, PostgreSQL, Docker, and Kubernetes. "
        "You will design high-throughput asynchronous services and distributed agent orchestration."
    )
    mock_llm = MagicMock()
    mock_llm.chat.return_value = """
    [
        {"category": "technical", "question": "How would you debug state loss and race conditions in a distributed LangChain agent pipeline running across multiple Kubernetes pods?"},
        {"category": "behavioral", "question": "Describe a scenario where you had to make trade-offs between system latency and model accuracy in a production AI system."},
        {"category": "design", "question": "How would you architect a fault-tolerant, scalable backend service using Python, PostgreSQL, and Docker to support high-throughput agent workflows?"}
    ]
    """
    agent_inst = PrepGuideAgent(llm_client=mock_llm)

    questions = agent_inst.generate_questions(
        jd_text=jd_text,
        company_name="ScaleTech",
        listing_type="job",
        round_types=["technical", "system_design"],
    )

    assert len(questions) >= 2
    categories = {q["category"] for q in questions}
    assert "technical" in categories
    assert "design" in categories

    # Verify deeper system/architecture questions for full-time job
    design_questions = [q["question"] for q in questions if q["category"] == "design"]
    assert len(design_questions) > 0
    assert any(
        "architect" in q.lower() or "scalable" in q.lower() or "system" in q.lower()
        for q in design_questions
    )


def test_generate_questions_heuristic_fallback():
    """Verify generate_questions falls back gracefully to heuristic engine when LLM client is None."""
    agent_no_llm = PrepGuideAgent(llm_client=None)
    agent_no_llm.llm_client = None

    jd_text = "Software Engineer position requiring experience with Python, FastAPI, Docker, and PostgreSQL."

    questions = agent_no_llm.generate_questions(
        jd_text=jd_text,
        company_name="Acme Systems",
        listing_type="job",
        round_types=["technical", "founder"],
    )

    assert isinstance(questions, list)
    assert len(questions) > 0

    for q in questions:
        assert "category" in q
        assert "question" in q
        assert q["category"] in {"technical", "behavioral", "design"}
        assert len(q["question"]) > 10
