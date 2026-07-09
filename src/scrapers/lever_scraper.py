"""Scraper for Lever career pages (jobs.lever.co).

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
logger = logging.getLogger("lever_scraper")


class LeverScraper:
    """Scraper class for scraping Lever (jobs.lever.co) job boards."""

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
        # Try to parse from URL slug first
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split("/") if p]
        if path_parts:
            # First directory segment is usually the company name, e.g. /anthropic/job-id or /anthropic
            slug = path_parts[0]
            # Replace hyphens with spaces and title case
            slug_name = slug.replace("-", " ").strip()
            if slug_name:
                return slug_name.title()

        # Fallback search in HTML meta tags if provided
        if html_content:
            meta_match = re.search(
                r'<meta\s+property=["\']og:site_name["\']\s+content=["\']([^"\']+)["\']',
                html_content,
                re.IGNORECASE,
            )
            if meta_match:
                return meta_match.group(1).strip()

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
                logger.info(f"Fetching job detail page: {detail_url} (Attempt {attempt + 1})")
                page.goto(detail_url, timeout=30000, wait_until="domcontentloaded")
                
                # Wait for core content wrapper if present
                try:
                    page.wait_for_selector(".posting-page, .section.page-centered", timeout=5000)
                except Exception:
                    logger.debug("Core selectors not found, attempting generic load wait.")

                # Extract page content
                html_content = page.content()

                # Extract company name from meta tags if we don't have a clean one
                extracted_company = self.extract_company_name(detail_url, html_content)
                if extracted_company and extracted_company != "Unknown Company":
                    company_name = extracted_company

                # Extract description
                # Typically, description text is located in .posting-sections or multiple .section.page-centered
                jd_text = ""
                
                # Try .posting-sections first
                posting_sections = page.locator(".posting-sections")
                if posting_sections.count() > 0:
                    jd_text = posting_sections.first.inner_text().strip()
                
                # Fallback to .section.page-centered
                if not jd_text:
                    sections = page.locator(".section.page-centered")
                    section_texts = []
                    for i in range(sections.count()):
                        # Avoid extracting the application form or submit buttons
                        sec_text = sections.nth(i).inner_text().strip()
                        if sec_text and "apply for this job" not in sec_text.lower():
                            section_texts.append(sec_text)
                    jd_text = "\n\n".join(section_texts).strip()

                # Absolute fallback: body text minus form if everything else fails
                if not jd_text:
                    body_text = page.locator("body").inner_text().strip()
                    jd_text = body_text

                # Clean location if detail page has better info
                detail_location = None
                location_el = page.locator(".posting-categories .location, .posting-headline .location").first
                if location_el.count() > 0:
                    detail_location = location_el.inner_text().strip()
                
                final_location = detail_location or location or "Remote"

                # Standardize workplace types (e.g. Remote, Hybrid, On-site) if present
                workplace_el = page.locator(".posting-categories .workplaceTypes").first
                if workplace_el.count() > 0:
                    workplace = workplace_el.inner_text().strip()
                    if workplace and workplace.lower() not in final_location.lower():
                        final_location = f"{final_location} ({workplace})"

                # Lever does not typically display a posting date, so we return None (or default to current day in DB if needed, but None matches the schema)
                posting_date = None

                job_data = {
                    "company_name": company_name,
                    "role_title": role_title,
                    "jd_text": jd_text,
                    "location": final_location,
                    "application_url": detail_url,
                    "posting_date": posting_date,
                    "listing_type": listing_type,
                    "source": "lever",
                }
                
                context.close()
                return job_data

            except Exception as e:
                logger.error(f"Error scraping job detail {detail_url} on attempt {attempt + 1}: {e}")
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
                logger.info(f"Job already exists in database: {job_data['application_url']}")
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
            logger.info(f"Successfully saved job to database: {job_data['role_title']} at {job_data['company_name']}")
            return db_job
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to save job {job_data['application_url']} to database: {e}")
            return None

    def scrape(self, board_url: str, target_mode: str) -> list[dict]:
        """Scrape the Lever board URL, filter by mode, and save to DB."""
        logger.info(f"Starting Lever scrape for {board_url} with mode {target_mode}")
        company_name = self.extract_company_name(board_url)
        scraped_jobs = []

        with sync_playwright() as p:
            # Launch browser in headless mode
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

            # Multi-page pagination loop
            listings = []
            visited_urls = set()
            page_num = 1

            while page_num <= 10:
                logger.info(f"Processing listings page {page_num}...")
                # Wait for posting elements
                try:
                    page.wait_for_selector(".posting", timeout=10000)
                except Exception:
                    logger.warning("No postings found on current page within timeout.")
                    break

                # Extract postings
                posting_elements = page.locator(".posting")
                count = posting_elements.count()
                logger.info(f"Found {count} postings on page {page_num}")

                for i in range(count):
                    el = posting_elements.nth(i)
                    
                    # Extract title and link
                    title_el = el.locator("a.posting-title h5, a.posting-title").first
                    link_el = el.locator("a.posting-title, a").first
                    
                    if title_el.count() == 0 or link_el.count() == 0:
                        continue

                    title = title_el.inner_text().strip()
                    href = link_el.get_attribute("href")
                    
                    if not href or not title:
                        continue

                    # Clean and standardize detail URL
                    detail_url = href.split("?")[0]
                    if not detail_url.startswith("http"):
                        # Handle relative paths, although Lever paths are usually absolute
                        detail_url = f"https://jobs.lever.co{detail_url}"

                    if detail_url in visited_urls:
                        continue
                    visited_urls.add(detail_url)

                    # Extract location if visible on main board
                    loc_el = el.locator(".posting-meta .location, .location").first
                    location = loc_el.inner_text().strip() if loc_el.count() > 0 else None

                    # Extract workplace type if visible on main board
                    workplace_el = el.locator(".posting-meta .workplaceTypes, .workplaceTypes").first
                    workplace = workplace_el.inner_text().strip() if workplace_el.count() > 0 else None
                    if workplace and location:
                        location = f"{location} ({workplace})"

                    # Classify listing type
                    listing_type = self.classify_listing_type(title)

                    # Filter based on target mode
                    if listing_type != target_mode:
                        logger.debug(f"Skipping '{title}' (classified as '{listing_type}', target is '{target_mode}')")
                        continue

                    listings.append({
                        "url": detail_url,
                        "title": title,
                        "location": location,
                        "listing_type": listing_type,
                    })

                # Check for pagination / Next page
                # Look for standard next selectors
                next_selectors = [
                    'a[rel="next"]',
                    'a.next',
                    'a.next-page',
                    '.pagination-next a',
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
                        # Wait for dynamic updates (at least 1s)
                        page.wait_for_timeout(2000)
                        page_num += 1
                    except Exception as e:
                        logger.error(f"Error clicking Next button: {e}")
                        break
                else:
                    logger.info("No Next Page button found. Pagination finished.")
                    break

            context.close()

            # Process matched listings and retrieve detail pages
            logger.info(f"Total listings matched with mode '{target_mode}': {len(listings)}")
            for index, list_item in enumerate(listings):
                # Rate limit check: delay at least 1 second
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
                        logger.info(f"Skipping detail page for existing job: {list_item['url']}")
                        scraped_jobs.append({
                            "company_name": existing.company_name,
                            "role_title": existing.role_title,
                            "jd_text": existing.jd_text,
                            "location": existing.location,
                            "application_url": existing.application_url,
                            "posting_date": existing.posting_date,
                            "listing_type": existing.listing_type,
                            "source": existing.source,
                        })
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

        logger.info(f"Finished Lever scrape. Successfully scraped {len(scraped_jobs)} jobs.")
        return scraped_jobs


def main() -> None:
    """CLI entry point for running the Lever scraper."""
    parser = argparse.ArgumentParser(description="Scrape Lever career page.")
    parser.add_argument(
        "--url", type=str, required=True, help="URL of the Lever career board"
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
        scraper = LeverScraper(db_session=db)
        scraper.scrape(args.url, args.mode)
    finally:
        db.close()


if __name__ == "__main__":
    main()
