"""
Database configuration for HireFlow AI.

Provides the SQLAlchemy engine, session factory, declarative base,
and a FastAPI-compatible dependency for database sessions.

Usage:
    from src.config.database import get_db, Base
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from src.config.settings import settings

<<<<<<< HEAD
DATABASE_URL = settings.database_url
=======
from src.config.settings import get_settings
>>>>>>> b4b919a (feat: implement profile creation API with JSON and PDF resume parsing support)

settings = get_settings()

if not settings.database_url:
    raise ValueError(
        "DATABASE_URL environment variable is not configured. "
        "Please set the DATABASE_URL environment variable or configure it in your .env file."
    )

engine = create_engine(settings.database_url, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Shared declarative base for all HireFlow models."""

    pass


def get_db():
    """FastAPI dependency that yields a database session.

    Ensures the session is closed after the request completes,
    even if an exception occurs.

    Yields:
        Session: A SQLAlchemy database session.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
