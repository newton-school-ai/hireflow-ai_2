"""
Database configuration for HireFlow AI.

Provides the SQLAlchemy engine, session factory, declarative base,
and a FastAPI-compatible dependency for database sessions.

Usage:
    from src.config.database import get_db, Base
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:password@localhost:5432/hireflow"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

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
