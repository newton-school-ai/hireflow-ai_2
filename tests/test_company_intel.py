"""
Tests for CompanyIntelAgent.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.agents.company_intel_agent import CompanyIntelAgent
from src.models.prep_guide import PrepGuide


@pytest.fixture
def mock_tavily():
    """Returns a mocked Tavily client."""
    return MagicMock()


@pytest.fixture
def agent(mock_tavily):
    """Returns a CompanyIntelAgent with a mocked Tavily client."""
    return CompanyIntelAgent(tavily_client=mock_tavily)


def test_research_known_company(agent, mock_tavily):
    """Tests research on a company with abundant data."""
    # Mock website validation
    with patch.object(agent, "_research_website", return_value="https://anthropic.com"):
        # Configure mock Tavily responses
        def mock_search(query, **kwargs):
            if "news" in query or "funding" in query:
                return {
                    "results": [
                        {
                            "title": "Anthropic raises Series C",
                            "url": "https://techcrunch.com/anthropic",
                            "content": "Anthropic raised a Series C to build LLMs in Python and Rust.",
                        }
                    ]
                }
            elif "interview" in query:
                return {
                    "results": [
                        {
                            "title": "Anthropic Interview Experience",
                            "url": "https://glassdoor.com/anthropic",
                            "content": "The interview focused on Python and system design.",
                        }
                    ]
                }
            return {"results": []}

        mock_tavily.search.side_effect = mock_search

        intel = agent.research("Anthropic", "https://anthropic.com")

        assert intel["company_name"] == "Anthropic"
        assert intel["stage"] == "growth"  # Extracted from "Series C"
        assert "Python" in intel["tech_stack"]
        assert "Rust" in intel["tech_stack"]
        assert len(intel["recent_news"]) == 1
        assert len(intel["interview_patterns"]) == 1
        assert intel["interview_patterns_note"] is None
        assert "https://anthropic.com" in intel["sources"]
        assert "https://glassdoor.com/anthropic" in intel["sources"]


def test_research_unknown_startup(agent, mock_tavily):
    """Tests research on a company with no web presence."""
    with patch.object(agent, "_research_website", return_value=None):
        mock_tavily.search.return_value = {"results": []}

        intel = agent.research("GhostStartup XYZ")

        assert intel["company_name"] == "GhostStartup XYZ"
        assert intel["stage"] == "unknown"
        assert intel["tech_stack"] == []
        assert intel["recent_news"] == []
        assert intel["interview_patterns"] == []
        assert (
            intel["interview_patterns_note"]
            == "No interview reviews found for this company"
        )
        assert intel["sources"] == []


def test_research_no_interview_reviews(agent, mock_tavily):
    """Tests when news exists but no interview patterns are found."""
    with patch.object(agent, "_research_website", return_value="https://example.com"):

        def mock_search(query, **kwargs):
            if "news" in query:
                return {
                    "results": [
                        {
                            "title": "Example Corp launches product",
                            "url": "https://news.example.com/1",
                            "content": "Using React and Node.js.",
                        }
                    ]
                }
            return {"results": []}

        mock_tavily.search.side_effect = mock_search

        intel = agent.research("Example Corp", "example.com")

        assert intel["stage"] == "unknown"
        assert "React" in intel["tech_stack"]
        assert "Node.js" in intel["tech_stack"]
        assert len(intel["recent_news"]) == 1
        assert intel["interview_patterns"] == []
        assert (
            intel["interview_patterns_note"]
            == "No interview reviews found for this company"
        )


def test_research_no_website(agent, mock_tavily):
    """Tests research when website is explicitly None."""
    with patch.object(agent, "_research_website", return_value=None):
        mock_tavily.search.return_value = {
            "results": [
                {
                    "title": "Company IPO",
                    "url": "https://news/1",
                    "content": "Going public on Nasdaq. Built with Java.",
                }
            ]
        }

        intel = agent.research("Public Corp", website=None)

        assert intel["stage"] == "enterprise"  # from "IPO" / "Nasdaq"
        assert "Java" in intel["tech_stack"]
        assert "https://news/1" in intel["sources"]


def test_persist_intel(agent):
    """Tests that intel is correctly persisted to the database."""
    mock_session = MagicMock(spec=Session)
    mock_guide = MagicMock(spec=PrepGuide)
    mock_session.get.return_value = mock_guide

    guide_id = uuid.uuid4()
    intel_data = {"company_name": "TestCorp", "stage": "startup"}

    agent._persist_intel(guide_id, intel_data, db_session=mock_session)

    mock_session.get.assert_called_once_with(PrepGuide, guide_id)
    assert mock_guide.company_intel == intel_data
    mock_session.commit.assert_called_once()
    mock_session.rollback.assert_not_called()


def test_persist_intel_db_error(agent):
    """Tests DB exception handling during persistence."""
    mock_session = MagicMock(spec=Session)
    mock_session.get.side_effect = SQLAlchemyError("DB connection failed")

    guide_id = uuid.uuid4()

    # Should not raise exception
    agent._persist_intel(guide_id, {}, db_session=mock_session)

    mock_session.rollback.assert_called_once()


def test_tavily_unavailable_graceful_degradation():
    """Tests that agent works even if Tavily client fails to initialize."""
    agent_no_tavily = CompanyIntelAgent(tavily_client=None)

    with patch.object(agent_no_tavily, "_init_tavily", return_value=None):
        agent_no_tavily._tavily = None

        with patch.object(
            agent_no_tavily, "_research_website", return_value="https://test.com"
        ):
            intel = agent_no_tavily.research("NoTavily Corp", "test.com")

            assert intel["company_name"] == "NoTavily Corp"
            assert intel["stage"] == "unknown"
            assert intel["recent_news"] == []
            assert intel["interview_patterns"] == []
            assert intel["sources"] == ["https://test.com"]
