"""Tests for the PDF Generation Pipeline."""

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.pipelines.pdf_generator import PDFGenerator


@pytest.fixture
def mock_db_session():
    """Mock the SQLAlchemy DB session."""
    with patch("src.pipelines.pdf_generator.SessionLocal") as mock_session_class:
        mock_db = MagicMock()
        mock_session_class.return_value = mock_db
        yield mock_db


@pytest.fixture
def mock_subprocess():
    """Mock subprocess.run to simulate xelatex compilation."""
    with patch("src.pipelines.pdf_generator.subprocess.run") as mock_run:
        # By default, pretend compilation succeeds and creates the PDF file
        def side_effect(command, **kwargs):
            # command[2] is -output-directory=DIR, command[3] is tex_path
            tex_path = Path(command[3])
            pdf_path = tex_path.with_suffix(".pdf")
            pdf_path.touch()  # Simulate the PDF being created

            mock_result = MagicMock()
            mock_result.returncode = 0
            return mock_result

        mock_run.side_effect = side_effect
        yield mock_run


@pytest.fixture(autouse=True)
def mock_shutil_which():
    with patch("src.pipelines.pdf_generator.shutil.which") as mock_which:
        mock_which.return_value = "/usr/bin/xelatex"
        yield mock_which


@pytest.fixture
def temp_output_dir(tmp_path, monkeypatch):
    """Provide a temporary output directory for tests."""
    with patch("src.pipelines.pdf_generator.settings.resume_output_dir", str(tmp_path)):
        yield tmp_path


@pytest.fixture
def sample_resume_data():
    return {
        "name": "John Doe",
        "email": "john@example.com",
        "phone": "555-1234",
        "summary": "A software engineer.",
        "education": [{"degree": "B.S.", "school": "MIT", "year": "2020"}],
        "experience": [
            {
                "role": "Engineer",
                "company": "Tech",
                "date": "2020-2023",
                "details": ["Task 1", "Task 2"],
            }
        ],
        "projects": [{"name": "Project X", "details": "Did cool things."}],
        "skills": "Python, SQL",
    }


def _setup_mock_app(mock_db):
    """Helper to set up a mock Application record."""
    mock_app = MagicMock()
    mock_app.id = uuid.uuid4()
    mock_app.user_id = uuid.uuid4()
    mock_app.job_id = uuid.uuid4()
    mock_app.status = "matched"

    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_app
    mock_query.filter.return_value = mock_filter
    mock_db.query.return_value = mock_query

    return mock_app


def test_normal_generation(
    mock_db_session, mock_subprocess, temp_output_dir, sample_resume_data
):
    """Test generating a PDF normally."""
    mock_app = _setup_mock_app(mock_db_session)
    generator = PDFGenerator()

    pdf_path_str = generator.generate(
        str(mock_app.user_id), str(mock_app.job_id), sample_resume_data
    )

    assert pdf_path_str.endswith(f"{mock_app.job_id}_resume_v1.pdf")

    # Verify DB was updated
    assert mock_app.resume_path == pdf_path_str
    assert mock_app.resume_version == 1
    assert mock_app.status == "resume_generated"
    mock_db_session.commit.assert_called_once()

    # Verify subprocess called
    mock_subprocess.assert_called_once()

    # Verify cleanup (tex should be deleted, pdf should remain)
    pdf_path = Path(pdf_path_str)
    assert pdf_path.exists()
    tex_path = pdf_path.with_suffix(".tex")
    assert not tex_path.exists()


def test_version_increment(
    mock_db_session, mock_subprocess, temp_output_dir, sample_resume_data
):
    """Test generating a PDF twice increments the version."""
    mock_app = _setup_mock_app(mock_db_session)
    generator = PDFGenerator()

    # First generation
    path1 = generator.generate(
        str(mock_app.user_id), str(mock_app.job_id), sample_resume_data
    )
    assert "v1.pdf" in path1
    assert mock_app.resume_version == 1

    # Mock finding the application again (since session acts like new)
    # The filesystem now has v1.pdf

    # Second generation
    path2 = generator.generate(
        str(mock_app.user_id), str(mock_app.job_id), sample_resume_data
    )
    assert "v2.pdf" in path2
    assert mock_app.resume_version == 2

    assert Path(path1).exists()
    assert Path(path2).exists()


def test_empty_optional_sections(mock_db_session, mock_subprocess, temp_output_dir):
    """Test generating a PDF without projects or experience."""
    mock_app = _setup_mock_app(mock_db_session)
    generator = PDFGenerator()

    sparse_data = {
        "name": "Jane Doe",
        "email": "jane@example.com",
    }

    pdf_path_str = generator.generate(
        str(mock_app.user_id), str(mock_app.job_id), sparse_data
    )
    assert pdf_path_str.endswith("v1.pdf")
    mock_db_session.commit.assert_called_once()


def test_long_project_description(
    mock_db_session, mock_subprocess, temp_output_dir, sample_resume_data
):
    """Test generating a PDF with extremely long text (which latex template must wrap natively)."""
    mock_app = _setup_mock_app(mock_db_session)
    generator = PDFGenerator()

    sample_resume_data["projects"][0]["details"] = "A very long text. " * 500

    # If the template breaks rendering, Jinja might throw. We just verify the pipeline succeeds.
    pdf_path_str = generator.generate(
        str(mock_app.user_id), str(mock_app.job_id), sample_resume_data
    )
    assert pdf_path_str.endswith("v1.pdf")


def test_compilation_failure(
    mock_db_session, mock_subprocess, temp_output_dir, sample_resume_data
):
    """Test XeLaTeX failure raises RuntimeError and triggers DB rollback."""
    mock_app = _setup_mock_app(mock_db_session)

    def side_effect(*args, **kwargs):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "some output"
        mock_result.stderr = "Fatal error"
        return mock_result

    mock_subprocess.side_effect = side_effect

    generator = PDFGenerator()

    with pytest.raises(
        RuntimeError, match="XeLaTeX compilation failed with exit code 1"
    ):
        generator.generate(
            str(mock_app.user_id), str(mock_app.job_id), sample_resume_data
        )

    # Verify DB rollback
    mock_db_session.rollback.assert_called_once()
    mock_db_session.commit.assert_not_called()


def test_database_rollback_on_db_error(
    mock_db_session, mock_subprocess, temp_output_dir, sample_resume_data
):
    """Test database commit failure triggers rollback."""
    mock_app = _setup_mock_app(mock_db_session)
    mock_db_session.commit.side_effect = Exception("DB Connection Lost")

    generator = PDFGenerator()

    with pytest.raises(Exception, match="DB Connection Lost"):
        generator.generate(
            str(mock_app.user_id), str(mock_app.job_id), sample_resume_data
        )

    mock_db_session.rollback.assert_called_once()


def test_output_directory_creation(
    mock_db_session, mock_subprocess, tmp_path, sample_resume_data
):
    """Test that absent directory is created automatically."""
    target_dir = tmp_path / "deep" / "nested" / "resumes"
    assert not target_dir.exists()

    with patch(
        "src.pipelines.pdf_generator.settings.resume_output_dir", str(target_dir)
    ):
        mock_app = _setup_mock_app(mock_db_session)
        generator = PDFGenerator()
        generator.generate(
            str(mock_app.user_id), str(mock_app.job_id), sample_resume_data
        )

    assert target_dir.exists()
    user_dir = target_dir / str(mock_app.user_id)
    assert user_dir.exists()


def test_path_format(
    mock_db_session, mock_subprocess, temp_output_dir, sample_resume_data
):
    """Verify the output path strictly follows the specified format."""
    mock_app = _setup_mock_app(mock_db_session)
    generator = PDFGenerator()

    pdf_path_str = generator.generate(
        str(mock_app.user_id), str(mock_app.job_id), sample_resume_data
    )

    expected_path = str(
        temp_output_dir / str(mock_app.user_id) / f"{mock_app.job_id}_resume_v1.pdf"
    )
    assert pdf_path_str == expected_path


def test_special_characters(
    mock_db_session, mock_subprocess, temp_output_dir, sample_resume_data
):
    """Test that special LaTeX characters in the resume data do not cause errors."""
    mock_app = _setup_mock_app(mock_db_session)
    generator = PDFGenerator()

    sample_resume_data["skills"] = "C++ & Python \\ % $ # _ { } ~ ^"

    pdf_path_str = generator.generate(
        str(mock_app.user_id), str(mock_app.job_id), sample_resume_data
    )
    assert pdf_path_str.endswith("v1.pdf")
    mock_db_session.commit.assert_called_once()
