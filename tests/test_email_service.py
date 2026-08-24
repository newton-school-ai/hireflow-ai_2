import os
from unittest.mock import MagicMock, patch

import pytest

from src.utils.email_service import EmailService


@pytest.fixture
def mock_settings():
    with patch("src.utils.email_service.settings") as mock_settings:
        mock_settings.email_provider = "resend"
        mock_settings.resend_api_key = "test_key"
        mock_settings.from_email = "test@example.com"
        yield mock_settings


@pytest.fixture
def mock_requests():
    with patch("src.utils.email_service.requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response
        yield mock_post


@pytest.fixture
def mock_os_path():
    with patch("src.utils.email_service.os.path.exists") as mock_exists:
        mock_exists.return_value = True
        with patch("src.utils.email_service.os.path.getsize") as mock_size:
            mock_size.return_value = 100 * 1024  # 100KB per file
            yield mock_exists, mock_size


@pytest.fixture
def mock_open_file():
    with patch("builtins.open", unittest.mock.mock_open(read_data=b"dummy pdf content")) as mock_file:
        yield mock_file


@pytest.fixture
def mock_db_session():
    with patch("src.utils.email_service.EmailService._get_db_session") as mock_get_db:
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        yield mock_db


def test_normal_send_with_attachments(mock_settings, mock_requests, mock_os_path, mock_open_file):
    import builtins
    service = EmailService()
    
    with patch("builtins.open", builtins.mock.mock_open(read_data=b"dummy content")):
        success = service.send_weekly_report(
            to_email="user@example.com",
            subject="Weekly Report",
            report_html="<h1>Report</h1>",
            resume_paths=["/path/to/resume1.pdf", "/path/to/resume2.pdf"]
        )

    assert success is True
    mock_requests.assert_called_once()
    
    call_args = mock_requests.call_args
    payload = call_args.kwargs["json"]
    assert "attachments" in payload
    assert len(payload["attachments"]) == 2
    assert payload["attachments"][0]["filename"] == "resume1.pdf"


def test_empty_attachments(mock_settings, mock_requests):
    service = EmailService()
    
    success = service.send_weekly_report(
        to_email="user@example.com",
        subject="Weekly Report",
        report_html="<h1>Report</h1>",
        resume_paths=[]
    )

    assert success is True
    mock_requests.assert_called_once()
    
    call_args = mock_requests.call_args
    payload = call_args.kwargs["json"]
    assert "attachments" not in payload


def test_provider_failure_handling(mock_settings, mock_requests):
    service = EmailService()
    
    # Configure mock to return 500 Internal Server Error
    mock_requests.return_value.status_code = 500
    mock_requests.return_value.text = "Internal Server Error"
    
    success = service.send_weekly_report(
        to_email="user@example.com",
        subject="Weekly Report",
        report_html="<h1>Report</h1>",
        resume_paths=[]
    )

    assert success is False
    mock_requests.assert_called_once()


def test_attachment_size_exceeds_limit(mock_settings, mock_requests, mock_os_path, mock_open_file):
    mock_exists, mock_size = mock_os_path
    # Set size to 11MB per file
    mock_size.return_value = 11 * 1024 * 1024 
    
    service = EmailService()
    
    import builtins
    with patch("builtins.open", builtins.mock.mock_open(read_data=b"dummy content")):
        success = service.send_weekly_report(
            to_email="user@example.com",
            subject="Weekly Report",
            report_html="<h1>Report</h1>",
            resume_paths=["/path/to/resume1.pdf"]
        )

    assert success is True
    mock_requests.assert_called_once()
    
    call_args = mock_requests.call_args
    payload = call_args.kwargs["json"]
    # Attachments should be stripped because size > 10MB
    assert "attachments" not in payload
    # HTML should contain the note
    assert "Resumes exceeded 10MB" in payload["html"]


def test_update_sent_at(mock_settings, mock_requests, mock_db_session):
    service = EmailService()
    
    # Mocking the report and db session
    mock_report = MagicMock()
    mock_db_session.query.return_value.filter.return_value.first.return_value = mock_report
    
    success = service.send_weekly_report(
        to_email="user@example.com",
        subject="Weekly Report",
        report_html="<h1>Report</h1>",
        resume_paths=[],
        report_id="123e4567-e89b-12d3-a456-426614174000"
    )

    assert success is True
    # Verify sent_at was set
    assert mock_report.sent_at is not None
    mock_db_session.commit.assert_called_once()
