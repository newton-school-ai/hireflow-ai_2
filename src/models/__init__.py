"""
HireFlow AI database models.

Re-exports all SQLAlchemy models and the shared Base for convenient imports:

    from src.models import Base, User, Job, Application, PrepGuide, WeeklyReport
"""

from src.config.database import Base
from src.models.application import Application
from src.models.job import Job
from src.models.prep_guide import PrepGuide
from src.models.report import WeeklyReport
from src.models.user import User

__all__ = [
    "Base",
    "Application",
    "Job",
    "PrepGuide",
    "User",
    "WeeklyReport",
]
