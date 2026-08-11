"""
PrepGuideAgent for HireFlow AI.

Analyzes job descriptions and candidate skills to predict interview round
structures, focus areas, durations, and preparation tips. Categorizes
candidate skills against job requirements into strong, moderate, and gap topics.
Finds real, validated learning resources for candidate topics/skills.
Generates JD-grounded mock interview questions tailored to position level
(internship vs full-time) and round types.
"""

import json
import logging
import re
from typing import Any
from urllib.parse import quote_plus

from src.config.settings import settings
from src.utils.llm_client import BaseLLMClient, get_llm_client, parse_llm_json

logger = logging.getLogger(__name__)

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
        "langgraph",
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

# Fallback curated resources for popular topics
KNOWN_RESOURCES: dict[str, list[dict[str, str]]] = {
    "typescript": [
        {
            "title": "TypeScript Official Documentation & Handbook",
            "url": "https://www.typescriptlang.org/docs/",
            "type": "docs",
        },
        {
            "title": "TypeScript Language Guide",
            "url": "https://www.typescriptlang.org/docs/handbook/intro.html",
            "type": "docs",
        },
        {
            "title": "TypeScript Course for Beginners",
            "url": "https://www.freecodecamp.org/news/learn-typescript/",
            "type": "course",
        },
    ],
    "docker": [
        {
            "title": "Docker Documentation & Get Started Guide",
            "url": "https://docs.docker.com/get-started/",
            "type": "docs",
        },
        {
            "title": "Docker Official Documentation",
            "url": "https://docs.docker.com/",
            "type": "docs",
        },
        {
            "title": "Docker Tutorial for Beginners",
            "url": "https://www.freecodecamp.org/news/docker-simplified/",
            "type": "course",
        },
    ],
    "langchain": [
        {
            "title": "LangChain Python Documentation",
            "url": "https://python.langchain.com/docs/get_started/introduction",
            "type": "docs",
        },
        {
            "title": "LangChain Official Conceptual Guide",
            "url": "https://python.langchain.com/",
            "type": "docs",
        },
        {
            "title": "LangChain Crash Course",
            "url": "https://www.freecodecamp.org/news/langchain-crash-course/",
            "type": "course",
        },
    ],
    "python": [
        {
            "title": "Python Official Documentation",
            "url": "https://docs.python.org/3/",
            "type": "docs",
        },
        {
            "title": "Python Official Tutorial",
            "url": "https://docs.python.org/3/tutorial/index.html",
            "type": "docs",
        },
        {
            "title": "Python Programming Course",
            "url": "https://www.freecodecamp.org/news/python-craftsmanship/",
            "type": "course",
        },
    ],
    "react": [
        {
            "title": "React Official Documentation",
            "url": "https://react.dev/learn",
            "type": "docs",
        },
        {
            "title": "React Reference Guide",
            "url": "https://react.dev/reference/react",
            "type": "docs",
        },
        {
            "title": "React Tutorials & Course",
            "url": "https://www.freecodecamp.org/news/tag/react/",
            "type": "course",
        },
    ],
    "postgresql": [
        {
            "title": "PostgreSQL Official Documentation",
            "url": "https://www.postgresql.org/docs/",
            "type": "docs",
        },
        {
            "title": "PostgreSQL Tutorial",
            "url": "https://www.postgresqltutorial.com/",
            "type": "course",
        },
    ],
}


class PrepGuideAgent:
    """Agent responsible for interview round prediction, topic analysis, resource finding, and mock question generation."""

    def __init__(self, llm_client: BaseLLMClient | None = None) -> None:
        """Initializes the PrepGuideAgent.

        Args:
            llm_client: Optional LLM client for advanced extraction/generation.
                If None, attempts to initialize from global settings with graceful fallback.
        """
        if llm_client is not None:
            self.llm_client = llm_client
        else:
            try:
                self.llm_client = get_llm_client()
            except Exception as e:  # noqa: BLE001
                logger.debug(f"LLM client unavailable, using heuristic engine: {e}")
                self.llm_client = None

    def predict_rounds(
        self,
        jd_text: str | None,
        company_stage: str = "startup",
        listing_type: str = "internship",
        company_name: str | None = None,
    ) -> dict[str, Any]:
        """Predicts interview rounds, types, focus areas, and durations.

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
            direct_alias_match = False
            for u_lower in user_skills_lower:
                if (
                    u_lower == jd_lower
                    or (len(jd_lower) >= 3 and jd_lower in u_lower)
                    or (len(u_lower) >= 3 and u_lower in jd_lower)
                ):
                    direct_alias_match = True
                    break

            if direct_alias_match:
                if jd_lower not in seen_strong_lower:
                    strong.append(jd_skill)
                    seen_strong_lower.add(jd_lower)
                continue

            # 3. Ecosystem Cluster Match -> Moderate
            in_cluster_match = False
            for cluster in SKILL_CLUSTERS:
                if jd_lower in cluster and user_skills_set.intersection(cluster):
                    in_cluster_match = True
                    break

            if in_cluster_match:
                if jd_lower not in seen_moderate_lower:
                    moderate.append(jd_skill)
                    seen_moderate_lower.add(jd_lower)
                continue

            # 4. No Match -> Gap
            if jd_lower not in seen_gaps_lower:
                gaps.append(jd_skill)
                seen_gaps_lower.add(jd_lower)

        return {
            "strong": strong,
            "moderate": moderate,
            "gaps": gaps,
        }

    # =========================================================================
    # Issue #18: Resource Finder
    # =========================================================================

    def find_resources(
        self, topics: list[str] | None
    ) -> dict[str, list[dict[str, str]]]:
        """Finds learning resources for each specified topic or skill.

        Args:
            topics: List of skill/topic names (e.g., ['TypeScript', 'Docker', 'LangChain']).

        Returns:
            Dictionary mapping each topic to a list of 2-3 resource items:
            [
                {
                    "title": "TypeScript Documentation",
                    "url": "https://www.typescriptlang.org/docs/",
                    "type": "docs"  # 'docs', 'video', 'article', or 'course'
                }
            ]
        """
        if not topics:
            return {}

        clean_topics = [
            str(t).strip() for t in topics if t is not None and str(t).strip()
        ]
        if not clean_topics:
            return {}

        results: dict[str, list[dict[str, str]]] = {}
        seen_urls: set[str] = set()

        for topic in clean_topics:
            topic_resources = self._fetch_resources_for_topic(topic, seen_urls)
            results[topic] = topic_resources

        return results

    def _fetch_resources_for_topic(
        self, topic: str, seen_urls: set[str]
    ) -> list[dict[str, str]]:
        """Fetches and validates 2-3 resources for a single topic."""
        candidates: list[dict[str, str]] = []

        # 1. Attempt Tavily web search if configured
        if settings.tavily_api_key:
            try:
                from tavily import TavilyClient

                tavily_client = TavilyClient(api_key=settings.tavily_api_key)
                search_res = tavily_client.search(
                    query=f"{topic} official documentation tutorial guide",
                    search_depth="basic",
                    max_results=8,
                )
                raw_items = search_res.get("results", [])
                for item in raw_items:
                    url = item.get("url", "").strip()
                    title = item.get("title", "").strip() or f"{topic} Resource"
                    if url and url not in seen_urls:
                        res_type = self._classify_resource_type(url, title)
                        candidates.append(
                            {"title": title, "url": url, "type": res_type}
                        )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Tavily search failed for topic '{topic}': {e}")

        # 2. Check fallback curated resources for known topics if candidates are sparse
        topic_lower = topic.lower().strip()
        if len(candidates) < 3 and topic_lower in KNOWN_RESOURCES:
            for item in KNOWN_RESOURCES[topic_lower]:
                if item["url"] not in seen_urls:
                    candidates.append(item)

        # 3. Dynamic search query fallback if candidates are still sparse
        if len(candidates) < 2:
            candidates.extend(self._generate_fallback_candidates(topic, seen_urls))

        # 4. Filter and validate candidates (accessibility + deduplication)
        validated: list[dict[str, str]] = []
        for cand in candidates:
            url = cand["url"]
            if url in seen_urls:
                continue

            if self._is_url_accessible(url):
                seen_urls.add(url)
                validated.append(cand)
                if len(validated) >= 3:
                    break

        # If strict accessibility filtering eliminated all candidates, return candidates avoiding crash
        if not validated and candidates:
            for cand in candidates:
                if cand["url"] not in seen_urls:
                    seen_urls.add(cand["url"])
                    validated.append(cand)
                    if len(validated) >= 2:
                        break

        return validated

    def _generate_fallback_candidates(
        self, topic: str, seen_urls: set[str]
    ) -> list[dict[str, str]]:
        """Generates fallback candidate resources for arbitrary topics."""
        topic_slug = quote_plus(topic)
        topic_lower = topic.lower().replace(" ", "")

        candidates = [
            {
                "title": f"{topic} Official Documentation",
                "url": f"https://docs.{topic_lower}.org/",
                "type": "docs",
            },
            {
                "title": f"{topic} Developer Guide & Tutorials",
                "url": f"https://developer.mozilla.org/en-US/search?q={topic_slug}",
                "type": "docs",
            },
            {
                "title": f"{topic} Community Tutorials & Articles",
                "url": f"https://freecodecamp.org/news/tag/{topic_lower}/",
                "type": "course",
            },
        ]
        return [c for c in candidates if c["url"] not in seen_urls]

    def _is_url_accessible(self, url: str) -> bool:
        """Checks if a URL is accessible via HTTP HEAD/GET request.

        Gracefully handles network errors, timeouts, and non-200 responses.
        """
        if not url or not url.startswith(("http://", "https://")):
            return False

        try:
            import httpx

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            with httpx.Client(
                timeout=1.5, follow_redirects=True, headers=headers
            ) as client:
                try:
                    response = client.head(url)
                    if response.status_code < 400:
                        return True
                except Exception:  # noqa: S110, BLE001
                    pass

                response = client.get(url)
                return response.status_code < 400
        except Exception as e:  # noqa: BLE001
            logger.debug(f"URL accessibility check failed for {url}: {e}")
            return False

    def _classify_resource_type(self, url: str, title: str) -> str:
        """Classifies resource URL and title into 'docs', 'video', 'article', or 'course'."""
        url_lower = url.lower()
        title_lower = title.lower()

        if (
            any(k in url_lower for k in ["youtube.com", "youtu.be", "vimeo.com"])
            or "video" in title_lower
            or "watch" in title_lower
        ):
            return "video"

        if (
            any(
                k in url_lower
                for k in [
                    "coursera.org",
                    "udemy.com",
                    "edx.org",
                    "pluralsight.com",
                    "freecodecamp.org",
                ]
            )
            or "course" in title_lower
            or "specialization" in title_lower
            or "tutorial" in title_lower
        ):
            return "course"

        if (
            any(
                k in url_lower
                for k in [
                    "docs.",
                    "/docs",
                    "/documentation",
                    "developer.mozilla.org",
                    "python.org",
                    "typescriptlang.org",
                    "docker.com",
                    "github.io",
                ]
            )
            or "documentation" in title_lower
            or "docs" in title_lower
            or "handbook" in title_lower
            or "guide" in title_lower
        ):
            return "docs"

        return "article"

    # =========================================================================
    # Issue #18: Mock Question Generator
    # =========================================================================

    def generate_questions(
        self,
        jd_text: str | None,
        company_name: str | None = None,
        listing_type: str = "internship",
        round_types: list[str] | None = None,
    ) -> list[dict[str, str]]:
        """Generates JD-grounded mock interview questions.

        Questions are tailored to position difficulty (internship vs full-time/job)
        and categorized as 'technical', 'behavioral', or 'design'.

        Args:
            jd_text: Job description text.
            company_name: Target company name.
            listing_type: 'internship' or 'job' / 'full-time'.
            round_types: Optional list of interview round types (e.g. ['technical', 'founder']).

        Returns:
            List of dictionaries with 'category' and 'question':
            [
                {"category": "technical", "question": "..."},
                {"category": "behavioral", "question": "..."},
                {"category": "design", "question": "..."}
            ]
        """
        clean_jd = (jd_text or "").strip()
        company = (company_name or "the company").strip()
        l_type = (listing_type or "internship").lower().strip()
        rounds = [
            str(r).lower().strip()
            for r in (round_types or [])
            if r is not None and str(r).strip()
        ]

        # 1. Attempt LLM generation if client is available
        if self.llm_client is not None:
            try:
                questions = self._generate_questions_with_llm(
                    clean_jd, company, l_type, rounds
                )
                if questions:
                    return questions
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    f"LLM question generation failed, falling back to heuristic engine: {e}"
                )

        # 2. Fallback heuristic question generation grounded in JD text
        return self._generate_heuristic_questions(clean_jd, company, l_type, rounds)

    def _generate_questions_with_llm(
        self,
        jd_text: str,
        company: str,
        listing_type: str,
        rounds: list[str],
    ) -> list[dict[str, str]]:
        """Generates questions using the unified LLM client."""
        rounds_str = ", ".join(rounds) if rounds else "all rounds"
        difficulty = (
            "INTERNSHIP (Lighter difficulty, fundamentals, practical implementation, basic project context)"
            if listing_type == "internship"
            else "FULL-TIME / SENIOR JOB (Deeper technical challenges, system design, architectural trade-offs, scenario debugging)"
        )

        prompt = f"""
You are an expert technical interviewer for HireFlow AI generating mock interview questions for {company}.

Job Description:
{jd_text or 'General Software Engineering Role'}

Position Level: {difficulty}
Interview Round Focus: {rounds_str}

CRITICAL INSTRUCTIONS:
1. Questions MUST be strictly grounded in the technologies, tools, frameworks, concepts, and responsibilities mentioned in the Job Description.
2. DO NOT ask generic, superficial interview questions like "What is Python?", "Tell me about yourself", or "What are your strengths?".
3. Respect Position Level difficulty:
   - For INTERNSHIP: focus on core concepts, practical implementation, and basic project problem solving. Keep system design conceptual.
   - For FULL-TIME JOB: ask deep technical questions, trade-offs, edge-case handling, scenario debugging, and system scalability.
4. Categorize each question into exactly one of: "technical", "behavioral", or "design".
5. Return ONLY a valid JSON array of objects with keys "category" and "question":
[
  {{"category": "technical", "question": "..."}},
  {{"category": "behavioral", "question": "..."}},
  {{"category": "design", "question": "..."}}
]
"""
        raw_response = self.llm_client.chat(prompt)
        text = parse_llm_json(raw_response)

        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and "questions" in parsed:
                parsed = parsed["questions"]

            if not isinstance(parsed, list):
                return []

            validated: list[dict[str, str]] = []
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                cat = str(item.get("category", "technical")).lower().strip()
                q_text = str(item.get("question", "")).strip()

                if not q_text:
                    continue

                norm_cat = "technical"
                if "behav" in cat or "fit" in cat or "person" in cat:
                    norm_cat = "behavioral"
                elif "desig" in cat or "arch" in cat or "sys" in cat:
                    norm_cat = "design"

                validated.append({"category": norm_cat, "question": q_text})

            return self._filter_questions_by_rounds(validated, rounds)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to parse LLM JSON questions: {e}")
            return []

    def _generate_heuristic_questions(
        self,
        jd_text: str,
        company: str,
        listing_type: str,
        rounds: list[str],
    ) -> list[dict[str, str]]:
        """Generates JD-grounded mock questions using extracted skills and templates."""
        extracted_skills = self._extract_jd_skills(jd_text)
        primary_skill = extracted_skills[0] if extracted_skills else "Python"
        secondary_skill = extracted_skills[1] if len(extracted_skills) > 1 else "SQL"
        tertiary_skill = extracted_skills[2] if len(extracted_skills) > 2 else "Docker"

        is_internship = listing_type == "internship"

        if is_internship:
            questions = [
                {
                    "category": "technical",
                    "question": f"In {primary_skill}, how would you implement structured input validation and error handling when building features for {company}?",
                },
                {
                    "category": "technical",
                    "question": f"How do you test and debug asynchronous calls or data pipelines using {secondary_skill} in your projects?",
                },
                {
                    "category": "behavioral",
                    "question": f"Can you describe a technical project where you used {primary_skill} and worked with team members to resolve a complex bug before a deadline?",
                },
                {
                    "category": "behavioral",
                    "question": f"How do you prioritize learning new frameworks like {tertiary_skill} when starting work on a new codebase at {company}?",
                },
                {
                    "category": "design",
                    "question": f"How would you organize a modular codebase using {primary_skill} and {secondary_skill} to maintain clean code and high test coverage?",
                },
            ]
        else:  # full-time / job
            questions = [
                {
                    "category": "technical",
                    "question": f"How would you diagnose and resolve state synchronization or memory bottlenecks in a high-throughput {primary_skill} microservice at {company}?",
                },
                {
                    "category": "technical",
                    "question": f"What architectural trade-offs would you evaluate when integrating {primary_skill} with {secondary_skill} for latency-critical production workloads?",
                },
                {
                    "category": "behavioral",
                    "question": f"Can you describe a critical engineering challenge involving {primary_skill} where you had to make architectural trade-offs under tight delivery timelines?",
                },
                {
                    "category": "design",
                    "question": f"How would you design a scalable, fault-tolerant event-driven architecture using {primary_skill}, {secondary_skill}, and {tertiary_skill} for {company}?",
                },
                {
                    "category": "design",
                    "question": f"What strategies would you employ to handle schema migrations, caching, and failover when scaling {secondary_skill} to support enterprise traffic?",
                },
            ]

        return self._filter_questions_by_rounds(questions, rounds)

    def _extract_jd_skills(self, jd_text: str) -> list[str]:
        """Extracts key technical skills mentioned in the JD text."""
        if not jd_text:
            return []

        jd_lower = jd_text.lower()
        extracted: list[str] = []

        common_techs = [
            "LangGraph",
            "LangChain",
            "Python",
            "TypeScript",
            "JavaScript",
            "React",
            "FastAPI",
            "Docker",
            "Kubernetes",
            "PostgreSQL",
            "Redis",
            "AWS",
            "GCP",
            "RAG",
            "Kafka",
            "Spark",
            "Go",
            "Rust",
            "Java",
            "Spring Boot",
            "GraphQL",
            "Node.js",
            "SQL",
        ]

        for tech in common_techs:
            if tech.lower() in jd_lower and tech not in extracted:
                extracted.append(tech)

        return extracted

    def _filter_questions_by_rounds(
        self, questions: list[dict[str, str]], rounds: list[str]
    ) -> list[dict[str, str]]:
        """Filters generated questions based on requested round types."""
        if not rounds or not questions:
            return questions

        rounds_lower = " ".join(rounds).lower()

        wants_tech = any(
            k in rounds_lower
            for k in ["tech", "coding", "assessment", "algorithm", "deep dive"]
        )
        wants_behav = any(
            k in rounds_lower
            for k in ["behavioral", "founder", "hr", "fit", "recruiter", "manager"]
        )
        wants_design = any(
            k in rounds_lower
            for k in ["design", "architecture", "system", "scalability"]
        )

        filtered = [
            q
            for q in questions
            if (
                (q["category"] == "technical" and wants_tech)
                or (q["category"] == "behavioral" and wants_behav)
                or (q["category"] == "design" and wants_design)
            )
        ]

        return filtered if filtered else questions

    # =========================================================================
    # Internal Helpers for Round Prediction
    # =========================================================================

    def _extract_explicit_rounds(
        self, jd_text: str, company: str
    ) -> list[dict[str, Any]] | None:
        """Attempts to extract explicitly specified interview rounds from JD text."""
        if not jd_text:
            return None

        jd_lower = jd_text.lower()

        # Match pattern like "2 rounds: technical and HR"
        round_count_match = re.search(r"(\d+)\s*rounds?\s*:\s*([^\.\n]+)", jd_lower)
        if round_count_match:
            try:
                count = int(round_count_match.group(1))
                process_text = round_count_match.group(2)
                rounds_list: list[dict[str, Any]] = []

                parts = re.split(r",|and|\+", process_text)
                for idx, part in enumerate(parts[:count], 1):
                    part_clean = part.strip()
                    r_type = self._classify_round_type(part_clean)

                    if r_type == "technical":
                        focus = "Programming, problem solving, data structures, and algorithms"
                    elif r_type == "screening":
                        focus = "Background alignment, resume walkthrough, and communication"
                    elif r_type == "assignment":
                        focus = "Hands-on project, implementation, and code quality assessment"
                    elif r_type == "founder":
                        focus = "Vision alignment, startup mindset, and culture fit"
                    else:
                        focus = f"Assessment of {part_clean} skills"

                    rounds_list.append(
                        {
                            "number": idx,
                            "type": r_type,
                            "focus": focus,
                            "duration": "45-60 mins",
                            "tips": f"Prepare examples demonstrating your {part_clean} experience for {company}.",
                        }
                    )

                if len(rounds_list) == count:
                    return rounds_list
            except Exception as e:  # noqa: BLE001
                logger.debug(f"Failed to parse explicit round text: {e}")

        # Match pattern like "Round 1: ... Round 2: ..."
        numbered_matches = re.findall(r"round\s*(\d+)\s*:\s*([^\.\n]+)", jd_lower)
        if numbered_matches:
            rounds_list = []
            for num_str, text_str in numbered_matches:
                num = int(num_str)
                text_clean = text_str.strip()
                r_type = self._classify_round_type(text_clean)
                rounds_list.append(
                    {
                        "number": num,
                        "type": r_type,
                        "focus": f"Focus on {text_clean}",
                        "duration": "45-60 mins",
                        "tips": f"Review concepts related to {text_clean} prior to interview with {company}.",
                    }
                )
            if rounds_list:
                return rounds_list

        return None

    def _classify_round_type(self, text: str) -> str:
        """Maps a textual round description to a canonical round type."""
        t = text.lower()
        if any(
            k in t
            for k in [
                "assignment",
                "take-home",
                "take home",
                "online coding assessment",
                "coding assessment",
                "oa",
            ]
        ):
            return "assignment"
        elif any(k in t for k in ["founder", "leadership", "ceo", "executive"]):
            return "founder"
        elif any(k in t for k in ["hr", "screening", "recruiter", "initial"]):
            return "screening"
        elif any(k in t for k in ["system design", "architecture", "deep dive"]):
            return "system_design"
        else:
            return "technical"

    def _generate_fallback_rounds(
        self, stage: str, listing_type: str, company: str
    ) -> dict[str, Any]:
        """Generates heuristic round structure based on listing type and company stage."""
        if listing_type == "internship":
            rounds = [
                {
                    "number": 1,
                    "type": "technical_and_project",
                    "focus": "Data structures, practical coding, resume project walkthrough, and problem solving",
                    "duration": "45 mins",
                    "tips": f"Be ready to explain your past projects in detail and demonstrate core CS fundamentals for {company}.",
                },
                {
                    "number": 2,
                    "type": "founder_or_team_fit",
                    "focus": "Culture fit, learning agility, enthusiasm, and alignment with company goals",
                    "duration": "30 mins",
                    "tips": f"Research {company}'s mission and express genuine curiosity about their product vision.",
                },
            ]
        else:  # job / full-time
            if stage in ["early-stage", "startup", "early"]:
                rounds = [
                    {
                        "number": 1,
                        "type": "technical_screen",
                        "focus": "Core domain technical discussion, past architecture decisions, and coding approach",
                        "duration": "45 mins",
                        "tips": "Focus on high-impact projects you led and be prepared to write production-quality code.",
                    },
                    {
                        "number": 2,
                        "type": "system_design_or_assignment",
                        "focus": "End-to-end architecture, API design, scalability, and system trade-offs",
                        "duration": "60 mins",
                        "tips": "Proactively discuss operational trade-offs, failure modes, and database scaling.",
                    },
                    {
                        "number": 3,
                        "type": "founder_and_culture_fit",
                        "focus": "Ownership mindset, autonomy, cross-functional collaboration, and vision alignment",
                        "duration": "45 mins",
                        "tips": f"Demonstrate initiative, builder mindset, and clear alignment with {company}'s product roadmap.",
                    },
                ]
            elif stage in ["enterprise", "faang", "large"]:
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
