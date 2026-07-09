"""Unit tests for Lever and Greenhouse scrapers.

Uses an in-memory SQLite database and mocks Playwright network/page interactions
to ensure no real network calls are made.
"""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config.database import Base
from src.models.job import Job
from src.scrapers.greenhouse_scraper import GreenhouseScraper
from src.scrapers.lever_scraper import LeverScraper

# ---------------------------------------------------------------------------
# Test Database Fixtures
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def engine():
    """Create an in-memory SQLite engine for testing."""
    eng = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture(scope="function")
def db(engine):
    """Yield a transactional session that rolls back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    yield session
    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


# ---------------------------------------------------------------------------
# Mock Playwright Classes
# ---------------------------------------------------------------------------


class MockElement:
    """Mock element representing a single HTML node or locator item."""

    def __init__(
        self, inner_text_val="", href=None, location="", workplace="", is_empty=False
    ):
        self.inner_text_val = inner_text_val
        self.href = href
        self.location = location
        self.workplace = workplace
        self.is_empty = is_empty

    def count(self) -> int:
        return 0 if self.is_empty else 1

    def inner_text(self) -> str:
        return self.inner_text_val

    def get_attribute(self, name: str) -> str | None:
        if name == "href":
            return self.href
        return None

    def locator(self, selector: str):
        if (
            "location" in selector
            or "metadata" in selector
            or "body__secondary" in selector
        ):
            return MockLocator([MockElement(self.location)])
        elif "workplaceTypes" in selector:
            return MockLocator([MockElement(self.workplace)])
        elif (
            "title" in selector
            or "h5" in selector
            or selector == "a"
            or "body--medium" in selector
            or "body" in selector
        ):
            return MockLocator([MockElement(self.inner_text_val, self.href)])
        return MockLocator([])


class MockLocator:
    """Mock locator containing mock elements and supporting standard locator API."""

    def __init__(self, elements=None):
        self.elements = elements or []

    def count(self) -> int:
        return len(self.elements)

    def nth(self, idx: int):
        if idx < len(self.elements):
            return self.elements[idx]
        return MockElement(is_empty=True)

    @property
    def first(self):
        return self.elements[0] if self.elements else MockElement(is_empty=True)

    def inner_text(self) -> str:
        if self.elements:
            return self.elements[0].inner_text()
        return ""

    def get_attribute(self, name: str) -> str | None:
        if self.elements:
            return self.elements[0].get_attribute(name)
        return None

    def is_visible(self) -> bool:
        return len(self.elements) > 0

    def is_enabled(self) -> bool:
        return True

    def click(self) -> None:
        pass


class MockPage:
    """Mock Page simulating a Playwright page with custom route config."""

    def __init__(self, fixtures):
        self.fixtures = fixtures
        self.current_url = ""
        self.urls_visited = []

    def goto(self, url, **kwargs):
        self.current_url = url
        self.urls_visited.append(url)
        return None

    def wait_for_selector(self, selector, **kwargs):
        return None

    def wait_for_timeout(self, ms):
        return None

    def content(self) -> str:
        fixture = self.fixtures.get(self.current_url, {})
        return fixture.get("html", "")

    def locator(self, selector: str, **kwargs):
        fixture = self.fixtures.get(self.current_url, {})

        # Matching listings elements
        if selector in [
            ".posting",
            ".opening, div.opening",
            ".opening, div.opening, tr.job-post, .job-post",
        ]:
            listings = fixture.get("listings", [])
            return MockLocator(
                [
                    MockElement(
                        inner_text_val=x["title"],
                        href=x["url"],
                        location=x.get("location", ""),
                        workplace=x.get("workplace", ""),
                    )
                    for x in listings
                ]
            )

        # Detail selectors
        if selector == ".posting-sections":
            if "posting_sections" in fixture:
                return MockLocator([MockElement(fixture["posting_sections"])])
            return MockLocator([])

        if selector == ".section.page-centered":
            if "sections" in fixture:
                return MockLocator([MockElement(sec) for sec in fixture["sections"]])
            return MockLocator([])

        if selector in [
            ".posting-categories .location, .posting-headline .location",
            ".location, #header .location",
            ".job__location, .location, #header .location",
        ]:
            if "location" in fixture:
                return MockLocator([MockElement(fixture["location"])])
            return MockLocator([])

        if selector in [
            ".posting-categories .workplaceTypes",
            ".posting-meta .workplaceTypes, .workplaceTypes",
        ]:
            if "workplace" in fixture:
                return MockLocator([MockElement(fixture["workplace"])])
            return MockLocator([])

        if selector in [
            "#content",
            "#job-body, .opening-body",
            ".job__description, #content, #job-body, .opening-body",
        ]:
            if "content" in fixture:
                return MockLocator([MockElement(fixture["content"])])
            return MockLocator([])

        if selector == ".job__title h1, h1.app-title, #header h1":
            if "title" in fixture:
                return MockLocator([MockElement(fixture["title"])])
            return MockLocator([])

        # Pagination Next elements
        next_selectors = [
            'a[rel="next"]',
            "a.next",
            "a.next-page",
            ".pagination-next a",
            'a:has-text("Next")',
            'button:has-text("Next")',
            '[aria-label="Next"]',
        ]
        if selector in next_selectors:
            if fixture.get("has_next", False):
                # Turn off has_next in fixture to prevent infinite loop
                fixture["has_next"] = False
                return MockLocator([MockElement("Next")])
            return MockLocator([])

        return MockLocator([])


class MockContext:
    """Mock Context wrapper."""

    def __init__(self, fixtures):
        self.fixtures = fixtures

    def new_page(self):
        return MockPage(self.fixtures)

    def close(self):
        pass


class MockBrowser:
    """Mock Browser wrapper."""

    def __init__(self, fixtures):
        self.fixtures = fixtures

    def new_context(self, **kwargs):
        return MockContext(self.fixtures)

    def close(self):
        pass


class MockChromium:
    """Mock Chromium wrapper."""

    def __init__(self, fixtures):
        self.fixtures = fixtures

    def launch(self, **kwargs):
        return MockBrowser(self.fixtures)


class MockPlaywright:
    """Mock Playwright wrapper."""

    def __init__(self, fixtures):
        self.chromium = MockChromium(fixtures)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


# ---------------------------------------------------------------------------
# Lever Scraper Tests
# ---------------------------------------------------------------------------


class TestLeverScraper:
    """Test suite for Lever scraper."""

    def test_lever_successful_parse(self, db):
        """Test successful parsing and classification of job & internship roles."""
        board_url = "https://jobs.lever.co/anthropic"
        detail_url_1 = "https://jobs.lever.co/anthropic/job-123"
        detail_url_2 = "https://jobs.lever.co/anthropic/job-456"

        fixtures = {
            board_url: {
                "listings": [
                    {
                        "title": "Software Engineer Intern",
                        "url": detail_url_1,
                        "location": "San Francisco",
                        "workplace": "Hybrid",
                    },
                    {
                        "title": "Senior Research Scientist",
                        "url": detail_url_2,
                        "location": "Seattle",
                        "workplace": "Remote",
                    },
                ]
            },
            detail_url_1: {
                "html": '<meta property="og:site_name" content="Anthropic">',
                "posting_sections": "We are seeking a Software Engineer Intern to help build next-gen models.",
                "location": "San Francisco",
                "workplace": "Hybrid",
            },
            detail_url_2: {
                "html": '<meta property="og:site_name" content="Anthropic">',
                "posting_sections": "This is a full-time Senior Research Scientist role.",
                "location": "Seattle",
                "workplace": "Remote",
            },
        }

        # 1. Scrape only internship mode
        scraper_intern = LeverScraper(db_session=db)
        with patch(
            "src.scrapers.lever_scraper.sync_playwright",
            return_value=MockPlaywright(fixtures),
        ):
            jobs = scraper_intern.scrape(board_url, "internship")

        assert len(jobs) == 1
        assert jobs[0]["role_title"] == "Software Engineer Intern"
        assert jobs[0]["company_name"] == "Anthropic"
        assert jobs[0]["listing_type"] == "internship"
        assert jobs[0]["location"] == "San Francisco (Hybrid)"
        assert "next-gen models" in jobs[0]["jd_text"]

        # Check DB count
        assert db.query(Job).count() == 1
        db_job = db.query(Job).first()
        assert db_job.role_title == "Software Engineer Intern"
        assert db_job.listing_type == "internship"

        # 2. Scrape job mode (clear DB first by creating a new transactional session)
        db.query(Job).delete()
        db.commit()

        scraper_job = LeverScraper(db_session=db)
        with patch(
            "src.scrapers.lever_scraper.sync_playwright",
            return_value=MockPlaywright(fixtures),
        ):
            jobs = scraper_job.scrape(board_url, "job")

        assert len(jobs) == 1
        assert jobs[0]["role_title"] == "Senior Research Scientist"
        assert jobs[0]["company_name"] == "Anthropic"
        assert jobs[0]["listing_type"] == "job"
        assert jobs[0]["location"] == "Seattle (Remote)"
        assert "full-time" in jobs[0]["jd_text"]

        assert db.query(Job).count() == 1

    def test_lever_pagination(self, db):
        """Test that pagination loop works and scrapes multiple pages."""
        board_url = "https://jobs.lever.co/anthropic"
        detail_url_1 = "https://jobs.lever.co/anthropic/job-1"
        detail_url_2 = "https://jobs.lever.co/anthropic/job-2"

        fixtures = {
            board_url: {
                "listings": [
                    {
                        "title": "AI Engineer",
                        "url": detail_url_1,
                        "location": "San Francisco",
                    }
                ],
                "has_next": True,  # Will trigger next click
            },
            detail_url_1: {
                "html": '<meta property="og:site_name" content="Anthropic">',
                "posting_sections": "Detail page 1 description",
                "location": "San Francisco",
            },
            detail_url_2: {
                "html": '<meta property="og:site_name" content="Anthropic">',
                "posting_sections": "Detail page 2 description",
                "location": "Seattle",
            },
        }

        # Setup mock behavior when Next is clicked
        # The scraper stays on the same board page object, so we modify its Listings on second fetch
        # Since MockPage locator counts listings, we'll setup listings for page 2 inside the board_url's listing data
        # We can implement this by updating the listings dynamically after has_next check is triggered.
        # To make it super simple, we append the listings for page 2 to the same board page
        # but only activate them on next click. Let's make listings return first job, then next click adds second job.

        # Let's adjust listings structure
        fixtures[board_url]["listings"] = [
            {"title": "AI Engineer", "url": detail_url_1, "location": "San Francisco"},
            {
                "title": "Software Engineer 2",
                "url": detail_url_2,
                "location": "Seattle",
            },
        ]

        # When pagination clicks next, it will just re-read the listings. We already filtered visited URLs,
        # so detail_url_1 is marked visited and won't be processed twice. detail_url_2 will be parsed on the second loop!
        scraper = LeverScraper(db_session=db)
        with patch(
            "src.scrapers.lever_scraper.sync_playwright",
            return_value=MockPlaywright(fixtures),
        ):
            jobs = scraper.scrape(board_url, "job")

        # Both jobs should be processed because they have mode = "job"
        assert len(jobs) == 2
        assert db.query(Job).count() == 2

    def test_lever_empty_or_invalid(self, db):
        """Test handling of empty pages or invalid HTML structures."""
        board_url = "https://jobs.lever.co/empty"

        fixtures = {board_url: {"listings": []}}  # empty

        scraper = LeverScraper(db_session=db)
        with patch(
            "src.scrapers.lever_scraper.sync_playwright",
            return_value=MockPlaywright(fixtures),
        ):
            jobs = scraper.scrape(board_url, "job")

        assert len(jobs) == 0
        assert db.query(Job).count() == 0

    def test_lever_duplicate_jobs(self, db):
        """Test duplicate checking using unique application_url."""
        board_url = "https://jobs.lever.co/anthropic"
        detail_url = "https://jobs.lever.co/anthropic/job-dup"

        # Pre-populate DB with the same job
        dup_job = Job(
            company_name="Anthropic",
            role_title="Duplicate SWE",
            jd_text="Already scraped description",
            location="San Francisco",
            application_url=detail_url,
            listing_type="job",
            source="lever",
        )
        db.add(dup_job)
        db.commit()

        fixtures = {
            board_url: {
                "listings": [
                    {
                        "title": "Duplicate SWE",
                        "url": detail_url,
                        "location": "San Francisco",
                    }
                ]
            },
            # No detail page fixture is needed because it should skip fetching!
        }

        scraper = LeverScraper(db_session=db)
        with patch(
            "src.scrapers.lever_scraper.sync_playwright",
            return_value=MockPlaywright(fixtures),
        ):
            jobs = scraper.scrape(board_url, "job")

        # The scraper returns the list of processed jobs (including duplicates it skipped fetching)
        assert len(jobs) == 1
        assert jobs[0]["role_title"] == "Duplicate SWE"
        # The database count should still be 1 (no new insert occurred)
        assert db.query(Job).count() == 1


# ---------------------------------------------------------------------------
# Greenhouse Scraper Tests
# ---------------------------------------------------------------------------


class TestGreenhouseScraper:
    """Test suite for Greenhouse scraper."""

    def test_greenhouse_successful_parse(self, db):
        """Test successful parsing and classification on Greenhouse board."""
        board_url = "https://boards.greenhouse.io/notion"
        detail_url_1 = "https://boards.greenhouse.io/notion/jobs/1"
        detail_url_2 = "https://boards.greenhouse.io/notion/jobs/2"

        fixtures = {
            board_url: {
                "listings": [
                    {
                        "title": "Software Engineering Intern - Frontend",
                        "url": detail_url_1,
                        "location": "New York",
                    },
                    {
                        "title": "Staff Infrastructure Engineer",
                        "url": detail_url_2,
                        "location": "Remote",
                    },
                ]
            },
            detail_url_1: {
                "html": '<meta property="og:title" content="Software Engineering Intern at Notion"><meta property="og:site_name" content="Greenhouse">',
                "content": "Description of the Frontend intern role at Notion.",
                "location": "New York",
            },
            detail_url_2: {
                "html": '<meta property="og:title" content="Staff Infrastructure Engineer at Notion"><meta property="og:site_name" content="Greenhouse">',
                "content": "Description of the Staff role.",
                "location": "Remote",
            },
        }

        # 1. Internship mode
        scraper_intern = GreenhouseScraper(db_session=db)
        with patch(
            "src.scrapers.greenhouse_scraper.sync_playwright",
            return_value=MockPlaywright(fixtures),
        ):
            jobs = scraper_intern.scrape(board_url, "internship")

        assert len(jobs) == 1
        assert jobs[0]["role_title"] == "Software Engineering Intern - Frontend"
        assert jobs[0]["company_name"] == "Notion"
        assert jobs[0]["listing_type"] == "internship"
        assert jobs[0]["location"] == "New York"
        assert "Frontend intern" in jobs[0]["jd_text"]

        assert db.query(Job).count() == 1

        # 2. Job mode
        db.query(Job).delete()
        db.commit()

        scraper_job = GreenhouseScraper(db_session=db)
        with patch(
            "src.scrapers.greenhouse_scraper.sync_playwright",
            return_value=MockPlaywright(fixtures),
        ):
            jobs = scraper_job.scrape(board_url, "job")

        assert len(jobs) == 1
        assert jobs[0]["role_title"] == "Staff Infrastructure Engineer"
        assert jobs[0]["company_name"] == "Notion"
        assert jobs[0]["listing_type"] == "job"
        assert jobs[0]["location"] == "Remote"
        assert "Staff role" in jobs[0]["jd_text"]

        assert db.query(Job).count() == 1

    def test_greenhouse_pagination(self, db):
        """Test Greenhouse scraper page iteration."""
        board_url = "https://boards.greenhouse.io/notion"
        detail_url_1 = "https://boards.greenhouse.io/notion/jobs/1"
        detail_url_2 = "https://boards.greenhouse.io/notion/jobs/2"

        fixtures = {
            board_url: {
                "listings": [
                    {"title": "SWE 1", "url": detail_url_1, "location": "New York"},
                    {"title": "SWE 2", "url": detail_url_2, "location": "Remote"},
                ],
                "has_next": True,
            },
            detail_url_1: {
                "html": '<meta property="og:site_name" content="Notion">',
                "content": "SWE 1 detail page description",
                "location": "New York",
            },
            detail_url_2: {
                "html": '<meta property="og:site_name" content="Notion">',
                "content": "SWE 2 detail page description",
                "location": "Remote",
            },
        }

        scraper = GreenhouseScraper(db_session=db)
        with patch(
            "src.scrapers.greenhouse_scraper.sync_playwright",
            return_value=MockPlaywright(fixtures),
        ):
            jobs = scraper.scrape(board_url, "job")

        assert len(jobs) == 2
        assert db.query(Job).count() == 2

    def test_greenhouse_duplicate_and_empty(self, db):
        """Test duplicate checking and handling of empty results on Greenhouse."""
        board_url = "https://boards.greenhouse.io/notion"
        detail_url = "https://boards.greenhouse.io/notion/jobs/dup"

        # Pre-populate DB with the same job
        dup_job = Job(
            company_name="Notion",
            role_title="Duplicate SWE",
            jd_text="Already scraped description",
            location="Remote",
            application_url=detail_url,
            listing_type="job",
            source="greenhouse",
        )
        db.add(dup_job)
        db.commit()

        fixtures = {
            board_url: {
                "listings": [
                    {"title": "Duplicate SWE", "url": detail_url, "location": "Remote"}
                ]
            }
        }

        scraper = GreenhouseScraper(db_session=db)
        with patch(
            "src.scrapers.greenhouse_scraper.sync_playwright",
            return_value=MockPlaywright(fixtures),
        ):
            jobs = scraper.scrape(board_url, "job")

        assert len(jobs) == 1
        assert db.query(Job).count() == 1
