## What does this PR do?
This PR implements the initial database schema for HireFlow AI using SQLAlchemy models and Alembic. It introduces the core database tables required by the application, including users, jobs, applications, prep guides, and weekly reports, along with the initial migration to create the schema on a fresh database.

## Related Issue
Closes #3

## Milestone
M1 - Project Scaffold and User Onboarding

## Changes Made
- Added `src/config/database.py` for SQLAlchemy engine and session management.
- Added SQLAlchemy models:
  - `src/models/user.py`
  - `src/models/job.py`
  - `src/models/application.py`
  - `src/models/prep_guide.py`
  - `src/models/report.py`
- Updated `src/models/__init__.py` to export models.
- Added Alembic configuration (`alembic.ini` and `migrations/`).
- Created the initial migration (`migrations/versions/001_initial_schema.py`).
- Added `tests/test_models.py` covering models, relationships, constraints, and CRUD operations.

## How did you test this?

- [x] Ran existing tests: `pytest`
- [x] Added new tests for new functionality
- [x] Manually tested with:

```bash
pytest -v
black --check src tests
ruff check src tests

alembic upgrade head
psql hireflow -c "\dt"
psql hireflow -c "\d users"

alembic downgrade -1
alembic upgrade head
```

## Key Design Decisions
- Used SQLAlchemy ORM to provide a maintainable, object-oriented schema definition.
- Used Alembic migrations to version database schema changes and ensure reproducible deployments.
- Used UUID primary keys for globally unique identifiers.
- Used JSONB columns for flexible profile and skill-related data without excessive normalization.
- Added foreign key constraints and relationships to maintain referential integrity.
- Added indexes and unique constraints on frequently queried fields such as email and application URLs.

## Defense Readiness
- [x] I can explain every function I wrote
- [x] I can explain why I chose this approach over alternatives
- [x] I can answer the defense questions listed in the issue
- [x] I have NOT hardcoded any API keys or secrets
- [x] I updated `requirements.txt` if I added new packages

## Screenshots / Output (if applicable)
Ran ``` bash 
pytest -v ```
![alt text](<Screenshot 2026-07-03 at 11.20.45 AM.png>)

Ran ```bash
black --check src tests
ruff check src tests ```
![alt text](<Screenshot 2026-07-03 at 11.21.08 AM.png>)

Ran ```bash
alembic upgrade head ```
![alt text](<Screenshot 2026-07-03 at 11.21.28 AM.png>)

Ran ```bash
psql hireflow -c "\dt" ```
![alt text](<Screenshot 2026-07-03 at 11.22.00 AM.png>)

Ran ```bash
psql hireflow -c "\d users" ```
![alt text](<Screenshot 2026-07-03 at 11.22.17 AM.png>)

Ran ```bash
alembic downgrade -1 ```
![alt text](<Screenshot 2026-07-03 at 11.22.46 AM.png>)

Ran ```bash
alembic upgrade head ```
![alt text](<Screenshot 2026-07-03 at 11.22.56 AM.png>)