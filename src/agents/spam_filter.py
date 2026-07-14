"""
Spam and quality filter agent for HireFlow AI.
Evaluates job listings for spam, low quality, or fake postings using rule-based heuristics and contextual LLM analysis.
"""

import logging
import argparse
from src.config.settings import settings
from src.utils.llm_client import get_llm_client
from src.config.database import SessionLocal
from src.models.job import Job

logger = logging.getLogger(__name__)


class SpamFilter:
    """Agent that evaluates job quality and classifies listings as spam or clean."""

    def __init__(self, threshold: float | None = None) -> None:
        """Initialize the spam filter agent.

        Args:
            threshold: Confidence score threshold above which a job is marked as spam.
                       Defaults to the value configured in Settings (0.7).
        """
        self.threshold = threshold if threshold is not None else settings.spam_threshold
        try:
            self.llm_client = get_llm_client()
        except Exception as e:
            logger.warning(
                f"Could not initialize LLM client: {e}. Will rely on rule-based heuristics."
            )
            self.llm_client = None

    def score(self, job_data: dict) -> float:
        """Evaluate a job listing and calculate a spam confidence score between 0.0 and 1.0.

        Args:
            job_data: A dictionary containing:
                      - company_name: Name of the company
                      - role_title: Job role/title
                      - jd_text: Full job description text
                      - skills_required: List of required skills
                      - stipend_salary: Salary/stipend information

        Returns:
            float: Spam confidence score between 0.0 and 1.0 (1.0 is definitely spam).
        """
        company_name = job_data.get("company_name") or ""
        role_title = job_data.get("role_title") or ""
        jd_text = job_data.get("jd_text") or ""
        skills_required = job_data.get("skills_required") or []
        stipend_salary = job_data.get("stipend_salary") or ""

        # 1. Hard Rule-Based Heuristics
        # Rule A: Missing company name (Hard failure)
        if not company_name or company_name.strip().lower() in [
            "",
            "n/a",
            "unknown",
            "none",
            "placeholder",
        ]:
            logger.info("Spam flagged: Missing or placeholder company name.")
            return 1.0

        # Rule B: JD under 50 words
        words = jd_text.split()
        is_short_jd = len(words) < 50

        # Rule C: No skills mentioned
        no_skills = not skills_required

        # Rule D: Unrealistic salary claims
        unrealistic_patterns = [
            "earn $",
            "daily pay",
            "weekly pay",
            "make money fast",
            "get rich",
            "payout daily",
            "make $",
            "passive income",
            "unlimited earning",
            "earn up to",
            "easy cash",
            "earn weekly",
        ]
        has_suspicious_salary = False
        if stipend_salary and any(
            pat in stipend_salary.lower() for pat in unrealistic_patterns
        ):
            has_suspicious_salary = True
        elif jd_text and any(pat in jd_text.lower() for pat in unrealistic_patterns):
            has_suspicious_salary = True

        # Flag combined signals or extreme cases
        if has_suspicious_salary:
            logger.info("Spam flagged: Suspicious or unrealistic salary claims.")
            return 0.9

        if is_short_jd and no_skills:
            logger.info("Spam flagged: Short description with no skills mentioned.")
            return 1.0

        # 2. LLM contextual quality evaluation (or default fallback for sparse cases)
        if not self.llm_client:
            logger.warning(
                "LLM client not available. Falling back to rule-based safe score."
            )
            # If it's short or lacks skills, but not both, and LLM is unavailable,
            # assign a moderate score below the spam threshold (0.7) so it passes.
            if is_short_jd or no_skills:
                return 0.4
            return 0.0

        prompt = f"""
        You are a job spam and quality filter for HireFlow AI.
        Analyze the following job listing and determine if it is spam, fake, low-quality, an MLM/scam, or a template placeholder.
        
        Company: {company_name}
        Role: {role_title}
        Skills required: {', '.join(skills_required) if skills_required else 'None specified'}
        Salary/Stipend info: {stipend_salary}
        
        Job Description:
        {jd_text}
        
        Respond ONLY in the following JSON format:
        {{
            "spam_confidence": <float between 0.0 and 1.0>,
            "reason": "<short description of why this is or isn't spam>"
        }}
        """

        try:
            res = self.llm_client.extract(prompt)
            if isinstance(res, dict) and "spam_confidence" in res:
                return float(res["spam_confidence"])
        except Exception as e:
            logger.error(f"Error calling LLM for spam check: {e}")

        return 0.0

    def is_spam(self, score: float) -> bool:
        """Determine if a spam score is at or above the threshold.

        Args:
            score: The spam confidence score.

        Returns:
            bool: True if classified as spam.
        """
        return score >= self.threshold


def run_spam_filter() -> None:
    """CLI runner to process all jobs currently in the database."""
    db = SessionLocal()
    sf = SpamFilter()

    try:
        jobs = db.query(Job).all()
        print(f"Found {len(jobs)} jobs in the database to evaluate.")

        updated_count = 0
        for job in jobs:
            job_data = {
                "company_name": job.company_name,
                "role_title": job.role_title,
                "jd_text": job.jd_text,
                "skills_required": job.skills_required,
                "stipend_salary": job.stipend_salary,
            }

            score = sf.score(job_data)
            is_spam = sf.is_spam(score)

            job.spam_confidence = score
            job.is_spam = is_spam
            updated_count += 1
            print(
                f"Evaluated '{job.role_title}' at '{job.company_name}': score={score:.2f}, is_spam={is_spam}"
            )

        if updated_count > 0:
            db.commit()
            print(f"Successfully updated {updated_count} jobs.")
        else:
            print("No jobs processed.")

    except Exception as e:
        db.rollback()
        logger.error(f"Error during bulk spam filter run: {e}", exc_info=True)
        print(f"Error: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="HireFlow AI Spam Filter agent command-line runner."
    )
    parser.add_argument(
        "--run", action="store_true", help="Score all jobs in the database."
    )
    args = parser.parse_args()

    if args.run:
        run_spam_filter()
