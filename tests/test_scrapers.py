import os
import pytest
from unittest.mock import patch, MagicMock
from playwright.sync_api import sync_playwright

from src.scrapers.lever_scraper import LeverScraper
from src.scrapers.greenhouse_scraper import GreenhouseScraper
from src.scrapers.generic_scraper import GenericScraper
from src.scrapers.static_scraper import StaticScraper

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def read_fixture(filename: str) -> str:
    with open(os.path.join(FIXTURES_DIR, filename), "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def browser_context():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


# ---------------------------------------------------------
# LEVER TESTS
# ---------------------------------------------------------


def test_lever_successful_extraction_and_internship(browser_context, monkeypatch):
    page = browser_context.new_page()

    mock_html = read_fixture("lever_job.html")
    page.route(
        "**/*",
        lambda route: route.fulfill(
            status=200, content_type="text/html", body=mock_html
        ),
    )

    scraper = LeverScraper(delay=0)
    saved_jobs = []

    def mock_save(**kwargs):
        saved_jobs.append(kwargs)

    monkeypatch.setattr("src.scrapers.lever_scraper.save_job", mock_save)

    scraper._scrape_job(page, "TestCompany", "http://fake.com/job")

    assert len(saved_jobs) == 1
    job = saved_jobs[0]
    assert job["company_name"] == "TestCompany"
    assert job["role_title"] == "Software Engineer Intern"
    assert job["location"] == "Remote"
    assert job["jd_text"] == "We are looking for an intern."
    assert job["listing_type"] == "internship"


def test_lever_pagination(browser_context):
    page = browser_context.new_page()

    page1_html = read_fixture("lever_board_page1.html")
    page2_html = read_fixture("lever_board_page2.html")

    call_count = {"count": 0}

    def route_handler(route):
        call_count["count"] += 1
        if call_count["count"] == 1:
            body = page1_html
        else:
            body = page2_html
        route.fulfill(status=200, content_type="text/html", body=body)

    page.route("**/*", route_handler)

    scraper = LeverScraper(delay=0)
    scraped_links = []
    scraper._scrape_job = lambda p, c, url: scraped_links.append(url)

    scraper._scrape_board(page, "TestCompany", "http://fake.com/board")

    assert len(scraped_links) == 2
    assert "http://fake.com/job1" in scraped_links
    assert "http://fake.com/job2" in scraped_links


def test_lever_missing_fields_and_malformed(browser_context, monkeypatch):
    page = browser_context.new_page()

    mock_html = read_fixture("lever_malformed.html")
    page.route(
        "**/*",
        lambda route: route.fulfill(
            status=200, content_type="text/html", body=mock_html
        ),
    )

    scraper = LeverScraper(delay=0)
    saved_jobs = []
    monkeypatch.setattr(
        "src.scrapers.lever_scraper.save_job",
        lambda **kwargs: saved_jobs.append(kwargs),
    )

    scraper._scrape_job(page, "TestCompany", "http://fake.com/job")

    assert len(saved_jobs) == 1
    job = saved_jobs[0]
    assert job["role_title"] == "Backend Developer"
    assert job["listing_type"] == "job"
    assert job["location"] is None
    assert "Random text that serves as body fallback." in job["jd_text"]


# ---------------------------------------------------------
# GREENHOUSE TESTS
# ---------------------------------------------------------


def test_greenhouse_successful_extraction(browser_context, monkeypatch):
    page = browser_context.new_page()

    mock_html = read_fixture("greenhouse_job.html")
    page.route(
        "**/*",
        lambda route: route.fulfill(
            status=200, content_type="text/html", body=mock_html
        ),
    )

    scraper = GreenhouseScraper(delay=0)
    saved_jobs = []
    monkeypatch.setattr(
        "src.scrapers.greenhouse_scraper.save_job",
        lambda **kwargs: saved_jobs.append(kwargs),
    )

    scraper._scrape_job(page, "TestCompany", "http://fake.com/job")

    assert len(saved_jobs) == 1
    job = saved_jobs[0]
    assert job["role_title"] == "Senior Data Scientist"
    assert job["location"] == "New York, NY"
    assert job["jd_text"] == "You will build models."
    assert job["listing_type"] == "job"


def test_greenhouse_pagination(browser_context):
    page = browser_context.new_page()

    page1_html = read_fixture("greenhouse_board_page1.html")
    page2_html = read_fixture("greenhouse_board_page2.html")

    call_count = {"count": 0}

    def route_handler(route):
        call_count["count"] += 1
        if call_count["count"] == 1:
            body = page1_html
        else:
            body = page2_html
        route.fulfill(status=200, content_type="text/html", body=body)

    page.route("**/*", route_handler)

    scraper = GreenhouseScraper(delay=0)
    scraped_links = []
    scraper._scrape_job = lambda p, c, url: scraped_links.append(url)

    scraper._scrape_board(page, "TestCompany", "http://fake.com/board")

    assert len(scraped_links) == 2
    # Check absolute url reconstruction
    assert "http://fake.com/jobs/123" in scraped_links
    assert "http://fake.com/jobs/456" in scraped_links


def test_greenhouse_malformed(browser_context, monkeypatch):
    page = browser_context.new_page()

    mock_html = read_fixture("greenhouse_malformed.html")
    page.route(
        "**/*",
        lambda route: route.fulfill(
            status=200, content_type="text/html", body=mock_html
        ),
    )

    scraper = GreenhouseScraper(delay=0)
    saved_jobs = []
    monkeypatch.setattr(
        "src.scrapers.greenhouse_scraper.save_job",
        lambda **kwargs: saved_jobs.append(kwargs),
    )

    scraper._scrape_job(page, "TestCompany", "http://fake.com/job")

    assert len(saved_jobs) == 1
    job = saved_jobs[0]
    assert job["role_title"] == "Unknown Role"  # Fallback due to timeout
    assert job["location"] is None
    assert "Just some random unformatted text" in job["jd_text"]


# ---------------------------------------------------------
# GENERIC SCRAPER TESTS
# ---------------------------------------------------------


def test_generic_static_page_extraction():
    """StaticScraper correctly extracts job links and job data from static HTML."""
    board_html = read_fixture("generic_static_page.html")
    job_html = read_fixture("generic_static_job.html")

    def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        if "101" in url:
            resp.text = job_html
        else:
            resp.text = board_html
        return resp

    scraper = StaticScraper(delay=0)

    with patch("src.scrapers.static_scraper.requests.get", side_effect=mock_get):
        jobs = scraper.scrape("http://fake.com/careers")

    # Only the first link (/jobs/101) points to the fixture with a title.
    # The second link (/jobs/102) returns the board HTML (no match for 102),
    # which has a title "Acme Corp — Careers".
    assert len(jobs) >= 1
    first_job = jobs[0]
    assert first_job["role_title"] == "Software Engineer"
    assert first_job["location"] == "San Francisco, CA"
    assert "Build amazing products" in first_job["jd_text"]
    assert first_job["listing_type"] == "job"
    assert first_job["application_url"] == "http://fake.com/jobs/101"


def test_generic_sequential_detection_static_first():
    """GenericScraper tries static scraping first and returns early if jobs are found."""
    scraper = GenericScraper(delay=0)

    mock_jobs = [
        {
            "company_name": "Test",
            "role_title": "Engineer",
            "application_url": "url",
            "listing_type": "job",
        }
    ]

    with patch("src.scrapers.generic_scraper.StaticScraper") as mock_static:
        mock_instance = mock_static.return_value
        mock_instance.scrape.return_value = mock_jobs

        with patch.object(scraper, "_scrape_dynamic") as mock_dynamic, patch.object(
            scraper, "_save_jobs"
        ):

            jobs = scraper.scrape("http://fake.com/careers")

            # Static scraper should be called
            mock_instance.scrape.assert_called_once_with("http://fake.com/careers")
            # Dynamic scraper should NOT be called
            mock_dynamic.assert_not_called()

            assert jobs == mock_jobs


def test_generic_sequential_detection_dynamic_fallback():
    """GenericScraper falls back to dynamic scraping if static returns no jobs."""
    scraper = GenericScraper(delay=0)

    mock_jobs = [
        {
            "company_name": "Test",
            "role_title": "Engineer",
            "application_url": "url",
            "listing_type": "job",
        }
    ]

    with patch("src.scrapers.generic_scraper.StaticScraper") as mock_static:
        mock_instance = mock_static.return_value
        # Static returns no jobs
        mock_instance.scrape.return_value = []

        with patch.object(scraper, "_scrape_dynamic") as mock_dynamic, patch.object(
            scraper, "_save_jobs"
        ):

            # Dynamic returns jobs
            mock_dynamic.return_value = mock_jobs

            jobs = scraper.scrape("http://fake.com/careers")

            # Both should be called
            mock_instance.scrape.assert_called_once_with("http://fake.com/careers")
            mock_dynamic.assert_called_once_with("http://fake.com/careers")

            assert jobs == mock_jobs


def test_generic_sequential_detection_runtime_error():
    """GenericScraper raises RuntimeError if both static and dynamic fail to find jobs."""
    scraper = GenericScraper(delay=0)

    with patch("src.scrapers.generic_scraper.StaticScraper") as mock_static:
        mock_instance = mock_static.return_value
        # Static returns no jobs
        mock_instance.scrape.return_value = []

        with patch.object(scraper, "_scrape_dynamic") as mock_dynamic:
            # Dynamic also returns no jobs
            mock_dynamic.return_value = []

            with pytest.raises(
                RuntimeError,
                match="Neither static nor dynamic parsing could find job listings",
            ):
                scraper.scrape("http://fake.com/careers")


def test_generic_malformed_page():
    """StaticScraper returns an empty list for a page with no job links."""
    malformed_html = read_fixture("generic_malformed_page.html")

    def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.text = malformed_html
        return resp

    scraper = StaticScraper(delay=0)

    with patch("src.scrapers.static_scraper.requests.get", side_effect=mock_get):
        jobs = scraper.scrape("http://fake.com/careers")

    assert jobs == []


def test_generic_empty_listings():
    """StaticScraper returns an empty list when the page has no anchor tags."""
    empty_html = "<html><body><h1>No openings</h1></body></html>"

    def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.text = empty_html
        return resp

    scraper = StaticScraper(delay=0)

    with patch("src.scrapers.static_scraper.requests.get", side_effect=mock_get):
        jobs = scraper.scrape("http://fake.com/careers")

    assert jobs == []


def test_generic_classify_listing_type():
    """Shared classify_listing_type correctly identifies internships."""
    from src.scrapers.scraper_utils import classify_listing_type

    assert classify_listing_type("Software Engineer Intern") == "internship"
    assert classify_listing_type("Data Science Co-Op") == "internship"
    assert classify_listing_type("Senior Backend Developer") == "job"
    assert classify_listing_type("Product Manager") == "job"
