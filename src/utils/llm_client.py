"""
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
