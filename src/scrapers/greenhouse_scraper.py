import time
import logging
import argparse
import urllib.parse
from playwright.sync_api import (
    sync_playwright,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

from src.scrapers.scraper_utils import (
    classify_listing_type,
    save_job,
    extract_company_name,
)

logger = logging.getLogger(__name__)


class GreenhouseScraper:
    def __init__(self, delay: float = 1.0):
        self.delay = delay
        self.source = "greenhouse"

    def scrape(self, company_name: str, board_url: str) -> None:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            try:
                self._scrape_board(page, company_name, board_url)
            except Exception as e:
                logger.error(f"Error scraping {board_url}: {e}")
            finally:
                browser.close()

    def _scrape_board(self, page: Page, company_name: str, board_url: str):
        try:
            page.goto(board_url, wait_until="domcontentloaded")
        except Exception as e:
            logger.error(f"Failed to load board {board_url}: {e}")
            return

        time.sleep(self.delay)

        job_links = set()
        while True:
            previous_size = len(job_links)

            # Find all job links
            try:
                # For new job-boards.greenhouse.io, wait for the links to load
                try:
                    page.wait_for_selector(
                        ".opening a, .job-post a, a[data-mapped='true'], a[href*='/jobs/']",
                        timeout=5000,
                    )
                except PlaywrightTimeoutError:
                    if len(job_links) == 0:
                        raise RuntimeError(
                            f"Could not find any job links on {board_url}. The board may be inactive or selectors have changed."
                        )

                # The classic Greenhouse uses ".opening a", the new "job-boards.greenhouse.io" uses ".job-post a".
                # We'll use a broad CSS selector to capture both.
                openings = page.locator(
                    ".opening a, .job-post a, a[data-mapped='true'], a[href*='/jobs/']"
                ).all()

                for link in openings:
                    try:
                        href = link.get_attribute("href")
                        if href:
                            abs_href = urllib.parse.urljoin(board_url, href)
                            # Ensure it's a greenhouse job link
                            parsed = urllib.parse.urlparse(abs_href)
                            path_parts = [p for p in parsed.path.split("/") if p]
                            if (
                                "greenhouse.io" in abs_href or "jobs" in abs_href
                            ) and len(path_parts) >= 2:
                                job_links.add(abs_href)
                    except Exception as e:
                        logger.error(f"Error extracting links: {e}")
            except Exception as e:
                logger.error(f"Error extracting links: {e}")

            # Pagination check
            try:
                next_btn = page.locator(
                    "a:has-text('Next'), button:has-text('Next'), .pagination-next"
                ).first
                if next_btn.is_visible(timeout=1000) and next_btn.is_enabled():
                    next_btn.click()
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=3000)
                    except PlaywrightTimeoutError:
                        # It might be an SPA, wait a bit for AJAX
                        page.wait_for_timeout(2000)
                    time.sleep(self.delay)
                else:
                    break
            except Exception as e:
                logger.debug(f"Pagination stopped: {e}")
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
                logger.error(f"Error scraping job {link}: {e}")
            time.sleep(self.delay)

    def _scrape_job(self, page: Page, company_name: str, job_url: str):
        try:
            page.goto(job_url, wait_until="domcontentloaded")
            # For new Greenhouse layout, we might need to wait for the job description to load
            try:
                page.wait_for_selector("#content, .job__description", timeout=3000)
            except PlaywrightTimeoutError:
                pass
        except Exception as e:
            logger.error(f"Failed to load job {job_url}: {e}")
            return

        try:
            role_title_loc = page.locator("#header h1, h1.job-title, h1.app-title")
            if role_title_loc.first.is_visible(timeout=3000):
                role_title = role_title_loc.first.inner_text().strip()
            else:
                role_title = page.locator("h1").first.inner_text(timeout=2000).strip()
        except PlaywrightTimeoutError:
            role_title = "Unknown Role"
        except Exception as e:
            logger.error(f"Failed to extract title for {job_url}: {e}")
            return

        try:
            loc_locator = page.locator(".location, .job__location").first
            if loc_locator.is_visible(timeout=1000):
                location = loc_locator.inner_text().strip()
            else:
                location = None
        except Exception:
            location = None

        try:
            jd_locator = page.locator("#content, .job__description").first
            if jd_locator.is_visible(timeout=1000):
                jd_text = jd_locator.inner_text().strip()
            else:
                try:
                    page.wait_for_selector("body", timeout=1000)
                    jd_text = page.locator("body").inner_text().strip()
                except Exception:
                    jd_text = "Description not found."
        except Exception:
            jd_text = "Description not found."

        # Note on posting_date: Greenhouse does not natively expose the posting date
        # in standard HTML elements on the public job posting page. We gracefully
        # store None.

        listing_type = classify_listing_type(role_title)

        save_job(
            source=self.source,
            company_name=company_name,
            role_title=role_title,
            jd_text=jd_text,
            location=location,
            application_url=job_url,
            posting_date=None,
            listing_type=listing_type,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape jobs from a Greenhouse board.")
    parser.add_argument("--url", required=True, help="URL of the Greenhouse job board.")
    parser.add_argument(
        "--mode", required=False, default="job", help="Mode filter (e.g., job)."
    )
    args = parser.parse_args()

    company_name = extract_company_name(args.url)

    logger.info(f"Starting Greenhouse Scraper for {company_name} at {args.url}")
    scraper = GreenhouseScraper()
    scraper.scrape(company_name, args.url)
    logger.info("Scraping completed.")
