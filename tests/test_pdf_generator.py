"""
Unit tests for LaTeX PDF Generator and Resume Storage pipeline (Issue #13).
"""

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config.database import Base
from src.models.application import Application
from src.models.job import Job
from src.models.user import User
from src.pipelines.pdf_generator import (
    InvalidResumeContentError,
    JobNotFoundError,
    LaTeXCompilationError,
    LaTeXTemplateNotFoundError,
    PDFGenerator,
    UserNotFoundError,
    _escape_latex,
)


@pytest.fixture
def db_session():
    """In-memory SQLite database session fixture."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def sample_user(db_session):
    """Fixture providing a persisted User record."""
    user = User(
        name="Jane Developer",
        email="jane@example.com",
        mode="job",
        master_profile={"skills": ["Python", "LaTeX", "SQL"]},
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def sample_job(db_session):
    """Fixture providing a persisted Job record."""
    job = Job(
        company_name="Acme Tech",
        role_title="Backend Engineer",
        jd_text="Looking for a Python software engineer.",
        application_url="https://example.com/job/123",
        listing_type="job",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


@pytest.fixture
def sample_application(db_session, sample_user, sample_job):
    """Fixture providing a persisted Application record."""
    app = Application(
        user_id=sample_user.id,
        job_id=sample_job.id,
        status="matched",
    )
    db_session.add(app)
    db_session.commit()
    db_session.refresh(app)
    return app


@pytest.fixture
def sample_resume_content():
    """Fixture providing valid structured resume content."""
    return {
        "name": "Jane Developer & Team",
        "contact": {
            "email": "jane@example.com",
            "phone": "+1 (555) 019-2834",
            "location": "San Francisco, CA",
            "github": "github.com/janedev",
        },
        "summary": "High-performing Senior Backend Engineer with 5+ years experience building APIs handling $10M+ transactions.",
        "skills": {
            "Languages": ["Python 3.11", "SQL", "Go & C++"],
            "Tools": ["Docker", "FastAPI", "PostgreSQL", "Git"],
        },
        "experience": [
            {
                "title": "Senior Engineer & Architect",
                "company": "Tech Corp",
                "location": "San Francisco, CA",
                "dates": "2021 -- Present",
                "description": "Led backend API microservices development.",
                "highlights": [
                    "Improved latency by 45% using Redis caching.",
                    "Managed a team of 6 engineers with 100% test coverage.",
                ],
            }
        ],
        "projects": [
            {
                "name": "HireFlow AI Engine",
                "technologies": ["Python", "LaTeX", "SQL"],
                "link": "github.com/hireflow/ai",
                "description": "Autonomous AI job match & resume generator.",
                "highlights": ["Deterministic PDF resume rendering engine."],
            }
        ],
        "education": [
            {
                "degree": "B.S. Computer Science",
                "institution": "Stanford University",
                "location": "Stanford, CA",
                "dates": "2017 -- 2021",
                "details": "GPA 3.9/4.0",
            }
        ],
    }


def test_escape_latex_special_characters():
    """Verify TeX special characters are properly escaped."""
    raw = r"C++ & Python_Script 100% $50 #1 {foo} ~ ^ " + "\\"
    escaped = _escape_latex(raw)
    assert r"\&" in escaped
    assert r"\_" in escaped
    assert r"\%" in escaped
    assert r"\$" in escaped
    assert r"\#" in escaped
    assert r"\{" in escaped
    assert r"\}" in escaped
    assert r"\textasciitilde{}" in escaped
    assert r"\textasciicircum{}" in escaped
    assert r"\textbackslash{}" in escaped


def test_successful_pdf_generation(
    tmp_path, db_session, sample_user, sample_job, sample_resume_content
):
    """Verify successful PDF generation end-to-end with mocked compiler."""
    generator = PDFGenerator(storage_path=tmp_path)

    mock_pdf_bytes = b"%PDF-1.4 Mock LaTeX PDF Output"

    with patch.object(generator, "_compile_pdf", return_value=mock_pdf_bytes):
        result = generator.generate(
            user_id=sample_user.id,
            job_id=sample_job.id,
            resume_content=sample_resume_content,
            db=db_session,
        )

    assert result.user_id == sample_user.id
    assert result.job_id == sample_job.id
    assert result.version == 1

    expected_path = tmp_path / str(sample_user.id) / f"{sample_job.id}_resume_v1.pdf"
    assert Path(result.resume_path) == expected_path
    assert expected_path.exists()
    assert expected_path.read_bytes() == mock_pdf_bytes

    # Check DB Application record
    app = (
        db_session.query(Application)
        .filter_by(user_id=sample_user.id, job_id=sample_job.id)
        .first()
    )
    assert app is not None
    assert app.resume_path == str(expected_path)
    assert app.resume_version == 1
    assert app.status == "resume_generated"


def test_version_increment(
    tmp_path, db_session, sample_user, sample_job, sample_resume_content
):
    """Verify automatic version incrementing for multiple resume generation calls."""
    generator = PDFGenerator(storage_path=tmp_path)
    mock_pdf_bytes = b"%PDF-1.4 Mock Versioning"

    with patch.object(generator, "_compile_pdf", return_value=mock_pdf_bytes):
        res1 = generator.generate(
            sample_user.id, sample_job.id, sample_resume_content, db=db_session
        )
        assert res1.version == 1
        assert Path(res1.resume_path).name == f"{sample_job.id}_resume_v1.pdf"

        res2 = generator.generate(
            sample_user.id, sample_job.id, sample_resume_content, db=db_session
        )
        assert res2.version == 2
        assert Path(res2.resume_path).name == f"{sample_job.id}_resume_v2.pdf"

        res3 = generator.generate(
            sample_user.id, sample_job.id, sample_resume_content, db=db_session
        )
        assert res3.version == 3
        assert Path(res3.resume_path).name == f"{sample_job.id}_resume_v3.pdf"

    # Verify all files exist concurrently (none overwritten)
    user_dir = tmp_path / str(sample_user.id)
    assert (user_dir / f"{sample_job.id}_resume_v1.pdf").exists()
    assert (user_dir / f"{sample_job.id}_resume_v2.pdf").exists()
    assert (user_dir / f"{sample_job.id}_resume_v3.pdf").exists()


def test_invalid_resume_content(tmp_path, db_session, sample_user, sample_job):
    """Verify exception handling for empty or malformed resume content."""
    generator = PDFGenerator(storage_path=tmp_path)

    with pytest.raises(InvalidResumeContentError):
        generator.generate(sample_user.id, sample_job.id, {}, db=db_session)

    with pytest.raises(InvalidResumeContentError):
        generator.generate(sample_user.id, sample_job.id, None, db=db_session)

    with pytest.raises(InvalidResumeContentError):
        generator.generate(
            sample_user.id, sample_job.id, {"unknown_field": "data"}, db=db_session
        )


def test_missing_user(tmp_path, db_session, sample_job, sample_resume_content):
    """Verify exception raised when user ID does not exist in DB."""
    generator = PDFGenerator(storage_path=tmp_path)
    fake_user_id = uuid.uuid4()

    with pytest.raises(UserNotFoundError):
        generator.generate(
            fake_user_id, sample_job.id, sample_resume_content, db=db_session
        )


def test_missing_job(tmp_path, db_session, sample_user, sample_resume_content):
    """Verify exception raised when job ID does not exist in DB."""
    generator = PDFGenerator(storage_path=tmp_path)
    fake_job_id = uuid.uuid4()

    with pytest.raises(JobNotFoundError):
        generator.generate(
            sample_user.id, fake_job_id, sample_resume_content, db=db_session
        )


def test_database_update(
    tmp_path,
    db_session,
    sample_user,
    sample_job,
    sample_application,
    sample_resume_content,
):
    """Verify application record is updated properly when already present."""
    generator = PDFGenerator(storage_path=tmp_path)
    mock_pdf_bytes = b"%PDF-1.4 Mock Application Update"

    with patch.object(generator, "_compile_pdf", return_value=mock_pdf_bytes):
        result = generator.generate(
            sample_user.id, sample_job.id, sample_resume_content, db=db_session
        )

    db_session.refresh(sample_application)
    assert sample_application.resume_path == result.resume_path
    assert sample_application.resume_version == 1
    assert sample_application.status == "resume_generated"


def test_temporary_file_cleanup(
    tmp_path, db_session, sample_user, sample_job, sample_resume_content
):
    """Verify temporary compilation artifacts directory is deleted after execution."""
    generator = PDFGenerator(storage_path=tmp_path)

    with patch("tempfile.mkdtemp") as mock_mkdtemp:
        temp_dir = tmp_path / "mock_temp_dir"
        temp_dir.mkdir()
        mock_mkdtemp.return_value = str(temp_dir)

        with patch.object(generator, "_compile_pdf", return_value=b"%PDF-1.4"):
            generator.generate(
                sample_user.id, sample_job.id, sample_resume_content, db=db_session
            )

        assert not temp_dir.exists()


def test_temporary_file_cleanup_on_failure(
    tmp_path, db_session, sample_user, sample_job, sample_resume_content
):
    """Verify temporary directory is cleaned up even if LaTeX compilation fails."""
    generator = PDFGenerator(storage_path=tmp_path)

    temp_dir = tmp_path / "failing_temp_dir"
    temp_dir.mkdir()

    with (
        patch("tempfile.mkdtemp", return_value=str(temp_dir)),
        patch.object(
            generator,
            "_compile_pdf",
            side_effect=LaTeXCompilationError("Compilation syntax error"),
        ),
        pytest.raises(LaTeXCompilationError),
    ):
        generator.generate(
            sample_user.id, sample_job.id, sample_resume_content, db=db_session
        )

    assert not temp_dir.exists()


def test_missing_template_error(
    tmp_path, db_session, sample_user, sample_job, sample_resume_content
):
    """Verify LaTeXTemplateNotFoundError when base_template.tex does not exist."""
    generator = PDFGenerator(
        storage_path=tmp_path, template_path=tmp_path / "missing.tex"
    )

    with pytest.raises(LaTeXTemplateNotFoundError):
        generator.generate(
            sample_user.id, sample_job.id, sample_resume_content, db=db_session
        )


def test_missing_compiler_error(tmp_path):
    """Verify LaTeXCompilationError when pdflatex binary is missing."""
    generator = PDFGenerator(
        storage_path=tmp_path, compiler="nonexistent_compiler_binary_xyz"
    )
    temp_dir = tmp_path / "compile_temp"
    temp_dir.mkdir()

    with pytest.raises(LaTeXCompilationError) as exc_info:
        generator._compile_pdf(
            r"\documentclass{article}\begin{document}Test\end{document}", temp_dir
        )

    assert "is not installed or available on PATH" in str(exc_info.value)
