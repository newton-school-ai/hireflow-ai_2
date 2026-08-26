"""
Unit and integration tests for the Profile and Onboarding API.
"""

import io
import uuid
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.config.database import Base, get_db
from src.models.user import User

TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="module")
def test_engine():
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def db_session(test_engine):
    connection = test_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()

    yield session

    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


@pytest.fixture()
def client(db_session):
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_profile_json_success(client, db_session):
    """POST /profile with valid JSON should create a user and return the profile."""
    payload = {
        "name": "Test Student",
        "email": "test@example.com",
        "skills": ["Python", "FastAPI"],
        "mode": "internship",
        "weekly_quota": 5,
        "target_roles": ["AI Engineer"],
        "preferred_locations": ["Remote"],
    }
    response = await client.post("/profile", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["name"] == "Test Student"
    assert data["email"] == "test@example.com"
    assert data["mode"] == "internship"
    assert data["weekly_quota"] == 5
    assert data["confirmation_mode"] == "batch"
    assert data["master_profile"]["skills"] == ["Python", "FastAPI"]

    # Verify in DB
    db_user = db_session.query(User).filter(User.email == "test@example.com").first()
    assert db_user is not None
    assert db_user.name == "Test Student"


@pytest.mark.asyncio
async def test_create_profile_json_invalid_mode(client):
    """POST /profile with invalid mode should fail validation."""
    payload = {
        "name": "Test Student",
        "email": "test@example.com",
        "mode": "invalid_mode",  # Should only accept internship or job
    }
    response = await client.post("/profile", json=payload)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_profile_json_duplicate_email(client):
    """POST /profile with duplicate email should return a 409 error."""
    payload1 = {
        "name": "User One",
        "email": "dup@example.com",
        "mode": "job",
    }
    response1 = await client.post("/profile", json=payload1)
    assert response1.status_code == 200

    payload2 = {
        "name": "User Two",
        "email": "dup@example.com",
        "mode": "internship",
    }
    response2 = await client.post("/profile", json=payload2)
    assert response2.status_code == 409
    assert "Email already registered" in response2.text


@pytest.mark.asyncio
async def test_get_profile_success(client, db_session):
    """GET /profile/{user_id} should return the user profile."""
    # Seed user in DB
    user = User(
        name="Get User",
        email="get@example.com",
        mode="job",
        weekly_quota=10,
        confirmation_mode="individual",
        master_profile={"skills": ["Go", "Docker"]},
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    response = await client.get(f"/profile/{user.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Get User"
    assert data["email"] == "get@example.com"
    assert data["mode"] == "job"
    assert data["weekly_quota"] == 10
    assert data["confirmation_mode"] == "individual"


@pytest.mark.asyncio
async def test_get_profile_not_found(client):
    """GET /profile/{non_existent_uuid} should return 404."""
    non_existent = uuid.uuid4()
    response = await client.get(f"/profile/{non_existent}")
    assert response.status_code == 404


@pytest.mark.asyncio
@patch("src.api.routes.profile.get_llm_client")
@patch("pypdf.PdfReader")
async def test_create_profile_pdf_success(
    mock_pdf_reader, mock_get_llm, client, db_session
):
    """POST /profile with PDF upload should parse structured data using LLM."""
    # Mock PDF reader page extraction
    mock_page = MagicMock()
    mock_page.extract_text.return_value = (
        "Resume content for John Doe. Skills: Python, SQL."
    )
    mock_reader_instance = MagicMock()
    mock_reader_instance.pages = [mock_page]
    mock_pdf_reader.return_value = mock_reader_instance

    # Mock LLM response
    mock_client_instance = MagicMock()
    mock_client_instance.extract.return_value = {
        "name": "John Doe",
        "email": "john@example.com",
        "skills": ["Python", "SQL"],
        "experience": [
            {"company": "A Corp", "role": "Dev", "duration": "1 yr", "description": ""}
        ],
        "education": [],
        "projects": [],
    }
    mock_get_llm.return_value = mock_client_instance

    # Prepare dummy PDF upload
    pdf_data = b"%PDF-1.4 dummy content"
    files = {"file": ("resume.pdf", io.BytesIO(pdf_data), "application/pdf")}
    data = {"mode": "internship", "weekly_quota": "3", "confirmation_mode": "batch"}

    response = await client.post("/profile", data=data, files=files)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["name"] == "John Doe"
    assert res_data["email"] == "john@example.com"
    assert res_data["mode"] == "internship"
    assert res_data["weekly_quota"] == 3
    assert res_data["master_profile"]["skills"] == ["Python", "SQL"]

    # Verify in DB
    db_user = db_session.query(User).filter(User.email == "john@example.com").first()
    assert db_user is not None
    assert db_user.name == "John Doe"
