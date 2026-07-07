"""
Tests for the Profile API (Issue #4).

Uses an in-memory SQLite database and mocks all LLM interactions.
No real API calls are made during testing.

Coverage targets:
  - POST /profile (JSON): valid, invalid mode, duplicate email, missing fields
  - POST /profile/upload (PDF): valid, empty, invalid, LLM invalid JSON, missing email
  - GET /profile/{user_id}: existing, missing
  - Response schema validation
  - master_profile structure validation
"""

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.config.database import Base, get_db

# ---------------------------------------------------------------------------
# Test database setup — in-memory SQLite
# ---------------------------------------------------------------------------
# StaticPool ensures every connection shares the same in-memory database.
# Without it, SQLite ':memory:' creates a new empty DB per connection,
# which causes "no such table" errors across sessions.

TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# SQLite does not enforce FK constraints by default. Enable them.
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def override_get_db():
    """Yield a test database session backed by SQLite."""
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


# Override the production DB dependency with our SQLite test DB.
app.dependency_overrides[get_db] = override_get_db

# Create all tables once at module import time.
Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_tables():
    """Truncate all tables between tests to avoid state leakage."""
    yield
    db = TestSessionLocal()
    for table in reversed(Base.metadata.sorted_tables):
        db.execute(table.delete())
    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_JSON_PROFILE = {
    "name": "Test Student",
    "email": "test@example.com",
    "mode": "internship",
    "skills": ["Python", "FastAPI"],
    "weekly_quota": 5,
    "target_roles": ["AI Engineer"],
    "preferred_locations": ["Remote"],
    "min_stipend": 15000,
}

MOCK_LLM_RESPONSE = json.dumps(
    {
        "name": "Resume User",
        "email": "resume@example.com",
        "phone": "+91-9876543210",
        "skills": ["Python", "Machine Learning", "FastAPI"],
        "education": [
            {
                "degree": "B.Tech Computer Science",
                "institution": "IIT Delhi",
                "year": "2024",
            }
        ],
        "experience": [
            {
                "title": "ML Intern",
                "company": "TechCorp",
                "duration": "3 months",
                "description": "Built recommendation systems.",
            }
        ],
        "projects": [
            {
                "name": "HireFlow",
                "description": "AI job application platform",
                "technologies": ["Python", "FastAPI", "LangGraph"],
            }
        ],
        "certifications": ["AWS Cloud Practitioner"],
        "languages": ["English", "Hindi"],
        "links": {
            "github": "https://github.com/testuser",
            "linkedin": "https://linkedin.com/in/testuser",
            "portfolio": "",
        },
        "target_roles": ["ML Engineer", "AI Engineer"],
        "preferred_locations": ["Bangalore", "Remote"],
    }
)


def _make_test_pdf() -> bytes:
    """Create a minimal valid PDF with some text using PyMuPDF.

    Returns:
        Raw bytes of a single-page PDF containing sample resume text.
    """
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (72, 72),
        "John Doe\njohn@example.com\nPython, FastAPI, ML\n" "B.Tech CS, IIT Delhi 2024",
        fontsize=12,
    )
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


# ---------------------------------------------------------------------------
# POST /profile — JSON tests
# ---------------------------------------------------------------------------


class TestPostJsonProfile:
    """Tests for POST /profile with JSON body."""

    @pytest.mark.asyncio
    async def test_create_profile_success(self):
        """Valid JSON payload should create a user and return 201."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/profile", json=VALID_JSON_PROFILE)

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Student"
        assert data["email"] == "test@example.com"
        assert data["mode"] == "internship"
        assert data["weekly_quota"] == 5
        assert data["master_profile"] is not None
        assert "Python" in data["master_profile"]["skills"]
        assert data["master_profile"]["min_stipend"] == 15000

    @pytest.mark.asyncio
    async def test_create_profile_invalid_mode(self):
        """Invalid mode value should return 422."""
        payload = {**VALID_JSON_PROFILE, "mode": "freelance", "email": "m@test.com"}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/profile", json=payload)

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_profile_duplicate_email(self):
        """Posting the same email twice should return 409."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp1 = await client.post("/profile", json=VALID_JSON_PROFILE)
            assert resp1.status_code == 201

            resp2 = await client.post("/profile", json=VALID_JSON_PROFILE)
            assert resp2.status_code == 409
            assert "already exists" in resp2.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_profile_missing_name(self):
        """Missing required field 'name' should return 422."""
        payload = {k: v for k, v in VALID_JSON_PROFILE.items() if k != "name"}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/profile", json=payload)

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_profile_job_mode(self):
        """Mode 'job' should be accepted."""
        payload = {**VALID_JSON_PROFILE, "mode": "job", "email": "job@test.com"}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/profile", json=payload)

        assert response.status_code == 201
        assert response.json()["mode"] == "job"

    @pytest.mark.asyncio
    async def test_response_schema_fields(self):
        """Response should contain all expected fields."""
        payload = {**VALID_JSON_PROFILE, "email": "schema@test.com"}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/profile", json=payload)

        assert response.status_code == 201
        data = response.json()
        expected_keys = {
            "id",
            "name",
            "email",
            "mode",
            "master_profile",
            "weekly_quota",
            "confirmation_mode",
            "created_at",
            "updated_at",
        }
        assert expected_keys.issubset(
            data.keys()
        ), f"Missing keys: {expected_keys - data.keys()}"

    @pytest.mark.asyncio
    async def test_master_profile_structure(self):
        """master_profile should have the forward-compatible structure."""
        payload = {**VALID_JSON_PROFILE, "email": "mp@test.com"}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/profile", json=payload)

        mp = response.json()["master_profile"]
        expected_keys = {
            "phone",
            "skills",
            "education",
            "experience",
            "projects",
            "certifications",
            "languages",
            "links",
            "target_roles",
            "preferred_locations",
            "min_stipend",
        }
        assert expected_keys.issubset(
            mp.keys()
        ), f"Missing master_profile keys: {expected_keys - mp.keys()}"


# ---------------------------------------------------------------------------
# GET /profile/{user_id} tests
# ---------------------------------------------------------------------------


class TestGetProfile:
    """Tests for GET /profile/{user_id}."""

    @pytest.mark.asyncio
    async def test_get_existing_profile(self):
        """GET an existing profile should return 200 with matching data."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            create_resp = await client.post(
                "/profile",
                json={**VALID_JSON_PROFILE, "email": "get@test.com"},
            )
            assert create_resp.status_code == 201
            user_id = create_resp.json()["id"]

            get_resp = await client.get(f"/profile/{user_id}")

        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["id"] == user_id
        assert data["email"] == "get@test.com"
        assert data["master_profile"]["skills"] == ["Python", "FastAPI"]

    @pytest.mark.asyncio
    async def test_get_missing_profile(self):
        """GET a non-existent user ID should return 404."""
        fake_id = str(uuid.uuid4())
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/profile/{fake_id}")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]


# ---------------------------------------------------------------------------
# POST /profile/upload — PDF tests
# ---------------------------------------------------------------------------


class TestPostPdfUpload:
    """Tests for POST /profile/upload with PDF file."""

    @pytest.mark.asyncio
    async def test_pdf_upload_success(self):
        """Valid PDF with mocked LLM should create profile and return 201."""
        pdf_bytes = _make_test_pdf()

        mock_client = AsyncMock()
        mock_client.generate = AsyncMock(return_value=MOCK_LLM_RESPONSE)

        with patch("src.api.routes.profile.get_llm_client", return_value=mock_client):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.post(
                    "/profile/upload",
                    files={"file": ("resume.pdf", pdf_bytes, "application/pdf")},
                    data={"mode": "internship"},
                )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Resume User"
        assert data["email"] == "resume@example.com"
        assert "Python" in data["master_profile"]["skills"]
        mock_client.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_pdf_upload_empty_file(self):
        """Empty file upload should return 400."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/profile/upload",
                files={"file": ("empty.pdf", b"", "application/pdf")},
                data={"mode": "internship"},
            )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_pdf_upload_invalid_pdf(self):
        """Non-PDF content should return 400."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/profile/upload",
                files={
                    "file": (
                        "bad.pdf",
                        b"this is not a pdf",
                        "application/pdf",
                    )
                },
                data={"mode": "internship"},
            )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_pdf_upload_llm_invalid_json(self):
        """LLM returning invalid JSON should return 422."""
        pdf_bytes = _make_test_pdf()

        mock_client = AsyncMock()
        mock_client.generate = AsyncMock(
            return_value="Sorry, I can't parse this resume."
        )

        with patch("src.api.routes.profile.get_llm_client", return_value=mock_client):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.post(
                    "/profile/upload",
                    files={"file": ("resume.pdf", pdf_bytes, "application/pdf")},
                    data={"mode": "internship"},
                )

        assert response.status_code == 422
        assert "unparseable" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_pdf_upload_llm_missing_email(self):
        """LLM extracting no email should return 400."""
        pdf_bytes = _make_test_pdf()
        no_email_response = json.dumps(
            {
                "name": "No Email Person",
                "email": "",
                "phone": "",
                "skills": ["Python"],
                "education": [],
                "experience": [],
                "projects": [],
                "certifications": [],
                "languages": [],
                "links": {"github": "", "linkedin": "", "portfolio": ""},
                "target_roles": [],
                "preferred_locations": [],
            }
        )

        mock_client = AsyncMock()
        mock_client.generate = AsyncMock(return_value=no_email_response)

        with patch("src.api.routes.profile.get_llm_client", return_value=mock_client):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.post(
                    "/profile/upload",
                    files={"file": ("resume.pdf", pdf_bytes, "application/pdf")},
                    data={"mode": "internship"},
                )

        assert response.status_code == 400
        assert "email" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_pdf_upload_invalid_mode(self):
        """Invalid mode on PDF upload should return 422."""
        pdf_bytes = _make_test_pdf()

        mock_client = AsyncMock()
        with patch("src.api.routes.profile.get_llm_client", return_value=mock_client):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.post(
                    "/profile/upload",
                    files={"file": ("resume.pdf", pdf_bytes, "application/pdf")},
                    data={"mode": "freelance"},
                )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_pdf_upload_duplicate_email(self):
        """Uploading two resumes with the same extracted email → 409."""
        pdf_bytes = _make_test_pdf()

        mock_client = AsyncMock()
        mock_client.generate = AsyncMock(return_value=MOCK_LLM_RESPONSE)

        with patch("src.api.routes.profile.get_llm_client", return_value=mock_client):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp1 = await client.post(
                    "/profile/upload",
                    files={"file": ("resume.pdf", pdf_bytes, "application/pdf")},
                    data={"mode": "internship"},
                )
                assert resp1.status_code == 201

                resp2 = await client.post(
                    "/profile/upload",
                    files={"file": ("resume.pdf", pdf_bytes, "application/pdf")},
                    data={"mode": "internship"},
                )
                assert resp2.status_code == 409


# ---------------------------------------------------------------------------
# Health check regression
# ---------------------------------------------------------------------------


class TestHealthCheck:
    """Ensure the root health check still works after router registration."""

    @pytest.mark.asyncio
    async def test_root_returns_ok(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
