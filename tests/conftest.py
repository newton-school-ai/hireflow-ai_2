"""
Pytest configuration and global fixtures.

Sets up dummy environment variables for tests to prevent validation
errors during module import.
"""

import os

# Set a dummy PostgreSQL URL for test execution.
# This prevents database initialization/import crashes when tests run in CI
# or local environments without a PostgreSQL server configured.
# The tests themselves override the database session to use SQLite,
# so this engine is never actually connected to or queried.
os.environ["DATABASE_URL"] = "postgresql://test_user:test_pass@localhost:5432/test_db"
