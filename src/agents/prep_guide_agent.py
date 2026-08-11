"""
PrepGuideAgent for HireFlow AI.

Analyzes job descriptions and candidate skills to predict interview round
structures, focus areas, durations, and preparation tips. Also categorizes
candidate skills against job requirements into strong, moderate, and gap topics.
Also provides a resource finder (Tavily-backed) and a JD-specific mock
question generator (LLM-backed) with heuristic fallbacks for both.
"""

import json
import logging
import re
from typing import Any

import httpx

from src.utils.llm_client import BaseLLMClient, get_llm_client

logger = logging.getLogger(__name__)


class ResourceSearchError(Exception):
    """Raised when resource search fails permanently and no fallback is possible."""


# ---------------------------------------------------------------------------
# Minimal curated fallback resources (used ONLY when Tavily is unavailable).
# Intentionally small — only canonical official docs for a handful of core
# topics. Unknown topics degrade to an empty list; we never fabricate URLs.
# ---------------------------------------------------------------------------
_FALLBACK_RESOURCES: dict[str, list[dict[str, str]]] = {
    "python": [
        {
            "title": "Official Python Docs",
            "url": "https://docs.python.org/3/",
            "type": "docs",
        },
        {
            "title": "Real Python Tutorials",
            "url": "https://realpython.com/",
            "type": "article",
        },
    ],
    "typescript": [
        {
            "title": "TypeScript Official Docs",
            "url": "https://www.typescriptlang.org/docs/",
            "type": "docs",
        },
    ],
    "javascript": [
        {
            "title": "MDN JavaScript Docs",
            "url": "https://developer.mozilla.org/en-US/docs/Web/JavaScript",
            "type": "docs",
        },
    ],
    "react": [
        {"title": "React Official Docs", "url": "https://react.dev/", "type": "docs"},
    ],
    "docker": [
        {
            "title": "Docker Official Docs",
            "url": "https://docs.docker.com/",
            "type": "docs",
        },
    ],
    "kubernetes": [
        {
            "title": "Kubernetes Official Docs",
            "url": "https://kubernetes.io/docs/home/",
            "type": "docs",
        },
    ],
    "langchain": [
        {
            "title": "LangChain Official Docs",
            "url": "https://python.langchain.com/docs/introduction/",
            "type": "docs",
        },
    ],
    "langgraph": [
        {
            "title": "LangGraph Official Docs",
            "url": "https://langchain-ai.github.io/langgraph/",
            "type": "docs",
        },
    ],
    "fastapi": [
        {
            "title": "FastAPI Official Docs",
            "url": "https://fastapi.tiangolo.com/",
            "type": "docs",
        },
    ],
    "postgresql": [
        {
            "title": "PostgreSQL Official Docs",
            "url": "https://www.postgresql.org/docs/",
            "type": "docs",
        },
    ],
}

# Skill cluster ontology for identifying partial / related skill overlap
SKILL_CLUSTERS: list[set[str]] = [
    # AI / ML / LLM
    {
        "python",
        "pytorch",
        "tensorflow",
        "keras",
        "scikit-learn",
        "sklearn",
        "nlp",
        "llm",
        "langchain",
        "llamaindex",
        "rag",
        "generative ai",
        "genai",
        "huggingface",
        "transformers",
        "vector db",
        "faiss",
        "chromadb",
        "pinecone",
        "qdrant",
        "pandas",
        "numpy",
        "deep learning",
        "machine learning",
        "data science",
        "openai",
        "anthropic",
        "groq",
        "gemini",
    },
    # Python backend
    {
        "python",
        "fastapi",
        "flask",
        "django",
        "tornado",
        "celery",
        "aiohttp",
        "sqlalchemy",
        "pydantic",
        "rest api",
        "graphql",
    },
    # JavaScript / TypeScript / Web frontend
    {
        "javascript",
        "typescript",
        "js",
        "ts",
        "react",
        "react.js",
        "next.js",
        "nextjs",
        "vue",
        "vue.js",
        "nuxt",
        "angular",
        "svelte",
        "html",
        "css",
        "tailwind",
        "bootstrap",
        "redux",
    },
    # Node backend
    {
        "node",
        "node.js",
        "nodejs",
        "express",
        "express.js",
        "nestjs",
        "fastify",
        "javascript",
        "typescript",
    },
    # Relational databases
    {
        "sql",
        "postgresql",
        "postgres",
        "mysql",
        "sqlite",
        "mariadb",
        "oracle",
        "sql server",
        "mssql",
        "database",
        "rdbms",
    },
    # NoSQL databases
    {
        "nosql",
        "mongodb",
        "redis",
        "dynamodb",
        "cassandra",
        "couchbase",
        "neo4j",
        "elasticsearch",
    },
    # Cloud & DevOps
    {
        "docker",
        "kubernetes",
        "k8s",
        "aws",
        "gcp",
        "azure",
        "ci/cd",
        "github actions",
        "terraform",
        "ansible",
        "linux",
        "bash",
        "shell",
        "devops",
        "cloud",
    },
    # Data engineering
    {
        "spark",
        "pyspark",
        "kafka",
        "hadoop",
        "airflow",
        "snowflake",
        "databricks",
        "dbt",
        "etl",
        "data engineering",
        "data pipeline",
    },
    # Java ecosystem
    {
        "java",
        "spring",
        "spring boot",
        "hibernate",
        "kotlin",
        "maven",
        "gradle",
    },
    # Systems & Other languages
    {"c", "c++", "cpp", "rust", "go", "golang"},
    {"c#", ".net", "dotnet", "asp.net"},
]


class PrepGuideAgent:
    """Agent responsible for interview round prediction and topic analysis.

    Provides:
    - predict_rounds: Predicts interview process structure from JD text.
    - analyze_topics: Categorizes skills into strong / moderate / gaps.
    - find_resources: Finds learning resources per topic via Tavily search.
    - generate_questions: Generates JD-specific mock interview questions via LLM.
    """

    def __init__(
        self,
        llm_client: BaseLLMClient | None = None,
        tavily_client: Any | None = None,
    ) -> None:
        """Initializes the PrepGuideAgent.

        Args:
            llm_client: Optional LLM client for question generation and advanced
                extraction. If None, attempts to initialize from global settings
                with graceful heuristic fallback.
            tavily_client: Optional pre-built TavilyClient for resource search.
                If None, attempts to initialize from settings.tavily_api_key.
                Pass a mock here in tests to avoid live network calls.
        """
        # --- LLM client ---
        if llm_client is not None:
            self.llm_client = llm_client
        else:
            try:
                self.llm_client = get_llm_client()
            except (ImportError, ValueError, RuntimeError, KeyError) as e:
                logger.debug(f"LLM client unavailable, using heuristic engine: {e}")
                self.llm_client = None

        # --- Tavily client ---
        if tavily_client is not None:
            self._tavily = tavily_client
        else:
            self._tavily = self._init_tavily()

    # -----------------------------------------------------------------------
    # Resource Finder
    # -----------------------------------------------------------------------

    def find_resources(self, topics: list[str]) -> dict[str, list[dict]]:
        """Finds 2-3 high-quality learning resources for each preparation topic.

        Uses Tavily web search to find current, relevant learning materials.
        Falls back to curated heuristic links when Tavily is unavailable or
        returns insufficient results for a topic.

        Args:
            topics: List of technology or skill topics to search for.

        Returns:
            Mapping of topic -> list of resource dicts, each containing:
            - title (str): Human-readable resource title.
            - url   (str): Direct URL to the resource.
            - type  (str): One of 'docs', 'video', 'course', 'article'.
        """
        if not topics:
            return {}

        result: dict[str, list[dict]] = {}
        for topic in topics:
            clean_topic = (topic or "").strip()
            if not clean_topic:
                continue
            resources = self._search_topic_resources(clean_topic)
            result[clean_topic] = resources

        return result

    def _init_tavily(self) -> Any | None:
        """Attempts to build a TavilyClient from settings. Returns None on failure."""
        try:
            from src.config.settings import settings

            api_key = settings.tavily_api_key
            if not api_key or api_key.startswith("your_"):
                logger.debug(
                    "TAVILY_API_KEY not configured; resource finder will use heuristic fallback."
                )
                return None
            from tavily import TavilyClient

            return TavilyClient(api_key=api_key)
        except (ImportError, ValueError) as e:
            logger.debug(f"Tavily client init failed: {e}")
            return None

    def _search_topic_resources(self, topic: str) -> list[dict]:
        """Searches for learning resources for a single topic via Tavily or fallback."""
        if self._tavily is not None:
            try:
                return self._tavily_search(topic)
            except (RuntimeError, OSError, ValueError) as e:
                logger.warning(
                    f"Tavily search failed for '{topic}': {e}. Using heuristic fallback."
                )

        return self._heuristic_resources(topic)

    def _tavily_search(self, topic: str) -> list[dict]:
        """Executes Tavily search, validates each URL, returns up to 3 live resources.

        For every Tavily candidate we perform a lightweight HTTP HEAD check.
        Inaccessible URLs are discarded and the next candidate is tried, so
        we never surface a broken link to the caller.
        """
        query = f"learn {topic} tutorial documentation beginner guide"
        # Request extra candidates so we still reach 3 after discarding broken links.
        response = self._tavily.search(
            query=query,
            search_depth="basic",
            max_results=8,
        )
        raw_results = response.get("results", []) if isinstance(response, dict) else []

        resources: list[dict] = []
        for item in raw_results:
            if len(resources) >= 3:
                break
            url = (item.get("url") or "").strip()
            title = (item.get("title") or "").strip()
            if not url or not title:
                # Skip malformed results immediately — no network call needed.
                continue
            if not self._validate_url(url):
                logger.debug(f"Skipping inaccessible URL for '{topic}': {url}")
                continue
            resources.append(
                {
                    "title": title,
                    "url": url,
                    "type": self._infer_resource_type(url),
                }
            )

        return resources

    def _validate_url(self, url: str, timeout: float = 5.0) -> bool:
        """Returns True if the URL is reachable; False on any error or non-2xx/3xx status.

        Uses a HEAD request first (cheap), falls back to a GET if the server
        rejects HEAD. Both attempts share the same short timeout so this never
        blocks the caller for more than ~10 seconds total.

        This method is intentionally separated so tests can patch it without
        making live network connections.
        """
        headers = {"User-Agent": "HireFlow-ResourceFinder/1.0"}
        try:
            r = httpx.head(url, timeout=timeout, follow_redirects=True, headers=headers)
            if r.status_code < 400:
                return True
            # Some servers (e.g. Cloudflare) reject HEAD — try GET with stream
            r2 = httpx.get(url, timeout=timeout, follow_redirects=True, headers=headers)
            return r2.status_code < 400
        except (httpx.HTTPError, OSError):
            return False

    def _infer_resource_type(self, url: str) -> str:
        """Infers resource type from URL patterns."""
        lower = url.lower()
        video_hosts = ("youtube.com", "youtu.be", "vimeo.com", "loom.com")
        course_hosts = (
            "udemy.com",
            "coursera.org",
            "edx.org",
            "pluralsight.com",
            "scrimba.com",
            "frontendmasters.com",
            "linkedin.com/learning",
            "educative.io",
            "egghead.io",
            "codecademy.com",
            "play-with-docker.com",
            "fast.ai",
            "developers.google.com/machine-learning",
        )
        doc_patterns = (
            ".readthedocs.io",
            "/docs/",
            "/documentation",
            "docs.",
            ".github.io",
            "/api/",
            "official",
        )
        if any(h in lower for h in video_hosts):
            return "video"
        if any(h in lower for h in course_hosts):
            return "course"
        if any(p in lower for p in doc_patterns):
            return "docs"
        return "article"

    def _heuristic_resources(self, topic: str) -> list[dict]:
        """Returns a small set of curated official docs for known topics.

        This is a DEGRADATION-ONLY path used when Tavily is unavailable.
        For unknown topics we return an empty list rather than fabricating
        URLs or constructing search-engine links.
        """
        key = topic.lower().strip()

        # Direct match
        if key in _FALLBACK_RESOURCES:
            return list(_FALLBACK_RESOURCES[key])

        # Safe canonical aliases only
        alias_map: dict[str, str] = {
            "react.js": "react",
            "reactjs": "react",
            "node": "javascript",
            "node.js": "javascript",
            "nodejs": "javascript",
            "postgres": "postgresql",
            "ts": "typescript",
            "js": "javascript",
            "k8s": "kubernetes",
        }
        resolved = alias_map.get(key)
        if resolved and resolved in _FALLBACK_RESOURCES:
            return list(_FALLBACK_RESOURCES[resolved])

        # Partial substring match against the known-safe set
        for known_key, resources in _FALLBACK_RESOURCES.items():
            if known_key in key or key in known_key:
                return list(resources)

        # Unknown topic — degrade gracefully with an empty list rather than
        # fabricating URLs that may not exist.
        return []

    # -----------------------------------------------------------------------
    # JD-Specific Mock Question Generator
    # -----------------------------------------------------------------------

    def generate_questions(
        self,
        jd_text: str,
        company_name: str | None = None,
        listing_type: str = "internship",
        round_types: list[str] | None = None,
    ) -> list[dict[str, str]]:
        """Generates JD-specific mock interview questions.

        Uses the LLM to produce questions grounded in the actual job description
        content. Questions are NOT generic ('top 50 Python questions') but
        directly reference technologies, domains, and responsibilities stated
        in the JD. Falls back to heuristic keyword extraction when the LLM is
        unavailable or returns invalid output.

        Args:
            jd_text: Full text or meaningful snippet of the job description.
            company_name: Company name, used to personalize behavioral questions.
            listing_type: 'internship' produces ~8 lighter questions; 'job' or
                'full-time' produces ~12 deeper questions.
            round_types: List of round types expected (e.g. ['technical',
                'founder']). If provided, only questions for those categories
                are generated. Defaults to all categories.

        Returns:
            List of question dicts, each containing:
            - category (str): 'technical', 'behavioral', or 'design'.
            - question (str): The interview question text.
        """
        clean_jd = (jd_text or "").strip()
        company = company_name or "the company"
        l_type = (listing_type or "internship").lower().strip()
        is_internship = "intern" in l_type
        question_count = 8 if is_internship else 12

        # Determine which categories to generate
        valid_categories = {"technical", "behavioral", "design", "founder"}
        if round_types:
            # Map 'founder' round to 'behavioral' category for question purposes
            categories = [
                ("behavioral" if rt.lower() == "founder" else rt.lower())
                for rt in round_types
                if rt.lower() in valid_categories
            ]
            # Deduplicate while preserving order
            seen: set[str] = set()
            categories = [c for c in categories if not (c in seen or seen.add(c))]  # type: ignore[func-returns-value]
        else:
            categories = ["technical", "behavioral", "design"]

        if not categories:
            categories = ["technical", "behavioral", "design"]

        # --- LLM path ---
        if self.llm_client is not None:
            try:
                return self._llm_generate_questions(
                    clean_jd, company, is_internship, question_count, categories
                )
            except (TypeError, ValueError, json.JSONDecodeError) as e:
                logger.warning(
                    f"LLM question generation failed: {e}. Using heuristic fallback."
                )

        # --- Heuristic fallback ---
        return self._heuristic_questions(clean_jd, is_internship, categories)

    def _llm_generate_questions(
        self,
        jd_text: str,
        company: str,
        is_internship: bool,
        question_count: int,
        categories: list[str],
    ) -> list[dict[str, str]]:
        """Uses the LLM to generate JD-specific interview questions."""
        depth_note = (
            "These are for an internship role, so keep questions at a junior/intermediate level."
            if is_internship
            else "These are for a full-time role, so questions should be in-depth and production-focused."
        )
        categories_str = ", ".join(categories)
        prompt = f"""\
You are an expert technical interviewer preparing a candidate for a job interview.

Job Description:
---
{jd_text[:3000]}
---

Company: {company}
{depth_note}

Generate exactly {question_count} mock interview questions based DIRECTLY on the technologies,
responsibilities, and requirements stated in the job description above.

IMPORTANT RULES:
- Questions MUST reference specific technologies/tools mentioned in the JD (e.g. if JD mentions
  LangGraph, ask about LangGraph - NOT generic Python questions).
- Do NOT generate generic questions like "Tell me about yourself" or "What are your weaknesses".
- Distribute questions across these categories only: {categories_str}.
- For 'technical': ask about specific frameworks, tools, or concepts in the JD.
- For 'behavioral': ask about past experiences relevant to the role's responsibilities.
- For 'design': ask about system/architecture decisions relevant to the JD domain.

Respond with a JSON array only, no extra text:
[
  {{"category": "technical", "question": "..."}},
  {{"category": "behavioral", "question": "..."}},
  ...
]"""

        raw = self.llm_client.extract(prompt)

        # Handle both list (already parsed) and dict responses
        if isinstance(raw, list):
            questions = raw
        elif isinstance(raw, str):
            cleaned = raw.strip()
            # Strip markdown fences if present
            if cleaned.startswith("```"):
                nl = cleaned.find("\n")
                cleaned = cleaned[nl + 1 :] if nl != -1 else cleaned
            cleaned = cleaned.removesuffix("```").strip()
            questions = json.loads(cleaned)
        else:
            raise TypeError(f"Unexpected LLM response type: {type(raw)}")

        validated: list[dict[str, str]] = []
        for item in questions:
            if not isinstance(item, dict):
                continue
            category = str(item.get("category", "technical")).lower()
            question = str(item.get("question", "")).strip()
            if not question:
                continue
            # Clamp to valid categories
            if category not in {"technical", "behavioral", "design"}:
                category = "technical"
            validated.append({"category": category, "question": question})

        if not validated:
            raise ValueError("LLM returned no valid questions.")

        return validated

    def _heuristic_questions(
        self,
        jd_text: str,
        is_internship: bool,
        categories: list[str],
    ) -> list[dict[str, str]]:
        """Generates heuristic questions by extracting keywords from the JD."""
        jd_lower = jd_text.lower()
        questions: list[dict[str, str]] = []

        # Tech keyword -> question templates
        tech_question_templates: list[tuple[str, str]] = [
            (
                "langchain",
                "How would you use LangChain to build a retrieval-augmented generation (RAG) pipeline?",
            ),
            (
                "langgraph",
                "Walk me through designing a multi-agent workflow using LangGraph. How do you handle state transitions?",
            ),
            (
                "fastapi",
                "How do you handle request validation and error responses in a FastAPI application?",
            ),
            (
                "docker",
                "Describe how you would containerize a Python application using Docker and manage it in a production environment.",
            ),
            (
                "kubernetes",
                "How does Kubernetes handle pod failure and what strategies do you use for zero-downtime deployments?",
            ),
            (
                "react",
                "Explain how React's reconciliation algorithm works and when you would use useMemo vs useCallback.",
            ),
            (
                "typescript",
                "How do you design a TypeScript type system for a complex domain model? When would you use generics?",
            ),
            (
                "postgresql",
                "How do you optimize a slow PostgreSQL query? Walk through your diagnostic process.",
            ),
            (
                "aws",
                "How would you architect a serverless API on AWS that scales to handle traffic spikes?",
            ),
            (
                "machine learning",
                "How do you evaluate and select between two competing ML models for a production use case?",
            ),
            (
                "python",
                "What Python concurrency approach (asyncio, threading, multiprocessing) would you choose for an I/O-bound data pipeline and why?",
            ),
            (
                "redis",
                "How do you use Redis as a caching layer? Describe your cache invalidation strategy.",
            ),
            (
                "kafka",
                "Explain the role of Kafka consumer groups and how you handle message ordering and exactly-once semantics.",
            ),
            (
                "graphql",
                "What are the trade-offs between REST and GraphQL? In what scenarios would you choose GraphQL?",
            ),
            (
                "mongodb",
                "How do you design a MongoDB schema for a document that has complex nested relationships?",
            ),
        ]

        depth_qualifier = "as an intern" if is_internship else "in a production system"

        if "technical" in categories:
            tech_added = 0
            for keyword, question in tech_question_templates:
                if keyword in jd_lower:
                    questions.append({"category": "technical", "question": question})
                    tech_added += 1
                    if tech_added >= (3 if is_internship else 5):
                        break

            if tech_added == 0:
                # Generic fallback technical questions
                questions.append(
                    {
                        "category": "technical",
                        "question": f"Describe the most technically complex project you've worked on {depth_qualifier}. What was your specific contribution?",
                    }
                )
                questions.append(
                    {
                        "category": "technical",
                        "question": "Walk through how you debug a production issue. What tools and process do you use?",
                    }
                )

        if "behavioral" in categories:
            questions.append(
                {
                    "category": "behavioral",
                    "question": "Describe a time you had to learn a new technology quickly to meet a project deadline. How did you approach it?",
                }
            )
            questions.append(
                {
                    "category": "behavioral",
                    "question": "Tell me about a time you disagreed with a technical decision. How did you handle it?",
                }
            )
            if not is_internship:
                questions.append(
                    {
                        "category": "behavioral",
                        "question": "How do you prioritize technical debt against new feature development when timelines are tight?",
                    }
                )

        if "design" in categories and not is_internship:
            questions.append(
                {
                    "category": "design",
                    "question": "Design a scalable REST API for this role's domain. Walk through your database schema, API contract, and caching strategy.",
                }
            )
            questions.append(
                {
                    "category": "design",
                    "question": "How would you design the data pipeline for this role to handle 10x the expected traffic?",
                }
            )

        return questions

    # -----------------------------------------------------------------------
    # Round Prediction
    # -----------------------------------------------------------------------

    def predict_rounds(
        self,
        jd_text: str | None,
        company_stage: str = "startup",
        listing_type: str = "internship",
        company_name: str | None = None,
    ) -> dict[str, Any]:
        """Predicts interview rounds, types, focus areas, and durations.

        Checks the JD text for explicitly stated interview processes or stages.
        If not explicitly specified, applies heuristic predictions tailored to
        the listing type (internship vs. full-time) and company stage.

        Args:
            jd_text: Full text or snippet of the job description.
            company_stage: Company stage (e.g. 'startup', 'growth', 'enterprise').
            listing_type: 'internship' or 'job' / 'full-time'.
            company_name: Optional company name for customized tips.

        Returns:
            Dictionary containing 'round_count' and 'rounds' list.
        """
        clean_jd = (jd_text or "").strip()
        stage = (company_stage or "startup").lower().strip()
        l_type = (listing_type or "internship").lower().strip()
        company = company_name or "the company"

        # 1. Attempt explicit round extraction from JD text
        explicit_rounds = self._extract_explicit_rounds(clean_jd, company)
        if explicit_rounds:
            return {
                "round_count": len(explicit_rounds),
                "rounds": explicit_rounds,
            }

        # 2. Fallback heuristic prediction
        return self._generate_fallback_rounds(stage, l_type, company)

    def analyze_topics(
        self,
        user_skills: list[str] | None,
        jd_skills: list[str] | None,
        skill_gaps: list[str] | None = None,
    ) -> dict[str, list[str]]:
        """Categorizes JD skills against candidate skills into strong, moderate, and gap.

        - Strong: Skills present in both user profile and JD (direct matches).
        - Moderate: Skills with partial match, overlapping domain knowledge,
                    or adjacent ecosystem familiarity.
        - Gaps: Required JD skills missing from candidate profile without
                related background.

        Args:
            user_skills: List of candidate's verified skills.
            jd_skills: List of skills required or mentioned in the JD.
            skill_gaps: Optional pre-computed skill gaps from match scorer.

        Returns:
            Dict with 'strong', 'moderate', and 'gaps' skill lists.
        """
        clean_user_skills = [
            str(s).strip()
            for s in (user_skills or [])
            if s is not None and str(s).strip()
        ]
        clean_jd_skills = [
            str(s).strip()
            for s in (jd_skills or [])
            if s is not None and str(s).strip()
        ]

        user_skills_lower = {s.lower(): s for s in clean_user_skills}
        user_skills_set = set(user_skills_lower.keys())

        strong: list[str] = []
        moderate: list[str] = []
        gaps: list[str] = []

        seen_strong_lower: set[str] = set()
        seen_moderate_lower: set[str] = set()
        seen_gaps_lower: set[str] = set()

        # Deduplicate JD skills while preserving order
        unique_jd_skills: list[str] = []
        seen_jd_lower: set[str] = set()
        for s in clean_jd_skills:
            s_lower = s.lower()
            if s_lower not in seen_jd_lower:
                seen_jd_lower.add(s_lower)
                unique_jd_skills.append(s)

        # Classify each JD skill
        for jd_skill in unique_jd_skills:
            jd_lower = jd_skill.lower()

            # 1. Exact Match -> Strong
            if jd_lower in user_skills_set:
                if jd_lower not in seen_strong_lower:
                    strong.append(jd_skill)
                    seen_strong_lower.add(jd_lower)
                continue

            # 2. Substring match or superstring match -> Strong / Moderate
            # e.g., user has "React.js" and JD has "React", or user has "Python 3" and JD has "Python"
            direct_alias_match = False
            for u_lower in user_skills_lower:
                if (
                    u_lower == jd_lower
                    or (len(jd_lower) >= 3 and jd_lower in u_lower)
                    or (len(u_lower) >= 3 and u_lower in jd_lower)
                ) and self._is_equivalent_tech(u_lower, jd_lower):
                    # Check if essentially the exact same technology (e.g. react vs react.js, node vs node.js)
                    if jd_lower not in seen_strong_lower:
                        strong.append(jd_skill)
                        seen_strong_lower.add(jd_lower)
                    direct_alias_match = True
                    break

            if direct_alias_match:
                continue

            # 3. Check for partial / related knowledge in skill clusters -> Moderate
            is_moderate = False
            for cluster in SKILL_CLUSTERS:
                if jd_lower in cluster:
                    # Check if user has ANY skill in the same cluster
                    overlapping_user_skills = cluster.intersection(user_skills_set)
                    if overlapping_user_skills:
                        if jd_lower not in seen_moderate_lower:
                            moderate.append(jd_skill)
                            seen_moderate_lower.add(jd_lower)
                        is_moderate = True
                        break

            if is_moderate:
                continue

            # 4. Otherwise -> Gap
            if jd_lower not in seen_gaps_lower:
                gaps.append(jd_skill)
                seen_gaps_lower.add(jd_lower)

        # If skill_gaps was explicitly provided, ensure any additional gaps not in JD list are captured
        if skill_gaps:
            for gap in skill_gaps:
                if not gap or not str(gap).strip():
                    continue
                gap_str = str(gap).strip()
                gap_lower = gap_str.lower()
                if (
                    gap_lower not in seen_strong_lower
                    and gap_lower not in seen_moderate_lower
                    and gap_lower not in seen_gaps_lower
                ):
                    # Check if it should be moderate or gap
                    is_mod = False
                    for cluster in SKILL_CLUSTERS:
                        if gap_lower in cluster and cluster.intersection(
                            user_skills_set
                        ):
                            moderate.append(gap_str)
                            seen_moderate_lower.add(gap_lower)
                            is_mod = True
                            break
                    if not is_mod:
                        gaps.append(gap_str)
                        seen_gaps_lower.add(gap_lower)

        return {
            "strong": strong,
            "moderate": moderate,
            "gaps": gaps,
        }

    def _is_equivalent_tech(self, skill_a: str, skill_b: str) -> bool:
        """Determines if two skill strings represent equivalent technologies."""
        equiv_pairs = [
            ("react", "react.js"),
            ("reactjs", "react"),
            ("node", "node.js"),
            ("nodejs", "node"),
            ("vue", "vue.js"),
            ("vuejs", "vue"),
            ("postgres", "postgresql"),
            ("golang", "go"),
            ("k8s", "kubernetes"),
            ("js", "javascript"),
            ("ts", "typescript"),
            ("cpp", "c++"),
        ]
        a = skill_a.strip().lower()
        b = skill_b.strip().lower()
        if a == b:
            return True
        for p1, p2 in equiv_pairs:
            if (a == p1 and b == p2) or (a == p2 and b == p1):
                return True
        return False

    def _extract_explicit_rounds(
        self, jd_text: str, company: str
    ) -> list[dict[str, Any]] | None:
        """Extracts explicitly stated interview rounds from the JD text if present."""
        if not jd_text or len(jd_text) < 10:
            return None

        # Pattern 1: Look for "X rounds: round1, round2, ..." or "X rounds: [type] and [type]"
        # e.g., "2 rounds: technical and HR" or "3 rounds of interview: screening, tech, founder"
        rounds_summary_match = re.search(
            r"(\d+)\s*rounds?(?:\s+of\s+interviews?)?[:\s-]+([^\.\n]+)",
            jd_text,
            re.IGNORECASE,
        )
        if rounds_summary_match:
            count_str, description = rounds_summary_match.groups()
            try:
                declared_count = int(count_str)
            except ValueError:
                declared_count = 0

            # Split stages by 'and', ',', ';', or 'then'
            raw_stages = re.split(r"[,;&]|\band\b|\bthen\b|->", description)
            stages = [s.strip() for s in raw_stages if s.strip()]

            if stages and declared_count > 0:
                parsed_rounds = []
                for idx, stage_name in enumerate(stages[:declared_count], 1):
                    stage_type, focus, duration, tips = self._classify_stage(
                        stage_name, idx, len(stages), company
                    )
                    parsed_rounds.append(
                        {
                            "number": idx,
                            "type": stage_type,
                            "focus": focus,
                            "duration": duration,
                            "tips": tips,
                        }
                    )
                # If parsed fewer than declared count, fill in sensible remaining rounds
                while len(parsed_rounds) < declared_count:
                    next_idx = len(parsed_rounds) + 1
                    stage_type, focus, duration, tips = self._classify_stage(
                        "Technical & HR Evaluation", next_idx, declared_count, company
                    )
                    parsed_rounds.append(
                        {
                            "number": next_idx,
                            "type": stage_type,
                            "focus": focus,
                            "duration": duration,
                            "tips": tips,
                        }
                    )
                return parsed_rounds

        # Pattern 2: Explicit multi-line or numbered rounds list
        # e.g., "Round 1: ... Round 2: ..." or "Step 1: ... Step 2: ..."
        numbered_rounds = re.findall(
            r"(?:Round|Stage|Step)\s*(\d+)[:\s-]+([^\n\.\;]+)",
            jd_text,
            re.IGNORECASE,
        )
        if numbered_rounds and len(numbered_rounds) >= 2:
            parsed_rounds = []
            total = len(numbered_rounds)
            for num_str, stage_name in numbered_rounds:
                try:
                    num = int(num_str)
                except ValueError:
                    num = len(parsed_rounds) + 1
                stage_type, focus, duration, tips = self._classify_stage(
                    stage_name.strip(), num, total, company
                )
                parsed_rounds.append(
                    {
                        "number": num,
                        "type": stage_type,
                        "focus": focus,
                        "duration": duration,
                        "tips": tips,
                    }
                )
            return parsed_rounds

        return None

    def _classify_stage(
        self, stage_text: str, round_num: int, total_rounds: int, company: str
    ) -> tuple[str, str, str, str]:
        """Classifies a round text description into type, focus, duration, and tips."""
        text = stage_text.lower().strip()

        if any(w in text for w in ["screen", "hr", "recruiter", "intro", "call"]):
            return (
                "screening",
                "Background review, communication skills, and role motivation",
                "30 mins",
                f"Be ready with your 2-minute elevator pitch and articulate why {company} excites you.",
            )
        elif any(
            w in text
            for w in [
                "assignment",
                "task",
                "take-home",
                "take home",
                "project",
                "assessment",
                "oa",
                "online test",
            ]
        ):
            return (
                "assignment",
                "Practical coding task or take-home domain challenge",
                "Take-home / 60 mins",
                "Focus on clean, documented, and modular code with proper tests.",
            )
        elif any(
            w in text
            for w in [
                "tech",
                "coding",
                "dsa",
                "algo",
                "live coding",
                "problem solving",
            ]
        ):
            return (
                "technical",
                "Core programming, data structures, algorithms, and practical problem solving",
                "45-60 mins",
                "Think out loud while coding and explain trade-offs between approaches.",
            )
        elif any(
            w in text for w in ["system design", "architecture", "design", "deep dive"]
        ):
            return (
                "system_design",
                "System architecture, scalability, API design, and component trade-offs",
                "60 mins",
                "Clarify requirements first, then design high-level before diving into database and API choices.",
            )
        elif any(
            w in text
            for w in [
                "founder",
                "ceo",
                "cto",
                "leadership",
                "executive",
                "manager",
                "culture",
                "behavioral",
                "fit",
            ]
        ):
            return (
                "founder" if "founder" in text or "ceo" in text else "behavioral",
                "Leadership alignment, culture fit, ownership mindset, and long-term vision",
                "30-45 mins",
                f"Prepare 2-3 questions for leadership regarding {company}'s roadmap and tech strategy.",
            )
        else:
            return (
                "technical" if round_num == 1 else "hr_and_fit",
                stage_text.capitalize() or "Technical and domain evaluation",
                "45 mins",
                "Review core concepts on your resume and practice key technical scenarios.",
            )

    def _generate_fallback_rounds(
        self, company_stage: str, listing_type: str, company: str
    ) -> dict[str, Any]:
        """Generates fallback interview rounds based on listing type and company stage."""
        is_internship = "intern" in listing_type

        if is_internship:
            # Internship default: 1 to 2 rounds (typically 2 lightweight rounds)
            if company_stage in ["early-stage", "seed", "bootstrap"]:
                rounds = [
                    {
                        "number": 1,
                        "type": "technical_and_screening",
                        "focus": "Core programming skills, project walkthrough, and problem solving",
                        "duration": "30-45 mins",
                        "tips": "Walk through your best hands-on projects and explain your design decisions.",
                    },
                    {
                        "number": 2,
                        "type": "founder_and_fit",
                        "focus": "Learning speed, curiosity, culture fit, and startup motivation",
                        "duration": "30 mins",
                        "tips": f"Show genuine excitement for what {company} is building and ask about current challenges.",
                    },
                ]
            elif company_stage in ["enterprise", "faang", "large"]:
                rounds = [
                    {
                        "number": 1,
                        "type": "coding_assessment_and_screen",
                        "focus": "Basic data structures, algorithms, and CS fundamentals",
                        "duration": "45-60 mins",
                        "tips": "Brush up on fundamental array/string operations, time complexity, and clean code.",
                    },
                    {
                        "number": 2,
                        "type": "technical_and_behavioral",
                        "focus": "Project deep-dive, teamwork, communication, and situational fit",
                        "duration": "45 mins",
                        "tips": "Use the STAR method to describe how you tackled past challenges in team projects.",
                    },
                ]
            else:  # startup / growth / default
                rounds = [
                    {
                        "number": 1,
                        "type": "technical",
                        "focus": "Core technical skills, live coding, and project discussion",
                        "duration": "45 mins",
                        "tips": "Be ready to write clean code and explain the architecture of your recent projects.",
                    },
                    {
                        "number": 2,
                        "type": "hr_and_fit",
                        "focus": "Team fit, communication, availability, and growth mindset",
                        "duration": "30 mins",
                        "tips": f"Research {company}'s mission and prepare thoughtful questions for the interviewer.",
                    },
                ]
        else:
            # Full-time job default: 3 rounds
            if company_stage in ["early-stage", "seed", "bootstrap"]:
                rounds = [
                    {
                        "number": 1,
                        "type": "screening",
                        "focus": "Experience alignment, technical background, and role expectations",
                        "duration": "30 mins",
                        "tips": "Summarize your relevant domain experience concisely and highlight recent wins.",
                    },
                    {
                        "number": 2,
                        "type": "technical_deep_dive",
                        "focus": "System architecture, live coding, and practical problem-solving",
                        "duration": "60 mins",
                        "tips": "Focus on production readiness, trade-offs, scalability, and code maintainability.",
                    },
                    {
                        "number": 3,
                        "type": "founder_and_culture",
                        "focus": "Vision alignment, ownership, startup culture, and growth expectations",
                        "duration": "45 mins",
                        "tips": f"Demonstrate an ownership mindset and discuss how you can contribute to {company}'s roadmap.",
                    },
                ]
            elif company_stage in ["enterprise", "faang", "large"]:
                rounds = [
                    {
                        "number": 1,
                        "type": "recruiter_screen",
                        "focus": "Resume walkthrough, role fit, communication, and compensation alignment",
                        "duration": "30 mins",
                        "tips": "Clearly articulate your career trajectory and alignment with the role responsibilities.",
                    },
                    {
                        "number": 2,
                        "type": "technical_and_system_design",
                        "focus": "Data structures, algorithms, high-level system design, and scalability",
                        "duration": "60 mins",
                        "tips": "Structure your system design systematically: requirements, API, DB schema, and bottlenecks.",
                    },
                    {
                        "number": 3,
                        "type": "hiring_manager_and_behavioral",
                        "focus": "Cross-functional leadership, conflict resolution, and behavioral competencies",
                        "duration": "45 mins",
                        "tips": "Provide structured behavioral examples showcasing leadership, collaboration, and delivery.",
                    },
                ]
            else:  # growth / startup / default
                rounds = [
                    {
                        "number": 1,
                        "type": "screening",
                        "focus": "Initial technical screen and background alignment",
                        "duration": "30-45 mins",
                        "tips": "Highlight key technologies you've worked with and your past project impact.",
                    },
                    {
                        "number": 2,
                        "type": "technical_assessment",
                        "focus": "Hands-on coding, architecture, and domain-specific challenges",
                        "duration": "60 mins",
                        "tips": "Explain your problem-solving process step-by-step and write testable code.",
                    },
                    {
                        "number": 3,
                        "type": "hiring_manager_and_fit",
                        "focus": "Cultural fit, team collaboration, and technical leadership",
                        "duration": "45 mins",
                        "tips": f"Showcase your curiosity and ask engaging questions about {company}'s tech stack.",
                    },
                ]

        return {
            "round_count": len(rounds),
            "rounds": rounds,
        }
