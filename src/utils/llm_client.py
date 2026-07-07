"""
<<<<<<< HEAD
Unified LLM client interface for HireFlow AI.
Supports Groq, Gemini, OpenAI, Anthropic, and Ollama.
"""

import json
import os
import re
from abc import ABC, abstractmethod
from src.config.settings import settings


class LLMClient(ABC):
    """Abstract Base Class for all LLM clients, ensuring consistent interface."""

    @abstractmethod
    def chat(self, prompt: str, system_prompt: str | None = None, **kwargs) -> str:
        """Send a chat prompt to the LLM and return the string response."""
        pass

    def extract(
        self, prompt: str, system_prompt: str | None = None, **kwargs
    ) -> str | dict | list:
        """Send a prompt requesting structured data.

        Attempts to return a parsed JSON object (dict or list), otherwise falls back to raw string.
        """
        # Append formatting instruction to prompt if not explicitly present
        if "json" not in prompt.lower():
            prompt = (
                f"{prompt}\n\n"
                "Respond ONLY with a valid JSON object or JSON array. "
                "Do not include any explanation or markdown formatting like ```json."
            )

        response = self.chat(prompt, system_prompt, **kwargs)
        clean_response = response.strip()

        # Strip markdown code fences if present
        if clean_response.startswith("```"):
            clean_response = re.sub(r"^```(?:json)?\n", "", clean_response)
            clean_response = re.sub(r"\n```$", "", clean_response)
            clean_response = clean_response.strip()

        try:
            return json.loads(clean_response)
        except json.JSONDecodeError:
            # Fallback regex search for JSON block
            match = re.search(r"(\{.*\}|\[.*\])", clean_response, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    pass
            return response


class GroqClient(LLMClient):
    """LLM Client for Groq API."""

    def __init__(self):
        api_key = settings.groq_api_key or os.getenv("GROQ_API_KEY")
        if not api_key or "your_groq" in api_key:
            raise ValueError(
                "Groq API key is missing. Please set GROQ_API_KEY in your environment or .env file."
            )
        try:
            from groq import Groq
        except ImportError:
            raise ImportError(
                "groq library is not installed. Please install it using pip."
            )
        self.client = Groq(api_key=api_key)
        self.model = settings.groq_model or "llama3-8b-8192"

    def chat(self, prompt: str, system_prompt: str | None = None, **kwargs) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Pop response_format for safety
        response_format = kwargs.pop("response_format", None)
        if "json" in prompt.lower() and not response_format:
            response_format = {"type": "json_object"}

        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format=response_format,
                **kwargs,
            )
            return completion.choices[0].message.content
        except Exception as e:
            raise RuntimeError(f"Groq API request failed: {e}")


class GeminiClient(LLMClient):
    """LLM Client for Google Gemini API."""

    def __init__(self):
        api_key = settings.google_api_key or os.getenv("GOOGLE_API_KEY")
        if not api_key or "your_google" in api_key:
            raise ValueError(
                "Google API key is missing. Please set GOOGLE_API_KEY in your environment or .env file."
            )
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError(
                "google-generativeai library is not installed. Please install it using pip."
            )
        genai.configure(api_key=api_key)
        self.model_name = settings.gemini_model or "gemini-1.5-flash"

    def chat(self, prompt: str, system_prompt: str | None = None, **kwargs) -> str:
        import google.generativeai as genai

        config = {}
        if system_prompt:
            config["system_instruction"] = system_prompt

        if "json" in prompt.lower() and "response_mime_type" not in kwargs:
            config["response_mime_type"] = "application/json"

        # Pop parameters not supported directly by GenerateContent
        for param in ["response_format", "response_mime_type"]:
            if param in kwargs:
                val = kwargs.pop(param)
                if param == "response_mime_type":
                    config["response_mime_type"] = val

        try:
            model = genai.GenerativeModel(self.model_name)
            response = model.generate_content(
                prompt,
                generation_config=(
                    genai.types.GenerationConfig(**config) if config else None
                ),
                **kwargs,
            )
            return response.text
        except Exception as e:
            raise RuntimeError(f"Gemini API request failed: {e}")


class OpenAIClient(LLMClient):
    """LLM Client for OpenAI API."""

    def __init__(self):
        api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
        if not api_key or "your_openai" in api_key:
            raise ValueError(
                "OpenAI API key is missing. Please set OPENAI_API_KEY in your environment or .env file."
            )
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError(
                "openai library is not installed. Please install it using pip."
            )
        self.client = OpenAI(api_key=api_key)
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def chat(self, prompt: str, system_prompt: str | None = None, **kwargs) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Handle json response format
        response_format = kwargs.pop("response_format", None)
        if "json" in prompt.lower() and not response_format:
            response_format = {"type": "json_object"}

        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format=response_format,
                **kwargs,
            )
            return completion.choices[0].message.content
        except Exception as e:
            raise RuntimeError(f"OpenAI API request failed: {e}")


class AnthropicClient(LLMClient):
    """LLM Client for Anthropic Claude API."""

    def __init__(self):
        api_key = settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
        if not api_key or "your_anthropic" in api_key:
            raise ValueError(
                "Anthropic API key is missing. Please set ANTHROPIC_API_KEY in your environment or .env file."
            )
        try:
            from anthropic import Anthropic
        except ImportError:
            raise ImportError(
                "anthropic library is not installed. Please install it using pip."
            )
        self.client = Anthropic(api_key=api_key)
        self.model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20240620")

    def chat(self, prompt: str, system_prompt: str | None = None, **kwargs) -> str:
        messages = [{"role": "user", "content": prompt}]
        max_tokens = kwargs.pop("max_tokens", 4000)

        # Remove response format params as Anthropic doesn't support them directly in the same way
        kwargs.pop("response_format", None)
        kwargs.pop("response_mime_type", None)

        try:
            completion = self.client.messages.create(
                model=self.model,
                messages=messages,
                system=system_prompt if system_prompt else None,
                max_tokens=max_tokens,
                **kwargs,
            )
            return completion.content[0].text
        except Exception as e:
            raise RuntimeError(f"Anthropic API request failed: {e}")


class OllamaClient(LLMClient):
    """LLM Client for local Ollama service."""

    def __init__(self):
        self.base_url = settings.ollama_base_url or "http://localhost:11434"
        self.model = settings.ollama_model or "llama3"

    def chat(self, prompt: str, system_prompt: str | None = None, **kwargs) -> str:
        import httpx

        url = f"{self.base_url}/api/chat"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }

        # Check format
        fmt = kwargs.pop("format", None)
        if "json" in prompt.lower() and not fmt:
            fmt = "json"
        if fmt:
            payload["format"] = fmt

        # Remove unsupported parameters
        kwargs.pop("response_format", None)
        kwargs.pop("response_mime_type", None)

        try:
            response = httpx.post(url, json=payload, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            return data["message"]["content"]
        except Exception as e:
            raise RuntimeError(f"Ollama request failed: {e}")


def get_llm_client(provider: str | None = None) -> LLMClient:
    """Returns the configured LLM client instance."""
    prov = provider or settings.llm_provider or os.getenv("LLM_PROVIDER", "groq")
    prov = prov.strip().lower()

    if prov == "groq":
        return GroqClient()
    elif prov == "gemini":
        return GeminiClient()
    elif prov == "openai":
        return OpenAIClient()
    elif prov == "anthropic":
        return AnthropicClient()
    elif prov == "ollama":
        return OllamaClient()
    else:
        raise ValueError(f"Unsupported LLM provider: {prov}")
=======
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


def _is_placeholder(value: str) -> bool:
    """Return True if a value looks like an unfilled .env placeholder."""
    return not value or value.startswith("your_")


def get_llm_client() -> BaseLLMClient:
    """Return an LLM client for the configured provider.

    Resolution order:
    1. If ``LLM_PROVIDER`` is explicitly set and its credentials exist → use it.
    2. Otherwise try Groq → Gemini → OpenAI → Ollama in priority order.
    3. If nothing is configured → raise ``LLMConfigError``.

    Returns:
        A concrete ``BaseLLMClient`` subclass instance.

    Raises:
        LLMConfigError: If no provider has valid credentials.
    """
    settings = get_settings()
    explicit = settings.llm_provider.lower().strip()

    # Priority list with explicit choice first.
    priority = ["groq", "gemini", "openai", "ollama"]
    if explicit in priority:
        priority.remove(explicit)
        priority.insert(0, explicit)

    for provider in priority:
        client = _try_build(provider, settings)
        if client is not None:
            logger.info("LLM provider resolved: %s", provider)
            return client

    raise LLMConfigError(
        "No LLM provider configured. Set at least one of: "
        "GROQ_API_KEY, GOOGLE_API_KEY, OPENAI_API_KEY, or configure Ollama. "
        "See .env.example for details."
    )


def _try_build(provider: str, settings) -> BaseLLMClient | None:  # noqa: ANN001
    """Attempt to build a client for *provider*. Returns None if credentials missing."""
    if provider == "groq" and not _is_placeholder(settings.groq_api_key):
        return GroqClient(settings.groq_api_key, settings.groq_model)
    if provider == "gemini" and not _is_placeholder(settings.google_api_key):
        return GeminiClient(settings.google_api_key, settings.gemini_model)
    if provider == "openai" and not _is_placeholder(settings.openai_api_key):
        return OpenAIClient(settings.openai_api_key)
    if provider == "ollama":
        return OllamaClient(settings.ollama_base_url, settings.ollama_model)
    return None


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
>>>>>>> b4b919a (feat: implement profile creation API with JSON and PDF resume parsing support)
