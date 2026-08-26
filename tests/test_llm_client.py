from unittest.mock import MagicMock, patch

import pytest

from src.config.settings import Settings
from src.utils.llm_client import (
    AnthropicClient,
    GeminiClient,
    GroqClient,
    LLMConfigError,
    OllamaClient,
    OpenAIClient,
    get_llm_client,
    parse_llm_json,
)


@pytest.fixture
def mock_settings():
    return Settings(
        llm_provider="groq",
        groq_api_key="test_groq",
        google_api_key="test_gemini",
        openai_api_key="test_openai",
        anthropic_api_key="test_anthropic",
        ollama_base_url="http://test_ollama",
    )


def test_get_llm_client_groq(mock_settings):
    with patch("src.utils.llm_client.settings", mock_settings):
        mock_settings.llm_provider = "groq"
        client = get_llm_client()
        assert isinstance(client, GroqClient)


def test_get_llm_client_gemini(mock_settings):
    with patch("src.utils.llm_client.settings", mock_settings):
        mock_settings.llm_provider = "gemini"
        client = get_llm_client()
        assert isinstance(client, GeminiClient)


def test_get_llm_client_openai(mock_settings):
    with patch("src.utils.llm_client.settings", mock_settings):
        mock_settings.llm_provider = "openai"
        client = get_llm_client()
        assert isinstance(client, OpenAIClient)


def test_get_llm_client_anthropic(mock_settings):
    with patch("src.utils.llm_client.settings", mock_settings):
        mock_settings.llm_provider = "anthropic"
        client = get_llm_client()
        assert isinstance(client, AnthropicClient)


def test_get_llm_client_ollama(mock_settings):
    with patch("src.utils.llm_client.settings", mock_settings):
        mock_settings.llm_provider = "ollama"
        client = get_llm_client()
        assert isinstance(client, OllamaClient)


def test_get_llm_client_unsupported(mock_settings):
    with patch("src.utils.llm_client.settings", mock_settings):
        mock_settings.llm_provider = "unknown"
        with pytest.raises(ValueError, match="Unsupported LLM provider: unknown"):
            get_llm_client()


def test_missing_api_key_raises_value_error():
    with pytest.raises(LLMConfigError, match="GROQ_API_KEY is missing or invalid"):
        GroqClient(api_key="", model="test")

    with pytest.raises(LLMConfigError, match="GOOGLE_API_KEY is missing or invalid"):
        GeminiClient(api_key="", model="test")

    with pytest.raises(LLMConfigError, match="OPENAI_API_KEY is missing or invalid"):
        OpenAIClient(api_key="", model="test")

    with pytest.raises(LLMConfigError, match="ANTHROPIC_API_KEY is missing or invalid"):
        AnthropicClient(api_key="", model="test")

    with pytest.raises(LLMConfigError, match="OLLAMA_BASE_URL is missing"):
        OllamaClient(base_url="", model="test")


# Test Chat and Extract for Groq
@patch("groq.Groq")
def test_groq_client_chat_and_extract(mock_groq_class):
    mock_instance = mock_groq_class.return_value
    mock_response = MagicMock()
    mock_response.choices[0].message.content = '{"name": "Test"}'
    mock_instance.chat.completions.create.return_value = mock_response

    client = GroqClient(api_key="test", model="test")

    # Test chat
    chat_result = client.chat("hello")
    assert chat_result == '{"name": "Test"}'

    # Test extract
    extract_result = client.extract("hello")
    assert extract_result == {"name": "Test"}


# Test Chat and Extract for Gemini
@patch("google.generativeai.GenerativeModel")
@patch("google.generativeai.configure")
def test_gemini_client_chat_and_extract(mock_configure, mock_model_class):
    mock_model_instance = mock_model_class.return_value
    mock_response = MagicMock()
    mock_response.text = '```json\n{"name": "Test"}\n```'
    mock_model_instance.generate_content.return_value = mock_response

    client = GeminiClient(api_key="test", model="test")

    # Test chat
    chat_result = client.chat("hello")
    assert chat_result == '```json\n{"name": "Test"}\n```'

    # Test extract
    extract_result = client.extract("hello")
    assert extract_result == {"name": "Test"}


# Test Chat and Extract for OpenAI
@patch("openai.OpenAI")
def test_openai_client_chat_and_extract(mock_openai_class):
    mock_instance = mock_openai_class.return_value
    mock_response = MagicMock()
    mock_response.choices[0].message.content = '{"name": "Test"}'
    mock_instance.chat.completions.create.return_value = mock_response

    client = OpenAIClient(api_key="test", model="test")

    # Test chat
    chat_result = client.chat("hello")
    assert chat_result == '{"name": "Test"}'

    # Test extract
    extract_result = client.extract("hello")
    assert extract_result == {"name": "Test"}


# Test Chat and Extract for Anthropic
@patch("anthropic.Anthropic")
def test_anthropic_client_chat_and_extract(mock_anthropic_class):
    mock_instance = mock_anthropic_class.return_value
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"name": "Test"}')]
    mock_instance.messages.create.return_value = mock_response

    client = AnthropicClient(api_key="test", model="test")

    # Test chat
    chat_result = client.chat("hello")
    assert chat_result == '{"name": "Test"}'

    # Test extract
    extract_result = client.extract("hello")
    assert extract_result == {"name": "Test"}


# Test Chat and Extract for Ollama
@patch("requests.post")
def test_ollama_client_chat_and_extract(mock_post):
    mock_response = MagicMock()
    mock_response.json.return_value = {"response": '{"name": "Test"}'}
    mock_response.raise_for_status.return_value = None
    mock_post.return_value = mock_response

    client = OllamaClient(base_url="http://test", model="test")

    # Test chat
    chat_result = client.chat("hello")
    assert chat_result == '{"name": "Test"}'

    # Test extract
    extract_result = client.extract("hello")
    assert extract_result == {"name": "Test"}


def test_parse_llm_json():
    # Test stripping code fences
    raw = '```json\n{"key": "value"}\n```'
    assert parse_llm_json(raw) == '{"key": "value"}'

    raw2 = '```\n{"key": "value"}\n```'
    assert parse_llm_json(raw2) == '{"key": "value"}'

    raw3 = '{"key": "value"}'
    assert parse_llm_json(raw3) == '{"key": "value"}'
