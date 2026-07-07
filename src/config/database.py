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
