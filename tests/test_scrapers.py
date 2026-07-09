
from unittest.mock import patch, MagicMock
from src.scrapers.lever_scraper import (
    scrape_lever,
    determine_listing_type as lever_determine_listing_type,
)
from src.scrapers.greenhouse_scraper import (
    scrape_greenhouse,
    determine_listing_type as gh_determine_listing_type,
)


def test_lever_determine_listing_type():
    assert lever_determine_listing_type("Software Engineering Intern") == "internship"
    assert lever_determine_listing_type("Summer Internship 2024") == "internship"
    assert lever_determine_listing_type("Senior Backend Engineer") == "job"


@patch("src.scrapers.lever_scraper.sync_playwright")
@patch("src.scrapers.lever_scraper.SessionLocal")
@patch("src.scrapers.lever_scraper.time.sleep")
def test_lever_extraction(mock_sleep, mock_db, mock_playwright):
    mock_browser = MagicMock()
    mock_page = MagicMock()
    mock_playwright.return_value.__enter__.return_value.chromium.launch.return_value = (
        mock_browser
    )
    mock_browser.new_page.return_value = mock_page

    mock_posting = MagicMock()
    mock_posting.get_attribute.return_value = "https://jobs.lever.co/company/job1"
    mock_page.query_selector_all.return_value = [mock_posting]

    mock_title = MagicMock()
    mock_title.inner_text.return_value = "Software Engineer"
    mock_loc = MagicMock()
    mock_loc.inner_text.return_value = "Remote"
    mock_jd = MagicMock()
    mock_jd.inner_text.return_value = "We are looking for..."

    def query_selector_side_effect(selector):
        if "h2" in selector:
            return mock_title
        elif ".location" in selector:
            return mock_loc
        elif (
            "content" in selector
            or "section-wrapper" in selector
            or "job-description" in selector
        ):
            return mock_jd
        return None

    mock_page.query_selector.side_effect = query_selector_side_effect

    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = None
    mock_db.return_value = mock_session

    scrape_lever("https://jobs.lever.co/testcompany", "all")

    mock_sleep.assert_called_once_with(1)
    mock_session.add.assert_called_once()
    added_job = mock_session.add.call_args[0][0]
    assert added_job.role_title == "Software Engineer"
    assert added_job.location == "Remote"
    assert added_job.company_name == "Testcompany"
    assert added_job.listing_type == "job"


@patch("src.scrapers.lever_scraper.sync_playwright")
@patch("src.scrapers.lever_scraper.SessionLocal")
@patch("src.scrapers.lever_scraper.time.sleep")
def test_lever_skips_existing(mock_sleep, mock_db, mock_playwright):
    mock_browser = MagicMock()
    mock_page = MagicMock()
    mock_playwright.return_value.__enter__.return_value.chromium.launch.return_value = (
        mock_browser
    )
    mock_browser.new_page.return_value = mock_page

    mock_posting = MagicMock()
    mock_posting.get_attribute.return_value = "https://jobs.lever.co/company/job1"
    mock_page.query_selector_all.return_value = [mock_posting]

    mock_session = MagicMock()
    # return a mock job so it skips insertion
    mock_session.query.return_value.filter.return_value.first.return_value = MagicMock()
    mock_db.return_value = mock_session

    scrape_lever("https://jobs.lever.co/testcompany", "all")

    mock_session.add.assert_not_called()


def test_greenhouse_determine_listing_type():
    assert gh_determine_listing_type("Product Manager Intern") == "internship"
    assert gh_determine_listing_type("Account Executive") == "job"


@patch("src.scrapers.greenhouse_scraper.sync_playwright")
@patch("src.scrapers.greenhouse_scraper.SessionLocal")
@patch("src.scrapers.greenhouse_scraper.time.sleep")
def test_greenhouse_extraction(mock_sleep, mock_db, mock_playwright):
    mock_browser = MagicMock()
    mock_page = MagicMock()
    mock_playwright.return_value.__enter__.return_value.chromium.launch.return_value = (
        mock_browser
    )
    mock_browser.new_page.return_value = mock_page

    mock_anchor = MagicMock()
    mock_anchor.get_attribute.return_value = "/testcompany/jobs/123"
    mock_page.query_selector_all.return_value = [mock_anchor]

    mock_title = MagicMock()
    mock_title.inner_text.return_value = "Data Science Intern"
    mock_loc = MagicMock()
    mock_loc.inner_text.return_value = "New York"
    mock_jd = MagicMock()
    mock_jd.inner_text.return_value = "Data analysis tasks..."

    def query_selector_side_effect(selector):
        if "h1.app-title" in selector:
            return mock_title
        elif "div.location" in selector:
            return mock_loc
        elif "div#content" in selector:
            return mock_jd
        return None

    mock_page.query_selector.side_effect = query_selector_side_effect

    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = None
    mock_db.return_value = mock_session

    scrape_greenhouse("https://boards.greenhouse.io/testcompany", "all")

    mock_sleep.assert_called_once_with(1)
    mock_session.add.assert_called_once()
    added_job = mock_session.add.call_args[0][0]
    assert added_job.role_title == "Data Science Intern"
    assert added_job.location == "New York"
    assert added_job.listing_type == "internship"


@patch("src.scrapers.greenhouse_scraper.sync_playwright")
@patch("src.scrapers.greenhouse_scraper.SessionLocal")
@patch("src.scrapers.greenhouse_scraper.time.sleep")
def test_greenhouse_pagination(mock_sleep, mock_db, mock_playwright):
    # Simulate finding multiple jobs
    mock_browser = MagicMock()
    mock_page = MagicMock()
    mock_playwright.return_value.__enter__.return_value.chromium.launch.return_value = (
        mock_browser
    )
    mock_browser.new_page.return_value = mock_page

    a1, a2 = MagicMock(), MagicMock()
    a1.get_attribute.return_value = "/jobs/1"
    a2.get_attribute.return_value = "/jobs/2"
    mock_page.query_selector_all.return_value = [a1, a2]

    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = None
    mock_db.return_value = mock_session

    scrape_greenhouse("https://boards.greenhouse.io/testcompany", "all")

    assert mock_sleep.call_count == 2
    assert mock_session.add.call_count == 2
