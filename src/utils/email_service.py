import base64
import logging
import os
from datetime import datetime, timezone

import requests

from src.config.settings import settings

logger = logging.getLogger(__name__)

MAX_ATTACHMENTS = 10
MAX_ATTACHMENT_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


class EmailService:
    def __init__(self):
        self.provider = settings.email_provider.lower()
        self.resend_api_key = settings.resend_api_key
        self.sendgrid_api_key = settings.sendgrid_api_key
        self.from_email = settings.from_email

    def _get_db_session(self):
        from src.config.database import SessionLocal
        return SessionLocal()

    def send_weekly_report(
        self,
        to_email: str,
        subject: str,
        report_html: str,
        resume_paths: list[str],
        report_id: str | None = None,
    ) -> bool:
        """Sends the weekly report via the configured email provider.

        Args:
            to_email: The recipient's email address.
            subject: The subject line.
            report_html: The HTML content of the email.
            resume_paths: List of file paths to PDF resumes to attach.
            report_id: Optional UUID string for the WeeklyReport to update sent_at.

        Returns:
            True if successful, False otherwise.
        """
        try:
            # Process attachments
            attachments = []
            total_size = 0
            attached_paths = resume_paths[:MAX_ATTACHMENTS]

            for path in attached_paths:
                if os.path.exists(path):
                    total_size += os.path.getsize(path)

            if total_size > MAX_ATTACHMENT_SIZE_BYTES:
                logger.warning(f"Attachments exceed 10MB limit ({total_size} bytes). Linking instead.")
                report_html += "<br><br><p><i>Note: Resumes exceeded 10MB and were not attached. Please check your local output folder.</i></p>"
                attached_paths = []
            
            for path in attached_paths:
                if os.path.exists(path):
                    with open(path, "rb") as f:
                        file_data = f.read()
                        encoded = base64.b64encode(file_data).decode("utf-8")
                        filename = os.path.basename(path)
                        attachments.append({
                            "filename": filename,
                            "content": encoded,
                            "type": "application/pdf"
                        })

            if self.provider == "resend":
                success = self._send_via_resend(to_email, subject, report_html, attachments)
            elif self.provider == "sendgrid":
                success = self._send_via_sendgrid(to_email, subject, report_html, attachments)
            else:
                logger.error(f"Unknown email provider: {self.provider}")
                success = False

            if success and report_id:
                try:
                    from src.models.report import WeeklyReport
                    db = self._get_db_session()
                    report = db.query(WeeklyReport).filter(WeeklyReport.id == report_id).first()
                    if report:
                        report.sent_at = datetime.now(timezone.utc)
                        db.commit()
                    db.close()
                except Exception as e:
                    logger.error(f"Failed to update sent_at for report {report_id}: {e}")

            return success

        except Exception as e:
            logger.error(f"Email delivery failed: {e}")
            return False

    def _send_via_resend(self, to_email: str, subject: str, html: str, attachments: list[dict]) -> bool:
        if not self.resend_api_key:
            logger.error("RESEND_API_KEY is not configured")
            return False

        payload = {
            "from": self.from_email,
            "to": [to_email],
            "subject": subject,
            "html": html,
        }
        
        if attachments:
            payload["attachments"] = attachments

        headers = {
            "Authorization": f"Bearer {self.resend_api_key}",
            "Content-Type": "application/json"
        }

        response = requests.post("https://api.resend.com/emails", json=payload, headers=headers, timeout=10)
        
        if response.status_code in (200, 201):
            return True
        else:
            logger.error(f"Resend API error: {response.status_code} {response.text}")
            return False

    def _send_via_sendgrid(self, to_email: str, subject: str, html: str, attachments: list[dict]) -> bool:
        if not self.sendgrid_api_key:
            logger.error("SENDGRID_API_KEY is not configured")
            return False

        try:
            import sendgrid
            from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition
        except ImportError:
            logger.error("sendgrid package is not installed")
            return False

        sg = sendgrid.SendGridAPIClient(api_key=self.sendgrid_api_key)
        message = Mail(
            from_email=self.from_email,
            to_emails=to_email,
            subject=subject,
            html_content=html
        )

        for att in attachments:
            attachment = Attachment()
            attachment.file_content = FileContent(att["content"])
            attachment.file_type = FileType(att.get("type", "application/pdf"))
            attachment.file_name = FileName(att["filename"])
            attachment.disposition = Disposition("attachment")
            message.add_attachment(attachment)

        response = sg.send(message)
        if response.status_code in (200, 201, 202):
            return True
        else:
            logger.error(f"SendGrid API error: {response.status_code}")
            return False
