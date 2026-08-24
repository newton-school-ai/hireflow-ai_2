import uuid
from unittest.mock import MagicMock, patch

import pytest
from src.utils.email_service import EmailService

# A mock for the settings so we can easily toggle the provider
@pytest.fixture
def mock_settings(monkeypatch):
    class MockSettings:
        email_provider = "sendgrid"
        sendgrid_api_key = "test_sg_key"
        resend_api_key = "test_resend_key"
        from_email = "test@hireflow.com"
    
    mock_set = MockSettings()
    monkeypatch.setattr("src.utils.email_service.settings", mock_set)
    return mock_set

@pytest.fixture
def db_session():
    # Mock the database session
    mock_session = MagicMock()
    with patch("src.utils.email_service.SessionLocal", return_value=mock_session):
        yield mock_session

@pytest.fixture
def dummy_resume(tmp_path):
    # Create a dummy 1KB pdf
    pdf_path = tmp_path / "test_resume.pdf"
    pdf_path.write_bytes(b"A" * 1024)
    return str(pdf_path)

@pytest.fixture
def large_resume(tmp_path):
    # Create a dummy 11MB pdf
    pdf_path = tmp_path / "large_resume.pdf"
    pdf_path.write_bytes(b"A" * 11_000_000)
    return str(pdf_path)


@patch("src.utils.email_service.SendGridAPIClient")
def test_sendgrid_normal_send(mock_sg_class, mock_settings, db_session, dummy_resume):
    mock_settings.email_provider = "sendgrid"
    
    # Mock SendGrid client
    mock_sg_instance = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 202
    mock_sg_instance.send.return_value = mock_response
    mock_sg_class.return_value = mock_sg_instance
    
    service = EmailService()
    success = service.send_weekly_report(
        to_email="user@test.com",
        report_html="<h1>Report</h1>",
        resume_paths=[dummy_resume]
    )
    
    assert success is True
    mock_sg_instance.send.assert_called_once()
    # Check that no DB query was executed since user_id wasn't provided
    db_session.query.assert_not_called()

@patch("src.utils.email_service.requests.post")
def test_resend_normal_send(mock_post, mock_settings, db_session, dummy_resume):
    mock_settings.email_provider = "resend"
    
    # Mock requests.post
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_post.return_value = mock_response
    
    service = EmailService()
    success = service.send_weekly_report(
        to_email="user@test.com",
        report_html="<h1>Report</h1>",
        resume_paths=[dummy_resume]
    )
    
    assert success is True
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert kwargs["json"]["subject"] == "HireFlow Weekly Report"
    assert "attachments" in kwargs["json"]

@patch("src.utils.email_service.SendGridAPIClient")
def test_empty_attachments(mock_sg_class, mock_settings):
    mock_settings.email_provider = "sendgrid"
    mock_sg_instance = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 202
    mock_sg_instance.send.return_value = mock_response
    mock_sg_class.return_value = mock_sg_instance
    
    service = EmailService()
    success = service.send_weekly_report(
        to_email="user@test.com",
        report_html="<h1>Report</h1>",
        resume_paths=[]
    )
    
    assert success is True
    mock_sg_instance.send.assert_called_once()

@patch("src.utils.email_service.SendGridAPIClient")
def test_provider_failure_handling(mock_sg_class, mock_settings):
    mock_settings.email_provider = "sendgrid"
    mock_sg_instance = MagicMock()
    # Throw an exception on send
    mock_sg_instance.send.side_effect = Exception("API Error")
    mock_sg_class.return_value = mock_sg_instance
    
    service = EmailService()
    # Should not crash, just return False
    success = service.send_weekly_report(
        to_email="user@test.com",
        report_html="<h1>Report</h1>",
        resume_paths=[]
    )
    
    assert success is False

@patch("src.utils.email_service.SendGridAPIClient")
def test_attachment_size_exceeds_10mb(mock_sg_class, mock_settings, large_resume):
    mock_settings.email_provider = "sendgrid"
    mock_sg_instance = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 202
    mock_sg_instance.send.return_value = mock_response
    mock_sg_class.return_value = mock_sg_instance
    
    service = EmailService()
    report_html = "<h1>Report</h1>"
    success = service.send_weekly_report(
        to_email="user@test.com",
        report_html=report_html,
        resume_paths=[large_resume]
    )
    
    assert success is True
    # Get the sent email content to verify attachments weren't added and HTML was modified
    sent_mail = mock_sg_instance.send.call_args[0][0]
    
    # SendGrid Mail object exposes attachments via attachment property (or it will be None/Empty)
    assert not sent_mail.attachment
    
    # HTML content should contain the appended link info
    html_content = sent_mail.contents[0].content
    assert "File too large, available on your HireFlow dashboard" in html_content

@patch("src.utils.email_service.SendGridAPIClient")
def test_logs_timestamp(mock_sg_class, mock_settings, db_session):
    mock_settings.email_provider = "sendgrid"
    mock_sg_instance = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 202
    mock_sg_instance.send.return_value = mock_response
    mock_sg_class.return_value = mock_sg_instance
    
    user_id = uuid.uuid4()
    # Setup mock db query
    mock_report = MagicMock()
    db_session.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_report
    
    service = EmailService()
    success = service.send_weekly_report(
        to_email="user@test.com",
        report_html="<h1>Report</h1>",
        resume_paths=[],
        user_id=user_id
    )
    
    assert success is True
    # Ensure db.commit() was called to save sent_at
    db_session.commit.assert_called_once()
    assert mock_report.sent_at is not None
