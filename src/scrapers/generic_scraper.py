"""Generic scraper for HireFlow AI.

Auto-detects whether a career page is static HTML or JavaScript-rendered
and routes to the appropriate parser:

* **Static** → requests + BeautifulSoup  (fast, lightweight)
* **Dynamic** → Playwright              (full browser, handles SPAs)

Usage::

    from src.scrapers.generic_scraper import GenericScraper

    scraper = GenericScraper()
    jobs = scraper.scrape("https://example.com/careers")
"""

import argparse
import logging
import time
import urllib.parse

from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)
from playwright.sync_api import (
    sync_playwright,
)

from src.scrapers.scraper_utils import (
    classify_listing_type,
    extract_company_name,
    is_job_path,
    save_job,
)
from src.scrapers.static_scraper import StaticScraper

logger = logging.getLogger(__name__)


class GenericScraper:
    """Scrapes any career page by auto-detecting static vs dynamic content."""

    def __init__(self, delay: float = 1.0):
        self.delay = delay
        self.source = "generic"

    def scrape(self, url: str) -> list[dict]:
        """Scrape job listings from any career page.

        1. Try parsing statically with requests + BeautifulSoup.
        2. If jobs are found, save and return them.
        3. If no jobs are found, fallback to Playwright (for JS-rendered pages).
        4. If Playwright finds jobs, save and return them.
        5. If neither works, raise RuntimeError.

        Args:
            url: The URL of the career / jobs listing page.

        Returns:
            A list of normalised job dicts.
        """
        logger.info(f"Attempting static scrape for {url}")
        static_scraper = StaticScraper(delay=self.delay)
        jobs = static_scraper.scrape(url)

        if jobs:
            logger.info(f"Static scrape successful. Found {len(jobs)} jobs.")
            self._save_jobs(jobs)
            return jobs

        logger.info(
            f"Static scrape found no jobs for {url}. Attempting dynamic scrape."
        )
        jobs = self._scrape_dynamic(url)

        if jobs:
            logger.info(f"Dynamic scrape successful. Found {len(jobs)} jobs.")
            self._save_jobs(jobs)
            return jobs

        raise RuntimeError(
            f"Neither static nor dynamic parsing could find job listings for {url}."
        )

    def _save_jobs(self, jobs: list[dict]) -> None:
        """Persist jobs using shared utility."""
        for job in jobs:
            save_job(
                source=self.source,
                company_name=job["company_name"],
                role_title=job["role_title"],
                jd_text=job["jd_text"],
                location=job.get("location"),
                application_url=job["application_url"],
                listing_type=job["listing_type"],
            )

    # ------------------------------------------------------------------
    # Dynamic path (Playwright)
    # ------------------------------------------------------------------

    def _scrape_dynamic(self, url: str) -> list[dict]:
        """Scrape a JS-rendered page using Playwright."""
        results: list[dict] = []

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()

                try:
                    page.goto(url, wait_until="networkidle", timeout=15000)
                except Exception as e:
                    logger.error(
                        f"Failed to load dynamic page {url}: {e}", exc_info=True
                    )
                    browser.close()
                    return []

                # Collect job links
                job_links = self._collect_dynamic_links(page, url)

                if not job_links:
                    logger.warning(f"No job links found on dynamic page {url}")
                    browser.close()
                    return []

                for link in job_links:
                    try:
                        job = self._scrape_dynamic_job(page, link, url)
                        if job:
                            results.append(job)
                    except Exception as e:
                        logger.error(
                            f"Error scraping dynamic job {link}: {e}", exc_info=True
                        )
                    time.sleep(self.delay)

                browser.close()
        except Exception as e:
            logger.error(f"Playwright error: {e}", exc_info=True)

        return results

    def _collect_dynamic_links(self, page, base_url: str) -> list[str]:
        """Extract job-like links from a Playwright-rendered page."""
        seen: set[str] = set()
        links: list[str] = []

        all_anchors = page.locator("a[href]").all()
        for anchor in all_anchors:
            try:
                href = anchor.get_attribute("href")
                if not href:
                    continue
                abs_url = urllib.parse.urljoin(base_url, href)
                if not is_job_path(abs_url):
                    continue

                if abs_url.rstrip("/") == base_url.rstrip("/"):
                    continue

                if abs_url not in seen:
                    seen.add(abs_url)
                    links.append(abs_url)
            except Exception:
                continue

        return links

    def _scrape_dynamic_job(self, page, job_url: str, board_url: str) -> dict | None:
        """Navigate to a single job page and extract data with Playwright."""
        try:
            page.goto(job_url, wait_until="domcontentloaded", timeout=10000)
        except Exception as e:
            logger.error(f"Failed to load job {job_url}: {e}", exc_info=True)
            return None

        # Title
        try:
            title_loc = page.locator("h1").first
            if title_loc.is_visible(timeout=3000):
                role_title = title_loc.inner_text().strip()
            else:
                role_title = page.locator("h2").first.inner_text(timeout=2000).strip()
        except PlaywrightTimeoutError:
            role_title = "Unknown Role"
        except Exception:
            role_title = "Unknown Role"

        if not role_title:
            role_title = "Unknown Role"

        # Location
        try:
            loc_locator = page.locator(".location, .job-location").first
            if loc_locator.is_visible(timeout=1000):
                location = loc_locator.inner_text().strip() or None
            else:
                location = None
        except Exception:
            location = None

        # Description
        try:
            desc_locator = page.locator(
                "#content, .job-description, .description, .job-details"
            ).first
            if desc_locator.is_visible(timeout=1000):
                jd_text = desc_locator.inner_text().strip()
            else:
                jd_text = page.locator("body").inner_text().strip()
        except Exception:
            jd_text = "Description not found."

        listing_type = classify_listing_type(role_title)

        company_name = extract_company_name(board_url)

        return {
            "company_name": company_name,
            "role_title": role_title,
            "jd_text": jd_text,
            "location": location,
            "application_url": job_url,
            "listing_type": listing_type,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(
        description="Scrape jobs from any career page (auto-detects static vs dynamic)."
    )
    parser.add_argument("--url", required=True, help="URL of the career page.")
    args = parser.parse_args()

    scraper = GenericScraper()
    jobs = scraper.scrape(args.url)
    logger.info(f"Scraped {len(jobs)} jobs from {args.url}")
    for job in jobs:
        logger.info(f"  {job['role_title']} — {job.get('location', 'N/A')}")
