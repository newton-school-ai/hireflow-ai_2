<<<<<<< HEAD
"""
Configuration settings for HireFlow AI.

Loads variables from .env and environment.
"""

from enum import Enum
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApplicationMode(str, Enum):
    INTERNSHIP = "internship"
    JOB = "job"


=======
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


>>>>>>> b4b919a (feat: implement profile creation API with JSON and PDF resume parsing support)
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
<<<<<<< HEAD
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

    # Anthropic
    anthropic_api_key: str | None = None

    # File Storage
    storage_backend: str = "local"
    local_storage_path: str = "./data"

    # Other API Keys
    tavily_api_key: str | None = None
    sendgrid_api_key: str | None = None
    from_email: str = "hireflow@yourdomain.com"
    next_public_api_url: str = "http://localhost:8000"


settings = Settings()
=======
    )

    # Database
    database_url: str = Field(alias="DATABASE_URL")

    # LLM
    llm_provider: str = Field(alias="LLM_PROVIDER")

    # Groq
    groq_api_key: str = Field(alias="GROQ_API_KEY")
    groq_model: str = Field(alias="GROQ_MODEL")

    # Gemini
    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    gemini_model: str = Field(default="", alias="GEMINI_MODEL")

    # OpenAI
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")

    # Ollama
    ollama_base_url: str = Field(default="", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="", alias="OLLAMA_MODEL")

    # App
    app_env: str = Field(default="development", alias="APP_ENV")
    debug: bool = Field(default=True, alias="DEBUG")


@lru_cache
def get_settings() -> Settings:
    return Settings()
>>>>>>> b4b919a (feat: implement profile creation API with JSON and PDF resume parsing support)
