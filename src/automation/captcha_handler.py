"""CAPTCHA detection for HireFlow AI.

Identifies CAPTCHA challenges on application pages so the agent can flag
them for manual action rather than crashing or attempting to solve them.

Solving CAPTCHAs programmatically violates the terms of service of virtually
every job portal and is legally problematic.  This module only *detects*
CAPTCHA presence.

Usage::

    from src.automation.captcha_handler import CaptchaHandler

    handler = CaptchaHandler()
    detected = handler.detect("file://tests/fixtures/captcha_form.html")
    # True

    # Also works with raw HTML
    detected = handler.detect("<div class='g-recaptcha'></div>")
    # True
"""

import logging
import re
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Detection patterns
# ---------------------------------------------------------------------------

# CSS class or id fragments that reliably indicate a CAPTCHA widget.
_CAPTCHA_CSS_PATTERNS: frozenset[str] = frozenset(
    {
        "g-recaptcha",
        "h-captcha",
        "recaptcha",
        "hcaptcha",
        "captcha-container",
        "captcha_container",
        "captcha-widget",
        "captcha_widget",
        "captcha-box",
        "captcha_box",
        "image-captcha",
        "image_captcha",
        "cf-turnstile",  # Cloudflare Turnstile
    }
)

# Iframe src substrings that indicate an embedded CAPTCHA.
_CAPTCHA_IFRAME_PATTERNS: frozenset[str] = frozenset(
    {
        "recaptcha",
        "hcaptcha",
        "captcha",
        "challenges.cloudflare.com",
    }
)

# textarea name/id attributes used by CAPTCHA widgets to store response tokens.
_CAPTCHA_TEXTAREA_NAMES: frozenset[str] = frozenset(
    {
        "g-recaptcha-response",
        "h-captcha-response",
        "recaptcha-token",
    }
)

# Script src patterns that indicate CAPTCHA JS libraries are loaded.
_CAPTCHA_SCRIPT_PATTERNS: frozenset[str] = frozenset(
    {
        "www.google.com/recaptcha",
        "hcaptcha.com/1/api",
        "challenges.cloudflare.com/turnstile",
    }
)

# Keywords whose presence anywhere in visible text or raw HTML strongly
# suggests a CAPTCHA challenge is being displayed.
_CAPTCHA_KEYWORDS: tuple[str, ...] = (
    "please complete the captcha",
    "prove you are human",
    "i'm not a robot",
    "i am not a robot",
    "verify you are human",
    "security check",
    "bot detection",
    "human verification",
)

# Compiled keyword regex for fast case-insensitive search over the full HTML.
_CAPTCHA_KEYWORD_RE: re.Pattern[str] = re.compile(
    "|".join(re.escape(kw) for kw in _CAPTCHA_KEYWORDS),
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# CaptchaHandler
# ---------------------------------------------------------------------------


class CaptchaHandler:
    """Detects CAPTCHA challenges on web pages.

    Supports three input modes:

    1. **URL** (``http://``, ``https://``, ``file://``) — fetched with
       :mod:`urllib.request`.
    2. **Playwright page object** — reads the page's current HTML via
       ``page.content()``.
    3. **Raw HTML string** — parsed directly.

    Attributes:
        None — this class is stateless; instantiate once and call freely.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, source: str | object) -> bool:
        """Return ``True`` if a CAPTCHA is present in the given source.

        This method is intentionally *resilient* — if the HTML cannot be
        loaded for any reason (network error, Playwright crash, unsupported
        type) it logs the failure and returns ``False`` rather than raising.
        The calling agent can then decide how to proceed.

        Args:
            source: One of:
                - A URL string (``http://``, ``https://``, ``file://``).
                - A Playwright ``Page`` object (must have a ``content()``
                  method).
                - A raw HTML string.

        Returns:
            ``True`` if any CAPTCHA signal is found; ``False`` otherwise.
        """
        try:
            html = self._resolve_html(source)
        except (RuntimeError, ValueError, TypeError):
            logger.exception(
                "CaptchaHandler: failed to load HTML for detection — "
                "assuming no CAPTCHA present"
            )
            return False

        return self._analyse(html)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_html(self, source: str | object) -> str:
        """Return raw HTML from *source*, regardless of its type.

        Args:
            source: URL, Playwright page, or raw HTML string.

        Returns:
            The raw HTML as a string.

        Raises:
            TypeError: If *source* is not a recognised type.
        """
        # Playwright page object (duck-typed by the presence of content())
        if hasattr(source, "content") and callable(source.content):
            logger.debug("CaptchaHandler: reading HTML from Playwright page")
            try:
                return source.content()
            except Exception as exc:
                raise RuntimeError(
                    "CaptchaHandler: Playwright page.content() failed"
                ) from exc

        if not isinstance(source, str):
            raise TypeError(
                f"CaptchaHandler.detect() received an unsupported source type: "
                f"{type(source)!r}"
            )

        # URL (http, https, or file)
        if source.startswith(("http://", "https://", "file://")):
            # Normalize relative file:// to absolute file:///
            # e.g. "file://tests/fixtures/x.html" → "file:///abs/path/tests/fixtures/x.html"
            if source.startswith("file://") and not source.startswith("file:///"):
                relative = source[len("file://") :]
                abs_path = (Path.cwd() / relative).resolve()
                source = abs_path.as_uri()
                logger.debug("CaptchaHandler: resolved relative file URL to %s", source)
            logger.debug("CaptchaHandler: fetching HTML from URL: %s", source)
            return self._fetch_url(source)

        # Assume raw HTML
        logger.debug("CaptchaHandler: using source as raw HTML string")
        return source

    @staticmethod
    def _fetch_url(url: str) -> str:
        """Fetch and return the HTML content at *url*.

        Args:
            url: An HTTP, HTTPS, or file:// URL.

        Returns:
            Decoded HTML string.

        Raises:
            RuntimeError: If the URL cannot be retrieved.
        """
        try:
            with urllib.request.urlopen(url) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            raise RuntimeError(
                f"CaptchaHandler could not fetch URL {url!r}: {exc}"
            ) from exc

    def _analyse(self, html: str) -> bool:
        """Run all CAPTCHA detection signals against *html*.

        Args:
            html: Raw HTML string.

        Returns:
            ``True`` if any signal fires.
        """
        soup = BeautifulSoup(html, "html.parser")

        if self._check_css_classes(soup):
            logger.info("CaptchaHandler: CAPTCHA detected via CSS class/id pattern")
            return True

        if self._check_iframes(soup):
            logger.info("CaptchaHandler: CAPTCHA detected via iframe src")
            return True

        if self._check_textareas(soup):
            logger.info("CaptchaHandler: CAPTCHA detected via textarea name")
            return True

        if self._check_scripts(soup):
            logger.info("CaptchaHandler: CAPTCHA detected via script src")
            return True

        if self._check_keywords(html):
            logger.info("CaptchaHandler: CAPTCHA detected via keyword match")
            return True

        return False

    @staticmethod
    def _check_css_classes(soup: BeautifulSoup) -> bool:
        """Return ``True`` if any element carries a known CAPTCHA class or id."""
        for tag in soup.find_all():
            classes: list[str] = tag.get("class") or []
            tag_id: str = (tag.get("id") or "").lower()

            if any(cls.lower() in _CAPTCHA_CSS_PATTERNS for cls in classes):
                return True

            if tag_id in _CAPTCHA_CSS_PATTERNS:
                return True

        return False

    @staticmethod
    def _check_iframes(soup: BeautifulSoup) -> bool:
        """Return ``True`` if any iframe src matches a CAPTCHA pattern."""
        for iframe in soup.find_all("iframe"):
            src: str = (iframe.get("src") or "").lower()
            if any(pattern in src for pattern in _CAPTCHA_IFRAME_PATTERNS):
                return True
        return False

    @staticmethod
    def _check_textareas(soup: BeautifulSoup) -> bool:
        """Return ``True`` if any textarea has a CAPTCHA response field name or id."""
        for textarea in soup.find_all("textarea"):
            name: str = (textarea.get("name") or "").lower()
            tag_id: str = (textarea.get("id") or "").lower()
            if name in _CAPTCHA_TEXTAREA_NAMES or tag_id in _CAPTCHA_TEXTAREA_NAMES:
                return True
        return False

    @staticmethod
    def _check_scripts(soup: BeautifulSoup) -> bool:
        """Return ``True`` if any script src loads a known CAPTCHA library."""
        for script in soup.find_all("script"):
            src: str = (script.get("src") or "").lower()
            if any(pattern in src for pattern in _CAPTCHA_SCRIPT_PATTERNS):
                return True
        return False

    @staticmethod
    def _check_keywords(html: str) -> bool:
        """Return ``True`` if any CAPTCHA keyword appears in the raw HTML."""
        return bool(_CAPTCHA_KEYWORD_RE.search(html))
