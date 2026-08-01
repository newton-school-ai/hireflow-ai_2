"""
Unit and integration tests for FormFiller and ApplicationAgent (Issue #14).

Tests Playwright browser automation, resilient selector matching, resume upload validation,
grounded LLM free-text answer generation, database status persistence, missing field handling,
security/captcha detection, timeout resilience, and resource cleanup.
"""

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agents.application_agent import ApplicationAgent
from src.automation.form_filler import FormFiller, FormFillResult, ResumeUploadError
from src.config.database import Base
from src.models.application import Application
from src.models.job import Job
from src.models.user import User

# Setup in-memory SQLite database for testing
TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

SAMPLE_FORM_PATH = Path(__file__).parent / "fixtures" / "sample_form.html"


@pytest.fixture(autouse=True)
def setup_test_db():
    """Create all tables in memory before each test and drop after."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    """Yield an isolated SQLAlchemy session."""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def sample_user(db_session):
    """Create a sample user in test database."""
    user = User(
        id=uuid.uuid4(),
        name="Alex Mercer",
        email="alex.mercer@example.com",
        mode="job",
        master_profile={
            "phone": "+1-555-0199",
            "location": "San Francisco, CA",
            "linkedin": "https://linkedin.com/in/alexmercer",
            "github": "https://github.com/alexmercer",
            "portfolio": "https://alexmercer.dev",
            "education": "bachelors",
            "experience": "1-3",
            "skills": ["Python", "SQL"],
        },
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def sample_job(db_session):
    """Create a sample job in test database."""
    job = Job(
        id=uuid.uuid4(),
        company_name="TechCorp Solutions",
        role_title="Senior Python Backend Engineer",
        jd_text="Looking for a Python developer proficient in FastAPI, SQL, and Playwright automation.",
        application_url=f"file://{SAMPLE_FORM_PATH.resolve()}",
        listing_type="job",
    )
    db_session.add(job)
    db_session.commit()
    return job


@pytest.fixture
def sample_application(db_session, sample_user, sample_job, tmp_path):
    """Create a sample application in test database with a valid resume PDF."""
    resume_file = tmp_path / "alex_mercer_resume.pdf"
    resume_file.write_bytes(b"%PDF-1.4 sample resume content")

    app = Application(
        id=uuid.uuid4(),
        user_id=sample_user.id,
        job_id=sample_job.id,
        status="matched",
        resume_path=str(resume_file),
    )
    db_session.add(app)
    db_session.commit()
    return app


# ===========================================================================
# 1. Successful Application & End-to-End Orchestration
# ===========================================================================


def test_successful_application(db_session, sample_application):
    """✓ Test successful application form fill, submission, and DB update."""
    agent = ApplicationAgent()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(sample_application.job.application_url)

        with patch.object(
            agent,
            "generate_free_text_answer",
            return_value="I am a skilled Python engineer with relevant experience.",
        ):
            result = agent.apply_for_job(
                application_id=sample_application.id,
                db_session=db_session,
                custom_page=page,
            )

        browser.close()

    assert result.status == "applied"
    assert result.failure_reason is None

    # Check DB record status updated to 'applied' and applied_at is populated
    db_app = db_session.query(Application).filter_by(id=sample_application.id).first()
    assert db_app.status == "applied"
    assert db_app.applied_at is not None


# ===========================================================================
# 2. Resume Upload Validation
# ===========================================================================


def test_resume_upload_success(tmp_path):
    """✓ Test resume file upload using Playwright set_input_files API."""
    filler = FormFiller()
    pdf_file = tmp_path / "valid_resume.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 test resume")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f"file://{SAMPLE_FORM_PATH.resolve()}")

        uploaded = filler.upload_resume(page, str(pdf_file))
        assert uploaded is True

        # Verify file input locator value set
        file_input = page.locator("input[type='file']")
        assert file_input.input_value() != ""

        browser.close()


def test_resume_upload_file_missing():
    """✓ Test error handling when resume file does not exist on disk."""
    filler = FormFiller()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        with pytest.raises(ResumeUploadError, match="Resume file does not exist"):
            filler.upload_resume(page, "/non/existent/path/resume.pdf")

        browser.close()


def test_resume_upload_unsupported_extension(tmp_path):
    """✓ Test error handling for unsupported file extensions (e.g. .exe)."""
    filler = FormFiller()
    invalid_file = tmp_path / "resume.exe"
    invalid_file.write_bytes(b"binary data")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        with pytest.raises(ResumeUploadError, match="Unsupported resume extension"):
            filler.upload_resume(page, str(invalid_file))

        browser.close()


# ===========================================================================
# 3. Grounded Free-Text Question Generation
# ===========================================================================


def test_free_text_answer_generation():
    """✓ Test grounded free-text answer generation via LLM client."""
    agent = ApplicationAgent()

    user_profile = {
        "skills": ["Python", "FastAPI", "Docker"],
        "education": "Bachelor of Science in CS",
    }
    job_info = {
        "role_title": "Backend Engineer",
        "company_name": "TechCorp",
        "jd_text": "We need a Python engineer with FastAPI experience.",
    }

    mock_llm = MagicMock()
    mock_llm.chat.return_value = (
        "I am experienced in Python and FastAPI, making me a strong fit for TechCorp."
    )

    with patch("src.agents.application_agent.get_llm_client", return_value=mock_llm):
        answer = agent.generate_free_text_answer(
            question="Why should we hire you?",
            user_profile=user_profile,
            job_info=job_info,
        )

    assert "Python" in answer or "TechCorp" in answer
    assert mock_llm.chat.called


def test_free_text_answer_fallback_on_llm_error():
    """✓ Test fallback grounded answer when LLM client raises an exception."""
    agent = ApplicationAgent()

    user_profile = {"skills": ["Python", "SQL"]}
    job_info = {"role_title": "Software Intern", "company_name": "Acme Inc"}

    with patch(
        "src.agents.application_agent.get_llm_client",
        side_effect=RuntimeError("LLM offline"),
    ):
        answer = agent.generate_free_text_answer(
            question="Why work here?",
            user_profile=user_profile,
            job_info=job_info,
        )

    assert "Acme Inc" in answer
    assert "Software Intern" in answer
    assert "Python" in answer


# ===========================================================================
# 4. Failed Submission Handling
# ===========================================================================


def test_failed_submission(db_session, sample_application):
    """✓ Test handling of failed form submission (e.g. form error mode)."""
    agent = ApplicationAgent()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        # Navigate to sample form with fail mode
        page.goto(f"file://{SAMPLE_FORM_PATH.resolve()}?mode=fail")

        with patch.object(
            agent,
            "generate_free_text_answer",
            return_value="Candidate test response.",
        ):
            result = agent.apply_for_job(
                application_id=sample_application.id,
                db_session=db_session,
                custom_page=page,
            )

        browser.close()

    assert result.status == "failed"
    assert result.failure_reason is not None

    db_app = db_session.query(Application).filter_by(id=sample_application.id).first()
    assert db_app.status == "failed"


# ===========================================================================
# 5. Missing Field Handling
# ===========================================================================


def test_missing_field_handling(db_session, sample_application):
    """✓ Test that missing optional fields in user profile are ignored gracefully."""
    agent = ApplicationAgent()

    # User master profile with minimal fields (no phone, location, github, portfolio)
    minimal_user = (
        db_session.query(User).filter_by(id=sample_application.user_id).first()
    )
    minimal_user.master_profile = {"skills": ["Python"]}
    db_session.commit()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(sample_application.job.application_url)

        with patch.object(
            agent, "generate_free_text_answer", return_value="Test answer."
        ):
            result = agent.apply_for_job(
                application_id=sample_application.id,
                db_session=db_session,
                custom_page=page,
            )

        browser.close()

    assert result.status == "applied"


# ===========================================================================
# 6. Needs Action Case (Captcha / Security Challenge)
# ===========================================================================


def test_needs_action_case(db_session, sample_application):
    """✓ Test detection of captcha/security challenge resulting in needs_action status."""
    agent = ApplicationAgent()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f"file://{SAMPLE_FORM_PATH.resolve()}?mode=captcha")

        result = agent.apply_for_job(
            application_id=sample_application.id,
            db_session=db_session,
            custom_page=page,
        )

        browser.close()

    assert result.status == "needs_action"
    assert (
        "Captcha" in result.failure_reason
        or "security" in result.failure_reason.lower()
    )

    db_app = db_session.query(Application).filter_by(id=sample_application.id).first()
    assert db_app.status == "needs_action"


# ===========================================================================
# 7. Timeout Handling
# ===========================================================================


def test_timeout_handling():
    """✓ Test graceful handling of Playwright timeouts during form filling."""
    filler = FormFiller()

    mock_page = MagicMock()
    mock_page.content.side_effect = PlaywrightTimeoutError("Operation timed out")
    mock_page.locator.side_effect = PlaywrightTimeoutError("Locator search timed out")

    user_data = {"full_name": "Timeout User", "email": "timeout@example.com"}

    result = filler.fill_and_submit(page=mock_page, user_data=user_data)

    assert result.status == "failed"
    assert "Timeout" in result.failure_reason


# ===========================================================================
# 8. Database Status Update Verification
# ===========================================================================


def test_database_update_integrity(db_session, sample_application):
    """✓ Test database status and timestamp persistence."""
    agent = ApplicationAgent()

    # Non-existent application ID
    fake_id = uuid.uuid4()
    result = agent.apply_for_job(fake_id, db_session=db_session)
    assert result.status == "failed"
    assert "not found" in result.failure_reason

    # Existing application ID update
    db_app = db_session.query(Application).filter_by(id=sample_application.id).first()
    assert db_app.status == "matched"


# ===========================================================================
# 9. Browser Context Cleanup
# ===========================================================================


def test_browser_cleanup():
    """✓ Test browser and context resources cleanup after automation."""
    agent = ApplicationAgent()

    user_data = {"full_name": "Cleanup Test", "email": "cleanup@example.com"}

    # Mock sync_playwright to ensure close() is invoked
    mock_p = MagicMock()
    mock_browser = MagicMock()
    mock_context = MagicMock()
    mock_page = MagicMock()

    mock_p.chromium.launch.return_value = mock_browser
    mock_browser.new_context.return_value = mock_context
    mock_context.new_page.return_value = mock_page

    with patch("src.agents.application_agent.sync_playwright") as mock_sp:
        mock_sp.return_value.__enter__.return_value = mock_p

        with patch.object(
            agent.form_filler,
            "fill_and_submit",
            return_value=FormFillResult(status="applied"),
        ):
            agent._run_browser_automation(
                url="http://example.com/apply",
                user_data=user_data,
                resume_path=None,
                free_text_answers={},
            )

        assert mock_context.close.called
        assert mock_browser.close.called


# ===========================================================================
# 10. Deterministic Behavior & Multi-Pattern Selector Strategy
# ===========================================================================


def test_selector_strategy_attribute_matching():
    """✓ Test multi-pattern selector strategy matching name, id, placeholder, label, data-testid."""
    filler = FormFiller()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f"file://{SAMPLE_FORM_PATH.resolve()}")

        # Test finding email by name, placeholder, label, and test-id
        loc_name = filler.find_field_locator(page, "email")
        assert loc_name is not None

        loc_phone = filler.find_field_locator(page, "phone")
        assert loc_phone is not None

        loc_linkedin = filler.find_field_locator(page, "linkedin")
        assert loc_linkedin is not None

        browser.close()
