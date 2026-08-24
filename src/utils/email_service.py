import base64
import logging
import os
from datetime import datetime, timezone
import uuid

import requests
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Mail,
    Attachment as SendGridAttachment,
    FileContent,
    FileName,
    FileType,
    Disposition,
)

from src.config.database import SessionLocal
from src.config.settings import settings
from src.models.report import WeeklyReport

logger = logging.getLogger(__name__)

class EmailService:
    def __init__(self):
        self.provider = settings.email_provider.lower() if settings.email_provider else "sendgrid"
        self.from_email = settings.from_email

    def send_weekly_report(
        self,
        to_email: str,
        report_html: str,
        resume_paths: list[str],
        subject: str = "HireFlow Weekly Report",
        user_id: uuid.UUID | str | None = None
    ) -> bool:
        """
        Sends the weekly report email with resume attachments.
        If attachments exceed 10MB total size, links will be provided in the email instead.
        """
        # Ensure max 10 attachments
        if len(resume_paths) > 10:
            logger.warning("More than 10 attachments provided. Truncating to 10.")
            resume_paths = resume_paths[:10]

        total_size = 0
        valid_paths = []
        for path in resume_paths:
            if os.path.exists(path):
                total_size += os.path.getsize(path)
                valid_paths.append(path)
            else:
                logger.warning(f"Attachment file not found: {path}")

        # 10 MB limit (10 * 1024 * 1024 bytes)
        exceeds_size = total_size > 10_485_760

        attachments_to_send = []
        if exceeds_size:
            logger.info(f"Total attachment size ({total_size} bytes) exceeds 10MB. Linking instead.")
            # Append links to the HTML
            link_html = "<br><hr><h3>Resume Attachments</h3><ul>"
            for path in valid_paths:
                filename = os.path.basename(path)
                # This assumes some hosting, but for now we just list them or point to the platform.
                link_html += f"<li>{filename} (File too large, available on your HireFlow dashboard)</li>"
            link_html += "</ul>"
            report_html += link_html
        else:
            attachments_to_send = valid_paths

        success = False
        try:
            if self.provider == "resend":
                success = self._send_via_resend(to_email, subject, report_html, attachments_to_send)
            else:
                success = self._send_via_sendgrid(to_email, subject, report_html, attachments_to_send)
            
            if success and user_id:
                self._log_sent_at(user_id)
                
            return success
        except Exception as e:
            logger.error(f"Failed to send email via {self.provider}: {e}")
            return False

    def _send_via_sendgrid(self, to_email: str, subject: str, html_content: str, attachment_paths: list[str]) -> bool:
        if not settings.sendgrid_api_key:
            logger.error("SendGrid API key is missing.")
            return False

        message = Mail(
            from_email=self.from_email,
            to_emails=to_email,
            subject=subject,
            html_content=html_content
        )

        for path in attachment_paths:
            with open(path, "rb") as f:
                data = f.read()
                encoded_file = base64.b64encode(data).decode()
                
            filename = os.path.basename(path)
            attachment = SendGridAttachment(
                FileContent(encoded_file),
                FileName(filename),
                FileType("application/pdf"),
                Disposition("attachment")
            )
            message.add_attachment(attachment)

        sg = SendGridAPIClient(settings.sendgrid_api_key)
        response = sg.send(message)
        if response.status_code in [200, 201, 202]:
            logger.info("Email sent successfully via SendGrid.")
            return True
        else:
            logger.error(f"SendGrid failed with status code {response.status_code}")
            return False

    def _send_via_resend(self, to_email: str, subject: str, html_content: str, attachment_paths: list[str]) -> bool:
        if not settings.resend_api_key:
            logger.error("Resend API key is missing.")
            return False

        attachments = []
        for path in attachment_paths:
            with open(path, "rb") as f:
                data = f.read()
                # Resend expects base64 encoded string or raw bytes depending on client, we'll use base64
                encoded_file = base64.b64encode(data).decode()
            filename = os.path.basename(path)
            attachments.append({
                "filename": filename,
                "content": encoded_file
            })

        payload = {
            "from": self.from_email,
            "to": [to_email],
            "subject": subject,
            "html": html_content
        }
        
        if attachments:
            payload["attachments"] = attachments

        headers = {
            "Authorization": f"Bearer {settings.resend_api_key}",
            "Content-Type": "application/json"
        }

        response = requests.post("https://api.resend.com/emails", json=payload, headers=headers)
        if response.status_code in [200, 201, 202]:
            logger.info("Email sent successfully via Resend.")
            return True
        else:
            logger.error(f"Resend failed with status code {response.status_code}: {response.text}")
            return False

    def _log_sent_at(self, user_id: uuid.UUID | str):
        db = SessionLocal()
        try:
            # Find the latest report for this user
            report = db.query(WeeklyReport).filter(WeeklyReport.user_id == user_id).order_by(WeeklyReport.created_at.desc()).first()
            if report:
                report.sent_at = datetime.now(timezone.utc)
                db.commit()
                logger.info(f"Logged sent_at timestamp for report {report.id}")
            else:
                logger.warning(f"No WeeklyReport found for user {user_id} to log sent_at.")
        except Exception as e:
            logger.error(f"Failed to log sent_at for user {user_id}: {e}")
        finally:
            db.close()
