# ClaimTracker

> **AI-powered health insurance claims processing platform**  
> Automates the 15–20 day manual claims review cycle down to seconds using OCR, RAG, and LLM reasoning.

---

## Problem

Insurers receive thousands of medical bills that human consultants manually cross-reference against a policy handbook — a process taking 15–20 days per claim with high error rates. ClaimTracker automates this: a user uploads a bill, the system extracts the details, checks the claim against the handbook using Retrieval-Augmented Generation (RAG), and returns an ACCEPTED / REJECTED / NEEDS_REVIEW decision with a cited executive summary — in seconds.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        ClaimTracker                             │
│                                                                 │
│  ┌──────────┐     ┌──────────────────────────────────────────┐  │
│  │ Next.js  │────▶│              FastAPI Backend              │  │
│  │ Frontend │     │                                          │  │
│  └──────────┘     │  ┌─────────┐  ┌───────────────────────┐ │  │
│                   │  │  Auth   │  │   Claim Pipeline      │ │  │
│  ┌──────────┐     │  │  (JWT)  │  │                       │ │  │
│  │   n8n    │◀────│  └─────────┘  │  OCR Service          │ │  │
│  │Automation│     │               │  Extraction Service   │ │  │
│  └──────────┘     │  ┌──────────┐ │  Validator Chain      │ │  │
│                   │  │PostgreSQL│ │  ├─ Completeness       │ │  │
│  ┌──────────┐     │  │SQLAlchemy│ │  ├─ Amount Check       │ │  │
│  │  FAISS   │────▶│  └──────────┘ │  ├─ Consistency        │ │  │
│  │  Index   │     │               │  ├─ Exclusion Check    │ │  │
│  └──────────┘     │  ┌──────────┐ │  └─ RAG Policy Check  │ │  │
│                   │  │  Groq    │ │                       │ │  │
│                   │  │  (LLM)   │ │  Decision Service     │ │  │
│                   │  └──────────┘ └───────────────────────┘ │  │
│                   └──────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Features

| Feature | Detail |
|---|---|
| **OCR + Extraction** | pytesseract (scanned) + pdfplumber (digital PDFs) → LLM JSON extraction |
| **Validator Chain** | 5-step Chain of Responsibility: completeness → amount → consistency → exclusions → RAG |
| **RAG Policy Check** | FAISS + sentence-transformers + Groq Llama 3 with cited clauses |
| **Confidence Score** | Below threshold → auto-routes to NEEDS_REVIEW |
| **Human-in-the-Loop** | Reviewer queue with approve / reject / override + audit log |
| **PII Masking** | Names, phone numbers, IDs masked before LLM call |
| **Analytics Dashboard** | 5 SQL queries: monthly rates, RANK() window, CTE processing time, JOIN claims-per-user |
| **n8n Automation** | Email + Slack notifications + Google Sheets logging on claim decided |
| **Audit Trail** | Every AI call logged: model, prompt version, retrieved chunks, confidence |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2.0 |
| Database | PostgreSQL (SQLite for local dev) + Alembic migrations |
| AI / LLM | Groq API (Llama 3.x) + sentence-transformers + FAISS |
| OCR | pytesseract + pdf2image + pdfplumber |
| Frontend | Next.js 14 App Router + TypeScript + Tailwind CSS |
| Automation | n8n (Docker) |
| DevOps | Docker + docker-compose + GitHub Actions CI |
| Deployment | AWS EC2 (see `docs/DEPLOY_AWS_EC2.md`) |

---

## Quick Start (Docker)

```bash
# 1. Clone and configure
git clone <repo-url> claimtracker
cd claimtracker
cp .env.example .env
# Edit .env — set SECRET_KEY and GROQ_API_KEY

# 2. Start all services
docker compose up --build

# 3. Run migrations
docker compose exec backend alembic upgrade head

# 4. Access
#   API docs:    http://localhost:8000/docs
#   Frontend:    http://localhost:3000
#   n8n:         http://localhost:5678
```

---

## Local Dev (no Docker)

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
# Set DATABASE_URL=sqlite+aiosqlite:///./dev.db in .env
alembic upgrade head
uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

---

## Running Tests

```bash
cd backend
pytest -v --cov=app
```

---

## Project Structure

```
claimtracker/
├── backend/          # FastAPI + AI pipeline
├── frontend/         # Next.js App Router
├── db/               # analytics.sql
├── docs/             # Architecture, ER diagram, interview notes
├── automation/       # n8n workflow JSON
├── samples/          # Test PDFs for all 4 claim scenarios
└── docker-compose.yml
```

---

## Phases

| Phase | Status | What |
|---|---|---|
| 1 | ✅ Complete | Repo, Docker, DB models, Alembic, Auth |
| 2 | 🔜 Next | Handbook ingestion + FAISS index |
| 3 | 🔜 | OCR + LLM extraction |
| 4 | 🔜 | Validator chain + exclusion engine |
| 5 | 🔜 | RAG decision + executive summary |
| 6 | 🔜 | Reviewer flow + audit logs |
| 7 | 🔜 | Frontend pages |
| 8 | 🔜 | Analytics SQL + dashboard |
| 9 | 🔜 | n8n, CI, deployment docs |

---

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — Component diagram, design decisions
- [`docs/ER_DIAGRAM.md`](docs/ER_DIAGRAM.md) — Mermaid ER diagram
- [`docs/RESPONSIBLE_AI.md`](docs/RESPONSIBLE_AI.md) — PII masking, audit, explainability
- [`docs/INTERVIEW_NOTES.md`](docs/INTERVIEW_NOTES.md) — Tech choices, trade-offs, scaling plan
- [`docs/DEPLOY_AWS_EC2.md`](docs/DEPLOY_AWS_EC2.md) — EC2 deployment guide

---

## Responsible AI

- PII (name, phone, address, ID numbers) masked before any LLM call
- Every AI decision logged with prompt version, model, retrieved chunks, and confidence
- Deterministic exclusion check runs **before** the LLM to prevent hallucinated approvals
- Confidence below threshold → human review (never auto-decide)
- Prompt injection protection: bill text wrapped in delimiters, model instructed to ignore embedded instructions

See [`docs/RESPONSIBLE_AI.md`](docs/RESPONSIBLE_AI.md).
