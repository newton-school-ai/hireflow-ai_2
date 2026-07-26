"""
Unified LLM client for HireFlow AI.
"""

import json
import logging
from abc import ABC, abstractmethod

from src.config.settings import settings

logger = logging.getLogger(__name__)


class LLMConfigError(ValueError):
    """Raised when no LLM provider is properly configured."""


class BaseLLMClient(ABC):
    """Abstract base for all LLM provider clients."""

    @abstractmethod
    def chat(self, prompt: str) -> str:
        """Send a prompt and return the raw text response."""

    @abstractmethod
    def extract(self, prompt: str) -> dict:
        """Send a prompt optimized for structured extraction."""


def parse_llm_json(raw: str) -> str:
    """Strip markdown code fences."""
    text = raw.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
    if text.endswith("```"):
        text = text[: -len("```")]
    return text.strip()


class GroqClient(BaseLLMClient):
    def __init__(self, api_key: str, model: str) -> None:
        if not api_key or api_key.startswith("your_"):
            raise LLMConfigError("GROQ_API_KEY is missing or invalid.")
        self._api_key = api_key
        self._model = model

    def chat(self, prompt: str) -> str:
        from groq import Groq

        try:
            client = Groq(api_key=self._api_key)
            response = client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"Groq API error: {e}")
            raise RuntimeError("Groq API call failed")

    def extract(self, prompt: str) -> dict:
        raw = self.chat(prompt)
        text = parse_llm_json(raw)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text


class GeminiClient(BaseLLMClient):
    def __init__(self, api_key: str, model: str) -> None:
        if not api_key or api_key.startswith("your_"):
            raise LLMConfigError("GOOGLE_API_KEY is missing or invalid.")
        self._api_key = api_key
        self._model = model

    def chat(self, prompt: str) -> str:
        import google.generativeai as genai

        try:
            genai.configure(api_key=self._api_key)
            model = genai.GenerativeModel(self._model)
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            raise RuntimeError("Gemini API call failed")

    def extract(self, prompt: str) -> dict:
        raw = self.chat(prompt)
        text = parse_llm_json(raw)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text


class OpenAIClient(BaseLLMClient):
    def __init__(self, api_key: str, model: str) -> None:
        if not api_key or api_key.startswith("your_"):
            raise LLMConfigError("OPENAI_API_KEY is missing or invalid.")
        self._api_key = api_key
        self._model = model

    def chat(self, prompt: str) -> str:
        from openai import OpenAI

        try:
            client = OpenAI(api_key=self._api_key)
            response = client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise RuntimeError("OpenAI API call failed")

    def extract(self, prompt: str) -> dict:
        raw = self.chat(prompt)
        text = parse_llm_json(raw)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text


class AnthropicClient(BaseLLMClient):
    def __init__(self, api_key: str, model: str) -> None:
        if not api_key or api_key.startswith("your_"):
            raise LLMConfigError("ANTHROPIC_API_KEY is missing or invalid.")
        self._api_key = api_key
        self._model = model

    def chat(self, prompt: str) -> str:
        from anthropic import Anthropic

        try:
            client = Anthropic(api_key=self._api_key)
            response = client.messages.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
                temperature=0.1,
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            raise RuntimeError("Anthropic API call failed")

    def extract(self, prompt: str) -> dict:
        raw = self.chat(prompt)
        text = parse_llm_json(raw)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text


class OllamaClient(BaseLLMClient):
    def __init__(self, base_url: str, model: str) -> None:
        if not base_url:
            raise LLMConfigError("OLLAMA_BASE_URL is missing.")
        self._base_url = base_url
        self._model = model

    def chat(self, prompt: str) -> str:
        import requests

        try:
            response = requests.post(
                f"{self._base_url}/api/generate",
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1},
                },
                timeout=60,
            )
            response.raise_for_status()
            return response.json().get("response", "")
        except Exception as e:
            logger.error(f"Ollama API error: {e}")
            raise RuntimeError("Ollama API call failed")

    def extract(self, prompt: str) -> dict:
        raw = self.chat(prompt)
        text = parse_llm_json(raw)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text


def get_llm_client() -> BaseLLMClient:
    provider = settings.llm_provider.lower().strip()

    if provider == "groq":
        return GroqClient(settings.groq_api_key, settings.groq_model)
    elif provider == "gemini":
        return GeminiClient(settings.google_api_key, settings.gemini_model)
    elif provider == "openai":
        return OpenAIClient(settings.openai_api_key, settings.openai_model)
    elif provider == "anthropic":
        return AnthropicClient(settings.anthropic_api_key, settings.anthropic_model)
    elif provider == "ollama":
        return OllamaClient(settings.ollama_base_url, settings.ollama_model)
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")
