"""
PrepGuideAgent for HireFlow AI.

Analyzes job descriptions and candidate skills to predict interview round
structures, focus areas, durations, and preparation tips. Also categorizes
candidate skills against job requirements into strong, moderate, and gap topics.
"""

import logging
import re
from typing import Any

from src.utils.llm_client import BaseLLMClient, get_llm_client

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
    """Agent responsible for interview round prediction and topic analysis."""

    def __init__(self, llm_client: BaseLLMClient | None = None) -> None:
        """Initializes the PrepGuideAgent.

        Args:
            llm_client: Optional LLM client for advanced extraction. If None,
                attempts to initialize from global settings with graceful fallback.
        """
        if llm_client is not None:
            self.llm_client = llm_client
        else:
            try:
                self.llm_client = get_llm_client()
            except Exception as e:
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
            for u_lower, u_orig in user_skills_lower.items():
                if (
                    u_lower == jd_lower
                    or (len(jd_lower) >= 3 and jd_lower in u_lower)
                    or (len(u_lower) >= 3 and u_lower in jd_lower)
                ):
                    # Check if essentially the exact same technology (e.g. react vs react.js, node vs node.js)
                    if self._is_equivalent_tech(u_lower, jd_lower):
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
                        if (
                            gap_lower in cluster
                            and cluster.intersection(user_skills_set)
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
            w in text
            for w in ["system design", "architecture", "design", "deep dive"]
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
