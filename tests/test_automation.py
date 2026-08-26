"""Tests for CAPTCHA detection, retry logic, and error recovery (Issue #15).

Tests are organised into five sections:

1. CaptchaHandler — HTML signal detection (raw strings)
2. CaptchaHandler — local file:// fixture detection
3. CaptchaHandler — Playwright page duck-type and edge cases
4. ApplicationAgent — failure classification (CAPTCHA / permanent / temporary)
5. ApplicationAgent — retry / exponential backoff
6. ApplicationAgent — captcha detection via URL integration
7. ApplicationAgent — constructor validation
"""

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from src.agents.application_agent import (
    ApplicationAgent,
    CaptchaDetectedError,
    PermanentApplicationError,
    TemporaryApplicationError,
)
from src.automation.captcha_handler import CaptchaHandler

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CAPTCHA_FORM_PATH = FIXTURES_DIR / "captcha_form.html"
FLAKY_FORM_PATH = FIXTURES_DIR / "flaky_form.html"

_USER_PROFILE = {"name": "Test User", "email": "test@example.com"}
_RESUME_PATH = "data/resumes/test/resume_v1.pdf"


def _make_agent(**kwargs) -> ApplicationAgent:
    """Return an ApplicationAgent with FormFiller mocked out."""
    with patch("src.agents.application_agent.FormFiller"):
        return ApplicationAgent(**kwargs)


# ===========================================================================
# 1. CaptchaHandler — raw HTML signal detection
# ===========================================================================


class TestCaptchaHandlerRawHtml:
    """CaptchaHandler.detect() with raw HTML strings."""

    def setup_method(self):
        self.handler = CaptchaHandler()

    def test_detects_g_recaptcha_class(self):
        """CSS class 'g-recaptcha' triggers detection."""
        html = "<div class='g-recaptcha' data-sitekey='abc'></div>"
        assert self.handler.detect(html) is True

    def test_detects_h_captcha_class(self):
        """CSS class 'h-captcha' triggers detection."""
        html = "<div class='h-captcha' data-sitekey='xyz'></div>"
        assert self.handler.detect(html) is True

    def test_detects_recaptcha_iframe(self):
        """Iframe with 'recaptcha' in src triggers detection."""
        html = "<iframe src='https://www.google.com/recaptcha/api2/anchor'></iframe>"
        assert self.handler.detect(html) is True

    def test_detects_hcaptcha_iframe(self):
        """Iframe with 'hcaptcha' in src triggers detection."""
        html = "<iframe src='https://newassets.hcaptcha.com/captcha/v1'></iframe>"
        assert self.handler.detect(html) is True

    def test_detects_g_recaptcha_response_textarea_by_name(self):
        """Textarea with name='g-recaptcha-response' triggers detection."""
        html = "<textarea name='g-recaptcha-response'></textarea>"
        assert self.handler.detect(html) is True

    def test_detects_g_recaptcha_response_textarea_by_id(self):
        """Textarea with id='g-recaptcha-response' triggers detection (id check)."""
        html = "<textarea id='g-recaptcha-response'></textarea>"
        assert self.handler.detect(html) is True

    def test_detects_h_captcha_response_textarea(self):
        """Textarea named 'h-captcha-response' triggers detection."""
        html = "<textarea name='h-captcha-response'></textarea>"
        assert self.handler.detect(html) is True

    def test_detects_recaptcha_script(self):
        """Script loading the reCAPTCHA API triggers detection."""
        html = "<script src='https://www.google.com/recaptcha/api.js'></script>"
        assert self.handler.detect(html) is True

    def test_detects_hcaptcha_script(self):
        """Script loading the hCaptcha API triggers detection."""
        html = "<script src='https://hcaptcha.com/1/api.js'></script>"
        assert self.handler.detect(html) is True

    def test_detects_keyword_please_complete_the_captcha(self):
        """Keyword 'please complete the captcha' triggers detection."""
        html = "<p>Please complete the CAPTCHA before submitting.</p>"
        assert self.handler.detect(html) is True

    def test_detects_keyword_i_am_not_a_robot(self):
        """Keyword 'i am not a robot' triggers detection."""
        html = "<p>Please tick <strong>I am not a robot</strong> to proceed.</p>"
        assert self.handler.detect(html) is True

    def test_detects_keyword_prove_you_are_human(self):
        """Keyword 'prove you are human' triggers detection."""
        html = "<h2>Prove you are human</h2><img src='captcha.png'>"
        assert self.handler.detect(html) is True

    def test_detects_cf_turnstile(self):
        """Cloudflare Turnstile widget class triggers detection."""
        html = "<div class='cf-turnstile' data-sitekey='key'></div>"
        assert self.handler.detect(html) is True

    def test_clean_form_not_detected(self):
        """A normal application form without CAPTCHA is not flagged."""
        html = """
        <form>
            <input type='text' name='name'>
            <input type='email' name='email'>
            <input type='file' name='resume'>
            <button type='submit'>Apply</button>
        </form>
        """
        assert self.handler.detect(html) is False

    def test_empty_html_not_detected(self):
        """Completely empty HTML string is not flagged."""
        assert self.handler.detect("") is False


# ===========================================================================
# 2. CaptchaHandler — local file:// fixture detection
# ===========================================================================


class TestCaptchaHandlerLocalFile:
    """CaptchaHandler.detect() with local file:// URLs."""

    def setup_method(self):
        self.handler = CaptchaHandler()

    def test_detects_captcha_in_fixture_file(self):
        """captcha_form.html exercises all 5 detection signals simultaneously."""
        url = CAPTCHA_FORM_PATH.as_uri()
        assert self.handler.detect(url) is True

    def test_clean_form_not_detected_in_flaky_fixture(self):
        """flaky_form.html has no CAPTCHA signals — passes CAPTCHA check cleanly."""
        url = FLAKY_FORM_PATH.as_uri()
        assert self.handler.detect(url) is False

    def test_bad_url_returns_false_not_exception(self):
        """Unreachable URL must return False, not raise, due to resilient detect()."""
        result = self.handler.detect("file:///nonexistent/path/missing.html")
        assert result is False


# ===========================================================================
# 3. CaptchaHandler — Playwright page duck-type and edge cases
# ===========================================================================


class TestCaptchaHandlerPlaywrightPage:
    """CaptchaHandler.detect() with Playwright page duck-type."""

    def test_detects_via_playwright_page_object(self):
        """A Playwright-like page object with content() is supported."""
        mock_page = MagicMock()
        mock_page.content.return_value = (
            "<div class='g-recaptcha' data-sitekey='key'></div>"
        )
        handler = CaptchaHandler()
        assert handler.detect(mock_page) is True

    def test_clean_page_not_detected(self):
        """A Playwright page without CAPTCHA signals returns False."""
        mock_page = MagicMock()
        mock_page.content.return_value = "<form><input name='email'></form>"
        handler = CaptchaHandler()
        assert handler.detect(mock_page) is False

    def test_playwright_crash_returns_false(self):
        """If page.content() raises, detect() must return False not propagate."""
        mock_page = MagicMock()
        mock_page.content.side_effect = RuntimeError("TargetClosedError")
        handler = CaptchaHandler()
        # detect() wraps all exceptions — must not raise
        result = handler.detect(mock_page)
        assert result is False

    def test_unsupported_type_returns_false(self):
        """Passing an unsupported type causes detect() to return False (resilient)."""
        handler = CaptchaHandler()
        result = handler.detect(12345)  # type: ignore[arg-type]
        assert result is False


# ===========================================================================
# 4. ApplicationAgent — failure classification
# ===========================================================================


class TestApplicationAgentFailureClassification:
    """Ensure each failure type produces the correct status with no wrong retry."""

    def test_captcha_detected_returns_needs_action(self):
        """CAPTCHA → needs_action immediately, no retry."""
        agent = _make_agent(max_retries=3, retry_delay=0)

        with patch.object(agent, "_submit_application") as mock_submit:
            mock_submit.side_effect = CaptchaDetectedError("CAPTCHA detected")
            result = agent.apply(
                application_url="http://example.com/apply",
                resume_path=_RESUME_PATH,
                user_profile=_USER_PROFILE,
            )

        assert result["status"] == "needs_action"
        assert "CAPTCHA" in result["failure_reason"]
        assert result["attempts"] == 1
        mock_submit.assert_called_once()  # No retry

    def test_permanent_failure_returns_failed_immediately(self):
        """PermanentApplicationError → failed with no retry."""
        agent = _make_agent(max_retries=3, retry_delay=0)

        with patch.object(agent, "_submit_application") as mock_submit:
            mock_submit.side_effect = PermanentApplicationError("Selector not found")
            result = agent.apply(
                application_url="http://example.com/apply",
                resume_path=_RESUME_PATH,
                user_profile=_USER_PROFILE,
            )

        assert result["status"] == "failed"
        assert "Selector not found" in result["failure_reason"]
        assert result["attempts"] == 1
        mock_submit.assert_called_once()

    def test_selector_failure_not_retried(self):
        """Missing selector is permanent — exactly 1 attempt regardless of max_retries."""
        agent = _make_agent(max_retries=5, retry_delay=0)

        with patch.object(agent, "_submit_application") as mock_submit:
            mock_submit.side_effect = PermanentApplicationError(
                "Required selector '#apply-btn' not found"
            )
            result = agent.apply(
                application_url="http://example.com/apply",
                resume_path=_RESUME_PATH,
                user_profile=_USER_PROFILE,
            )

        assert result["attempts"] == 1

    def test_successful_application_returns_applied(self):
        """Successful submission → status=applied, failure_reason=None, attempts=1."""
        agent = _make_agent(max_retries=3, retry_delay=0)

        with patch.object(agent, "_submit_application"):  # no exception = success
            result = agent.apply(
                application_url="http://example.com/apply",
                resume_path=_RESUME_PATH,
                user_profile=_USER_PROFILE,
            )

        assert result["status"] == "applied"
        assert result["failure_reason"] is None
        assert result["attempts"] == 1


# ===========================================================================
# 5. ApplicationAgent — retry and exponential backoff
# ===========================================================================


class TestApplicationAgentRetry:
    """Verify retry behaviour and exponential-backoff sleep timing."""

    def test_temporary_failure_retried_up_to_max_retries(self):
        """TemporaryApplicationError is retried until all attempts are exhausted."""
        agent = _make_agent(max_retries=3, retry_delay=0)

        with patch.object(agent, "_submit_application") as mock_submit:
            mock_submit.side_effect = TemporaryApplicationError("Timeout")
            result = agent.apply(
                application_url="http://example.com/apply",
                resume_path=_RESUME_PATH,
                user_profile=_USER_PROFILE,
            )

        assert result["status"] == "failed"
        assert result["attempts"] == 4  # 1 initial + 3 retries
        assert mock_submit.call_count == 4

    def test_flaky_form_succeeds_on_second_attempt(self):
        """Temporary failure on attempt 1, success on attempt 2 → status=applied."""
        agent = _make_agent(max_retries=3, retry_delay=0)
        call_count = {"n": 0}

        def flaky(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise TemporaryApplicationError("Network timeout on first attempt")
            # Second call succeeds silently

        with patch.object(agent, "_submit_application", side_effect=flaky):
            result = agent.apply(
                application_url=FLAKY_FORM_PATH.as_uri(),
                resume_path=_RESUME_PATH,
                user_profile=_USER_PROFILE,
            )

        assert result["status"] == "applied"
        assert result["attempts"] == 2

    def test_zero_retries_fails_on_first_temporary_error(self):
        """max_retries=0 means exactly 1 attempt before failing."""
        agent = _make_agent(max_retries=0, retry_delay=0)

        with patch.object(agent, "_submit_application") as mock_submit:
            mock_submit.side_effect = TemporaryApplicationError("Timeout")
            result = agent.apply(
                application_url="http://example.com/apply",
                resume_path=_RESUME_PATH,
                user_profile=_USER_PROFILE,
            )

        assert result["status"] == "failed"
        assert result["attempts"] == 1
        mock_submit.assert_called_once()

    def test_exponential_backoff_sleep_calls(self):
        """Sleep durations strictly follow retry_delay * 2^(attempt-1)."""
        agent = _make_agent(max_retries=3, retry_delay=1)

        with (
            patch.object(agent, "_submit_application") as mock_submit,
            patch("src.agents.application_agent.time.sleep") as mock_sleep,
        ):
            mock_submit.side_effect = TemporaryApplicationError("Timeout")
            agent.apply(
                application_url="http://example.com/apply",
                resume_path=_RESUME_PATH,
                user_profile=_USER_PROFILE,
            )

        # 3 sleeps between 4 attempts: 1s, 2s, 4s
        mock_sleep.assert_has_calls([call(1.0), call(2.0), call(4.0)])
        assert mock_sleep.call_count == 3

    def test_no_sleep_after_permanent_failure(self):
        """Permanent failures never trigger a sleep."""
        agent = _make_agent(max_retries=3, retry_delay=1)

        with (
            patch.object(agent, "_submit_application") as mock_submit,
            patch("src.agents.application_agent.time.sleep") as mock_sleep,
        ):
            mock_submit.side_effect = PermanentApplicationError("Bad selector")
            agent.apply(
                application_url="http://example.com/apply",
                resume_path=_RESUME_PATH,
                user_profile=_USER_PROFILE,
            )

        mock_sleep.assert_not_called()

    def test_no_sleep_after_captcha(self):
        """CAPTCHA detection never triggers a sleep."""
        agent = _make_agent(max_retries=3, retry_delay=1)

        with (
            patch.object(agent, "_submit_application") as mock_submit,
            patch("src.agents.application_agent.time.sleep") as mock_sleep,
        ):
            mock_submit.side_effect = CaptchaDetectedError("CAPTCHA detected")
            agent.apply(
                application_url="http://example.com/apply",
                resume_path=_RESUME_PATH,
                user_profile=_USER_PROFILE,
            )

        mock_sleep.assert_not_called()

    def test_timeout_retried_until_exhausted(self):
        """Network timeout is retried up to max_retries, then status=failed."""
        agent = _make_agent(max_retries=2, retry_delay=0)

        with patch.object(agent, "_submit_application") as mock_submit:
            mock_submit.side_effect = TemporaryApplicationError(
                "playwright: Timeout 30000ms exceeded"
            )
            result = agent.apply(
                application_url="http://example.com/apply",
                resume_path=_RESUME_PATH,
                user_profile=_USER_PROFILE,
            )

        assert result["status"] == "failed"
        assert result["attempts"] == 3  # 1 initial + 2 retries
        assert "Timeout" in result["failure_reason"]


# ===========================================================================
# 6. ApplicationAgent — CAPTCHA detection via URL (integration)
# ===========================================================================


class TestCaptchaDetectionViaUrl:
    """_submit_application() detects CAPTCHA before touching Playwright."""

    def test_captcha_url_raises_captcha_detected_error(self):
        """CAPTCHA fixture URL causes _submit_application to raise CaptchaDetectedError."""
        agent = _make_agent(max_retries=0, retry_delay=0)
        url = CAPTCHA_FORM_PATH.as_uri()

        with pytest.raises(CaptchaDetectedError):
            agent._submit_application(
                application_url=url,
                resume_path=_RESUME_PATH,
                user_profile=_USER_PROFILE,
            )

    def test_captcha_url_via_apply_returns_needs_action(self):
        """Full apply() with captcha_form.html fixture → needs_action, 1 attempt."""
        agent = _make_agent(max_retries=0, retry_delay=0)
        result = agent.apply(
            application_url=CAPTCHA_FORM_PATH.as_uri(),
            resume_path=_RESUME_PATH,
            user_profile=_USER_PROFILE,
        )
        assert result["status"] == "needs_action"
        assert result["attempts"] == 1

    def test_clean_url_passes_captcha_check_reaches_form_filler(self):
        """Clean URL passes CAPTCHA check and reaches _fill_and_submit_form."""
        agent = _make_agent(max_retries=0, retry_delay=0)
        url = FLAKY_FORM_PATH.as_uri()

        with pytest.raises(PermanentApplicationError):
            agent._submit_application(
                application_url=url,
                resume_path=_RESUME_PATH,
                user_profile=_USER_PROFILE,
            )


# ===========================================================================
# 7. ApplicationAgent — constructor validation
# ===========================================================================


class TestApplicationAgentConstruction:
    def test_default_max_retries(self):
        assert _make_agent().max_retries == 3

    def test_default_retry_delay(self):
        assert _make_agent().retry_delay == 1.0

    def test_negative_max_retries_raises(self):
        with pytest.raises(ValueError, match="max_retries"):
            _make_agent(max_retries=-1)

    def test_negative_retry_delay_raises(self):
        with pytest.raises(ValueError, match="retry_delay"):
            _make_agent(retry_delay=-0.5)
