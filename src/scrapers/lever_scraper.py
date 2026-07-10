import time
import logging
import argparse
import urllib.parse
from playwright.sync_api import (
    sync_playwright,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

from src.models.job import Job
from src.config.database import SessionLocal

logger = logging.getLogger(__name__)


class LeverScraper:
    def __init__(self, delay: float = 1.0):
        self.delay = delay
        self.source = "lever"

    def scrape(self, company_name: str, board_url: str) -> None:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            try:
                self._scrape_board(page, company_name, board_url)
            except Exception as e:
                logger.error(f"Error scraping {board_url}: {e}", exc_info=True)
            finally:
                browser.close()

    def _scrape_board(self, page: Page, company_name: str, board_url: str):
        try:
            page.goto(board_url, wait_until="domcontentloaded")
        except Exception as e:
            logger.error(f"Failed to load board {board_url}: {e}", exc_info=True)
            return

        time.sleep(self.delay)

        job_links = set()
        while True:
            previous_size = len(job_links)

            # Find all job links
            try:
                links = page.locator(".posting-title").all()
                for link in links:
                    href = link.get_attribute("href")
                    if href:
                        abs_href = urllib.parse.urljoin(board_url, href)
                        # Ensure it's a valid link with a path
                        parsed = urllib.parse.urlparse(abs_href)
                        path_parts = [p for p in parsed.path.split("/") if p]
                        if len(path_parts) >= 1:
                            job_links.add(abs_href)
            except Exception as e:
                logger.error(f"Error extracting links: {e}", exc_info=True)

            # Pagination check
            try:
                next_btn = page.locator(
                    "a:has-text('Next'), button:has-text('Next'), .pagination-next"
                ).first
                if next_btn.is_visible(timeout=1000) and next_btn.is_enabled():
                    next_btn.click()
                    # Wait for stability instead of arbitrary sleep
                    page.wait_for_load_state("domcontentloaded")
                    time.sleep(self.delay)
                else:
                    break
            except Exception:
                break

            # Infinite loop protection
            if len(job_links) == previous_size:
                logger.warning(
                    "Pagination did not yield new links. Breaking to avoid infinite loop."
                )
                break

        # Scrape each job
        for link in job_links:
            try:
                self._scrape_job(page, company_name, link)
            except Exception as e:
                logger.error(f"Error scraping job {link}: {e}", exc_info=True)
            time.sleep(self.delay)

    def _classify_listing_type(self, title: str) -> str:
        title_lower = title.lower()
        if any(
            keyword in title_lower
            for keyword in ["intern", "internship", "co-op", "coop"]
        ):
            return "internship"
        return "job"

    def _scrape_job(self, page: Page, company_name: str, job_url: str):
        try:
            page.goto(job_url, wait_until="domcontentloaded")
        except Exception as e:
            logger.error(f"Failed to load job {job_url}: {e}", exc_info=True)
            return

        try:
            role_title_loc = page.locator(".posting-headline h2")
            if role_title_loc.is_visible(timeout=3000):
                role_title = role_title_loc.inner_text().strip()
            else:
                role_title = page.locator("h1").first.inner_text(timeout=2000).strip()
        except PlaywrightTimeoutError:
            role_title = "Unknown Role"
        except Exception as e:
            logger.error(f"Failed to extract title for {job_url}: {e}", exc_info=True)
            return

        try:
            loc_locator = page.locator(
                ".sort-by-time.posting-category, .location"
            ).first
            if loc_locator.is_visible(timeout=1000):
                location = loc_locator.inner_text().strip()
            else:
                location = None
        except Exception:
            location = None

        try:
            # Lever typically uses data-qa attributes for the job description and requirements
            jd_locators = page.locator(
                "[data-qa='job-description'], [data-qa='posting-requirements']"
            ).all()
            if jd_locators:
                jd_text = "\n\n".join(loc.inner_text().strip() for loc in jd_locators)
            else:
                # Fallback to general content wrapper or page-centered section (used by tests)
                try:
                    page.wait_for_selector(
                        ".content-wrapper, .section.page-centered", timeout=2000
                    )
                    jd_text = (
                        page.locator(".content-wrapper, .section.page-centered")
                        .first.inner_text()
                        .strip()
                    )
                except Exception:
                    page.wait_for_selector("body", timeout=2000)
                    jd_text = page.locator("body").inner_text().strip()
        except Exception:
            jd_text = "Description not found."

        # Note on posting_date: Lever does not natively expose the posting date
        # in standard HTML elements on the public job posting page. We gracefully
        # store None.

        listing_type = self._classify_listing_type(role_title)

        self._save_job(
            company_name=company_name,
            role_title=role_title,
            jd_text=jd_text,
            location=location,
            application_url=job_url,
            posting_date=None,
            listing_type=listing_type,
        )

    def _save_job(
        self,
        company_name,
        role_title,
        jd_text,
        location,
        application_url,
        posting_date,
        listing_type,
    ):
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
                    source=self.source,
                )
                db.add(job)
                db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"DB Error saving job {application_url}: {e}", exc_info=True)
        finally:
            db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape jobs from a Lever board.")
    parser.add_argument("--url", required=True, help="URL of the Lever job board.")
    parser.add_argument(
        "--mode", required=False, default="job", help="Mode filter (e.g., job)."
    )
    args = parser.parse_args()

    parsed_url = urllib.parse.urlparse(args.url)
    path_segments = [seg for seg in parsed_url.path.split("/") if seg]

    if path_segments:
        company_name = path_segments[0]
    else:
        company_name = "unknown_company"

    logger.info(f"Starting Lever Scraper for {company_name} at {args.url}")
    scraper = LeverScraper()
    scraper.scrape(company_name, args.url)
    logger.info("Scraping completed.")
