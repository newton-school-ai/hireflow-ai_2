"""
Unified LLM client for HireFlow AI.

Provides a single interface for calling language models across multiple
providers. The active provider is chosen from the LLM_PROVIDER environment
variable with automatic fallback.

Current PR scope (Issue #4):
    - Groq: fully implemented (free tier, recommended default).
    - Gemini, OpenAI, Ollama: interface preserved, raises NotImplementedError.
      Will be completed in future milestones as needed.

Usage:
    from src.utils.llm_client import get_llm_client

    client = get_llm_client()
    result = await client.generate("Extract skills from this resume...")
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod

from src.config.settings import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LLMConfigError(Exception):
    """Raised when no LLM provider is properly configured."""


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class BaseLLMClient(ABC):
    """Abstract base for all LLM provider clients.

    Every provider must implement ``generate(prompt) -> str``.  The rest
    of the application codes against this interface so providers can be
    swapped without changing call sites.
    """

    @abstractmethod
    async def generate(self, prompt: str) -> str:
        """Send a prompt and return the raw text response.

        Args:
            prompt: The text prompt to send to the LLM.

        Returns:
            The LLM's text response.

        Raises:
            LLMConfigError: If the provider is misconfigured.
            RuntimeError: If the API call fails.
        """


# ---------------------------------------------------------------------------
# Groq — fully implemented
# ---------------------------------------------------------------------------


class GroqClient(BaseLLMClient):
    """Client for the Groq Cloud API.

    Uses the official ``groq`` SDK.  Groq provides fast inference on
    open-source models (Llama 3, Mixtral) with a generous free tier,
    making it the recommended default for this project.
    """

    def __init__(self, api_key: str, model: str) -> None:
        if not api_key or api_key.startswith("your_"):
            raise LLMConfigError(
                "GROQ_API_KEY is missing or invalid. "
                "Please configure it in .env to use Groq."
            )
        self._api_key = api_key
        self._model = model

    async def generate(self, prompt: str) -> str:
        from groq import Groq

        client = Groq(api_key=self._api_key)
        response = client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=4096,
        )
        return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Placeholder providers — interface preserved for future milestones
# ---------------------------------------------------------------------------


class GeminiClient(BaseLLMClient):
    """Placeholder for the Google Gemini API.

    Will be implemented when Gemini support is needed in a future milestone.
    The interface is preserved so ``get_llm_client()`` already knows how
    to route to it once the implementation is filled in.
    """

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    async def generate(self, prompt: str) -> str:
        raise NotImplementedError(
            "GeminiClient is not yet implemented. "
            "Set LLM_PROVIDER=groq in your .env for now."
        )


class OpenAIClient(BaseLLMClient):
    """Placeholder for the OpenAI API."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def generate(self, prompt: str) -> str:
        raise NotImplementedError(
            "OpenAIClient is not yet implemented. "
            "Set LLM_PROVIDER=groq in your .env for now."
        )


class OllamaClient(BaseLLMClient):
    """Placeholder for a local Ollama instance."""

    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model

    async def generate(self, prompt: str) -> str:
        raise NotImplementedError(
            "OllamaClient is not yet implemented. "
            "Set LLM_PROVIDER=groq in your .env for now."
        )


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------


def get_llm_client() -> BaseLLMClient:
    """Return an LLM client for the configured provider.

    Returns:
        A concrete ``BaseLLMClient`` subclass instance.

    Raises:
        LLMConfigError: If the configured provider is missing required keys.
    """
    settings = get_settings()
    provider = settings.llm_provider.lower().strip()

    if provider == "groq":
        client = GroqClient(settings.groq_api_key, settings.groq_model)
    elif provider == "gemini":
        client = GeminiClient(settings.google_api_key, settings.gemini_model)
    elif provider == "openai":
        client = OpenAIClient(settings.openai_api_key)
    elif provider == "ollama":
        client = OllamaClient(settings.ollama_base_url, settings.ollama_model)
    else:
        raise LLMConfigError(f"Unknown LLM provider configured: {provider}")

    logger.info("LLM provider resolved: %s", provider)
    return client


# ---------------------------------------------------------------------------
# Resume extraction prompt
# ---------------------------------------------------------------------------

RESUME_EXTRACTION_PROMPT = """\
You are a precise resume data extraction system.

Extract structured information from the resume text below and return ONLY
a valid JSON object.

STRICT RULES — violating any of these is a failure:
1. Return ONLY the raw JSON object. Nothing else.
2. Do NOT wrap the response in markdown code fences (``` or ```json).
3. Do NOT include any explanations, commentary, or extra text.
4. Do NOT hallucinate or invent information that is not in the resume.
5. For any field where data is not found, use an empty array [], empty
   string "", or null as appropriate for the field type.
6. Extract skills as individual short strings (e.g. "Python", "FastAPI").

Return this exact JSON structure:
{
  "name": "",
  "email": "",
  "phone": "",
  "skills": [],
  "education": [],
  "experience": [],
  "projects": [],
  "certifications": [],
  "languages": [],
  "links": {"github": "", "linkedin": "", "portfolio": ""},
  "target_roles": [],
  "preferred_locations": []
}

Field details:
- education: array of objects with "degree", "institution", "year"
- experience: array of objects with "title", "company", "duration", "description"
- projects: array of objects with "name", "description", "technologies"
- certifications: array of strings
- languages: array of strings (spoken/written languages)
- links: object with github, linkedin, portfolio URLs as strings

Resume text:
---
%s
---

JSON:"""


def build_extraction_prompt(resume_text: str) -> str:
    """Build the LLM prompt for structured resume data extraction.

    Args:
        resume_text: Raw text extracted from the uploaded PDF.

    Returns:
        The fully formatted prompt string ready for the LLM.
    """
    return RESUME_EXTRACTION_PROMPT % resume_text


def parse_llm_json(raw: str) -> dict:
    """Parse JSON from LLM output, handling common formatting issues.

    LLMs sometimes wrap JSON in markdown code fences despite explicit
    instructions.  This function strips those before parsing.

    Args:
        raw: Raw string output from the LLM.

    Returns:
        Parsed dictionary.

    Raises:
        ValueError: If the output cannot be parsed as valid JSON.
    """
    text = raw.strip()

    # Strip markdown code fences if present.
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
    if text.endswith("```"):
        text = text[: -len("```")]
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"LLM returned invalid JSON. First 500 chars: {raw[:500]}"
        ) from exc
