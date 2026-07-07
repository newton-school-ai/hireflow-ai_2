"""
FastAPI application entry point for HireFlow AI.

Registers all API routers and provides the health check endpoint.

Usage:
    uvicorn src.api.main:app --reload
"""

from fastapi import FastAPI
from src.api.routes.profile import router as profile_router

app = FastAPI(
    title="HireFlow AI",
    description="AI-powered job application automation platform.",
    version="0.1.0",
)

# -- Register routers --
app.include_router(profile_router)


@app.get("/", tags=["Health"])
def health_check():
    """Root health check endpoint."""
    return {"status": "ok"}
