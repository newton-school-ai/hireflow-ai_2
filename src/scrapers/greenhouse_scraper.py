"""Scraper for Greenhouse career pages (boards.greenhouse.io).

Extracts job details using Playwright and saves them to the SQLAlchemy database.
"""

import argparse
import logging
import re
import sys
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from sqlalchemy.orm import Session

from src.config.database import SessionLocal
from src.models.job import Job

# Set up logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("greenhouse_scraper")


class GreenhouseScraper:
    """Scraper class for scraping Greenhouse (boards.greenhouse.io) job boards."""

    def __init__(self, db_session: Session | None = None) -> None:
        """Initialize the scraper with an optional database session."""
        self.db = db_session

    def classify_listing_type(self, title: str) -> str:
        """Classify the listing type as internship or job using title keywords."""
        title_lower = title.lower()
        internship_keywords = [
            "intern",
            "internship",
            "co-op",
            "coop",
            "apprentice",
            "fellow",
            "fellowship",
            "placement",
            "undergrad",
            "student",
        ]
        # Match only whole-word keywords to avoid matching "internal" or "international"
        for kw in internship_keywords:
            pattern = r"\b" + re.escape(kw) + r"\b"
            if re.search(pattern, title_lower):
                return "internship"
        return "job"

    def extract_company_name(self, url: str, html_content: str = "") -> str:
        """Extract the company name from the URL or page headers."""
        # Try to parse from URL path slug first
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split("/") if p]
        if path_parts:
            # Typically, path_parts is [company_slug] or [company_slug, 'jobs', job_id]
            slug = path_parts[0]
            # Replace hyphens/underscores with spaces and title case
            slug_name = slug.replace("-", " ").replace("_", " ").strip()
            if slug_name:
                return slug_name.title()

        # Fallback search in HTML meta tags if provided
        if html_content:
            meta_match = re.search(
                r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)["\']',
                html_content,
                re.IGNORECASE,
            )
            if meta_match:
                content = meta_match.group(1).strip()
                # Frequently og:title is e.g. "Job Application for Role at Company"
                at_match = re.search(r"\bat\s+(.+)$", content, re.IGNORECASE)
                if at_match:
                    return at_match.group(1).strip()

            meta_site_name = re.search(
                r'<meta\s+property=["\']og:site_name["\']\s+content=["\']([^"\']+)["\']',
                html_content,
                re.IGNORECASE,
            )
            if meta_site_name:
                return meta_site_name.group(1).strip()

        return "Unknown Company"

    def scrape_job_detail(
        self,
        playwright_browser,
        detail_url: str,
        company_name: str,
        role_title: str,
        location: str | None,
        listing_type: str,
    ) -> dict | None:
        """Navigate to the job detail page, parse description, and return details."""
        context = playwright_browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Fetching job detail page: {detail_url} (Attempt {attempt + 1})"
                )
                page.goto(detail_url, timeout=30000, wait_until="domcontentloaded")
                # Wait for content container
                try:
                    page.wait_for_selector(
                        "#content, #job-body, .opening-body, .job__description",
                        timeout=5000,
                    )
                except Exception:
                    logger.debug(
                        "Greenhouse content selectors not found, using general wait."
                    )

                html_content = page.content()

                # Extract company name from meta tags if we don't have a clean one
                extracted_company = self.extract_company_name(detail_url, html_content)
                if extracted_company and extracted_company != "Unknown Company":
                    company_name = extracted_company

                # Extract title if not set, or verify title
                title_el = page.locator(
                    ".job__title h1, h1.app-title, #header h1"
                ).first
                final_title = (
                    title_el.inner_text().strip()
                    if title_el.count() > 0
                    else role_title
                )

                # Extract JD text
                jd_text = ""
                desc_el = page.locator(
                    ".job__description, #content, #job-body, .opening-body"
                ).first
                if desc_el.count() > 0:
                    jd_text = desc_el.inner_text().strip()

                if not jd_text:
                    body_text = page.locator("body").inner_text().strip()
                    jd_text = body_text

                # Extract location if not set, or get clean location
                detail_location = None
                loc_el = page.locator(
                    ".job__location, .location, #header .location"
                ).first
                if loc_el.count() > 0:
                    detail_location = loc_el.inner_text().replace("at ", "").strip()

                final_location = detail_location or location or "Remote"

                # Greenhouse doesn't show posting date, return None
                posting_date = None

                job_data = {
                    "company_name": company_name,
                    "role_title": final_title,
                    "jd_text": jd_text,
                    "location": final_location,
                    "application_url": detail_url,
                    "posting_date": posting_date,
                    "listing_type": listing_type,
                    "source": "greenhouse",
                }

                context.close()
                return job_data
            except Exception as e:
                logger.error(
                    f"Error scraping job detail {detail_url} on attempt {attempt + 1}: {e}"
                )
                if attempt == max_retries - 1:
                    context.close()
                    return None
                time.sleep(2)

        context.close()
        return None

    def save_job(self, job_data: dict) -> Job | None:
        """Save job listing to database if it doesn't already exist."""
        if not self.db:
            logger.warning("No database session provided. Job not saved to database.")
            return None

        try:
            # Check for existing job by application_url to avoid duplicates
            existing = (
                self.db.query(Job)
                .filter(Job.application_url == job_data["application_url"])
                .first()
            )
            if existing:
                logger.info(
                    f"Job already exists in database: {job_data['application_url']}"
                )
                return existing

            db_job = Job(
                company_name=job_data["company_name"],
                role_title=job_data["role_title"],
                jd_text=job_data["jd_text"],
                location=job_data.get("location"),
                application_url=job_data["application_url"],
                posting_date=job_data.get("posting_date"),
                listing_type=job_data["listing_type"],
                source=job_data["source"],
                skills_required=[],
            )
            self.db.add(db_job)
            self.db.commit()
            self.db.refresh(db_job)
            logger.info(
                f"Successfully saved job to database: {job_data['role_title']} at {job_data['company_name']}"
            )
            return db_job
        except Exception as e:
            self.db.rollback()
            logger.error(
                f"Failed to save job {job_data['application_url']} to database: {e}"
            )
            return None

    def scrape(self, board_url: str, target_mode: str) -> list[dict]:
        """Scrape the Greenhouse board URL, filter by mode, and save to DB."""
        logger.info(
            f"Starting Greenhouse scrape for {board_url} with mode {target_mode}"
        )
        company_name = self.extract_company_name(board_url)
        scraped_jobs = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            try:
                page.goto(board_url, timeout=30000, wait_until="domcontentloaded")
            except Exception as e:
                logger.error(f"Failed to load board page {board_url}: {e}")
                browser.close()
                return []

            listings = []
            visited_urls = set()
            page_num = 1

            while page_num <= 10:
                logger.info(f"Processing listings page {page_num}...")
                # Check for standard opening container
                try:
                    page.wait_for_selector(
                        ".opening, div.opening, tr.job-post, .job-post", timeout=10000
                    )
                except Exception:
                    logger.warning("No openings found on current page within timeout.")
                    break

                opening_elements = page.locator(
                    ".opening, div.opening, tr.job-post, .job-post"
                )
                count = opening_elements.count()
                logger.info(f"Found {count} openings on page {page_num}")

                for i in range(count):
                    el = opening_elements.nth(i)

                    # Extract title link
                    link_el = el.locator("a").first
                    if link_el.count() == 0:
                        continue

                    # Extract title text
                    title = ""
                    title_p = link_el.locator("p.body--medium, p.body").first
                    if title_p.count() > 0:
                        title = title_p.inner_text().strip()
                    else:
                        title = link_el.inner_text().strip()

                    href = link_el.get_attribute("href")

                    if not href or not title:
                        continue

                    # Standardize URL dynamically using board_url domain
                    if href.startswith("/"):
                        parsed_board = urlparse(board_url)
                        base_domain = f"{parsed_board.scheme}://{parsed_board.netloc}"
                        detail_url = f"{base_domain}{href}"
                    else:
                        detail_url = href

                    detail_url = detail_url.split("?")[0]

                    if detail_url in visited_urls:
                        continue
                    visited_urls.add(detail_url)

                    # Extract location
                    loc_el = el.locator(
                        "span.location, .location, p.body__secondary, p.body--metadata"
                    ).first
                    location = (
                        loc_el.inner_text().strip() if loc_el.count() > 0 else None
                    )
                    listing_type = self.classify_listing_type(title)

                    # Filter based on target mode
                    if listing_type != target_mode:
                        logger.debug(
                            f"Skipping '{title}' (classified as '{listing_type}', target is '{target_mode}')"
                        )
                        continue

                    listings.append(
                        {
                            "url": detail_url,
                            "title": title,
                            "location": location,
                            "listing_type": listing_type,
                        }
                    )

                # Check for pagination / Next page
                next_selectors = [
                    'a[rel="next"]',
                    "a.next",
                    "a.next-page",
                    ".pagination-next a",
                    'a:has-text("Next")',
                    'button:has-text("Next")',
                    '[aria-label="Next"]',
                ]

                next_button = None
                for selector in next_selectors:
                    try:
                        btn = page.locator(selector).first
                        if btn.count() > 0 and btn.is_visible() and btn.is_enabled():
                            next_button = btn
                            break
                    except Exception:
                        continue

                if next_button:
                    logger.info("Found Next Page button. Clicking it...")
                    try:
                        next_button.click()
                        page.wait_for_timeout(2000)
                        page_num += 1
                    except Exception as e:
                        logger.error(f"Error clicking Next button: {e}")
                        break
                else:
                    logger.info("No Next Page button found. Pagination finished.")
                    break

            context.close()

            # Process matched listings
            logger.info(
                f"Total listings matched with mode '{target_mode}': {len(listings)}"
            )
            for index, list_item in enumerate(listings):
                # Rate limit: 1.2 second delay between calls
                if index > 0:
                    time.sleep(1.2)

                # Check duplicate before visiting detail page
                if self.db:
                    existing = (
                        self.db.query(Job)
                        .filter(Job.application_url == list_item["url"])
                        .first()
                    )
                    if existing:
                        logger.info(
                            f"Skipping detail page for existing job: {list_item['url']}"
                        )
                        scraped_jobs.append(
                            {
                                "company_name": existing.company_name,
                                "role_title": existing.role_title,
                                "jd_text": existing.jd_text,
                                "location": existing.location,
                                "application_url": existing.application_url,
                                "posting_date": existing.posting_date,
                                "listing_type": existing.listing_type,
                                "source": existing.source,
                            }
                        )
                        continue

                job_detail = self.scrape_job_detail(
                    browser,
                    list_item["url"],
                    company_name,
                    list_item["title"],
                    list_item["location"],
                    list_item["listing_type"],
                )
                if job_detail:
                    self.save_job(job_detail)
                    scraped_jobs.append(job_detail)

            browser.close()

        logger.info(
            f"Finished Greenhouse scrape. Successfully scraped {len(scraped_jobs)} jobs."
        )
        return scraped_jobs


def main() -> None:
    """CLI entry point for running the Greenhouse scraper."""
    parser = argparse.ArgumentParser(description="Scrape Greenhouse career page.")
    parser.add_argument(
        "--url", type=str, required=True, help="URL of the Greenhouse career board"
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["job", "internship"],
        required=True,
        help="Type of listing to filter: 'job' or 'internship'",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        scraper = GreenhouseScraper(db_session=db)
        scraper.scrape(args.url, args.mode)
    finally:
        db.close()


if __name__ == "__main__":
    main()
