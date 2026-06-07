# Cowork Prompt: Scaffold HireFlow AI Project

Copy everything below the line and paste into Claude Cowork.

---

I want you to scaffold a new open-source project called **HireFlow AI** - an agentic job application and hiring assistant. This is a student team project for Newton School of Technology's Summer Profile Building Drive 2026. A pod of 5 students (1 Maintainer + 4 Contributors) will build it over 8 milestones using a GitHub-based workflow.

## Step 1: Create the Local Project Folder

Create a folder `hireflow-ai/` in my projects directory with this exact structure:

```
hireflow-ai/
+-- .github/
|   +-- ISSUE_TEMPLATE/
|   |   +-- milestone-task.md
|   |   +-- bug-report.md
|   |   +-- feature-request.md
|   +-- PULL_REQUEST_TEMPLATE.md
|   +-- workflows/
|       +-- ci.yml
+-- src/
|   +-- agents/
|   |   +-- __init__.py
|   |   +-- supervisor.py
|   |   +-- application_agent.py
|   |   +-- prep_guide_agent.py
|   |   +-- spam_filter.py
|   |   +-- company_intel_agent.py
|   |   +-- hiring_shortlist_agent.py
|   +-- scrapers/
|   |   +-- __init__.py
|   |   +-- lever_scraper.py
|   |   +-- greenhouse_scraper.py
|   |   +-- generic_scraper.py
|   +-- pipelines/
|   |   +-- __init__.py
|   |   +-- match_scorer.py
|   |   +-- embedding_pipeline.py
|   |   +-- resume_generator.py
|   +-- automation/
|   |   +-- __init__.py
|   |   +-- form_filler.py
|   |   +-- captcha_handler.py
|   +-- api/
|   |   +-- __init__.py
|   |   +-- main.py
|   |   +-- routes/
|   +-- models/
|   |   +-- __init__.py
|   |   +-- user.py
|   |   +-- job.py
|   |   +-- application.py
|   |   +-- prep_guide.py
|   +-- templates/
|   |   +-- resume_latex/
|   +-- utils/
|   |   +-- __init__.py
|   +-- config/
|       +-- __init__.py
+-- tests/
|   +-- __init__.py
|   +-- README.md
+-- notebooks/
|   +-- README.md
+-- data/
|   +-- README.md
+-- docs/
|   +-- architecture.md
|   +-- setup.md
|   +-- milestone-reports/
+-- frontend/
|   +-- README.md
+-- .env.example
+-- .gitignore
+-- requirements.txt
+-- Dockerfile
+-- docker-compose.yml
+-- README.md
+-- LICENSE
+-- CONTRIBUTING.md
```

## Step 2: Populate the Key Files

### `README.md`

Create a polished README with:
- Project title: **HireFlow AI**
- Tagline: "Your AI-powered career autopilot - discover jobs, tailor resumes, apply automatically, and get a custom prep guide for every application."
- Badges (placeholder): Python version, License, Build status, Contributors
- Overview section explaining the dual-purpose system (candidate side + hiring side)
- Features section listing: Job Discovery, Smart Match Scoring, Weekly Quota System, ATS Resume Tailoring, Application Automation, Preparation Guide Generator, Weekly Reports, Hiring Side Shortlister
- Architecture diagram (placeholder - note "see docs/architecture.md")
- Tech Stack table (LangGraph, Claude/OpenAI, Playwright, FAISS, FastAPI, React, PostgreSQL, LaTeX)
- Getting Started: clone, venv, requirements, .env setup
- Project Structure overview
- Contributing section pointing to CONTRIBUTING.md
- Pod Roles section (Maintainer + 4 Contributors with their owned modules)
- Milestone overview (M1 through M8)
- License

### `.gitignore`

Standard Python + Node + IDE gitignore:
- `__pycache__/`, `*.pyc`, `*.pyo`
- `.venv/`, `venv/`, `env/`
- `.env`, `.env.local`
- `node_modules/`, `dist/`, `build/`
- `.DS_Store`, `.idea/`, `.vscode/`
- `*.log`
- `data/raw/`, `data/processed/`
- `resumes/` (generated user resumes)
- `*.pdf` in root
- `.pytest_cache/`, `.coverage`, `htmlcov/`

### `requirements.txt`

```
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
langchain>=0.1.0
langgraph>=0.0.30
langchain-openai>=0.1.0
langchain-anthropic>=0.1.0
playwright>=1.42.0
beautifulsoup4>=4.12.0
requests>=2.31.0
faiss-cpu>=1.7.4
sentence-transformers>=2.5.0
openai>=1.12.0
anthropic>=0.18.0
psycopg2-binary>=2.9.9
sqlalchemy>=2.0.0
pydantic>=2.6.0
python-dotenv>=1.0.0
PyPDF2>=3.0.0
reportlab>=4.0.0
pylatex>=1.4.2
sendgrid>=6.11.0
tavily-python>=0.3.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
black>=24.0.0
ruff>=0.3.0
```

### `.env.example`

```
# LLM APIs
ANTHROPIC_API_KEY=your_anthropic_key_here
OPENAI_API_KEY=your_openai_key_here

# Database
DATABASE_URL=postgresql://user:password@localhost:5432/hireflow

# Email
SENDGRID_API_KEY=your_sendgrid_key_here
FROM_EMAIL=noreply@hireflow.ai

# Web Search
TAVILY_API_KEY=your_tavily_key_here

# Storage
RESUME_STORAGE_PATH=./data/resumes

# Application Settings
DEFAULT_WEEKLY_QUOTA=10
SPAM_CONFIDENCE_THRESHOLD=0.7
RATE_LIMIT_SECONDS=5
```

### `CONTRIBUTING.md`

Create with:
- How to set up dev environment
- Branch naming convention: `m{milestone-number}/{contributor-name}/{feature}` (e.g., `m2/c1/lever-scraper`)
- Commit message format: Conventional Commits (feat:, fix:, docs:, refactor:, test:)
- PR process: PR must reference an issue, must include "Defense Questions" section, requires Maintainer review
- Code style: Black + Ruff for Python, Prettier for frontend
- Defense Questions requirement: every PR must answer "what decisions did I make and why"

### `.github/ISSUE_TEMPLATE/milestone-task.md`

```markdown
---
name: Milestone Task
about: A task within a sprint milestone
title: '[M_]: '
labels: milestone, task
---

## Milestone
M_ - [Milestone Name]

## Task Title
[Short, action-oriented title]

## Objective
[What this task delivers - 1-2 sentences]

## Acceptance Criteria
- [ ] [Criterion 1]
- [ ] [Criterion 2]
- [ ] [Criterion 3]

## Technical Notes
[Any implementation guidance, gotchas, links to docs]

## Defense Questions
Before this PR is merged, the contributor must be able to answer:
1. [Question about a key decision]
2. [Question about an alternative considered]
3. [Question about edge cases]

## Estimated Effort
[Hours / days]

## Assigned Pod Role
[Maintainer / C1 / C2 / C3 / C4]
```

### `.github/PULL_REQUEST_TEMPLATE.md`

```markdown
## Closes
Closes #[issue-number]

## What does this PR do?
[Brief description of the change]

## Milestone
M_ - [Milestone Name]

## Changes
- [Change 1]
- [Change 2]
- [Change 3]

## How to test
1. [Step 1]
2. [Step 2]

## Defense Answers
Answer the Defense Questions from the linked issue:
1. **[Question 1]:** [Your answer]
2. **[Question 2]:** [Your answer]
3. **[Question 3]:** [Your answer]

## Screenshots / Logs (if applicable)

## Checklist
- [ ] My code follows the style guide (Black + Ruff)
- [ ] I have added tests where applicable
- [ ] I have updated documentation
- [ ] I have referenced the linked issue
- [ ] I can defend every decision in this PR
```

### `docs/architecture.md`

A placeholder file with section headers:
- System Overview
- Data Flow (User -> Job Discovery -> Match Scoring -> Quota Selection -> Resume Tailoring -> Application -> Prep Guide -> Weekly Report)
- Agent Architecture (LangGraph supervisor + sub-agents)
- Database Schema
- Tech Stack Rationale
- Deployment Architecture

### `Dockerfile` and `docker-compose.yml`

Standard FastAPI + PostgreSQL setup, Python 3.11 base image.

## Step 3: Initialize Git and Make First Commit

```bash
cd hireflow-ai
git init
git add .
git commit -m "chore: initial project scaffold for HireFlow AI"
git branch -M main
```

## Step 4: Create GitHub Repository

Create a new public repository on GitHub:
- Name: `hireflow-ai`
- Owner: [my GitHub org or username - ask me which]
- Description: "Your AI-powered career autopilot - agentic job application + preparation system. Built by Newton School of Technology students."
- Public, with no auto-generated files (since we have our own)

Then push:
```bash
git remote add origin <repo-url>
git push -u origin main
```

## Step 5: Create GitHub Labels

Create these labels for the workflow:
- `milestone` (blue) - milestone tasks
- `m1` through `m8` (purple) - milestone number
- `bug` (red)
- `feature` (green)
- `documentation` (gray)
- `agent` (orange) - agent-related work
- `scraper` (yellow) - scraping work
- `frontend` (cyan) - frontend work
- `infra` (brown) - infrastructure work
- `good first issue` (light green)
- `needs-review` (pink)

## Step 6: Create GitHub Issues for All 8 Milestones

Create one issue per milestone. Use the `milestone-task` template. Title format: `[M1]: Project Scaffold & User Onboarding`. Here are the 8 issues to create:

**Issue #1 - [M1]: Project Scaffold & User Onboarding**
- Labels: `milestone`, `m1`, `infra`
- Objective: Set up the repo structure, database schema, user profile model, and onboarding API
- Acceptance Criteria:
  - Repo structure matches the architecture doc
  - PostgreSQL schema created for `users` table
  - User profile intake API (POST /users) with resume upload
  - LLM-based skill extraction from uploaded resume
  - Weekly quota field with default of 10
  - `.env.example` and `requirements.txt` finalized
- Defense Questions:
  - How does your skill extraction handle resumes in different formats (PDF vs DOCX)?
  - Why did you choose PostgreSQL over a NoSQL store for user profiles?
  - What happens when a user updates their profile mid-week?
- Assigned: Maintainer + Contributor 1

**Issue #2 - [M2]: Job Discovery Engine + Spam Filter**
- Labels: `milestone`, `m2`, `scraper`, `agent`
- Objective: Build scrapers for 3 career page formats and an NLP-based spam classifier
- Acceptance Criteria:
  - Playwright scraper for Lever career pages
  - Playwright scraper for Greenhouse career pages
  - Generic scraper using BeautifulSoup
  - Spam classifier (TF-IDF baseline + LLM enhancement)
  - Job records stored in `jobs` table with all required fields
  - Scheduled scraping via APScheduler or similar
- Defense Questions:
  - Why Playwright over Selenium?
  - How do you handle career pages with infinite scroll?
  - Your spam classifier flags a real startup with a sparse JD - how do you reduce false positives?
  - What's your scraping rate limit strategy?
- Assigned: Contributor 1

**Issue #3 - [M3]: Job-Profile Match Scorer**
- Labels: `milestone`, `m3`, `pipeline`
- Objective: Build the embedding-based matching and multi-factor scoring system
- Acceptance Criteria:
  - Embedding pipeline (JD + profile -> vectors)
  - FAISS index for similarity search
  - Multi-factor scoring (skill 40%, role 20%, experience 15%, location 10%, salary 10%, company 5%)
  - Skill gap extraction (matched, partial, missing)
  - Ranked list output for any user
- Defense Questions:
  - What embedding model did you use? Why? How did you evaluate retrieval quality?
  - Why FAISS over ChromaDB?
  - How did you decide the scoring weights?
  - Two jobs have the same match score - how does the system break the tie?
- Assigned: Contributor 2

**Issue #4 - [M4]: Weekly Quota Selector + Resume Tailoring Engine**
- Labels: `milestone`, `m4`, `agent`, `pipeline`
- Objective: Build the top-N selector and per-job resume tailoring with LaTeX PDF output
- Acceptance Criteria:
  - Top-N selector based on user's weekly quota
  - Weekly Application Plan generator with user confirmation flow
  - Resume tailoring RAG pipeline (master profile + JD -> tailored resume content)
  - LaTeX templates for ATS-optimized resumes
  - PDF generation via XeLaTeX
  - Resume versioning and storage at `/data/resumes/{user_id}/{job_id}_resume.pdf`
  - Resume linked to application record in DB
- Defense Questions:
  - What chunk size did you use for the RAG pipeline? Why?
  - What happens if the JD is very short (3 lines)?
  - How does the engine handle a user with no relevant projects for a JD?
  - Why LaTeX for resume generation?
- Assigned: Contributor 2 + Contributor 3

**Issue #5 - [M5]: Application Automation Agent**
- Labels: `milestone`, `m5`, `agent`, `automation`
- Objective: Build the Playwright-driven form filling and submission agent
- Acceptance Criteria:
  - Form filler for Lever and Greenhouse application flows
  - Multi-page application handling
  - Rate limiting (configurable, default 5s between actions)
  - CAPTCHA detection (flag, do not solve)
  - Error recovery and retry logic
  - Application status logging (`applied`, `failed`, `needs_action`)
  - File upload handling for resume PDF
- Defense Questions:
  - How do you handle multi-page application forms? What if page 3 fails?
  - The career page has a CAPTCHA - what does your agent do?
  - How do you avoid being detected as a bot?
  - A form asks "Why do you want to work here?" - how does your agent answer?
- Assigned: Contributor 3

**Issue #6 - [M6]: Preparation Guide Generator**
- Labels: `milestone`, `m6`, `agent`
- Objective: Generate a comprehensive prep guide per job application
- Acceptance Criteria:
  - JD analysis -> predicted interview rounds with round-wise focus
  - Topic categorization (Strong / Moderate / Gaps) based on user profile
  - Resource finder via web search (Tavily) for each topic
  - Mock interview question generator (JD-specific, not generic)
  - Company intel agent (tech stack, stage, recent news, Glassdoor pattern)
  - Prep guide stored in `prep_guides` table
- Defense Questions:
  - How do you predict the number of interview rounds when JD doesn't mention it?
  - How do you ensure resource links are valid and high-quality?
  - How do you generate mock questions specific to the JD, not generic?
  - The company has zero Glassdoor reviews - how does intel module handle this?
- Assigned: Contributor 4

**Issue #7 - [M7]: Weekly Report Generator + Hiring Side Module**
- Labels: `milestone`, `m7`, `agent`
- Objective: Bundle all applications, resumes, and prep guides into a weekly report. Also build the hiring side shortlister.
- Acceptance Criteria:
  - Weekly report generator (PDF/HTML) with all applications + resumes + prep guides + cross-application insights
  - Email delivery via SendGrid
  - Cross-application skill gap analysis ("TypeScript appears in 3 JDs")
  - Hiring side: bulk application parser -> scorer -> top-N shortlist -> summary email to hiring team
- Defense Questions:
  - The weekly report has 10 prep guides - how do you keep them distinct?
  - How do you prioritize which skill gap to study first?
  - For hiring side: how do you prevent bias in shortlisting?
- Assigned: Contributor 4 + Maintainer

**Issue #8 - [M8]: React Dashboard + Integration + Demo**
- Labels: `milestone`, `m8`, `frontend`
- Objective: Build the user-facing dashboard and complete end-to-end integration
- Acceptance Criteria:
  - React + Tailwind dashboard with: Onboarding flow, Weekly Plan view, Application Tracker, Resume viewer, Prep Guide viewer
  - End-to-end integration testing
  - Edge case handling documented
  - Demo video (3-5 min)
  - Final README polish
  - Architecture diagram
- Defense Questions:
  - Walk me through the complete data flow from "user sets quota = 10" to "weekly report delivered"
  - What's your error handling strategy across the full pipeline?
  - How would you add a new job source without changing the core architecture?
- Assigned: All

## Step 7: Create a GitHub Project Board (Optional)

Create a project board called "HireFlow AI Roadmap" with columns:
- Backlog
- In Progress
- In Review
- Done

Add all 8 milestone issues to the Backlog column.

## Step 8: Confirm and Summarize

Once done, show me:
1. The local folder tree
2. The GitHub repo URL
3. The 8 issue URLs
4. Any errors or blockers

---

**Notes for Cowork:**
- Use my GitHub credentials already configured locally
- If GitHub CLI (`gh`) is available, prefer it for issue creation
- Create files using UTF-8 encoding
- Confirm before any destructive operation
- If anything is unclear, ask before proceeding
