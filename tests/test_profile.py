"""
Tests for HireFlow profile API routes.

Uses an in-memory SQLite database and test client to test:
- POST /profile (JSON mode)
- POST /profile (Multipart file mode with LLM mock)
- GET /profile/{user_id}
"""

import uuid
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.config.database import Base, get_db
from src.models.user import User

TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture(scope="module")
def engine():
    """Create in-memory SQLite engine for tests."""
    eng = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def db_session(engine):
    """Yield a transactional session that rolls back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()

    # Override get_db dependency
    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    yield session

    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_profile_json_internship(db_session):
    """POST /profile (JSON) creates an internship profile successfully."""
    payload = {
        "name": "Jane Doe",
        "email": "jane.doe@example.com",
        "skills": ["Python", "FastAPI"],
        "mode": "internship",
        "weekly_quota": 8,
        "target_roles": ["Software Engineer Intern"],
        "preferred_locations": ["Remote", "New York"],
        "min_stipend": 2000,
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/profile",
            json=payload,
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Jane Doe"
    assert data["email"] == "jane.doe@example.com"
    assert data["mode"] == "internship"
    assert data["weekly_quota"] == 8
    assert data["confirmation_mode"] == "batch"  # defaults to batch
    assert data["master_profile"]["skills"] == ["Python", "FastAPI"]
    assert data["master_profile"]["min_stipend"] == 2000

    # Verify database entry
    user = db_session.query(User).filter(User.email == "jane.doe@example.com").first()
    assert user is not None
    assert user.name == "Jane Doe"


@pytest.mark.asyncio
async def test_create_profile_json_job(db_session):
    """POST /profile (JSON) creates a job profile successfully."""
    payload = {
        "name": "Alice Smith",
        "email": "alice@example.com",
        "skills": ["Go", "Kubernetes"],
        "mode": "job",
        "weekly_quota": 5,
        "target_roles": ["DevOps Engineer"],
        "preferred_locations": ["San Francisco"],
        "min_stipend": None,
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/profile",
            json=payload,
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Alice Smith"
    assert data["mode"] == "job"
    assert data["weekly_quota"] == 5


@pytest.mark.asyncio
async def test_create_profile_validation_errors(db_session):
    """POST /profile (JSON) returns 400 / 422 for invalid inputs."""
    # Invalid mode
    payload = {
        "name": "Bob",
        "email": "bob@example.com",
        "skills": [],
        "mode": "freelancer",  # invalid mode
        "weekly_quota": 5,
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/profile",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
    # FastAPI returns 400 (our route logic wrapper) or 422 validation error
    assert response.status_code in (400, 422)


@pytest.mark.asyncio
async def test_create_profile_duplicate_email(db_session):
    """POST /profile returns 400 if user email already exists."""
    user = User(
        name="Existing User",
        email="existing@example.com",
        mode="job",
        weekly_quota=5,
    )
    db_session.add(user)
    db_session.commit()

    payload = {
        "name": "Another User",
        "email": "existing@example.com",
        "skills": [],
        "mode": "job",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/profile",
            json=payload,
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


@pytest.mark.asyncio
@patch("src.api.routes.profile.extract_text_from_pdf")
@patch("src.utils.llm_client.LLMClient.generate_json")
async def test_create_profile_multipart(
    mock_generate_json, mock_extract_text, db_session
):
    """POST /profile (Multipart) extracts PDF text and calls LLM client successfully."""
    mock_extract_text.return_value = "Candidate Resume Text Content"
    mock_generate_json.return_value = {
        "name": "Robert Brown",
        "email": "robert.brown@example.com",
        "skills": ["Java", "Spring Boot", "SQL"],
        "mode": "job",
        "weekly_quota": 5,
        "target_roles": ["Java Developer"],
        "preferred_locations": ["Austin", "Remote"],
        "min_stipend": 5000,
    }

    files = {
        "file": ("resume.pdf", b"%PDF-1.4 dummy binary content", "application/pdf")
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/profile",
            files=files,
        )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Robert Brown"
    assert data["email"] == "robert.brown@example.com"
    assert data["mode"] == "job"
    assert data["master_profile"]["skills"] == ["Java", "Spring Boot", "SQL"]

    mock_extract_text.assert_called_once()
    mock_generate_json.assert_called_once()


@pytest.mark.asyncio
async def test_get_profile_by_id(db_session):
    """GET /profile/{user_id} fetches the profile correctly."""
    user = User(
        id=uuid.uuid4(),
        name="Charlie Green",
        email="charlie@example.com",
        mode="job",
        weekly_quota=10,
        master_profile={"skills": ["C++", "Python"]},
    )
    db_session.add(user)
    db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/profile/{user.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(user.id)
    assert data["name"] == "Charlie Green"
    assert data["master_profile"]["skills"] == ["C++", "Python"]


@pytest.mark.asyncio
async def test_get_profile_not_found(db_session):
    """GET /profile/{user_id} returns 404 if profile doesn't exist."""
    random_id = uuid.uuid4()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/profile/{random_id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"
