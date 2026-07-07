"""
Configuration settings for HireFlow AI.

Loads variables from .env and environment.
"""

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # General App Config
    app_env: str = Field(default="development", alias="APP_ENV")
    debug: bool = Field(default=True, alias="DEBUG")
    secret_key: str = Field(
        default="change_this_to_a_random_secret_string", alias="SECRET_KEY"
    )
    allowed_origins: str = Field(
        default="http://localhost:3000", alias="ALLOWED_ORIGINS"
    )

    # Database
    database_url: str = Field(alias="DATABASE_URL")

    # LLM Provider Configuration
    llm_provider: str = Field(default="groq", alias="LLM_PROVIDER")

    # Groq
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_model: str = Field(default="llama-3.1-8b-instant", alias="GROQ_MODEL")

    # Gemini
    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    gemini_model: str = Field(default="", alias="GEMINI_MODEL")

    # OpenAI
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")

    # Ollama
    ollama_base_url: str = Field(default="", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="", alias="OLLAMA_MODEL")

    # Anthropic
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")

    # File Storage
    storage_backend: str = Field(default="local", alias="STORAGE_BACKEND")
    local_storage_path: str = Field(default="./data", alias="LOCAL_STORAGE_PATH")

    # Other API Keys
    tavily_api_key: str | None = Field(default=None, alias="TAVILY_API_KEY")
    sendgrid_api_key: str | None = Field(default=None, alias="SENDGRID_API_KEY")
    from_email: str = Field(default="hireflow@yourdomain.com", alias="FROM_EMAIL")
    next_public_api_url: str = Field(
        default="http://localhost:8000", alias="NEXT_PUBLIC_API_URL"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
