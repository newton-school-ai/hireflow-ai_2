"""
Configuration settings for HireFlow AI.

Loads variables from .env and environment.
"""

from enum import Enum

from pydantic_settings import BaseSettings, SettingsConfigDict


class ApplicationMode(str, Enum):
    INTERNSHIP = "internship"
    JOB = "job"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # General App Config
    app_env: str = "development"
    debug: bool = True
    secret_key: str = "change_this_to_a_random_secret_string"
    allowed_origins: str = "http://localhost:3000"
    database_url: str = "postgresql://postgres:password@localhost:5432/hireflow"

    # LLM Settings
    llm_provider: str = "groq"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    faiss_index_dir: str = "./data/faiss_index"

    # Agent Settings
    spam_threshold: float = 0.7

    # Groq
    groq_api_key: str | None = None
    groq_model: str = "llama3-8b-8192"

    # Google Gemini
    google_api_key: str | None = None
    gemini_model: str = "gemini-1.5-flash"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"

    # OpenAI
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    # Anthropic
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-3-haiku-20240307"

    # File Storage
    storage_backend: str = "local"
    local_storage_path: str = "./data"

    # Other API Keys
    tavily_api_key: str | None = None
    sendgrid_api_key: str | None = None
    from_email: str = "hireflow@yourdomain.com"
    next_public_api_url: str = "http://localhost:8000"


settings = Settings()
