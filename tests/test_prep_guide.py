"""
Unit tests for PrepGuideAgent - Interview Round Predictor, Topic Analyzer,
Resource Finder, and JD-Specific Mock Question Generator.

Tests explicit round extraction from JD text, fallback heuristic predictions
across different listing types (internship vs. full-time) and company stages,
skill topic categorization (strong, moderate, gaps), resource finding with
Tavily (mocked) and heuristic fallback, JD-specific question generation
(LLM mocked), and resilience edge cases.

Critically:
- No live HTTP requests are made in any test; _validate_url is patched.
- Question specificity is validated by asserting concrete JD keywords appear
  in question text, not merely that questions are non-empty.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.agents.prep_guide_agent import PrepGuideAgent


@pytest.fixture
def agent():
    """PrepGuideAgent fixture without external LLM or Tavily dependency."""
    return PrepGuideAgent(llm_client=MagicMock(), tavily_client=None)


@pytest.fixture
def mock_tavily():
    """Returns a MagicMock mimicking TavilyClient.search() with valid results."""
    client = MagicMock()
    client.search.return_value = {
        "results": [
            {
                "title": "LangChain Docs",
                "url": "https://python.langchain.com/docs/introduction/",
            },
            {
                "title": "LangChain GitHub",
                "url": "https://github.com/langchain-ai/langchain",
            },
            {
                "title": "LangChain Tutorial",
                "url": "https://realpython.com/langchain-tutorial",
            },
            {"title": "Extra Result", "url": "https://example.com/langchain-extra"},
        ]
    }
    return client


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
# 5. Resource Finder Tests
# ===========================================================================


def test_find_resources_returns_valid_structure(mock_tavily):
    """Tavily search returns well-formed results; all required fields present."""
    agent = PrepGuideAgent(llm_client=MagicMock(), tavily_client=mock_tavily)

    # Patch URL validation to always pass — no live HTTP calls in tests.
    with patch.object(agent, "_validate_url", return_value=True):
        resources = agent.find_resources(["LangChain"])

    assert "LangChain" in resources
    links = resources["LangChain"]
    assert 2 <= len(links) <= 3, f"Expected 2-3 links, got {len(links)}"

    for link in links:
        assert "title" in link, "Each resource must have a 'title' field"
        assert "url" in link, "Each resource must have a 'url' field"
        assert "type" in link, "Each resource must have a 'type' field"
        assert link["title"], "Title must be non-empty"
        assert link["url"].startswith("http"), "URL must be a valid http(s) address"
        assert link["type"] in {"docs", "video", "course", "article"}


def test_find_resources_skips_broken_links(mock_tavily):
    """Inaccessible URLs are discarded; only validated URLs are returned."""
    # 4 Tavily candidates; 2 will fail URL validation (containing 'broken').
    mock_tavily.search.return_value = {
        "results": [
            {"title": "Broken Link A", "url": "https://broken-a.example.com/"},
            {
                "title": "Good Link 1",
                "url": "https://python.langchain.com/docs/introduction/",
            },
            {"title": "Broken Link B", "url": "https://broken-b.example.com/"},
            {
                "title": "Good Link 2",
                "url": "https://langchain-ai.github.io/langgraph/",
            },
        ]
    }
    agent = PrepGuideAgent(llm_client=MagicMock(), tavily_client=mock_tavily)

    def fake_validate(url: str, timeout: float = 5.0) -> bool:
        """Accept everything except URLs containing 'broken'."""
        return "broken" not in url

    with patch.object(agent, "_validate_url", side_effect=fake_validate):
        resources = agent.find_resources(["LangChain"])

    links = resources["LangChain"]
    returned_urls = [r["url"] for r in links]
    assert all(
        "broken" not in u for u in returned_urls
    ), "Broken URLs must be filtered out — only validated URLs should appear"
    assert len(links) >= 1


def test_find_resources_tavily_error_returns_heuristic_fallback(mock_tavily):
    """When Tavily raises, the method falls back to heuristic resources for known topics."""
    mock_tavily.search.side_effect = RuntimeError("Tavily quota exceeded")
    agent = PrepGuideAgent(llm_client=MagicMock(), tavily_client=mock_tavily)

    resources = agent.find_resources(["python"])

    assert "python" in resources
    urls = [r["url"] for r in resources["python"]]
    assert any(
        "docs.python.org" in u for u in urls
    ), "Heuristic fallback must include the canonical Python docs URL"


def test_find_resources_empty_topics(agent):
    """Empty topic list returns {} without errors."""
    with patch.object(agent, "_validate_url", return_value=True):
        result = agent.find_resources([])
    assert result == {}


def test_find_resources_no_tavily_returns_heuristic_for_known_topic():
    """When Tavily is unavailable, heuristic resources are returned for known topics."""
    agent = PrepGuideAgent(llm_client=MagicMock(), tavily_client=None)
    agent._tavily = None  # force heuristic path explicitly

    resources = agent.find_resources(["langchain"])

    assert "langchain" in resources
    urls = [r["url"] for r in resources["langchain"]]
    assert any(
        "langchain" in u.lower() for u in urls
    ), "Heuristic fallback for 'langchain' must include its official docs URL"


def test_find_resources_unknown_topic_returns_empty_not_fabricated():
    """An unknown topic with no Tavily returns [] — never fabricated URLs."""
    agent = PrepGuideAgent(llm_client=MagicMock(), tavily_client=None)
    agent._tavily = None  # force heuristic path

    result = agent.find_resources(["XQuantumFuzzyTech9000"])
    links = result.get("XQuantumFuzzyTech9000", [])

    assert links == [], (
        "Unknown topics must degrade to an empty list — "
        "fabricated or search-engine URLs are not acceptable"
    )


def test_find_resources_infers_resource_type():
    """_infer_resource_type correctly classifies docs, video, course, and article URLs."""
    agent = PrepGuideAgent(llm_client=MagicMock(), tavily_client=None)
    assert agent._infer_resource_type("https://docs.python.org/3/") == "docs"
    assert agent._infer_resource_type("https://www.youtube.com/watch?v=abc") == "video"
    assert agent._infer_resource_type("https://www.udemy.com/course/python") == "course"
    assert (
        agent._infer_resource_type("https://realpython.com/some-article") == "article"
    )


# ===========================================================================
# 6. Mock Question Generator Tests
# ===========================================================================

_AGENTIC_JD = (
    "Agentic AI Intern — You will build production multi-agent systems using "
    "LangChain and LangGraph. Responsibilities include designing agent workflows, "
    "integrating RAG pipelines, and deploying Python microservices. "
    "Strong Python skills required. Experience with LangGraph state machines preferred."
)


def _make_llm_with_questions(questions: list[dict]) -> MagicMock:
    """Helper: LLM mock whose .extract() returns a pre-parsed list of question dicts."""
    llm = MagicMock()
    llm.extract.return_value = questions  # already a list — no JSON parsing needed
    return llm


def test_generate_questions_internship_specificity():
    """Questions for an LLM-backed internship must reference concrete JD concepts."""
    questions = [
        {
            "category": "technical",
            "question": "How would you use LangChain to build a RAG pipeline in Python?",
        },
        {
            "category": "technical",
            "question": "Explain how LangGraph manages state transitions in a multi-agent workflow.",
        },
        {
            "category": "behavioral",
            "question": "Describe a time you debugged a complex Python issue under time pressure.",
        },
        {
            "category": "technical",
            "question": "What are the trade-offs between LangGraph and a simple LangChain chain?",
        },
        {
            "category": "behavioral",
            "question": "How do you approach learning a new framework like LangGraph quickly?",
        },
    ]
    llm = _make_llm_with_questions(questions)
    agent = PrepGuideAgent(llm_client=llm, tavily_client=None)

    result = agent.generate_questions(
        jd_text=_AGENTIC_JD,
        company_name="AIBridge",
        listing_type="internship",
    )

    assert len(result) > 0, "Must produce at least one question"

    # JD specificity: at least 2 concrete JD concepts must appear in question text
    all_text = " ".join(q["question"].lower() for q in result)
    jd_concepts = ["langchain", "langgraph", "multi-agent", "rag", "python"]
    matched = [c for c in jd_concepts if c in all_text]
    assert len(matched) >= 2, (
        f"Questions must reference concrete JD concepts. "
        f"Matched only {matched} in: {all_text[:300]}"
    )

    # Categories must only be from the allowed set
    valid = {"technical", "behavioral", "design"}
    for q in result:
        assert q["category"] in valid, f"Invalid category: {q['category']}"


def test_generate_questions_job_deeper_than_internship():
    """Full-time job generates more questions than internship (12 vs 8)."""
    internship_qs = [
        {
            "category": "technical",
            "question": f"Internship Q{i}: How does LangGraph handle state?",
        }
        for i in range(8)
    ]
    job_qs = [
        {
            "category": "technical",
            "question": f"Job Q{i}: Design a LangGraph multi-agent pipeline.",
        }
        for i in range(12)
    ]

    intern_agent = PrepGuideAgent(
        llm_client=_make_llm_with_questions(internship_qs), tavily_client=None
    )
    job_agent = PrepGuideAgent(
        llm_client=_make_llm_with_questions(job_qs), tavily_client=None
    )

    intern_result = intern_agent.generate_questions(
        _AGENTIC_JD, listing_type="internship"
    )
    job_result = job_agent.generate_questions(_AGENTIC_JD, listing_type="job")

    assert len(job_result) > len(
        intern_result
    ), "Full-time role must produce more questions than internship"


def test_generate_questions_founder_round_maps_to_behavioral():
    """round_types=['technical','founder'] must not produce a 'founder' category.

    'founder' is a round *type*, not a question category. It must be mapped to
    'behavioral' in the prompt — every returned question must be in
    {technical, behavioral, design}.
    """
    questions = [
        {
            "category": "technical",
            "question": "How do you design LangGraph agents for fault tolerance?",
        },
        {
            "category": "behavioral",
            "question": "Tell me about a time you drove a project autonomously.",
        },
        {
            "category": "behavioral",
            "question": "How do you handle ambiguity when requirements change?",
        },
    ]
    llm = _make_llm_with_questions(questions)
    agent = PrepGuideAgent(llm_client=llm, tavily_client=None)

    result = agent.generate_questions(
        jd_text=_AGENTIC_JD,
        company_name="AIBridge",
        listing_type="internship",
        round_types=["technical", "founder"],
    )

    valid_categories = {"technical", "behavioral", "design"}
    for q in result:
        assert (
            q["category"] in valid_categories
        ), f"'founder' round_type must not produce a 'founder' category; got: {q['category']}"

    # Verify the prompt passed to the LLM listed 'behavioral' (not 'founder') as a category
    prompt_arg = llm.extract.call_args[0][0]
    # The categories line appears after "Distribute questions across these categories only:"
    categories_line = prompt_arg.split("categories only:")[1].split("\n")[0]
    assert (
        "founder" not in categories_line
    ), "The LLM prompt must not list 'founder' as a question category"
    assert (
        "behavioral" in categories_line
    ), "The LLM prompt must map 'founder' round to 'behavioral' category"


def test_generate_questions_llm_unavailable_heuristic_fallback():
    """When llm_client is None, heuristic questions referencing JD keywords are returned."""
    agent = PrepGuideAgent(llm_client=None, tavily_client=None)

    result = agent.generate_questions(
        jd_text=_AGENTIC_JD,
        company_name="AIBridge",
        listing_type="internship",
    )

    assert len(result) > 0, "Heuristic fallback must return at least one question"
    valid = {"technical", "behavioral", "design"}
    for q in result:
        assert "category" in q and "question" in q
        assert q["category"] in valid

    # Heuristic must pick up LangChain / LangGraph from the JD text
    all_text = " ".join(q["question"].lower() for q in result)
    assert (
        "langchain" in all_text or "langgraph" in all_text
    ), "Heuristic questions must reference JD-specific technologies (langchain/langgraph)"


def test_generate_questions_llm_returns_invalid_json_falls_back():
    """When the LLM returns invalid JSON, heuristic fallback is used without raising."""
    llm = MagicMock()
    llm.extract.return_value = "this is not valid json ][["  # triggers JSONDecodeError
    agent = PrepGuideAgent(llm_client=llm, tavily_client=None)

    result = agent.generate_questions(jd_text=_AGENTIC_JD, listing_type="internship")

    assert isinstance(result, list), "Must always return a list even after LLM failure"
    assert (
        len(result) > 0
    ), "Heuristic fallback must supply questions when LLM output is garbage"


def test_generate_questions_all_three_categories_for_full_time():
    """Full-time job with default round_types returns questions across all three categories."""
    questions = [
        {
            "category": "technical",
            "question": "How does LangGraph manage agent memory?",
        },
        {
            "category": "behavioral",
            "question": "Describe an autonomous project you drove end-to-end.",
        },
        {
            "category": "design",
            "question": "Design a multi-agent orchestration layer for this role.",
        },
        {
            "category": "technical",
            "question": "Compare LangChain chains vs LangGraph graphs for long tasks.",
        },
    ]
    llm = _make_llm_with_questions(questions)
    agent = PrepGuideAgent(llm_client=llm, tavily_client=None)

    result = agent.generate_questions(jd_text=_AGENTIC_JD, listing_type="job")

    returned_categories = {q["category"] for q in result}
    assert "technical" in returned_categories
    assert "behavioral" in returned_categories
    assert "design" in returned_categories
