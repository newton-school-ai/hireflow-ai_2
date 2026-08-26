"""
Health check test for the HireFlow API.

Verifies the root endpoint (GET /) returns the expected status response.
This is the baseline smoke test — if this fails, the API isn't starting at all.

This test uses httpx.AsyncClient with ASGITransport to test the FastAPI app
directly in-process, without starting a real server. This is faster than
spawning a subprocess and avoids port conflicts in CI.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app


@pytest.mark.asyncio
async def test_root_returns_ok():
    """GET / should return 200 with {"status": "ok"}."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
