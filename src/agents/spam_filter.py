"""Spam and quality filter for HireFlow AI.

Scores every scraped job listing and determines whether it is spam.
Uses multiple independent signals — missing company name, short description,
absent skills, unrealistic salary claims, and spam language — to produce
a single confidence score between 0.0 and 1.0.

Usage::

    from src.agents.spam_filter import SpamFilter

    sf = SpamFilter(threshold=0.7)
    result = sf.score(job_dict)
    # {"is_spam": True, "spam_confidence": 0.82}
"""

import argparse
import logging
import re

from src.config.database import SessionLocal
from src.config.settings import settings
from src.models.job import Job

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_JD_WORD_COUNT = 50

KNOWN_SKILLS: set[str] = {
    "python",
    "java",
    "c++",
    "c#",
    "javascript",
    "typescript",
    "react",
    "node",
    "node.js",
    "sql",
    "nosql",
    "mongodb",
    "docker",
    "kubernetes",
    "aws",
    "azure",
    "gcp",
    "git",
    "tensorflow",
    "pytorch",
    "pandas",
    "numpy",
    "scikit-learn",
    "fastapi",
    "flask",
    "django",
    "langchain",
    "llm",
    "rust",
    "go",
    "swift",
    "kotlin",
    "ruby",
    "rails",
    "spring",
    "html",
    "css",
    "vue",
    "angular",
    "redis",
    "kafka",
    "spark",
    "hadoop",
    "linux",
    "bash",
    "graphql",
    "rest",
    "api",
    "machine learning",
    "deep learning",
    "data science",
    "data engineering",
}

SPAM_PHRASES: list[str] = [
    "rockstar",
    "ninja",
    "guru",
    "quick money",
    "easy money",
    "passionate self-starter",
    "must hustle",
    "work hard play hard",
    "dream job",
    "guaranteed riches",
    "unlimited salary",
    "be your own boss",
    "get rich",
    "no experience needed",
]

# Detects unusually large or promotional salary claims
# (e.g. "$500k", "$1,000,000", "$500K/yr")
_UNREALISTIC_SALARY_RE = re.compile(
    r"""
    \$\s*(?:
        [2-9]\d{2}\s*k                       # $200k – $999k
      | [1-9],?\d{3}\s*k                     # $1,000k+
      | [1-9][,\d]{5,}                        # $100,000+ (six+ digit figures)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Matches phrases like "earn 10 lakh per month" or "salary 50 lakh"
_LAKH_SALARY_RE = re.compile(
    r"\b\d+\s*lakh\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Signal weights — each signal contributes a weighted amount to the final
# confidence score.  Weights sum to 1.0.
# ---------------------------------------------------------------------------

SIGNAL_WEIGHTS: dict[str, float] = {
    "missing_company": 0.20,
    "short_description": 0.15,
    "no_skills": 0.20,
    "unrealistic_salary": 0.20,
    "spam_language": 0.20,
    "low_technical_content": 0.05,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Single-word skills use word-boundary matching to reduce false positives.
# Multi-word skills (e.g. "machine learning") are matched as plain substrings
# since the phrase itself is specific enough.
_SINGLE_WORD_SKILL_PATTERNS: dict[str, re.Pattern[str]] = {}
_MULTI_WORD_SKILLS: list[str] = []

for _skill in KNOWN_SKILLS:
    if " " in _skill:
        _MULTI_WORD_SKILLS.append(_skill)
    else:
        _SINGLE_WORD_SKILL_PATTERNS[_skill] = re.compile(
            rf"\b{re.escape(_skill)}\b", re.IGNORECASE
        )


def detect_skills(text: str) -> list[str]:
    """Return recognised skills found in *text*.

    Uses word-boundary matching for single-word skills to avoid false
    positives (e.g. "ago" inside "django" won't match "go").  Multi-word
    skills are matched as case-insensitive substrings.

    Returns a sorted list to guarantee deterministic output order.
    """
    found: list[str] = []
    text_lower = text.lower()

    for skill, pattern in _SINGLE_WORD_SKILL_PATTERNS.items():
        if pattern.search(text):
            found.append(skill)

    for skill in _MULTI_WORD_SKILLS:
        if skill in text_lower:
            found.append(skill)

    # Sort to guarantee deterministic output order since the patterns
    # are derived from an unordered set (KNOWN_SKILLS).
    return sorted(found)


# ---------------------------------------------------------------------------
# SpamFilter
# ---------------------------------------------------------------------------


class SpamFilter:
    """Scores job listings for spam likelihood.

    Attributes:
        threshold: Confidence above which a job is classified as spam.
    """

    def __init__(self, threshold: float | None = None):
        val = threshold if threshold is not None else settings.spam_threshold
        if not 0.0 <= val <= 1.0:
            raise ValueError("threshold must be between 0 and 1")
        self.threshold = val

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(self, job: dict) -> dict:
        """Score a single job dict and return spam classification.

        Args:
            job: A dict with at least ``jd_text``.  Optional keys:
                 ``company_name``, ``skills_required``.

        Returns:
            ``{"is_spam": bool, "spam_confidence": float}``
        """
        signals = self._compute_signals(job)
        confidence = self._aggregate(signals)
        return {
            "is_spam": confidence >= self.threshold,
            "spam_confidence": round(confidence, 4),
        }

    def run(self) -> None:
        """Score every job in the database and persist the results."""
        db = SessionLocal()
        try:
            jobs = db.query(Job).all()
            logger.info(f"Scoring {len(jobs)} jobs for spam.")

            for job in jobs:
                job_dict = {
                    "company_name": job.company_name,
                    "jd_text": job.jd_text,
                    "skills_required": job.skills_required or [],
                }
                result = self.score(job_dict)

                job.is_spam = result["is_spam"]
                job.spam_confidence = result["spam_confidence"]

            db.commit()
            logger.info("Spam scoring complete.")
        except Exception as e:
            db.rollback()
            logger.error(f"Error during spam scoring: {e}")
            raise
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_signals(self, job: dict) -> dict[str, float]:
        """Evaluate each independent spam signal.

        Returns a dict mapping signal name → value in [0.0, 1.0].
        """
        jd_text = job.get("jd_text", "") or ""
        company_name = job.get("company_name", "") or ""
        skills_required = job.get("skills_required") or []

        return {
            "missing_company": self._check_missing_company(company_name),
            "short_description": self._check_short_description(jd_text),
            "no_skills": self._check_no_skills(jd_text, skills_required),
            "unrealistic_salary": self._check_unrealistic_salary(jd_text),
            "spam_language": self._check_spam_language(jd_text),
            "low_technical_content": self._check_low_technical_content(jd_text),
        }

    @staticmethod
    def _aggregate(signals: dict[str, float]) -> float:
        """Combine weighted signals into a single confidence in [0.0, 1.0]."""
        confidence = sum(
            signals[name] * SIGNAL_WEIGHTS[name] for name in SIGNAL_WEIGHTS
        )
        return max(0.0, min(1.0, confidence))

    # -- Individual signal checkers ------------------------------------

    @staticmethod
    def _check_missing_company(company_name: str) -> float:
        """Return 1.0 if company name is empty or placeholder."""
        return 1.0 if not company_name.strip() else 0.0

    @staticmethod
    def _check_short_description(jd_text: str) -> float:
        """Return 1.0 if the description has fewer than MIN_JD_WORD_COUNT words."""
        word_count = len(jd_text.split())
        if word_count >= MIN_JD_WORD_COUNT:
            return 0.0
        # Partial penalty: very short is worse than slightly short
        return 1.0 - (word_count / MIN_JD_WORD_COUNT)

    @staticmethod
    def _check_no_skills(jd_text: str, skills_required: list) -> float:
        """Return 1.0 if no recognisable skills are found anywhere."""
        if skills_required:
            return 0.0
        detected = detect_skills(jd_text)
        return 0.0 if detected else 1.0

    @staticmethod
    def _check_unrealistic_salary(jd_text: str) -> float:
        """Return 1.0 if the text contains unrealistic salary claims."""
        text_lower = jd_text.lower()

        if _UNREALISTIC_SALARY_RE.search(jd_text):
            return 1.0
        if _LAKH_SALARY_RE.search(jd_text):
            return 1.0
        if any(
            phrase in text_lower for phrase in ["unlimited salary", "guaranteed riches"]
        ):
            return 1.0
        return 0.0

    @staticmethod
    def _check_spam_language(jd_text: str) -> float:
        """Return a score based on how many spam phrases appear."""
        text_lower = jd_text.lower()
        matches = sum(1 for phrase in SPAM_PHRASES if phrase in text_lower)
        if matches == 0:
            return 0.0
        # Cap at 1.0; two or more distinct phrases → full signal
        return min(1.0, matches / 2)

    @staticmethod
    def _check_low_technical_content(jd_text: str) -> float:
        """Return 1.0 when the description has many words but no skills."""
        word_count = len(jd_text.split())
        # Only penalise long descriptions that lack technical content.
        # Short descriptions are already penalised by short_description.
        if word_count < MIN_JD_WORD_COUNT:
            return 0.0
        detected = detect_skills(jd_text)
        return 0.0 if detected else 1.0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(
        description="Score all jobs in the database for spam."
    )
    parser.add_argument(
        "--run",
        action="store_true",
        required=True,
        help="Run the spam filter on all jobs.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Spam confidence threshold (default: loaded from settings).",
    )
    args = parser.parse_args()

    sf = SpamFilter(threshold=args.threshold)
    sf.run()
