"""Static page scraper for HireFlow AI.

Uses requests + BeautifulSoup to scrape career pages that are plain HTML
(no JavaScript rendering required).  This is faster and lighter than
Playwright and should be preferred whenever a page delivers its content
in the initial HTML response.
"""

import time
import logging
import urllib.parse

import requests
from bs4 import BeautifulSoup

from src.scrapers.scraper_utils import (
    classify_listing_type,
    extract_company_name,
    is_job_path,
)

logger = logging.getLogger(__name__)


class StaticScraper:
    """Scrapes static HTML career pages using requests + BeautifulSoup."""

    def __init__(self, delay: float = 1.0):
        self.delay = delay
        self.source = "generic"

    def scrape(self, url: str) -> list[dict]:
        """Scrape job listings from a static career page.

        Args:
            url: The URL of the career / jobs listing page.

        Returns:
            A list of normalised job dicts.
        """
        html = self._fetch(url)
        if html is None:
            return []

        soup = BeautifulSoup(html, "lxml")
        job_links = self._extract_job_links(soup, url)

        if not job_links:
            logger.warning(f"No job links found on {url}")
            return []

        results: list[dict] = []
        for link in job_links:
            try:
                job = self._scrape_job(link, url)
                if job:
                    results.append(job)
            except Exception as e:
                logger.error(f"Error scraping job {link}: {e}", exc_info=True)
            time.sleep(self.delay)

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch(self, url: str) -> str | None:
        """Fetch a URL and return the response text, or None on failure."""
        try:
            resp = requests.get(url, timeout=15, headers={"User-Agent": "HireFlow/1.0"})
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            logger.error(f"Failed to fetch {url}: {e}")
            return None

    def _extract_job_links(self, soup: BeautifulSoup, base_url: str) -> list[str]:
        """Find anchor tags whose href looks like a job posting link."""
        seen: set[str] = set()
        links: list[str] = []

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            abs_url = urllib.parse.urljoin(base_url, href)
            # Only follow links whose path contains a job-related keyword
            if not is_job_path(abs_url):
                continue

            # Skip if it's the same page we're already on
            if abs_url.rstrip("/") == base_url.rstrip("/"):
                continue

            if abs_url not in seen:
                seen.add(abs_url)
                links.append(abs_url)

        return links

    def _scrape_job(self, job_url: str, board_url: str) -> dict | None:
        """Fetch an individual job page and extract structured data."""
        html = self._fetch(job_url)
        if html is None:
            return None

        soup = BeautifulSoup(html, "lxml")

        # Extract role title from the first heading
        role_title = self._extract_title(soup)
        if role_title is None:
            logger.warning(f"Could not extract title from {job_url}")
            return None

        location = self._extract_location(soup)
        jd_text = self._extract_description(soup)
        listing_type = classify_listing_type(role_title)

        # Derive company name from the board URL's domain
        company_name = extract_company_name(board_url)

        return {
            "company_name": company_name,
            "role_title": role_title,
            "jd_text": jd_text,
            "location": location,
            "application_url": job_url,
            "listing_type": listing_type,
        }

    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> str | None:
        """Return the role title from the first h1 or h2 on the page."""
        for tag in ("h1", "h2"):
            el = soup.find(tag)
            if el:
                text = el.get_text(strip=True)
                if text:
                    return text
        return None

    @staticmethod
    def _extract_location(soup: BeautifulSoup) -> str | None:
        """Try to find a location element on the page."""
        for class_name in ["location", "job-location", "posting-location"]:
            el = soup.find(class_=class_name)
            if el:
                text = el.get_text(strip=True)
                if text:
                    return text
        return None

    @staticmethod
    def _extract_description(soup: BeautifulSoup) -> str:
        """Extract the main content text from the page."""
        # Try id-based container first
        el = soup.find(id="content")
        if el:
            text = el.get_text(separator="\n", strip=True)
            if text:
                return text

        # Try class-based containers
        for class_name in ["job-description", "description", "job-details"]:
            el = soup.find(class_=class_name)
            if el:
                text = el.get_text(separator="\n", strip=True)
                if text:
                    return text

        # Fallback: body text
        body = soup.find("body")
        if body:
            return body.get_text(separator="\n", strip=True)

        return "Description not found."
