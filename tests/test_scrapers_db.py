from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.config.database import Base
from src.models.job import Job
from src.scrapers.lever_scraper import LeverScraper
from src.scrapers.greenhouse_scraper import GreenhouseScraper

# Set up SQLite test database
TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def test_lever_save_job_db():
    Base.metadata.create_all(bind=engine)
    try:
        scraper = LeverScraper(delay=0)
        # Patch SessionLocal to return our in-memory SQLite session
        with patch("src.scrapers.lever_scraper.SessionLocal", TestingSessionLocal):
            scraper._save_job(
                company_name="TestCompany",
                role_title="Software Engineer Intern",
                jd_text="Description text",
                location="San Francisco, CA",
                application_url="https://jobs.lever.co/testcompany/12345",
                posting_date=None,
                listing_type="internship",
            )

            # Query the DB to check
            db = TestingSessionLocal()
            try:
                job = (
                    db.query(Job)
                    .filter_by(
                        application_url="https://jobs.lever.co/testcompany/12345"
                    )
                    .first()
                )
                assert job is not None
                assert job.company_name == "TestCompany"
                assert job.role_title == "Software Engineer Intern"
                assert job.location == "San Francisco, CA"
                assert job.source == "lever"
            finally:
                db.close()
    finally:
        Base.metadata.drop_all(bind=engine)


def test_greenhouse_save_job_db():
    Base.metadata.create_all(bind=engine)
    try:
        scraper = GreenhouseScraper(delay=0)
        # Patch SessionLocal to return our in-memory SQLite session
        with patch("src.scrapers.greenhouse_scraper.SessionLocal", TestingSessionLocal):
            scraper._save_job(
                company_name="TestCompany",
                role_title="Backend Developer",
                jd_text="Description text",
                location="Remote",
                application_url="https://boards.greenhouse.io/testcompany/jobs/67890",
                posting_date=None,
                listing_type="job",
            )

            # Query the DB to check
            db = TestingSessionLocal()
            try:
                job = (
                    db.query(Job)
                    .filter_by(
                        application_url="https://boards.greenhouse.io/testcompany/jobs/67890"
                    )
                    .first()
                )
                assert job is not None
                assert job.company_name == "TestCompany"
                assert job.role_title == "Backend Developer"
                assert job.location == "Remote"
                assert job.source == "greenhouse"
            finally:
                db.close()
    finally:
        Base.metadata.drop_all(bind=engine)
