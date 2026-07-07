"""
Unified LLM Client for HireFlow AI.

Supports Groq, Gemini, OpenAI, and Ollama.
Generates structured JSON output from prompt input.
"""

import json
import logging
from typing import Any, Dict
import httpx
from openai import OpenAI
from groq import Groq
import google.generativeai as genai

from src.config.settings import settings

logger = logging.getLogger(__name__)


class LLMClient:
    """A unified LLM client that supports Groq, Gemini, OpenAI, and Ollama."""

    def __init__(self) -> None:
        self.provider = settings.llm_provider.lower()

    def generate_json(self, prompt: str, schema_prompt: str) -> Dict[str, Any]:
        """Generates structured JSON output from the LLM based on the prompt.

        Args:
            prompt: The user prompt or text to analyze.
            schema_prompt: Instructions detailing the required JSON schema format.

        Returns:
            A dictionary parsed from the LLM's JSON response.
        """
        full_prompt = f"{prompt}\n\n{schema_prompt}"

        if self.provider == "groq":
            return self._call_groq(full_prompt)
        elif self.provider == "gemini":
            return self._call_gemini(full_prompt)
        elif self.provider == "openai":
            return self._call_openai(full_prompt)
        elif self.provider == "ollama":
            return self._call_ollama(full_prompt)
        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")

    def _call_groq(self, prompt: str) -> Dict[str, Any]:
        if not settings.groq_api_key:
            raise ValueError("GROQ_API_KEY is not set in environment settings")

        client = Groq(api_key=settings.groq_api_key)
        model = settings.groq_model

        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": "You are a precise resume parser. Output JSON ONLY. Do not write markdown blocks or any text outside of the JSON structure.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            model=model,
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        content = chat_completion.choices[0].message.content
        if not content:
            raise ValueError("Groq returned an empty response")
        return json.loads(content)

    def _call_gemini(self, prompt: str) -> Dict[str, Any]:
        if not settings.google_api_key:
            raise ValueError("GOOGLE_API_KEY is not set in environment settings")

        genai.configure(api_key=settings.google_api_key)
        model = genai.GenerativeModel(
            settings.gemini_model,
            generation_config={"response_mime_type": "application/json"},
        )
        response = model.generate_content(prompt)
        content = response.text
        if not content:
            raise ValueError("Gemini returned an empty response")
        return json.loads(content)

    def _call_openai(self, prompt: str) -> Dict[str, Any]:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not set in environment settings")

        client = OpenAI(api_key=settings.openai_api_key)
        model = settings.openai_model

        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": "You are a precise resume parser. Output JSON ONLY.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            model=model,
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        content = chat_completion.choices[0].message.content
        if not content:
            raise ValueError("OpenAI returned an empty response")
        return json.loads(content)

    def _call_ollama(self, prompt: str) -> Dict[str, Any]:
        url = f"{settings.ollama_base_url}/api/chat"
        payload = {
            "model": settings.ollama_model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a precise resume parser. Output JSON ONLY. Do not write markdown blocks or any text outside of the JSON structure.",
                },
                {"role": "user", "content": prompt},
            ],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.0},
        }
        with httpx.Client(timeout=60.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            content = data["message"]["content"]
            if not content:
                raise ValueError("Ollama returned an empty response")
            return json.loads(content)
