import os
import pytest
from playwright.sync_api import sync_playwright

from src.scrapers.lever_scraper import LeverScraper
from src.scrapers.greenhouse_scraper import GreenhouseScraper

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


def test_lever_successful_extraction_and_internship(browser_context):
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

    scraper._save_job = mock_save

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


def test_lever_missing_fields_and_malformed(browser_context):
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
    scraper._save_job = lambda **kwargs: saved_jobs.append(kwargs)

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


def test_greenhouse_successful_extraction(browser_context):
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
    scraper._save_job = lambda **kwargs: saved_jobs.append(kwargs)

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


def test_greenhouse_malformed(browser_context):
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
    scraper._save_job = lambda **kwargs: saved_jobs.append(kwargs)

    scraper._scrape_job(page, "TestCompany", "http://fake.com/job")

    assert len(saved_jobs) == 1
    job = saved_jobs[0]
    assert job["role_title"] == "Unknown Role"  # Fallback due to timeout
    assert job["location"] is None
    assert "Just some random unformatted text" in job["jd_text"]
