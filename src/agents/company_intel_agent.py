"""
Company Intelligence Agent for HireFlow AI.

Researches companies using Tavily search to extract recent news, funding stage,
tech stack inferences, and interview patterns (e.g. from Glassdoor/AmbitionBox).
Gracefully handles missing data and falls back safely without fabricating info.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.config.database import SessionLocal
from src.models.prep_guide import PrepGuide

logger = logging.getLogger(__name__)


class CompanyIntelAgent:
    """Agent responsible for researching company intelligence prior to interviews."""

    def __init__(self, tavily_client: Any | None = None) -> None:
        """Initializes the CompanyIntelAgent.

        Args:
            tavily_client: Optional pre-built TavilyClient for web search.
                If None, attempts to initialize from settings.
                Pass a mock here in tests to avoid live network calls.
        """
        if tavily_client is not None:
            self._tavily = tavily_client
        else:
            self._tavily = self._init_tavily()

    def research(
        self,
        company_name: str,
        website: str | None = None,
        prep_guide_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Conducts structured research on a company.

        Executes multiple independent search phases. If one fails, it degrades
        gracefully and returns the data it could find.

        Args:
            company_name: The name of the company.
            website: Optional company website URL.
            prep_guide_id: Optional PrepGuide ID. If provided, results are
                persisted to the database.

        Returns:
            Dictionary matching the `company_intel` JSONB schema.
        """
        valid_website = self._research_website(website)
        recent_news = self._search_recent_news(company_name)
        interview_patterns = self._search_interview_patterns(company_name)

        stage = self._infer_stage(recent_news)
        tech_stack = self._infer_tech_stack(recent_news, interview_patterns)

        sources = []
        if valid_website:
            sources.append(valid_website)

        # Extract unique URLs from news and interview patterns for sources list
        for item in recent_news:
            if "url" in item and item["url"] not in sources:
                sources.append(item["url"])
        for item in interview_patterns:
            if "url" in item and item["url"] not in sources:
                sources.append(item["url"])

        intel = {
            "company_name": company_name,
            "stage": stage,
            "team_size_estimate": "unknown",  # We can't reliably infer this without specialized APIs
            "tech_stack": tech_stack,
            "recent_news": recent_news,
            "interview_patterns": interview_patterns,
            "interview_patterns_note": (
                None
                if interview_patterns
                else "No interview reviews found for this company"
            ),
            "key_people": [],  # Avoid fabricating people; could add heuristic later if needed
            "sources": sources,
            "researched_at": datetime.now(timezone.utc).isoformat(),
        }

        if prep_guide_id:
            self._persist_intel(prep_guide_id, intel)

        return intel

    def _init_tavily(self) -> Any | None:
        """Attempts to build a TavilyClient from settings. Returns None on failure."""
        try:
            from src.config.settings import settings

            api_key = settings.tavily_api_key
            if not api_key or api_key.startswith("your_"):
                logger.debug(
                    "TAVILY_API_KEY not configured; company intel will use graceful degradation."
                )
                return None
            from tavily import TavilyClient

            return TavilyClient(api_key=api_key)
        except (ImportError, ValueError) as e:
            logger.debug(f"Tavily client init failed: {e}")
            return None

    def _research_website(
        self, website: str | None, timeout: float = 5.0
    ) -> str | None:
        """Validates the website URL with a lightweight HEAD/GET request."""
        if not website:
            return None

        url = website.strip()
        if not url.startswith("http"):
            url = f"https://{url}"

        headers = {"User-Agent": "HireFlow-CompanyIntel/1.0"}
        try:
            r = httpx.head(url, timeout=timeout, follow_redirects=True, headers=headers)
            if r.status_code < 400:
                return url
            # Some servers (e.g. Cloudflare) reject HEAD — try GET with stream
            r2 = httpx.get(url, timeout=timeout, follow_redirects=True, headers=headers)
            if r2.status_code < 400:
                return url
            return None
        except (httpx.HTTPError, OSError):
            return None

    def _search_recent_news(self, company_name: str) -> list[dict[str, str]]:
        """Searches for recent news and funding events."""
        if not self._tavily:
            return []

        # Target major tech/business news sources and funding keywords
        query = f'"{company_name}" (news OR funding OR "series" OR "raise") 2025'

        try:
            response = self._tavily.search(
                query=query,
                search_depth="basic",
                max_results=5,
            )
            raw_results = (
                response.get("results", []) if isinstance(response, dict) else []
            )

            news = []
            company_words = [w.lower() for w in company_name.split() if len(w) > 2]
            if not company_words:
                company_words = [company_name.lower()]

            for item in raw_results:
                url = (item.get("url") or "").strip()
                title = (item.get("title") or "").strip()
                snippet = (item.get("content") or "").strip()
                text = title.lower() + " " + snippet.lower()

                mentions_company = any(w in text for w in company_words)

                if url and title and mentions_company:
                    news.append({"title": title, "url": url, "snippet": snippet})
            return news
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning(f"Tavily news search failed for '{company_name}': {e}")
            return []

    def _search_interview_patterns(self, company_name: str) -> list[dict[str, str]]:
        """Searches for interview experiences on Glassdoor/AmbitionBox."""
        if not self._tavily:
            return []

        query = f'"{company_name}" interview (glassdoor OR ambitionbox OR experience OR process)'

        try:
            response = self._tavily.search(
                query=query,
                search_depth="basic",
                max_results=5,
            )
            raw_results = (
                response.get("results", []) if isinstance(response, dict) else []
            )

            patterns = []
            company_words = [w.lower() for w in company_name.split() if len(w) > 2]
            if not company_words:
                company_words = [company_name.lower()]

            for item in raw_results:
                url = (item.get("url") or "").strip()
                title = (item.get("title") or "").strip()
                snippet = (item.get("content") or "").strip()
                text = title.lower() + " " + snippet.lower()

                mentions_company = any(w in text for w in company_words)

                # Only include results that seem related to interviews AND mention the company
                if url and title and "interview" in text and mentions_company:
                    source = "unknown"
                    if "glassdoor" in url.lower():
                        source = "glassdoor"
                    elif "ambitionbox" in url.lower():
                        source = "ambitionbox"

                    patterns.append({"source": source, "snippet": snippet, "url": url})
            return patterns
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning(f"Tavily interview search failed for '{company_name}': {e}")
            return []

    def _infer_stage(self, news: list[dict[str, str]]) -> str:
        """Infers company stage (startup, growth, enterprise) from news snippets."""
        combined_text = " ".join(
            [n.get("title", "") + " " + n.get("snippet", "") for n in news]
        ).lower()

        startup_keywords = ["seed", "series a", "pre-seed", "stealth"]
        growth_keywords = [
            "series b",
            "series c",
            "series d",
            "unicorn",
            "rapid growth",
        ]
        enterprise_keywords = [
            "ipo",
            "public company",
            "nasdaq",
            "nyse",
            "enterprise",
            "fortune",
        ]

        if any(k in combined_text for k in enterprise_keywords):
            return "enterprise"
        if any(k in combined_text for k in growth_keywords):
            return "growth"
        if any(k in combined_text for k in startup_keywords):
            return "startup"

        return "unknown"

    def _infer_tech_stack(
        self, news: list[dict[str, str]], interview_patterns: list[dict[str, str]]
    ) -> list[str]:
        """Infers tech stack from snippets. Only returns explicitly mentioned techs."""
        combined_text = " ".join(
            [n.get("title", "") + " " + n.get("snippet", "") for n in news]
            + [p.get("snippet", "") for p in interview_patterns]
        ).lower()

        # Fixed vocabulary of common technologies to scan for
        tech_vocabulary = [
            "python",
            "javascript",
            "typescript",
            "java",
            "c++",
            "c#",
            "go",
            "golang",
            "rust",
            "ruby",
            "react",
            "angular",
            "vue",
            "next.js",
            "node",
            "node.js",
            "express",
            "django",
            "flask",
            "fastapi",
            "aws",
            "gcp",
            "azure",
            "docker",
            "kubernetes",
            "k8s",
            "terraform",
            "postgresql",
            "mysql",
            "mongodb",
            "redis",
            "kafka",
            "rabbitmq",
            "elasticsearch",
            "machine learning",
            "pytorch",
            "tensorflow",
            "llm",
            "langchain",
        ]

        found_techs = []
        for tech in tech_vocabulary:
            # Simple word boundary check to avoid partial matches (e.g., 'go' in 'good')
            if (
                f" {tech} " in f" {combined_text} "
                or f" {tech}," in f" {combined_text} "
                or f" {tech}." in f" {combined_text} "
            ):
                # Normalize names slightly for output
                display_name = (
                    "Go" if tech == "golang" or tech == "go" else tech.title()
                )
                display_name = "Node.js" if "node" in tech else display_name
                display_name = "Kubernetes" if tech == "k8s" else display_name
                display_name = "React" if tech == "react.js" else display_name
                display_name = "AWS" if tech == "aws" else display_name
                display_name = "GCP" if tech == "gcp" else display_name
                display_name = "LLM" if tech == "llm" else display_name

                if display_name not in found_techs:
                    found_techs.append(display_name)

        return found_techs

    def _persist_intel(
        self,
        prep_guide_id: uuid.UUID,
        intel: dict,
        db_session: Session | None = None,
    ) -> None:
        """Saves intelligence to the PrepGuide record in the database."""
        close_db = db_session is None
        session = db_session or SessionLocal()

        try:
            guide = session.get(PrepGuide, prep_guide_id)
            if guide:
                guide.company_intel = intel
                session.commit()
                logger.info(f"Persisted company intel for PrepGuide {prep_guide_id}")
            else:
                logger.warning(
                    f"PrepGuide {prep_guide_id} not found for intel persistence"
                )
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Failed to persist company intel for {prep_guide_id}: {e}")
        finally:
            if close_db:
                session.close()
