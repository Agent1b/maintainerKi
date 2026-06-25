# 🛡️ maintainerKi

**An open source tool that helps maintainers sort through the flood of pull requests and issues.**

maintainerKi is a GitHub App that automatically reads every new pull request and issue, scores its quality, detects duplicates, flags suspicious patterns, and shows maintainers a clean priority inbox — so they can focus on what matters.

> maintainerKi never rejects anything automatically. It only sorts and suggests. The human maintainer always makes the final decision.

---

## Table of Contents

- [Why This Exists](#why-this-exists)
- [What maintainerKi Does](#what-maintainerki-does)
- [How It Works (Big Picture)](#how-it-works-big-picture)
- [Architecture](#architecture)
- [Prerequisites (What You Need Before Starting)](#prerequisites-what-you-need-before-starting)
- [Step-by-Step Development Guide](#step-by-step-development-guide)
  - [Phase 0: Set Up Your Computer](#phase-0-set-up-your-computer)
  - [Phase 1: Build the GitHub Connection](#phase-1-build-the-github-connection)
  - [Phase 2: Add the AI Scoring Engine](#phase-2-add-the-ai-scoring-engine)
  - [Phase 3: Add Duplicate Detection](#phase-3-add-duplicate-detection)
  - [Phase 4: Build the Dashboard](#phase-4-build-the-dashboard)
  - [Phase 5: Polish and Package](#phase-5-polish-and-package)
  - [Phase 6: Go to Production](#phase-6-go-to-production)
- [How to Test Everything](#how-to-test-everything)
- [Project Structure](#project-structure)
- [Tech Stack Explained](#tech-stack-explained)
- [Glossary (Words Explained)](#glossary-words-explained)
- [Contributing](#contributing)
- [License](#license)

---

## Why This Exists

AI coding tools made it very easy to write code fast. Now maintainers of open source projects are drowning in pull requests and issues — many of them low quality, duplicates, or AI-generated junk.

Real examples from 2026:

- **Jazzband** (a Python project community) shut down completely because of the flood
- **curl** (used by every computer in the world) canceled its bug bounty program
- **Godot** (a game engine) maintainers described triage as "draining and demoralizing"
- GitHub saw PRs grow from 25 million/month to 90 million/month in 3 years

maintainerKi exists to give maintainers their time back.

---

## What maintainerKi Does

When a new pull request or issue arrives on a GitHub repository:

```
1. Someone opens a PR or issue
         ↓
2. GitHub sends a message to maintainerKi (called a "webhook")
         ↓
3. maintainerKi reads the title, description, code changes, and contributor info
         ↓
4. maintainerKi asks an AI model: "Is this good quality? Is it relevant? Is it suspicious?"
         ↓
5. maintainerKi checks: "Have we seen something like this before?" (duplicate detection)
         ↓
6. maintainerKi adds labels to the PR/issue on GitHub (like "high-priority" or "needs-review")
         ↓
7. maintainerKi updates its dashboard so the maintainer sees a sorted inbox
```

**What the maintainer sees:**

Instead of 200 unsorted notifications, they see:

- **Review first (5 items):** High quality, relevant, from known contributors
- **Worth a look (12 items):** Decent quality, might be useful
- **Probably duplicates (8 items):** Matched to existing issues
- **Suspicious (15 items):** Low quality, possible AI slop, new accounts with many PRs

---

## How It Works (Big Picture)

maintainerKi has 4 main parts:

```
┌──────────────────────────────────────────────────────────────────────┐
│                              GITHUB                                  │
│   (where the PRs and issues live)                                    │
│                                                                      │
│   When a new PR or issue is created, GitHub sends a message ──────┐  │
└──────────────────────────────────────────────────────────────────────┘
                                                                    │
                                                                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│                          MAINTAINERKI SERVER                                │
│                                                                      │
│   ┌──────────────┐   ┌──────────────┐   ┌────────────────────────┐  │
│   │  Webhook      │   │  AI Scorer   │   │  Duplicate Detector    │  │
│   │  Receiver     │──▶│              │──▶│                        │  │
│   │              │   │  Reads the   │   │  Compares to existing  │  │
│   │  Catches the │   │  PR/issue    │   │  issues using          │  │
│   │  message     │   │  and gives   │   │  embeddings            │  │
│   │  from GitHub │   │  it a score  │   │                        │  │
│   └──────────────┘   └──────────────┘   └────────────────────────┘  │
│                                                    │                 │
│                                                    ▼                 │
│                              ┌──────────────────────────────┐       │
│                              │  Database                     │       │
│                              │                               │       │
│                              │  Stores all scores, labels,   │       │
│                              │  embeddings, and history       │       │
│                              └──────────────────────────────┘       │
│                                                    │                 │
│                                                    ▼                 │
│                              ┌──────────────────────────────┐       │
│                              │  GitHub API                   │       │
│                              │                               │       │
│                              │  Adds labels and comments     │       │
│                              │  back to the PR/issue         │       │
│                              └──────────────────────────────┘       │
└──────────────────────────────────────────────────────────────────────┘
                                                    │
                                                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│                          DASHBOARD                                   │
│                                                                      │
│   A web page where maintainers see their sorted inbox                │
│   - Priority items first                                             │
│   - Filter by label, score, contributor                              │
│   - Review queue depth and burnout-risk metrics                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Architecture

### System Components

```
maintainerki/
├── server/              ← The main backend (Python + FastAPI)
│   ├── webhooks/        ← Receives messages from GitHub
│   ├── scorer/          ← AI quality scoring
│   ├── duplicates/      ← Duplicate detection with embeddings
│   ├── labeler/         ← Adds labels back to GitHub
│   ├── models/          ← Database table definitions
│   └── api/             ← API endpoints for the dashboard
│
├── dashboard/           ← The web frontend (React)
│   ├── components/      ← Reusable UI pieces
│   ├── pages/           ← Full page views
│   └── hooks/           ← Data fetching logic
│
├── worker/              ← Background job processor (handles AI calls)
│   └── tasks/           ← Individual task definitions
│
├── tests/               ← All tests live here
│   ├── unit/            ← Tests for individual functions
│   ├── integration/     ← Tests for components working together
│   └── fixtures/        ← Sample data for tests
│
├── docker-compose.yml   ← Runs everything together
├── Dockerfile           ← Instructions to build the container
├── .env.example         ← Template for secret settings
└── README.md            ← This file
```

### Data Flow (Step by Step)

```
Step 1: GitHub sends webhook
    → POST request to /webhooks/github

Step 2: Webhook handler validates the request
    → Checks the secret signature (security)
    → Parses the JSON payload
    → Extracts: PR title, body, diff, author info

Step 3: Handler puts a job on the queue
    → This means: "process this later in the background"
    → Why? So we can respond to GitHub quickly (within 10 seconds)

Step 4: Worker picks up the job
    → Sends the PR/issue text to the AI scorer
    → AI returns a quality score (0-100) and reasons
    → Worker sends text to the embedding model
    → Embedding model returns a vector (a list of numbers representing meaning)
    → Worker compares this vector to stored vectors of existing issues
    → If similarity is above threshold → flag as potential duplicate

Step 5: Worker saves results to database
    → Score, labels, embedding vector, duplicate candidates

Step 6: Worker calls GitHub API
    → Adds labels to the PR/issue (e.g., "maintainerki:high-priority")
    → Optionally adds a comment with the analysis summary

Step 7: Dashboard reads from database
    → Shows maintainer their sorted inbox
```

---

## Prerequisites (What You Need Before Starting)

This section tells you everything to install on your computer before writing any code.

### Things to install

| What | Why you need it | How to install |
|------|----------------|---------------|
| **Python 3.11 or newer** | The main programming language for the server | https://www.python.org/downloads/ |
| **Node.js 20 or newer** | Needed for the dashboard (React frontend) | https://nodejs.org/ |
| **Git** | Version control — saves your work and tracks changes | https://git-scm.com/downloads |
| **Docker** | Runs the database and other services in containers | https://docs.docker.com/get-docker/ |
| **A code editor** | Where you write code — VS Code is recommended | https://code.visualstudio.com/ |
| **A GitHub account** | You need this to create the GitHub App | https://github.com/signup |

### Things to sign up for (all have free tiers)

| What | Why | Free tier |
|------|-----|-----------|
| **Ollama** (optional) | Run AI models on your own computer for free | Completely free, runs locally |
| **OpenAI API** (optional) | Cloud AI if your computer isn't powerful enough | $5 free credit for new accounts |
| **Smee.io** | Forwards GitHub webhooks to your computer during development | Free |

### Hardware requirements

- **Minimum:** Any modern computer with 8GB RAM (uses cloud AI)
- **Recommended:** 16GB+ RAM (can run local AI models with Ollama)

---

## Step-by-Step Development Guide

### Phase 0: Set Up Your Computer

**Goal:** Get everything installed and create the project.

**Time estimate:** 1–2 hours

```
STEP 0.1: Install Python
──────────────────────────
Go to https://www.python.org/downloads/
Download Python 3.11 or newer
Run the installer
IMPORTANT: Check the box that says "Add Python to PATH"

To verify it worked, open a terminal and type:
    python --version
You should see something like: Python 3.12.x


STEP 0.2: Install Node.js
──────────────────────────
Go to https://nodejs.org/
Download the LTS (Long Term Support) version
Run the installer

To verify:
    node --version
    npm --version


STEP 0.3: Install Docker
─────────────────────────
Go to https://docs.docker.com/get-docker/
Follow the instructions for your operating system
After install, open a terminal and type:
    docker --version


STEP 0.4: Install Git
──────────────────────
Go to https://git-scm.com/downloads
Download and install

To verify:
    git --version


STEP 0.5: Create the project
─────────────────────────────
Open a terminal and run these commands one by one:

    mkdir maintainerKi
    cd maintainerKi
    git init
    mkdir -p server/webhooks server/scorer server/duplicates server/labeler
    mkdir -p server/models server/api
    mkdir -p dashboard worker/tasks
    mkdir -p tests/unit tests/integration tests/fixtures
    touch README.md .gitignore .env.example


STEP 0.6: Set up Python virtual environment
────────────────────────────────────────────
A virtual environment keeps your project's packages separate from other projects.

    python -m venv venv

To activate it:
    On Mac/Linux:   source venv/bin/activate
    On Windows:     venv\Scripts\activate

You should see (venv) at the start of your terminal line.


STEP 0.7: Install Python packages
──────────────────────────────────
Create a file called requirements.txt with these contents:

    fastapi==0.115.0
    uvicorn==0.30.0
    httpx==0.27.0
    pydantic==2.9.0
    sqlalchemy==2.0.35
    alembic==1.13.0
    celery==5.4.0
    redis==5.1.0
    sentence-transformers==3.1.0
    PyGithub==2.4.0
    python-dotenv==1.0.1
    cryptography==43.0.0
    pytest==8.3.0
    pytest-asyncio==0.24.0
    pytest-httpx==0.30.0

Then install them:
    pip install -r requirements.txt


STEP 0.8: Set up Docker services
─────────────────────────────────
Create a file called docker-compose.yml:
(This sets up the database and job queue)

    version: "3.9"
    services:
      db:
        image: postgres:16
        environment:
          POSTGRES_USER: maintainerki
          POSTGRES_PASSWORD: maintainerki_dev_password
          POSTGRES_DB: maintainerki
        ports:
          - "5432:5432"
        volumes:
          - pgdata:/var/lib/postgresql/data

      redis:
        image: redis:7-alpine
        ports:
          - "6379:6379"

    volumes:
      pgdata:

Start the services:
    docker compose up -d

To verify they're running:
    docker compose ps
```

---

### Phase 1: Build the GitHub Connection

**Goal:** Your server receives a message from GitHub when a PR or issue is created.

**Time estimate:** 1–2 weeks

**What you will learn:** Webhooks, HTTP servers, GitHub Apps

```
STEP 1.1: Create the web server
────────────────────────────────
File: server/main.py

This is the "front door" of your app. It listens for incoming messages.

    What FastAPI does:
    - It's a Python framework that makes it easy to build web servers
    - You define "routes" (URLs that do different things)
    - When GitHub sends a POST request to /webhooks/github, your code runs


STEP 1.2: Create the webhook handler
─────────────────────────────────────
File: server/webhooks/github.py

This file does three things:
    1. Receives the message from GitHub
    2. Verifies it's really from GitHub (using a secret signature)
    3. Reads the data and decides what to do

    The webhook payload (the data GitHub sends) includes:
    - action: what happened ("opened", "closed", "edited")
    - pull_request or issue: all the details
    - repository: which repo this happened in
    - sender: who did it


STEP 1.3: Register a GitHub App
────────────────────────────────
A GitHub App is like an account for your tool on GitHub.

    1. Go to https://github.com/settings/apps
    2. Click "New GitHub App"
    3. Fill in:
       - Name: "maintainerKi" (or your chosen name)
       - Homepage URL: your GitHub repo URL
       - Webhook URL: your Smee.io URL (for development)
       - Webhook secret: a random password you create
    4. Under "Permissions":
       - Pull requests: Read & write
       - Issues: Read & write
       - Metadata: Read-only
    5. Under "Subscribe to events":
       - Check: Pull request
       - Check: Issues
    6. Click "Create GitHub App"
    7. After creation:
       - Note your App ID
       - Generate a private key (downloads a .pem file)
       - Save both — you'll need them

    8. Install the app on a test repository:
       - Go to your app's settings
       - Click "Install App"
       - Choose a test repo


STEP 1.4: Set up webhook forwarding for development
────────────────────────────────────────────────────
During development, GitHub can't reach your computer directly.
Smee.io acts as a bridge.

    1. Go to https://smee.io/
    2. Click "Start a new channel"
    3. Copy the URL (looks like https://smee.io/abc123xyz)
    4. Install the Smee client:
       npm install -g smee-client
    5. Run it:
       smee --url https://smee.io/YOUR_URL --target http://localhost:8000/webhooks/github


STEP 1.5: Create your .env file
────────────────────────────────
Copy .env.example to .env and fill in:

    GITHUB_APP_ID=your_app_id
    GITHUB_PRIVATE_KEY_PATH=./private-key.pem
    GITHUB_WEBHOOK_SECRET=your_webhook_secret
    DATABASE_URL=postgresql://maintainerki:maintainerki_dev_password@localhost:5432/maintainerki
    REDIS_URL=redis://localhost:6379
    LLM_PROVIDER=ollama
    LLM_MODEL=llama3.2
    LLM_API_URL=http://localhost:11434


STEP 1.6: Test the connection
─────────────────────────────
    1. Start your server: uvicorn server.main:app --reload --port 8000
    2. Start Smee: smee --url YOUR_SMEE_URL --target http://localhost:8000/webhooks/github
    3. Go to your test repo and create a new issue with any title
    4. Check your terminal — you should see the webhook data printed

    If you see the data → Phase 1 is complete!
```

---

### Phase 2: Add the AI Scoring Engine

**Goal:** When a PR/issue arrives, ask an AI model to evaluate its quality.

**Time estimate:** 2–3 weeks

**What you will learn:** LLM APIs, prompt engineering, background jobs

```
STEP 2.1: Set up Ollama (free, local AI)
─────────────────────────────────────────
    1. Go to https://ollama.ai/ and install Ollama
    2. Pull a model:
       ollama pull llama3.2
    3. Verify it works:
       ollama run llama3.2 "Say hello"

    If your computer is too slow, skip this and use OpenAI API instead.


STEP 2.2: Build the scorer module
──────────────────────────────────
File: server/scorer/quality.py

This module:
    1. Takes the PR/issue text as input
    2. Sends it to the AI model with a specific prompt
    3. Gets back a quality score and reasons
    4. Returns a structured result

    The prompt looks something like this:

    """
    You are a code review assistant for open source projects.
    Analyze this pull request and return a JSON response.

    Title: {title}
    Description: {body}
    Files changed: {files}
    Author: {author} (account age: {age}, previous contributions: {count})

    Score each category from 0 to 100:
    - quality: Is the code well-written?
    - relevance: Does this match the project's needs?
    - completeness: Is the description clear? Are tests included?
    - suspicion: Does this look AI-generated or spammy? (0 = not suspicious)

    Return ONLY valid JSON:
    {
      "quality": <number>,
      "relevance": <number>,
      "completeness": <number>,
      "suspicion": <number>,
      "summary": "<one sentence explanation>",
      "suggested_labels": ["<label1>", "<label2>"]
    }
    """


STEP 2.3: Build the LLM client
───────────────────────────────
File: server/scorer/llm_client.py

This file talks to the AI model. It supports two providers:

    Provider 1: Ollama (local, free)
    - API endpoint: http://localhost:11434/api/chat
    - Send a POST request with the prompt
    - Get back the AI's response

    Provider 2: OpenAI-compatible API (cloud, paid)
    - API endpoint: https://api.openai.com/v1/chat/completions
    - Same idea, different URL and format

    The client reads from .env which provider to use.
    This means you can switch between local and cloud without changing code.


STEP 2.4: Set up the job queue
───────────────────────────────
File: worker/tasks/score_task.py

Why a job queue?
    - GitHub expects a response within 10 seconds
    - AI scoring takes 15-60 seconds
    - Solution: respond to GitHub immediately ("got it!")
       then process in the background

    We use Celery + Redis for this:
    - Celery is a Python library for background jobs
    - Redis is a fast in-memory database used as the job queue

    How it works:
    1. Webhook handler receives PR data
    2. Handler puts a "score this PR" job on the Redis queue
    3. Handler responds to GitHub immediately: "200 OK"
    4. A separate worker process picks up the job from Redis
    5. Worker calls the AI scorer
    6. Worker saves the result to the database
    7. Worker calls GitHub API to add labels


STEP 2.5: Create the database tables
─────────────────────────────────────
File: server/models/tables.py

Tables you need:

    Table: repositories
    ├── id (unique number)
    ├── github_id (GitHub's ID for this repo)
    ├── name (like "facebook/react")
    └── settings (JSON — custom labels, thresholds)

    Table: contributions
    ├── id (unique number)
    ├── repository_id (which repo)
    ├── github_id (GitHub's ID for this PR/issue)
    ├── type ("pull_request" or "issue")
    ├── title
    ├── body
    ├── author_username
    ├── author_account_age
    ├── author_contribution_count
    ├── quality_score (0-100)
    ├── relevance_score (0-100)
    ├── completeness_score (0-100)
    ├── suspicion_score (0-100)
    ├── overall_score (0-100, weighted average)
    ├── suggested_labels (list of strings)
    ├── ai_summary (one sentence explanation)
    ├── embedding (vector for duplicate detection — added in Phase 3)
    ├── duplicate_of_id (link to potential duplicate — added in Phase 3)
    ├── status ("pending", "scored", "reviewed", "dismissed")
    ├── created_at (when the PR/issue was created)
    └── scored_at (when maintainerKi finished scoring)

    Table: scoring_feedback
    ├── id
    ├── contribution_id (which PR/issue)
    ├── maintainer_action ("agreed", "disagreed", "override")
    ├── correct_labels (what it should have been)
    └── created_at

    This last table is important — it lets maintainers tell maintainerKi
    when it got something wrong, so you can improve over time.


STEP 2.6: Test the scoring
──────────────────────────
    1. Start your server, worker, and Smee
    2. Open a new PR on your test repo
    3. Wait 30-60 seconds
    4. Check: does the PR now have labels added by maintainerKi?
    5. Check: does your database have a new row in contributions?

    If yes → Phase 2 is complete!
```

---

### Phase 3: Add Duplicate Detection

**Goal:** Detect when a new issue is similar to an existing one.

**Time estimate:** 1–2 weeks

**What you will learn:** Text embeddings, vector similarity, semantic search

```
STEP 3.1: Understand embeddings (plain explanation)
────────────────────────────────────────────────────
An "embedding" turns text into a list of numbers (called a vector).
Similar texts get similar numbers.

    Example:
    "Fix the login button" → [0.23, 0.87, 0.12, 0.45, ...]
    "Login button is broken" → [0.21, 0.85, 0.14, 0.44, ...]
    "Add dark mode theme"   → [0.91, 0.11, 0.78, 0.03, ...]

    The first two are about the same thing → their numbers are close.
    The third is about something different → its numbers are far away.

    We use "cosine similarity" to measure how close two vectors are:
    - 1.0 = identical meaning
    - 0.8+ = very similar (probably duplicate)
    - 0.5 = somewhat related
    - 0.0 = completely unrelated


STEP 3.2: Set up the embedding model
─────────────────────────────────────
File: server/duplicates/embedder.py

    We use the "sentence-transformers" library with a multilingual model.
    Model: "all-MiniLM-L6-v2" (small, fast, runs on any computer)

    This model:
    - Runs locally on your computer (no API needed)
    - Takes text in, gives a vector out
    - Works in many languages


STEP 3.3: Build the duplicate detector
───────────────────────────────────────
File: server/duplicates/detector.py

    How it works:
    1. New issue/PR arrives
    2. Create an embedding of its title + body
    3. Compare this embedding to all stored embeddings for this repo
    4. If any similarity is above 0.80 → flag as potential duplicate
    5. Return the top 3 most similar existing issues

    For small repos (under 10,000 issues):
    - Compare directly using cosine similarity in Python
    - This is fast enough

    For large repos (over 10,000 issues):
    - Use pgvector (a PostgreSQL extension for vector search)
    - This is much faster for large datasets


STEP 3.4: Store embeddings in the database
───────────────────────────────────────────
    Option A (simple): Store as a JSON list of numbers in the contributions table
    Option B (better): Use pgvector extension in PostgreSQL

    For your MVP, Option A is fine. Switch to B when performance matters.


STEP 3.5: Connect it to the scoring pipeline
─────────────────────────────────────────────
    Update the score_task.py worker:

    After scoring quality → also:
    1. Generate embedding for this contribution
    2. Search for duplicates
    3. If duplicate found:
       - Add "maintainerki:possible-duplicate" label on GitHub
       - Add comment: "This looks similar to #123 — is this a duplicate?"
    4. Save embedding and duplicate link to database


STEP 3.6: Test duplicate detection
───────────────────────────────────
    1. Create an issue on your test repo: "Login button doesn't work on mobile"
    2. Wait for maintainerKi to process it
    3. Create another issue: "The login button is broken on phones"
    4. Wait for maintainerKi to process it
    5. Check: did maintainerKi flag the second one as a possible duplicate?

    If yes → Phase 3 is complete!
```

---

### Phase 4: Build the Dashboard

**Goal:** A web page where maintainers see their sorted inbox.

**Time estimate:** 2–3 weeks

**What you will learn:** React, API design, data visualization

```
STEP 4.1: Set up the React project
───────────────────────────────────
    cd dashboard
    npx create-react-app . --template typescript
    npm install axios recharts date-fns


STEP 4.2: Build the API endpoints
──────────────────────────────────
File: server/api/routes.py

    Endpoints your dashboard needs:

    GET /api/repos
    → Returns list of repositories maintainerKi is installed on

    GET /api/repos/{repo_id}/inbox
    → Returns all contributions, sorted by priority
    → Supports filters: ?status=pending&type=pull_request&min_score=50

    GET /api/repos/{repo_id}/stats
    → Returns metrics: queue depth, avg response time, score distribution

    GET /api/contributions/{id}
    → Returns full details for one contribution

    POST /api/contributions/{id}/feedback
    → Maintainer says "this score was wrong" (for improving accuracy)


STEP 4.3: Build the dashboard pages
────────────────────────────────────
    Page 1: Repository Selector
    ├── Shows all repos where maintainerKi is installed
    └── Click one to see its inbox

    Page 2: Inbox (the main page)
    ├── Sorted list of PRs and issues
    ├── Each item shows: title, score, labels, author, time
    ├── Color-coded: green (high quality), yellow (medium), red (suspicious)
    ├── Filter tabs: All / PRs only / Issues only / Duplicates / Suspicious
    ├── Search bar
    └── Click an item to see details

    Page 3: Detail View
    ├── Full PR/issue description
    ├── AI analysis breakdown (quality, relevance, completeness, suspicion)
    ├── Duplicate candidates (if any)
    ├── Link to the actual PR/issue on GitHub
    └── Feedback buttons: "Good score" / "Wrong score"

    Page 4: Stats (optional but nice)
    ├── Queue depth over time (line chart)
    ├── Score distribution (bar chart)
    ├── Contributors breakdown (new vs returning)
    └── Average time from PR creation to first review


STEP 4.4: Test the dashboard
─────────────────────────────
    1. Start the backend: uvicorn server.main:app --reload --port 8000
    2. Start the frontend: cd dashboard && npm start
    3. Open http://localhost:3000
    4. You should see your test repo and any scored contributions

    If you see data → Phase 4 is complete!
```

---

### Phase 5: Polish and Package

**Goal:** Make maintainerKi easy for anyone to install and use.

**Time estimate:** 1–2 weeks

```
STEP 5.1: Create a Dockerfile
──────────────────────────────
    This packages your entire app into a single container
    that anyone can run with one command.


STEP 5.2: Create a docker-compose.production.yml
─────────────────────────────────────────────────
    This runs everything together:
    - maintainerKi server
    - Celery worker
    - PostgreSQL database
    - Redis queue
    - Dashboard (served by nginx)


STEP 5.3: Write a setup wizard
──────────────────────────────
    When someone runs maintainerKi for the first time:
    1. Ask for their GitHub App credentials
    2. Test the connection
    3. Ask which repos to monitor
    4. Set default score thresholds
    5. Done — maintainerKi is running


STEP 5.4: Write documentation
─────────────────────────────
    - Installation guide (for non-technical maintainers)
    - Configuration guide (for customization)
    - Troubleshooting guide
    - FAQ
```

---

### Phase 6: Go to Production

**Goal:** Deploy maintainerKi so it runs 24/7 and other people can use it.

**Time estimate:** 1–2 weeks

```
STEP 6.1: Choose a hosting option
──────────────────────────────────
    Option A: Self-hosted (cheapest)
    - Run on a VPS (Virtual Private Server)
    - Providers: Hetzner ($5/mo), DigitalOcean ($6/mo), Vultr ($6/mo)
    - You manage everything yourself

    Option B: Cloud hosting (easier)
    - Use Railway, Render, or Fly.io
    - They handle deployment and scaling
    - Slightly more expensive but much less work

    Option C: GitHub App Marketplace (future goal)
    - Publish maintainerKi as a GitHub App anyone can install with one click
    - Requires a hosted version that handles multiple users


STEP 6.2: Set up the production environment
────────────────────────────────────────────
    1. Get a VPS or cloud hosting account
    2. Point a domain name to your server (e.g., maintainerki.yourdomain.com)
    3. Set up HTTPS (required for GitHub webhooks in production)
       - Use Let's Encrypt (free) with Caddy or nginx
    4. Copy your docker-compose.production.yml to the server
    5. Set your production .env variables
    6. Run: docker compose -f docker-compose.production.yml up -d


STEP 6.3: Set up monitoring
────────────────────────────
    You need to know if maintainerKi crashes or slows down.

    Simple option: UptimeRobot (free)
    - Pings your server every 5 minutes
    - Sends you an email/SMS if it goes down

    Better option: Add logging
    - Use Python's logging module
    - Log every webhook received, every score computed, every error
    - Store logs in a file or use a service like Logtail


STEP 6.4: Update your GitHub App settings
──────────────────────────────────────────
    1. Go to your GitHub App settings
    2. Change the Webhook URL from Smee.io to your production URL
       (https://maintainerki.yourdomain.com/webhooks/github)
    3. Save


STEP 6.5: Test in production
─────────────────────────────
    1. Install maintainerKi on a real repo (start with your own)
    2. Create a test PR
    3. Verify labels appear and dashboard updates
    4. Monitor logs for errors

    If everything works → You're in production!
```

---

## How to Test Everything

Testing is how you make sure your code works before other people use it. Here's a complete testing guide.

### Types of Tests

```
┌─────────────────────────────────────────────────────────────┐
│                    Testing Pyramid                           │
│                                                              │
│                      /\                                      │
│                     /  \        End-to-End Tests              │
│                    / E2E\       (few — slow but thorough)     │
│                   /──────\                                    │
│                  /        \     Integration Tests             │
│                 / INTEGR.  \    (medium — test parts working  │
│                /────────────\    together)                    │
│               /              \                                │
│              /    UNIT TESTS  \  Unit Tests                   │
│             /                  \ (many — fast, test one thing │
│            /────────────────────\ at a time)                  │
└─────────────────────────────────────────────────────────────┘
```

### Unit Tests (test individual pieces)

```
File: tests/unit/test_scorer.py

What to test:
├── Does the scorer return a valid score (0-100)?
├── Does it handle missing fields (no PR body)?
├── Does it handle AI model errors gracefully?
├── Does it reject invalid AI responses?
└── Does it correctly calculate the overall score?

How to run:
    pytest tests/unit/ -v

Example test:

    def test_score_is_in_valid_range():
        """The quality score should always be between 0 and 100."""
        result = score_contribution(
            title="Fix typo in README",
            body="Changed 'teh' to 'the'",
            files_changed=1,
            author_age_days=365,
            author_contributions=10
        )
        assert 0 <= result.quality_score <= 100
        assert 0 <= result.suspicion_score <= 100


    def test_handles_empty_body():
        """PRs with no description should still get scored (lower quality)."""
        result = score_contribution(
            title="Update files",
            body="",
            files_changed=50,
            author_age_days=1,
            author_contributions=0
        )
        assert result.completeness_score < 30


    def test_suspicious_pattern_detected():
        """A brand new account with many files should score high suspicion."""
        result = score_contribution(
            title="Refactor entire codebase",
            body="Used AI to improve all files",
            files_changed=200,
            author_age_days=1,
            author_contributions=0
        )
        assert result.suspicion_score > 70
```

```
File: tests/unit/test_duplicates.py

What to test:
├── Do identical texts return similarity > 0.95?
├── Do similar texts return similarity > 0.80?
├── Do completely different texts return similarity < 0.30?
├── Does it handle empty text?
└── Does it handle very long text?

Example test:

    def test_identical_texts_are_detected():
        """Identical issues should have near-perfect similarity."""
        embedding1 = create_embedding("Login button is broken")
        embedding2 = create_embedding("Login button is broken")
        similarity = cosine_similarity(embedding1, embedding2)
        assert similarity > 0.95


    def test_similar_texts_are_detected():
        """Rephrased issues should still be detected as similar."""
        embedding1 = create_embedding("Login button doesn't work on mobile")
        embedding2 = create_embedding("The login button is broken on phones")
        similarity = cosine_similarity(embedding1, embedding2)
        assert similarity > 0.75


    def test_different_texts_are_not_flagged():
        """Unrelated issues should not be flagged as duplicates."""
        embedding1 = create_embedding("Login button doesn't work on mobile")
        embedding2 = create_embedding("Add dark mode support to settings page")
        similarity = cosine_similarity(embedding1, embedding2)
        assert similarity < 0.40
```

```
File: tests/unit/test_webhook.py

What to test:
├── Does it verify the GitHub signature correctly?
├── Does it reject requests with wrong signatures?
├── Does it parse pull_request events correctly?
├── Does it parse issue events correctly?
└── Does it ignore events we don't care about (like "labeled")?
```

### Integration Tests (test parts working together)

```
File: tests/integration/test_pipeline.py

What to test:
├── Webhook → Queue → Scorer → Database (full pipeline)
├── Webhook → Queue → Scorer → GitHub API (labels added)
├── Webhook → Queue → Duplicate Detector → GitHub API (comment added)
└── API → Database → Dashboard response (correct data returned)

How to run (requires Docker services running):
    pytest tests/integration/ -v

Example test:

    async def test_full_scoring_pipeline():
        """
        When a webhook arrives for a new PR,
        the PR should end up scored in the database.
        """
        # Simulate a GitHub webhook
        webhook_data = load_fixture("pull_request_opened.json")
        response = await client.post(
            "/webhooks/github",
            json=webhook_data,
            headers=make_signature_headers(webhook_data)
        )
        assert response.status_code == 200

        # Wait for the background worker to process it
        await wait_for_task_completion(timeout=60)

        # Check the database
        contribution = get_contribution_by_github_id(webhook_data["pull_request"]["id"])
        assert contribution is not None
        assert contribution.status == "scored"
        assert 0 <= contribution.overall_score <= 100
```

### End-to-End Tests (test everything together)

```
File: tests/e2e/test_full_flow.py

What to test:
├── Install maintainerKi on a test repo
├── Create a real PR via GitHub API
├── Wait for maintainerKi to process it
├── Check that labels were added on GitHub
├── Check that the dashboard shows the PR
└── Submit feedback and verify it's saved

How to run:
    These tests need a real GitHub repo and running maintainerKi instance.
    Only run these before releases, not on every change.

    MAINTAINERKI_TEST_REPO=owner/repo pytest tests/e2e/ -v
```

### Test Fixtures (sample data)

```
File: tests/fixtures/pull_request_opened.json

    This is a saved copy of a real GitHub webhook payload.
    You use it in tests so you don't need to hit GitHub every time.

    How to get one:
    1. Go to your GitHub App settings
    2. Click "Advanced"
    3. Look at "Recent Deliveries"
    4. Copy the payload JSON
    5. Save it in tests/fixtures/

    Create fixtures for:
    ├── pull_request_opened.json      (new PR)
    ├── pull_request_edited.json      (edited PR)
    ├── issues_opened.json            (new issue)
    ├── issues_opened_spam.json       (obvious spam for testing)
    ├── issues_opened_duplicate.json  (similar to another fixture)
    └── pull_request_bot.json         (from a bot account)
```

### Running All Tests

```
# Run only fast unit tests (do this constantly while developing)
pytest tests/unit/ -v

# Run unit + integration tests (do this before committing code)
pytest tests/unit/ tests/integration/ -v

# Run everything including slow e2e tests (do this before releases)
pytest -v

# Run tests and show code coverage (how much of your code is tested)
pytest --cov=server --cov-report=html
# Then open htmlcov/index.html in your browser to see the report

# Run a specific test file
pytest tests/unit/test_scorer.py -v

# Run a specific test
pytest tests/unit/test_scorer.py::test_score_is_in_valid_range -v
```

---

## Tech Stack Explained

Every technology used in this project, what it does, and why we chose it.

| Technology | What it is | Why we use it |
|-----------|-----------|--------------|
| **Python** | Programming language | Most AI libraries are in Python. Large community. Easy to read. |
| **FastAPI** | Web server framework | Fast, modern, automatic API documentation. |
| **Celery** | Background job processor | Handles slow tasks (AI scoring) without blocking webhooks. |
| **Redis** | In-memory database | Fast job queue for Celery. Also useful for caching. |
| **PostgreSQL** | Main database | Reliable, supports vectors (pgvector), good for complex queries. |
| **SQLAlchemy** | Database toolkit | Write Python instead of SQL. Handles database migrations. |
| **sentence-transformers** | Embedding library | Creates text embeddings locally. No API needed. Free. |
| **PyGithub** | GitHub API library | Makes it easy to interact with GitHub from Python. |
| **React** | Frontend framework | Popular, lots of tutorials, good for dashboards. |
| **Docker** | Container platform | Package everything so it runs the same on any computer. |
| **Ollama** | Local AI runner | Run AI models on your computer for free. No API keys needed. |

---

## Glossary (Words Explained)

| Word | What it means |
|------|--------------|
| **API** | Application Programming Interface — a way for programs to talk to each other |
| **Background job** | A task that runs separately from the main program, so the main program isn't slowed down |
| **CI/CD** | Continuous Integration / Continuous Delivery — automatic testing and deployment |
| **Container** | A packaged version of your app that includes everything it needs to run |
| **Cosine similarity** | A math formula that measures how similar two lists of numbers are (0 = different, 1 = identical) |
| **Docker** | Software that runs containers |
| **Embedding** | Turning text into a list of numbers that represents its meaning |
| **Endpoint** | A specific URL that does a specific thing (like /api/repos returns a list of repos) |
| **FastAPI** | A Python library for building web servers |
| **GitHub App** | A bot account on GitHub that can read and modify repos it's installed on |
| **JSON** | A text format for storing data, like: {"name": "maintainerKi", "version": 1} |
| **LLM** | Large Language Model — the AI that reads text and generates responses |
| **MVP** | Minimum Viable Product — the smallest version of your app that's still useful |
| **Ollama** | Software that runs AI models on your own computer |
| **Payload** | The data sent in a message (the webhook payload is the PR/issue details) |
| **PR** | Pull Request — a proposed change to code in a repository |
| **Queue** | A waiting line for tasks — first in, first out |
| **Redis** | A very fast database that stores things in memory |
| **REST API** | A common style for building APIs using HTTP methods (GET, POST, etc.) |
| **Route** | A URL pattern that triggers specific code (like /webhooks/github) |
| **Smee** | A service that forwards webhooks to your local computer during development |
| **Vector** | A list of numbers — in our case, numbers that represent the meaning of text |
| **VPS** | Virtual Private Server — a computer in the cloud you rent |
| **Webhook** | A message sent automatically when something happens (GitHub sends one when a PR is created) |

---

## Contributing

We welcome contributions! Here's how:

1. Fork this repository
2. Create a branch: `git checkout -b my-feature`
3. Make your changes
4. Run tests: `pytest -v`
5. Commit: `git commit -m "Add my feature"`
6. Push: `git push origin my-feature`
7. Open a Pull Request

Please be kind and respectful. We follow the [Contributor Covenant](https://www.contributor-covenant.org/) code of conduct.

---

## License

MIT License — free to use, modify, and distribute.

---

## Support

- **GitHub Issues:** Report bugs or request features
- **Discussions:** Ask questions and share ideas
- **Discord:** Community chat (link coming soon)

---

*Built with ❤️ for open source maintainers everywhere.*
