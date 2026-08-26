"""
Form Filler automation module using Playwright.

Fills job application forms using a resilient, multi-pattern selector strategy.
Supports standard inputs, file uploads, dropdowns, radio/checkbox options,
and free-text questions, cleanly handling outcomes (applied, failed, needs_action).
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.sync_api import (
    Locator,
    Page,
)
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)

logger = logging.getLogger(__name__)

SUPPORTED_RESUME_EXTENSIONS: set[str] = {".pdf", ".docx", ".doc", ".txt"}

# Candidate attribute patterns for resilient selector matching
FIELD_PATTERNS: dict[str, list[str]] = {
    "full_name": [
        "name",
        "full_name",
        "full-name",
        "fullname",
        "applicant-name",
        "full name",
    ],
    "first_name": [
        "first_name",
        "first-name",
        "fname",
        "firstname",
        "given-name",
        "first name",
    ],
    "last_name": [
        "last_name",
        "last-name",
        "lname",
        "lastname",
        "family-name",
        "last name",
    ],
    "email": ["email", "email_address", "email-address", "e-mail", "email address"],
    "phone": [
        "phone",
        "phone_number",
        "mobile",
        "telephone",
        "tel",
        "phone number",
        "mobile number",
    ],
    "location": [
        "location",
        "city",
        "address",
        "current_location",
        "city, country",
        "location / city",
    ],
    "linkedin": ["linkedin", "linkedin_url", "linkedin-url", "linkedin profile"],
    "github": ["github", "github_url", "github-url", "github profile"],
    "portfolio": [
        "portfolio",
        "website",
        "portfolio_url",
        "personal_website",
        "portfolio url",
        "personal site",
    ],
    "education": ["education", "degree", "school", "university", "education level"],
    "experience": [
        "experience",
        "years_experience",
        "years of experience",
        "work experience",
    ],
    "skills": ["skills", "technical_skills", "skills / technologies", "primary skills"],
}


class ResumeUploadError(ValueError):
    """Raised when resume file is invalid or missing."""


@dataclass
class FormFillResult:
    """Represents the outcome of a form filling operation.

    Attributes:
        status: Outcome status - 'applied', 'failed', or 'needs_action'.
        failure_reason: Description of error or action required if status != 'applied'.
        metadata: Details such as filled fields count or submission URL.
    """

    status: str
    failure_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class FormFiller:
    """Automates form filling on job application pages using Playwright.

    Executes a resilient selector strategy to match form fields, upload resumes,
    fill free-text questions, and determine application submission status.
    """

    def __init__(self, default_timeout_ms: int = 5000) -> None:
        self.default_timeout_ms = default_timeout_ms

    # ------------------------------------------------------------------
    # Locator / Selector Strategy
    # ------------------------------------------------------------------

    def find_field_locator(
        self, page: Page, field_name: str, custom_patterns: list[str] | None = None
    ) -> Locator | None:
        """Find a resilient locator for a given field name using multi-pattern search.

        Searches via:
        1. name attribute
        2. id attribute
        3. placeholder text
        4. label text
        5. aria-label attribute
        6. autocomplete attribute
        7. data-testid attribute

        Args:
            page: Playwright Page instance.
            field_name: Logical field name (e.g. 'email', 'full_name').
            custom_patterns: Optional additional pattern strings to attempt.

        Returns:
            Matching visible Playwright Locator, or None if not found.
        """
        patterns = custom_patterns or FIELD_PATTERNS.get(field_name, [field_name])

        for p in patterns:
            # 1. Exact or substring name attribute
            loc = page.locator(
                f"input[name='{p}'], textarea[name='{p}'], select[name='{p}']"
            )
            if self._is_locator_usable(loc):
                return loc.first

            loc = page.locator(f"[name*='{p}' i]")
            if self._is_locator_usable(loc):
                return loc.first

            # 2. ID attribute
            loc = page.locator(f"#{p}")
            if self._is_locator_usable(loc):
                return loc.first

            # 3. Placeholder
            try:
                loc = page.get_by_placeholder(p, exact=False)
                if self._is_locator_usable(loc):
                    return loc.first
            except Exception as e:  # noqa: BLE001
                logger.debug(f"Placeholder search skipped for '{p}': {e}")

            # 4. Label
            try:
                loc = page.get_by_label(p, exact=False)
                if self._is_locator_usable(loc):
                    return loc.first
            except Exception as e:  # noqa: BLE001
                logger.debug(f"Label search skipped for '{p}': {e}")

            # 5. Aria-label
            loc = page.locator(f"[aria-label*='{p}' i]")
            if self._is_locator_usable(loc):
                return loc.first

            # 6. Autocomplete
            loc = page.locator(f"[autocomplete*='{p}' i]")
            if self._is_locator_usable(loc):
                return loc.first

            # 7. Data-testid
            try:
                loc = page.get_by_test_id(p)
                if self._is_locator_usable(loc):
                    return loc.first
            except Exception as e:  # noqa: BLE001
                logger.debug(f"Test-id search skipped for '{p}': {e}")

        return None

    def _is_locator_usable(self, locator: Locator) -> bool:
        """Check if a locator matches at least one visible and enabled element."""
        try:
            if locator.count() > 0:
                first = locator.first
                return first.is_visible() and first.is_enabled()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Locator state check failed: {e}")
        return False

    # ------------------------------------------------------------------
    # Field Filling Helpers
    # ------------------------------------------------------------------

    def fill_standard_fields(self, page: Page, user_data: dict[str, Any]) -> int:
        """Fill standard text, email, phone, location, and link fields.

        Args:
            page: Playwright Page instance.
            user_data: User information dictionary.

        Returns:
            Number of fields successfully located and filled.
        """
        filled_count = 0

        # Full Name or First/Last split
        if "full_name" in user_data or "name" in user_data:
            name_val = user_data.get("full_name") or user_data.get("name") or ""
            loc = self.find_field_locator(page, "full_name")
            if loc:
                loc.fill(name_val)
                filled_count += 1
                logger.info("Filled full_name field.")
            else:
                parts = name_val.split(" ", 1)
                first_name = parts[0]
                last_name = parts[1] if len(parts) > 1 else ""
                first_loc = self.find_field_locator(page, "first_name")
                last_loc = self.find_field_locator(page, "last_name")

                if first_loc:
                    first_loc.fill(first_name)
                    filled_count += 1
                if last_loc and last_name:
                    last_loc.fill(last_name)
                    filled_count += 1

        # Single string fields: email, phone, location, linkedin, github, portfolio
        single_fields = [
            ("email", user_data.get("email")),
            ("phone", user_data.get("phone") or user_data.get("phone_number")),
            ("location", user_data.get("location")),
            ("linkedin", user_data.get("linkedin") or user_data.get("linkedin_url")),
            ("github", user_data.get("github") or user_data.get("github_url")),
            ("portfolio", user_data.get("portfolio") or user_data.get("portfolio_url")),
        ]

        for field_key, field_val in single_fields:
            if not field_val:
                continue
            loc = self.find_field_locator(page, field_key)
            if loc:
                try:
                    loc.fill(str(field_val))
                    filled_count += 1
                    logger.info(f"Filled field '{field_key}'.")
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"Could not fill field '{field_key}': {e}")

        return filled_count

    def handle_dropdowns_and_options(
        self, page: Page, user_data: dict[str, Any]
    ) -> int:
        """Handle select dropdowns, radio buttons, and checkboxes.

        Args:
            page: Playwright Page instance.
            user_data: User information dictionary.

        Returns:
            Number of options selected.
        """
        filled_count = 0

        # 1. Education select
        edu_val = user_data.get("education")
        if edu_val:
            loc = self.find_field_locator(page, "education")
            if loc:
                try:
                    tag = loc.evaluate("el => el.tagName.toLowerCase()")
                    if tag == "select":
                        try:
                            loc.select_option(label=str(edu_val))
                        except Exception:  # noqa: BLE001
                            try:
                                loc.select_option(value=str(edu_val))
                            except Exception:  # noqa: BLE001
                                loc.select_option(index=1)
                        filled_count += 1
                        logger.info("Selected education option.")
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"Failed selecting education: {e}")

        # 2. Experience radio buttons
        exp_val = user_data.get("experience")
        if exp_val:
            try:
                radios = page.locator("input[type='radio']")
                for i in range(radios.count()):
                    radio = radios.nth(i)
                    radio_val = radio.get_attribute("value") or ""
                    if str(exp_val).lower() in radio_val.lower():
                        radio.check()
                        filled_count += 1
                        logger.info("Checked experience radio option.")
                        break
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Failed checking experience radio: {e}")

        # 3. Skills checkboxes
        skills_val = user_data.get("skills")
        if skills_val:
            skills_list = skills_val if isinstance(skills_val, list) else [skills_val]
            for skill in skills_list:
                try:
                    cb = page.locator(f"input[type='checkbox'][value*='{skill}' i]")
                    if self._is_locator_usable(cb):
                        cb.first.check()
                        filled_count += 1
                        logger.info("Checked skill checkbox.")
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"Failed checking skill checkbox for '{skill}': {e}")

        return filled_count

    # ------------------------------------------------------------------
    # Resume Upload
    # ------------------------------------------------------------------

    def upload_resume(self, page: Page, resume_path: str) -> bool:
        """Upload resume file using Playwright's file upload API.

        Validates:
        1. File exists on disk.
        2. Supported extension (.pdf, .docx, .doc, .txt).
        3. Upload success.

        Args:
            page: Playwright Page instance.
            resume_path: Path to the resume file on local disk.

        Returns:
            True if uploaded successfully.

        Raises:
            ResumeUploadError: If file is missing or has unsupported extension.
        """
        path_obj = Path(resume_path)
        if not path_obj.is_file():
            raise ResumeUploadError(f"Resume file does not exist: {resume_path}")

        if path_obj.suffix.lower() not in SUPPORTED_RESUME_EXTENSIONS:
            raise ResumeUploadError(
                f"Unsupported resume extension '{path_obj.suffix}'. "
                f"Allowed: {', '.join(sorted(SUPPORTED_RESUME_EXTENSIONS))}"
            )

        # Locate file input element
        file_input = page.locator("input[type='file']")
        if not self._is_locator_usable(file_input):
            loc = self.find_field_locator(
                page, "resume", ["resume", "cv", "attach", "upload"]
            )
            if loc and self._is_locator_usable(loc):
                file_input = loc
            else:
                logger.warning("No file input element found on application page.")
                return False

        try:
            file_input.first.set_input_files(str(path_obj.resolve()))
            logger.info("Resume file uploaded successfully.")
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed uploading resume file via Playwright: {e}")
            return False

    # ------------------------------------------------------------------
    # Free Text Questions
    # ------------------------------------------------------------------

    def fill_free_text_fields(self, page: Page, answers: dict[str, str]) -> int:
        """Fill open textareas with generated answers.

        Args:
            page: Playwright Page instance.
            answers: Dictionary mapping question keyword/name to answer text.

        Returns:
            Number of textareas filled.
        """
        filled_count = 0
        if not answers:
            return filled_count

        textareas = page.locator("textarea")
        count = textareas.count()

        for i in range(count):
            ta = textareas.nth(i)
            if not (ta.is_visible() and ta.is_enabled()):
                continue

            ta_name = ta.get_attribute("name") or ""
            ta_id = ta.get_attribute("id") or ""
            ta_placeholder = ta.get_attribute("placeholder") or ""

            matched_answer = None

            for key, ans in answers.items():
                key_lower = key.lower()
                if (
                    key_lower in ta_name.lower()
                    or key_lower in ta_id.lower()
                    or key_lower in ta_placeholder.lower()
                ):
                    matched_answer = ans
                    break

            if not matched_answer and answers:
                matched_answer = next(iter(answers.values()))

            if matched_answer:
                try:
                    ta.fill(matched_answer)
                    filled_count += 1
                    logger.info("Filled free-text question field.")
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"Could not fill textarea: {e}")

        return filled_count

    # ------------------------------------------------------------------
    # Submission & Outcome Detection
    # ------------------------------------------------------------------

    def submit_form(self, page: Page) -> None:
        """Locate submit button and click to submit form."""
        submit_btn = None

        candidates = [
            page.locator("button[type='submit']"),
            page.locator("input[type='submit']"),
            page.get_by_role("button", name="Submit", exact=False),
            page.get_by_role("button", name="Apply", exact=False),
            page.get_by_test_id("submit-button"),
        ]

        for cand in candidates:
            if self._is_locator_usable(cand):
                submit_btn = cand.first
                break

        if not submit_btn:
            raise RuntimeError("Submit button not found on application form.")

        submit_btn.click()
        logger.info("Clicked form submit button.")

    def detect_outcome(self, page: Page) -> FormFillResult:
        """Detect submission outcome from page state.

        Returns:
            FormFillResult with status 'applied', 'failed', or 'needs_action'.
        """
        # 1. Security / Captcha / Bot wall detection -> needs_action
        captcha_indicators = [
            ".g-recaptcha",
            "#captcha",
            "[id*='captcha' i]",
            "iframe[src*='captcha' i]",
            "iframe[src*='cloudflare' i]",
        ]
        for selector in captcha_indicators:
            try:
                elem = page.locator(selector)
                if elem.count() > 0 and elem.first.is_visible():
                    return FormFillResult(
                        status="needs_action",
                        failure_reason="Captcha or security verification detected on page.",
                    )
            except Exception as e:  # noqa: BLE001
                logger.debug(f"Captcha indicator check skipped: {e}")

        # Check visible body text for security challenges
        try:
            body_text_lower = page.inner_text("body").lower()
            if (
                "please complete the captcha" in body_text_lower
                or "verify you are human" in body_text_lower
            ):
                return FormFillResult(
                    status="needs_action",
                    failure_reason="Security verification required.",
                )
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Body inner_text check skipped: {e}")

        # 2. Success message or redirection -> applied
        success_selectors = [
            "#success-message",
            ".success-message",
            ".application-submitted",
            "[data-testid='success-message']",
        ]
        for selector in success_selectors:
            try:
                elem = page.locator(selector)
                if elem.count() > 0 and elem.first.is_visible():
                    return FormFillResult(status="applied")
            except Exception as e:  # noqa: BLE001
                logger.debug(f"Success indicator check skipped: {e}")

        url_lower = page.url.lower()
        if any(
            term in url_lower
            for term in ["success", "thank-you", "thanks", "submitted", "confirmation"]
        ):
            return FormFillResult(status="applied")

        try:
            if any(
                phrase in body_text_lower
                for phrase in [
                    "application submitted",
                    "thank you for applying",
                    "application received",
                    "successfully submitted",
                ]
            ):
                return FormFillResult(status="applied")
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Content text check skipped: {e}")

        # 3. Explicit error indicators -> failed
        error_selectors = [
            "#error-message",
            ".error-message",
            ".form-error",
            "[data-testid='error-message']",
        ]
        for selector in error_selectors:
            try:
                elem = page.locator(selector)
                if elem.count() > 0 and elem.first.is_visible():
                    reason = elem.first.text_content() or "Form validation error"
                    return FormFillResult(
                        status="failed",
                        failure_reason=reason.strip(),
                    )
            except Exception as e:  # noqa: BLE001
                logger.debug(f"Error indicator check skipped: {e}")

        # Fallback check
        try:
            form = page.locator("form")
            if form.count() > 0 and not form.first.is_visible():
                return FormFillResult(status="applied")
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Form visibility check skipped: {e}")

        return FormFillResult(
            status="failed",
            failure_reason="Could not confirm application submission success.",
        )

    # ------------------------------------------------------------------
    # Main Orchestration API
    # ------------------------------------------------------------------

    def fill_and_submit(
        self,
        page: Page,
        user_data: dict[str, Any],
        resume_path: str | None = None,
        free_text_answers: dict[str, str] | None = None,
    ) -> FormFillResult:
        """Fill all application fields, upload resume, submit form, and detect outcome.

        Args:
            page: Playwright Page instance navigated to target job form.
            user_data: User details dict.
            resume_path: Path to resume file to upload.
            free_text_answers: Dictionary of generated free-text answers.

        Returns:
            FormFillResult containing status ('applied', 'failed', 'needs_action').
        """
        try:
            early_outcome = self.detect_outcome(page)
            if early_outcome.status == "needs_action":
                return early_outcome

            filled_std = self.fill_standard_fields(page, user_data)
            filled_opts = self.handle_dropdowns_and_options(page, user_data)

            if resume_path:
                try:
                    self.upload_resume(page, resume_path)
                except ResumeUploadError as e:
                    logger.error(f"Resume upload error: {e}")
                    return FormFillResult(
                        status="failed",
                        failure_reason=str(e),
                    )

            filled_text = self.fill_free_text_fields(page, free_text_answers or {})
            self.submit_form(page)

            try:
                page.wait_for_load_state("networkidle", timeout=2000)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"Wait for network idle timed out: {e}")

            outcome = self.detect_outcome(page)
            outcome.metadata = {
                "filled_standard_fields": filled_std,
                "filled_option_fields": filled_opts,
                "filled_free_text_fields": filled_text,
            }
            return outcome

        except PlaywrightTimeoutError as e:
            logger.error(f"Playwright operation timed out: {e}")
            return FormFillResult(
                status="failed",
                failure_reason=f"Timeout during form interaction: {e}",
            )
        except Exception as e:
            logger.exception("Unexpected error during form filling.")
            return FormFillResult(
                status="failed",
                failure_reason=f"Error filling form: {e}",
            )
