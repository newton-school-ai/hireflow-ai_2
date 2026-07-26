"""Shared utilities for HireFlow scrapers.

Centralises common logic used by Lever, Greenhouse, and generic scrapers
so that it is defined once rather than duplicated in every module.
"""

import logging
import urllib.parse

from src.config.database import SessionLocal
from src.models.job import Job

logger = logging.getLogger(__name__)


def classify_listing_type(title: str) -> str:
    """Classify a job listing as 'internship' or 'job' based on its title."""
    title_lower = title.lower()
    if any(
        keyword in title_lower for keyword in ["intern", "internship", "co-op", "coop"]
    ):
        return "internship"
    return "job"


def extract_company_name(board_url: str) -> str:
    """Derive company name from common ATS URLs, falling back to hostname."""
    parsed = urllib.parse.urlparse(board_url)
    hostname = parsed.hostname or ""
    path_parts = [p for p in parsed.path.split("/") if p]

    # 1. Lever: jobs.lever.co/<company>
    if "lever.co" in hostname and path_parts:
        return path_parts[0]

    # 2. Greenhouse: boards.greenhouse.io/<company> or
    # job-boards.greenhouse.io/<company>
    if "greenhouse.io" in hostname and path_parts:
        return path_parts[0]

    # 3. Fallback to domain name
    company_name = hostname or "unknown_company"
    for prefix in ("www.", "jobs.", "careers.", "boards.", "job-boards."):
        if company_name.startswith(prefix):
            company_name = company_name[len(prefix) :]
            break

    return company_name


def is_job_path(url: str) -> bool:
    """Check if a URL path contains common job keywords or looks like a job link."""
    path_lower = urllib.parse.urlparse(url).path.lower()

    # Exclude obvious non-job pages
    if any(
        kw in path_lower for kw in ["support", "privacy", "terms", "login", "about"]
    ):
        return False

    keywords = [
        "job",
        "jobs",
        "position",
        "positions",
        "career",
        "careers",
        "opening",
        "openings",
        "role",
        "roles",
        "apply",
        "vacancy",
        "vacancies",
    ]
    if any(kw in path_lower for kw in keywords):
        return True

    # Accept paths ending with a UUID (common for Lever, Ashby)
    parts = path_lower.strip("/").split("/")
    if parts:
        last_part = parts[-1]
        if len(last_part) > 20 and "-" in last_part:
            return True
        if last_part.isdigit() and len(last_part) > 4:
            return True

    return False


def save_job(
    source: str,
    company_name: str,
    role_title: str,
    jd_text: str,
    location: str | None,
    application_url: str,
    posting_date=None,
    listing_type: str = "job",
) -> None:
    """Persist a job to the database, skipping duplicates by application_url."""
    db = SessionLocal()
    try:
        existing = db.query(Job).filter_by(application_url=application_url).first()
        if not existing:
            job = Job(
                company_name=company_name,
                role_title=role_title,
                jd_text=jd_text,
                location=location,
                application_url=application_url,
                posting_date=posting_date,
                listing_type=listing_type,
                source=source,
            )
            db.add(job)
            db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"DB Error saving job {application_url}: {e}", exc_info=True)
    finally:
        db.close()
