# HireFlow AI - Complete Project Blueprint

## Intelligent Job Application & Hiring Agent + Career Prep System

**Track:** AI Agents & Agentic Systems
**Pod Size:** 5 (1 Maintainer + 4 Contributors)
**Duration:** 5 Weeks | 8 Milestones
**Framework:** Build -> Understand -> Defend

---

## The Vision

HireFlow AI is not just a job application bot. It's a **career autopilot** with three distinct value layers:

```
Layer 1: DISCOVER    -> Find and rank the best jobs for YOU
Layer 2: APPLY       -> Tailor resume + apply (within YOUR weekly quota)
Layer 3: PREPARE     -> Give you a battle plan for every application
Layer 4: HIRE (flip) -> Help companies shortlist from their applicant pool
```

The user says:
> "I want to apply to 10 jobs per week. Here's my profile."

HireFlow then:
1. Scrapes and discovers 100+ relevant openings
2. Scores every job against the user's profile
3. Picks the **top 10** (or whatever the user's weekly quota is)
4. For each of those 10: generates a tailored ATS resume, applies, and sends the user back:
   - The **exact resume** used for that application
   - A **preparation guide** (topics, skills, expected rounds, resources)
5. Optionally: flips to the hiring side to shortlist applicants

---

## System Architecture

```
+------------------------------------------------------------------+
|                         USER ONBOARDING                          |
|  Master Profile -> Weekly Quota (e.g. 10) -> Preferences          |
|  (resume, skills, experience, target roles, locations, salary)   |
+----------------------------+-------------------------------------+
                             |
                             v
+------------------------------------------------------------------+
|                    JOB DISCOVERY ENGINE                           |
|  Career Page Scraper (Playwright) -> Portal Aggregator            |
|  -> Spam/Quality Filter -> Raw Job Pool (100+ jobs)                |
+----------------------------+-------------------------------------+
                             |
                             v
+------------------------------------------------------------------+
|                    JOB-PROFILE MATCH SCORER                      |
|  Embedding-based similarity (JD <-> Profile)                       |
|  + Skill gap analysis + Location/salary filter                   |
|  -> Ranked list of ALL discovered jobs                            |
+----------------------------+-------------------------------------+
                             |
                             v
+------------------------------------------------------------------+
|                    WEEKLY QUOTA SELECTOR                          |
|  User quota = 10 -> Pick top 10 from ranked list                  |
|  -> Confirm with user (optional) or auto-proceed                  |
|  -> Generate Weekly Application Plan                              |
+----------------------------+-------------------------------------+
                             |
                    +--------+--------+
                    v                 v
+-------------------------+ +-------------------------------------+
|   RESUME TAILORING      | |    PREP GUIDE GENERATOR              |
|   ENGINE (per job)      | |    (per job)                         |
|                         | |                                       |
| Master Profile          | | JD Analysis                           |
|   + JD Requirements     | |   -> Topics & Skills to Prepare       |
|   -> ATS-Optimized       | |   -> Expected Interview Rounds        |
|     Tailored Resume     | |   -> Round-wise Focus Areas           |
|   -> PDF Generation      | |   -> Curated Resources                |
|                         | |   -> Company-Specific Insights         |
| Resume saved &          | |   -> Similar Interview Experiences     |
| sent back to user       | |                                       |
+------------+------------+ +------------------+------------------+
             |                                  |
             v                                  |
+-------------------------+                     |
|   APPLICATION AGENT     |                     |
|   (Playwright)          |                     |
|                         |                     |
| Fill forms -> Upload     |                     |
| resume -> Submit         |                     |
| -> Log result            |                     |
+------------+------------+                     |
             |                                  |
             v                                  v
+------------------------------------------------------------------+
|                    WEEKLY REPORT TO USER                          |
|                                                                   |
|  "This week HireFlow applied to 10 jobs for you."                |
|                                                                   |
|  For each job:                                                    |
|    +-- Company & Role                                            |
|    +-- Match Score (87%)                                          |
|    +-- Resume Used (PDF attached / link)                          |
|    +-- Application Status (Applied / Failed / Needs Action)      |
|    +-- Preparation Guide                                         |
|         +-- Key Topics: [RAG, LangChain, System Design]          |
|         +-- Skill Gaps: [Docker - you should learn this]         |
|         +-- Expected Rounds: 3 (HR -> Technical -> Founder)        |
|         +-- Round-wise Focus                                     |
|         |    +-- HR: Communication, motivation, salary            |
|         |    +-- Technical: RAG implementation, LLM evaluation    |
|         |    +-- Founder: Product thinking, ownership examples    |
|         +-- Resources                                            |
|         |    +-- LangChain docs (link)                            |
|         |    +-- RAG tutorial by (link)                           |
|         |    +-- Company blog / tech stack article (link)         |
|         +-- Company Intel                                        |
|              +-- Tech stack used (from JD + career page)         |
|              +-- Recent news / funding                           |
|              +-- Glassdoor interview pattern (if available)      |
|                                                                   |
+------------------------------------------------------------------+
             |
             v
+------------------------------------------------------------------+
|              HIRING SIDE (OPTIONAL MODULE)                        |
|                                                                   |
|  Company gets 100+ applications ->                                |
|  Agent scores against JD -> Ranks -> Shortlists top 20-30 ->       |
|  Sends email to hiring team with summary report                  |
+------------------------------------------------------------------+
```

---

## Module Deep Dive

### Module 1: User Onboarding & Profile Builder

**What it does:**
User uploads their master resume or fills a structured profile. System extracts and stores: skills, experience, education, projects, target roles, preferred locations, salary expectations, and weekly application quota.

**Key Fields:**

| Field | Type | Example |
|-------|------|---------|
| `name` | string | "Rahul Sharma" |
| `email` | string | "rahul@example.com" |
| `master_resume` | file (PDF) | Uploaded PDF |
| `skills` | list | ["Python", "LangChain", "RAG", "FastAPI", "React"] |
| `experience_years` | int | 0 (fresher) / 2 |
| `education` | object | { degree: "B.Tech CS", college: "NST", year: 2026 } |
| `projects` | list[object] | [{ name: "...", tech: [...], description: "..." }] |
| `target_roles` | list | ["AI Engineer", "GenAI Developer", "ML Intern"] |
| `preferred_locations` | list | ["Bangalore", "Remote", "Pune"] |
| `min_stipend` | int | 15000 |
| `weekly_quota` | int | 10 |
| `auto_apply` | bool | true / false (if false, confirm before each apply) |

**How profile is used downstream:**
- **Job Matching:** Profile embedding compared against JD embeddings
- **Resume Tailoring:** Skills and projects cherry-picked per JD
- **Prep Guide:** Skill gaps computed against JD requirements
- **Quota Selection:** Top N jobs ranked by profile-JD fit

---

### Module 2: Job Discovery Engine

**What it does:**
Scrapes career pages and portals to build a pool of 100+ relevant openings per cycle.

**Sources:**
- Company career pages (Lever, Greenhouse, Workable, custom)
- Job portals (LinkedIn Jobs, Internshala, Wellfound, etc.)
- Aggregator APIs (where available)

**Scraping Strategy:**

| Source Type | Tool | Approach |
|-------------|------|----------|
| Static HTML pages | BeautifulSoup | Direct parse |
| JS-rendered SPAs | Playwright | Headless browser, wait for content |
| API-backed portals | Requests | Direct API calls where possible |

**Data Extracted Per Job:**

| Field | Source |
|-------|--------|
| `company_name` | Career page |
| `role_title` | Listing |
| `jd_text` | Full job description |
| `skills_required` | Extracted from JD via LLM |
| `experience_required` | Parsed |
| `location` | Parsed |
| `stipend_salary` | Parsed (if available) |
| `application_url` | Direct link |
| `posting_date` | Parsed |
| `selection_process` | Extracted (if mentioned) - critical for prep guide |
| `company_website` | Scraped |
| `source` | "lever" / "greenhouse" / "linkedin" / etc. |

**Spam Filter:**
NLP classifier trained on signals: vague JDs, unrealistic salary claims, missing company details, known spam patterns. Confidence threshold - below threshold, the job is flagged and excluded.

---

### Module 3: Job-Profile Match Scorer

**What it does:**
Scores every discovered job against the user's profile. Produces a ranked list where rank 1 = best fit.

**Scoring Components:**

| Component | Weight | How It Works |
|-----------|--------|-------------|
| **Skill Match** | 40% | Embedding similarity between user skills and JD required skills. Counts exact matches, partial matches, and missing skills |
| **Role Fit** | 20% | Semantic similarity between user's target roles and the job title/description |
| **Experience Fit** | 15% | Does user's experience level match? Fresher applying to 3+ year role = penalty |
| **Location Match** | 10% | User preference vs job location. Remote gets bonus if user prefers remote |
| **Stipend/Salary Fit** | 10% | Job stipend >= user's minimum? If undisclosed, neutral score |
| **Company Signal** | 5% | Verified company, clear JD, known brand = slight bonus |

**Output:**

```json
{
  "job_id": "job_042",
  "company": "AIBridge",
  "role": "Agentic AI Intern",
  "match_score": 0.87,
  "skill_match": {
    "matched": ["Python", "LangChain", "LLMs", "AI Agents"],
    "partial": ["TypeScript"],
    "missing": ["Vercel AI SDK"]
  },
  "skill_gap": ["Vercel AI SDK", "TypeScript"],
  "rank": 3
}
```

---

### Module 4: Weekly Quota Selector

**What it does:**
User says "10 per week." System picks top 10 from the ranked list and generates a Weekly Application Plan.

**Logic:**
1. Sort all jobs by `match_score` descending
2. Apply filters: exclude already-applied companies, expired listings, user blacklist
3. Pick top N (N = weekly quota)
4. If `auto_apply = false`: send the list to user for confirmation before proceeding
5. If `auto_apply = true`: proceed directly to resume tailoring + application

**Weekly Application Plan (sent to user before execution):**

```
===============================================
   HIREFLOW WEEKLY PLAN - Week of June 9, 2026
   Quota: 10 jobs | Profile: Rahul Sharma
===============================================

   #1  AIBridge - Agentic AI Intern
       Match: 92% | Remote | 20-30k
       Skills Matched: 8/10 | Gap: TypeScript, Vercel AI SDK
   
   #2  Lemon Tea Studio - Software Dev Intern (GenAI)
       Match: 89% | Pune (Hybrid) | 25k
       Skills Matched: 7/9 | Gap: Angular
   
   #3  Augle AI - AI Engineer Intern
       Match: 85% | Pune | 20k
       Skills Matched: 6/10 | Gap: PyTorch, Edge Deployment
   
   ... (7 more)
   
   ---------------------------------
   [Confirm & Apply All]  [Edit List]
===============================================
```

---

### Module 5: Resume Tailoring Engine (Per Job)

**What it does:**
For each of the N selected jobs, generates a unique ATS-optimized resume tailored to that specific JD.

**Pipeline:**

```
Master Profile + JD
       |
       v
  Skill Extraction (from JD)
       |
       v
  Skill Mapping (which user skills match, which projects demonstrate them)
       |
       v
  Resume Section Generation (RAG)
       +-- Summary: Tailored to role
       +-- Skills: Reordered by JD priority
       +-- Experience: Relevant bullets emphasized
       +-- Projects: Top 2-3 most relevant selected
       +-- Education: Standard
       |
       v
  ATS Formatting (clean, parseable, keyword-rich)
       |
       v
  PDF Generation (using LaTeX / ReportLab)
       |
       v
  Resume stored: /resumes/{user_id}/{job_id}_resume.pdf
  Resume sent back to user in weekly report
```

**Key Design Decisions (Interview Hooks):**

| Decision | Options | Chosen | Why |
|----------|---------|--------|-----|
| Resume format | LaTeX vs HTML vs DOCX | LaTeX (XeLaTeX) | Best ATS parsing, consistent formatting |
| Skill reordering | Alphabetical vs JD-priority | JD-priority | First skills listed get more ATS weight |
| Project selection | All vs top-3 relevant | Top 2-3 by relevance score | Space-efficient, targeted |
| Summary generation | Template vs LLM-generated | LLM with constraints | Unique per JD but ATS-compliant |

**Resume Tracking:**
Every resume is version-controlled. User can see exactly which resume was sent to which company:

```json
{
  "application_id": "app_001",
  "job_id": "job_042",
  "company": "AIBridge",
  "role": "Agentic AI Intern",
  "resume_path": "/resumes/rahul/aibridge_agentic_ai_resume.pdf",
  "resume_version": "v1",
  "skills_highlighted": ["LangChain", "Python", "AI Agents", "LLMs"],
  "projects_included": ["ClaimFlow AI", "ScheduleGenie"],
  "applied_at": "2026-06-10T14:30:00Z",
  "status": "applied"
}
```

---

### Module 6: Preparation Guide Generator (Per Job)

**What it does:**
For every job applied to, generates a structured interview preparation guide. This is the "career coach" layer - the thing that makes HireFlow more than a bot.

**Guide Components:**

#### 6a. Interview Structure Prediction

The agent analyzes the JD and company career page to predict the interview process:

| Signal Source | What It Tells Us |
|---------------|-----------------|
| JD text | Often mentions "selection process" or "rounds" explicitly |
| Company career page | May describe hiring process |
| Company size/stage | Startup = 2-3 rounds, Enterprise = 4-5 rounds |
| Role type | Intern = lighter, Full-time = heavier |
| Web search | Glassdoor/AmbitionBox interview reviews |

**Output:**

```
EXPECTED INTERVIEW PROCESS
---------------------------
Predicted Rounds: 3
Confidence: High (process mentioned in JD)

Round 1: HR Screening (Telephonic)
  +-- Focus: Introduction, motivation, communication
  +-- Duration: ~15-20 min
  +-- Prep: Elevator pitch, "Why this company?", salary expectation

Round 2: Technical Round
  +-- Focus: Core concepts, problem-solving, project discussion
  +-- Duration: ~45-60 min
  +-- Topics: LangChain, RAG pipelines, AI Agents, Python
  +-- Prep: Be ready to explain your projects in depth

Round 3: Founder / Hiring Manager Round
  +-- Focus: Culture fit, ownership, product thinking
  +-- Duration: ~30 min
  +-- Prep: Company research, "What would you build?" questions
```

#### 6b. Topics & Skills to Prepare

Based on JD skill extraction + user's skill gap analysis:

```
TOPICS TO PREPARE
-----------------

STRONG (You already know - revise & be ready to go deep):
  1. Python - You have strong experience. Expect coding questions.
  2. LangChain - Your ClaimFlow project demonstrates this. Be ready
     to explain agent orchestration and state management.
  3. REST APIs - Your FastAPI experience covers this.

MODERATE (You know basics - need deeper prep):
  4. LLMs & Prompt Engineering - Study few-shot prompting, chain-of-thought,
     temperature/top-p tuning. Likely a discussion topic.
  5. AI Agents - Understand ReAct pattern, tool use, planning loops.
     Your projects cover this but prepare theoretical depth.

GAPS (Skills in JD that you're missing - start learning):
  6. TypeScript - JD mentions it. At minimum, understand basics and how
     it differs from Python. Resource: TypeScript Handbook (link)
  7. Vercel AI SDK - JD mentions it as "good to have." Quick overview
     recommended. Resource: Vercel AI SDK docs (link)
```

#### 6c. Curated Resources

For each topic, the agent finds relevant learning resources:

```
RESOURCES
---------

LangChain & Agents:
   LangChain Documentation - https://python.langchain.com/docs/
   "Building AI Agents with LangGraph" - DeepLearning.AI (link)
   Your own project: ClaimFlow AI - review your LangGraph code

TypeScript (Gap):
   TypeScript Handbook - https://www.typescriptlang.org/docs/handbook/
   "TypeScript in 1 Hour" - Fireship (YouTube)
   Practice: Convert one of your Python scripts to TypeScript

Vercel AI SDK (Gap):
   Official Docs - https://sdk.vercel.ai/docs
   "Build AI Apps with Vercel AI SDK" - (YouTube)

Company-Specific:
   AIBridge product - https://app.aibridge.one (explore it)
   Recent news about AIBridge - (web search result)
   Their tech blog (if available)
```

#### 6d. Company Intelligence

```
COMPANY INTEL
-------------

Company: AIBridge
Website: https://app.aibridge.one
Stage: Startup (early-stage)
Team Size: Small (~10-30 estimated)
Focus: Agentic AI systems, autonomous workflows
Tech Stack (inferred): Python, TypeScript, LangChain, Vercel AI SDK

Recent Activity:
   [Web search result: any recent funding, product launch, press]

Interview Pattern (from Glassdoor/AmbitionBox if available):
   [Scraped interview experiences if found]
   If not found: "No interview reviews found - this is a newer company.
    Expect a less structured process focused on problem-solving and
    cultural fit."

Key People:
   [Founder name from LinkedIn/website if publicly available]

What They Might Ask:
   "Build an AI agent that does X" - hands-on task likely
   "How would you architect a multi-agent system?" - design question
   "Walk us through a project where you used LangChain" - project deep dive
```

#### 6e. Mock Interview Questions (Generated Per JD)

```
LIKELY INTERVIEW QUESTIONS
--------------------------

Technical:
  1. What is an AI agent? How is it different from a chatbot?
  2. Explain the ReAct pattern. When would you use it vs a simple chain?
  3. Walk me through your [most relevant project]. What was the hardest part?
  4. How would you build a multi-agent system for [company's domain]?
  5. What is RAG? When would you use it vs fine-tuning?

Behavioral:
  6. Why do you want to work at [company]?
  7. Tell me about a time you learned something new quickly.
  8. How do you handle ambiguity in a project?

Design:
  9. Design an AI agent that can [task relevant to company's product].
  10. How would you evaluate whether an LLM-based feature is working well?
```

---

### Module 7: Weekly Report Generator

**What it does:**
After all N applications are submitted, generates a comprehensive weekly report sent to the user.

**Report Structure:**

```
==============================================================
        HIREFLOW WEEKLY REPORT
        Week: June 9 - June 15, 2026
        User: Rahul Sharma
        Quota: 10 | Applied: 9 | Failed: 1
==============================================================

SUMMARY
-------
  Applications Sent: 9/10
  Average Match Score: 86%
  Top Match: AIBridge (92%)
  Failed Application: Augle AI (career page CAPTCHA blocked bot)
  Skill Gaps Identified Across All JDs: TypeScript (3 JDs), 
    Docker (2 JDs), PyTorch (2 JDs)
  
  Recommendation: This week, spend 3 hours learning TypeScript 
  basics - it appeared in 3 of your top 10 JDs.

--------------------------------------------------------------

APPLICATION #1 - AIBridge
-------------------------
  Role: Agentic AI Intern
  Match Score: 92%
  Status:  Applied
  Resume Used: [ aibridge_agentic_ai_resume.pdf]
  
  Preparation Guide:
    Expected Rounds: 2 (Technical -> Founder)
    Key Topics: AI Agents, LangChain, Multi-Agent Systems, Python
    Skill Gaps: TypeScript, Vercel AI SDK
    Resources: [3 links]
    Mock Questions: [5 questions]
    Company Intel: Early-stage startup, agentic AI focus
    
     [View Full Prep Guide]

--------------------------------------------------------------

APPLICATION #2 - Lemon Tea Studio
---------------------------------
  Role: Software Dev Intern (Full Stack & Gen-AI)
  Match Score: 89%
  Status:  Applied
  Resume Used: [ lemontea_fullstack_genai_resume.pdf]
  
  Preparation Guide:
    Expected Rounds: 2 (HR -> Technical)
    Key Topics: React, Python/Node.js, GenAI, LLM Integration
    Skill Gaps: Angular
    Resources: [3 links]
    Mock Questions: [5 questions]
    Company Intel: Pune-based, hybrid, GenAI products
    
     [View Full Prep Guide]

... (7 more applications)

--------------------------------------------------------------

CROSS-APPLICATION INSIGHTS
--------------------------
  Most In-Demand Skills This Week:
    1. Python (10/10 JDs)
    2. LangChain (6/10 JDs)
    3. LLMs / GenAI (8/10 JDs)
    4. TypeScript (3/10 JDs) <- GAP
    5. React (4/10 JDs)
  
  Your Strongest Matches: AI Agent roles (avg 90%)
  Your Weakest Matches: Full-stack heavy roles (avg 78%)
  
  Weekly Study Plan:
    Priority 1: TypeScript basics (3 JDs need it)
    Priority 2: Docker fundamentals (2 JDs mention containerization)
    Priority 3: Review your LangGraph project for interview prep

==============================================================
```

---

### Module 8: Hiring Side Agent (Optional)

**What it does:**
Flips the system: a company gets 100+ applications, and HireFlow shortlists the best 20-30.

**Flow:**
1. Company uploads JD + receives applications (CSV/JSON or scraped from portal)
2. Agent parses each application: extracts skills, experience, projects
3. Scores each applicant against JD (same scoring engine as candidate side)
4. Ranks and shortlists top N (company specifies: "give me top 20")
5. Generates shortlist report with per-candidate summary
6. Sends email to hiring team

**Shortlist Email to Hiring Team:**

```
Subject: HireFlow Shortlist - Agentic AI Intern (20 of 127 applicants)

Hi [Hiring Manager],

You received 127 applications for the Agentic AI Intern role. 
HireFlow has analyzed all applications and shortlisted the 
top 20 candidates based on skill match, experience, and project relevance.

Top 5 Highlights:
  #1 Priya M. - 94% match - LangGraph, CrewAI, Python, 2 agentic projects
  #2 Arjun K. - 91% match - LangChain, RAG, FastAPI, published on arXiv
  #3 Sneha R. - 89% match - Multi-agent systems, TypeScript, React
  #4 Rohan D. - 87% match - AI Agents, Python, Docker, MLflow
  #5 Ananya S. - 86% match - LLMs, Prompt Engineering, Streamlit

Full shortlist with individual profiles attached.

- HireFlow AI
```

---

## Tech Stack (Complete)

| Layer | Tool | Purpose |
|-------|------|---------|
| **Agent Orchestration** | LangGraph | Multi-agent workflow with state (JobState, ApplicationState) |
| **LLM** | Claude / OpenAI API | Resume generation, JD parsing, prep guide, scoring reasoning |
| **Web Scraping** | Playwright | Career page scraping, JS-rendered pages, form automation |
| **Web Scraping (light)** | BeautifulSoup + Requests | Static pages, API-backed portals |
| **Vector Store** | FAISS | Profile-JD embedding similarity for matching |
| **Embedding Model** | OpenAI / Sentence-Transformers | JD and profile embeddings |
| **Backend** | FastAPI | REST API for all modules |
| **Frontend** | React + Tailwind | User dashboard, weekly plan, prep guides |
| **Database** | PostgreSQL | User profiles, job records, applications, resumes, prep guides |
| **Resume Generation** | LaTeX (XeLaTeX) / ReportLab | ATS-optimized PDF resumes |
| **Email** | SendGrid / Resend | Weekly reports to users, shortlist emails to hiring teams |
| **Web Search** | Tavily / SerpAPI | Company intel, interview reviews, resource discovery |
| **File Storage** | Local / S3 | Resume PDFs, prep guide PDFs |
| **Deployment** | Docker + Railway / Render | Containerized |

---

## GitHub Milestones (8 Sprints, ~3 days each)

| Sprint | Milestone | Key Deliverables | Owner |
|--------|-----------|-----------------|-------|
| **M1** | **Project Scaffold & User Onboarding** | Repo structure, `.env`, `requirements.txt`, DB schema, user profile model, profile intake API (upload resume -> extract skills via LLM), weekly quota setting | Maintainer + C1 |
| **M2** | **Job Discovery Engine** | Playwright scrapers for 3 career page formats (Lever, Greenhouse, custom). BeautifulSoup for static pages. Spam classifier (TF-IDF baseline). Job data model. Scheduled scraping | C1 |
| **M3** | **Job-Profile Match Scorer** | Embedding pipeline (JD + Profile -> vectors). FAISS index. Multi-factor scoring (skill match 40%, role fit 20%, experience 15%, location 10%, salary 10%, company signal 5%). Skill gap extraction | C2 |
| **M4** | **Weekly Quota Selector + Resume Tailoring Engine** | Top-N selection logic. Resume tailoring RAG pipeline (master profile + JD -> tailored resume). LaTeX PDF generation. Resume versioning and storage. Resume sent back with application record | C2 + C3 |
| **M5** | **Application Automation Agent** | Playwright form filler for career pages. Multi-step flow handling. Rate limiting. CAPTCHA detection (flag, don't solve). Error recovery. Retry logic. Application status logging | C3 |
| **M6** | **Preparation Guide Generator** | JD analysis -> interview rounds prediction. Topic/skill extraction with gap analysis. Resource finder (web search for tutorials, docs, courses). Mock question generator. Company intel scraper. Per-job prep guide PDF/HTML generation | C4 |
| **M7** | **Weekly Report + Hiring Side Module** | Weekly report generator (all applications + resumes + prep guides). Email delivery. Hiring side: bulk application parser -> scorer -> shortlist -> email to hiring team | C4 + Maintainer |
| **M8** | **Dashboard, Integration & Demo** | React dashboard (weekly plan view, application tracker, prep guides, resume viewer). End-to-end flow testing. Edge cases. Demo video. README. Architecture docs | All |

---

## Pod Role Breakdown (Detailed)

### Maintainer
**Owns:** Repo architecture, LangGraph orchestration, state management, PR reviews, integration across all modules, M1 scaffold, M7 hiring side co-owner, M8 integration

**Key Files:**
- `src/agents/supervisor.py` - Main LangGraph workflow
- `src/config/` - All configuration
- `src/models/` - Data models (User, Job, Application, PrepGuide)

**Defense Questions:**
1. Walk me through the complete data flow from "user sets quota = 10" to "weekly report delivered."
2. How do agents coordinate? What's the state schema? What happens when the scraper fails mid-pipeline?
3. How would you add a new job source (e.g., a new portal) without changing the core architecture?

---

### Contributor 1 - Job Discovery Engine
**Owns:** M2 (Job Discovery + Spam Filter)

**Key Files:**
- `src/scrapers/lever_scraper.py`
- `src/scrapers/greenhouse_scraper.py`
- `src/scrapers/generic_scraper.py`
- `src/agents/spam_filter.py`

**Defense Questions:**
1. Why Playwright over Selenium? When would Selenium be better?
2. How do you handle career pages that load jobs via infinite scroll?
3. Your spam classifier flags a real startup with a sparse JD. How do you reduce false positives?
4. What's your scraping rate limit strategy? How do you avoid IP bans?
5. A career page changes its HTML structure overnight. How does your scraper handle this?

---

### Contributor 2 - Match Scorer + Resume Tailoring
**Owns:** M3 (Match Scorer) + M4 co-owner (Resume Engine)

**Key Files:**
- `src/pipelines/match_scorer.py`
- `src/pipelines/embedding_pipeline.py`
- `src/pipelines/resume_generator.py`
- `src/templates/resume_latex/`

**Defense Questions:**
1. What embedding model did you use? Why? How did you evaluate retrieval quality?
2. Why FAISS over ChromaDB for this use case?
3. Your match score weights skill at 40%. Why not 60%? How did you decide the weights?
4. Two jobs have the same match score (87%). How does the system break the tie?
5. What chunk size did you use for the RAG pipeline? What happens if the JD is very short (3 lines)?
6. How does the resume engine handle a user who has no relevant projects for a particular JD?
7. Why LaTeX for resume generation? What if the user wants a different format?

---

### Contributor 3 - Application Automation Agent
**Owns:** M5 (Application Automation) + M4 co-owner (Resume integration)

**Key Files:**
- `src/agents/application_agent.py`
- `src/automation/form_filler.py`
- `src/automation/captcha_handler.py`

**Defense Questions:**
1. How do you handle multi-page application forms? What if page 3 fails?
2. The career page has a CAPTCHA. You can't solve it. What does your agent do?
3. How do you avoid being detected as a bot? What anti-detection measures did you implement?
4. What's your retry strategy? After how many failures do you give up?
5. A form asks a free-text question: "Why do you want to work here?" How does your agent generate this?
6. How do you handle file upload fields for resume? What about cover letter fields?
7. How do you verify the application actually went through?

---

### Contributor 4 - Prep Guide Generator + Weekly Report
**Owns:** M6 (Prep Guide) + M7 co-owner (Weekly Report + Hiring Side)

**Key Files:**
- `src/agents/prep_guide_agent.py`
- `src/agents/company_intel_agent.py`
- `src/agents/report_generator.py`
- `src/agents/hiring_shortlist_agent.py`

**Defense Questions:**
1. How do you predict the number of interview rounds when the JD doesn't mention it?
2. Your prep guide recommends resources. How do you ensure the links are valid and high-quality?
3. How do you generate mock interview questions that are specific to the JD, not generic?
4. The company has zero Glassdoor reviews. How does your company intel module handle this?
5. For the hiring side: how do you prevent bias in shortlisting? What if the scoring penalizes non-traditional backgrounds?
6. The weekly report has 10 prep guides. How do you keep them distinct and not repetitive?
7. How do you prioritize which skill gap to study first when multiple JDs have different gaps?

---

## Database Schema (Key Tables)

```sql
-- Users
CREATE TABLE users (
    id UUID PRIMARY KEY,
    name VARCHAR(255),
    email VARCHAR(255) UNIQUE,
    master_profile JSONB,        -- skills, experience, education, projects
    target_roles TEXT[],
    preferred_locations TEXT[],
    min_stipend INTEGER,
    weekly_quota INTEGER DEFAULT 10,
    auto_apply BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP
);

-- Discovered Jobs
CREATE TABLE jobs (
    id UUID PRIMARY KEY,
    company_name VARCHAR(255),
    role_title VARCHAR(255),
    jd_text TEXT,
    skills_required TEXT[],
    experience_required VARCHAR(50),
    location VARCHAR(255),
    stipend_salary VARCHAR(100),
    application_url TEXT,
    selection_process TEXT,        -- critical for prep guide
    source VARCHAR(50),
    is_spam BOOLEAN DEFAULT FALSE,
    spam_confidence FLOAT,
    scraped_at TIMESTAMP
);

-- Applications
CREATE TABLE applications (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    job_id UUID REFERENCES jobs(id),
    match_score FLOAT,
    skill_matches TEXT[],
    skill_gaps TEXT[],
    resume_path TEXT,             -- path to tailored resume PDF
    resume_version VARCHAR(10),
    status VARCHAR(20),           -- 'planned', 'applied', 'failed', 'needs_action'
    failure_reason TEXT,
    applied_at TIMESTAMP,
    week_number INTEGER           -- which weekly cycle this belongs to
);

-- Preparation Guides
CREATE TABLE prep_guides (
    id UUID PRIMARY KEY,
    application_id UUID REFERENCES applications(id),
    predicted_rounds INTEGER,
    round_details JSONB,          -- [{round: 1, type: "HR", focus: [...], duration: "15min"}]
    topics_strong TEXT[],
    topics_moderate TEXT[],
    topics_gaps TEXT[],
    resources JSONB,              -- [{topic: "LangChain", type: "docs", url: "...", title: "..."}]
    mock_questions JSONB,         -- [{category: "technical", question: "...", hint: "..."}]
    company_intel JSONB,          -- {stage, team_size, tech_stack, recent_news, interview_reviews}
    study_time_estimate VARCHAR(50),  -- "~4 hours"
    generated_at TIMESTAMP
);

-- Weekly Reports
CREATE TABLE weekly_reports (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    week_start DATE,
    week_end DATE,
    quota INTEGER,
    applied_count INTEGER,
    failed_count INTEGER,
    avg_match_score FLOAT,
    top_skill_gaps JSONB,         -- [{skill: "TypeScript", frequency: 3}]
    weekly_study_plan TEXT,
    report_path TEXT,              -- path to generated report
    sent_at TIMESTAMP
);

-- Hiring Shortlists (optional module)
CREATE TABLE shortlists (
    id UUID PRIMARY KEY,
    company_name VARCHAR(255),
    role_title VARCHAR(255),
    jd_text TEXT,
    total_applicants INTEGER,
    shortlist_size INTEGER,
    shortlisted JSONB,            -- [{name, score, skills_matched, summary}]
    report_path TEXT,
    email_sent_to VARCHAR(255),
    created_at TIMESTAMP
);
```

---

## Sample User Journey (End-to-End)

```
Day 1: Rahul signs up -> uploads resume -> sets quota = 10 -> targets "AI Engineer Intern"

Day 2: HireFlow scrapes 150 jobs -> filters 23 spam -> scores 127 remaining
        -> sends Weekly Plan: "Here are your top 10. Confirm?"
        Rahul reviews -> swaps #8 with #11 -> confirms

Day 2-3: HireFlow generates 10 tailored resumes -> applies to 9 
         (1 failed: Augle AI had CAPTCHA)
         -> generates 10 prep guides

Day 3: Rahul receives Weekly Report:
       - 9 applications with resumes attached
       - 10 prep guides with topics, rounds, resources
       - Cross-application insight: "Learn TypeScript this week"
       - Augle AI flagged: "Manual apply needed (CAPTCHA)"

Day 4-7: Rahul studies using prep guides. Gets interview call from AIBridge.
         Opens prep guide -> reviews predicted rounds, topics, mock questions.
         Aces the interview.

Day 8: Next weekly cycle begins automatically.
```

---

*Document Version: 3.0 | Project 1 of 5 | AI Track*
*Summer Profile Building Drive 2026 - Newton School of Technology*
*Framework: Build -> Understand -> Defend*
