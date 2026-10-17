# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout note

The git root is one level **above** this directory (`D:\Vedant\claimTracker`); the project lives in
`claimtracker/`. Run `git` from either, but build/test commands from `claimtracker/backend`.

Only `backend/` is implemented so far. `frontend/` (Next.js) and `automation/` (n8n workflow JSON)
are referenced by `README.md`, `docker-compose.yml`, and `.github/workflows/ci.yml` but **do not
exist yet** — the frontend CI job and the `frontend`/`n8n` compose services will fail until they
are created. `docs/DEPLOY_AWS_EC2.md` and the `samples/*.pdf` files are likewise still missing
(run `python samples/create_sample_pdfs.py`, needs `reportlab`, to generate the PDFs).

## Commands

All backend commands run from `backend/`:

```bash
pip install -r requirements.txt

alembic upgrade head                      # apply migrations
alembic revision --autogenerate -m "msg"  # new migration (imports app.models for metadata)

uvicorn app.main:app --reload             # dev server → http://localhost:8000/docs

pytest -v                                 # full suite (coverage gate is in pytest.ini)
pytest tests/unit/test_pii_masker.py -v   # one file
pytest tests/unit/test_pii_masker.py::test_name -v
pytest --no-cov -q                        # skip the --cov-fail-under=60 gate while iterating

ruff check app/ tests/                    # the lint CI runs
```

`ruff` is not in `requirements.txt` (CI installs it separately) and there is no `pyproject.toml`
or `ruff.toml`, so it runs on defaults — `pip install ruff` before linting locally.

Docker (from `claimtracker/`): `docker compose up --build`. The backend service runs
`alembic upgrade head` before uvicorn, so no manual migration step is needed there.

### Environment

`app/core/config.py` requires `SECRET_KEY`, `GROQ_API_KEY`, and `DATABASE_URL` — the app will not
import without them. Copy `.env.example` → `.env` (compose reads `.env` at the repo root; local
dev reads `backend/.env`). For local dev without Postgres set
`DATABASE_URL=sqlite+aiosqlite:///./claimtracker_dev.db`.

`pytest.ini` sets `asyncio_mode = auto`, so async tests need no `@pytest.mark.asyncio` (existing
tests have it anyway). `tests/conftest.py` hardcodes its own in-memory SQLite engine and overrides
the `get_db` dependency, so tests never touch `DATABASE_URL` — but `Settings` still has to
construct, so the three required vars must be set in the environment.

OCR requires system binaries: `tesseract-ocr` and `poppler-utils`. `TESSERACT_CMD` defaults to the
Linux path `/usr/bin/tesseract`; override it when running natively on Windows.

## Architecture

### Layering (enforced by convention, follow it)

`api/` (routers, thin) → `services/` (orchestration, business rules) → `repositories/` (all SQL)
→ `models/` (SQLAlchemy). Rules that already hold throughout:

- **No raw SQL in services** except `analytics_service.py`, which deliberately runs `text()` queries
  mirroring `db/analytics.sql`.
- **No `os.environ`** anywhere — always `get_settings()` from `app/core/config.py` (an `lru_cache`
  singleton).
- **No stdlib `logging`** — `get_logger()` from `app/core/logging.py` (structlog, JSON, kwargs-style
  event fields: `logger.info("claim_submitted", claim_id=...)`).
- **Services raise domain exceptions** from `app/core/exceptions.py`, never `HTTPException`. The
  status-code mapping lives in handlers registered in `app/main.py::create_app`. Routers may raise
  `HTTPException` directly (and the role guards in `core/dependencies.py` do).
- Routers have **no `/api/v1` prefix** — paths are `/auth`, `/claims`, `/exclusions`, `/handbooks`,
  `/analytics`, plus `/health`. Reviews mount under `/claims/{claim_id}/review`.

Auth is JWT bearer (HS256) with roles `user` / `reviewer` / `admin`; use the
`require_reviewer` / `require_admin` dependencies from `app/core/dependencies.py` rather than
checking `current_user.role` inline. Ownership filtering for regular users happens in
`ClaimService.get_claim`.

### The claim pipeline

`POST /claims` validates + persists synchronously, then returns `(claim, _pipeline)`; the router
schedules `_pipeline` as a FastAPI `BackgroundTask`. The pipeline closure in
`services/claim_service.py` **opens its own `AsyncSessionLocal` session** (the request session is
already closed) and captures only plain values/IDs, never ORM objects. Any exception there sets the
claim to `NEEDS_REVIEW` and writes a `PIPELINE_ERROR` audit row — the pipeline must never leave a
claim stuck in `PROCESSING`.

Stages: status→`PROCESSING` → OCR (`ocr_service`) → LLM extraction (`extraction_service`) →
validator chain (`decision_service`) → persist `Decision` + update status → `AuditLog` →
best-effort n8n webhook (`_fire_webhook` never raises).

### Validator chain (Chain of Responsibility)

`services/decision_service.py` builds and runs, **in this order**, stopping at the first non-`PASS`:

1. `completeness` 2. `amount_check` 3. `consistency_check` 4. `exclusion_check`
(all deterministic) — then 5. `rag_policy_check` (the only LLM step).

The ordering is load-bearing, not incidental: the deterministic exclusion check runs *before* the
LLM specifically because the LLM hallucinated approvals for excluded conditions. Do not reorder,
and do not move exclusion logic into the prompt. `ValidationOutcome` maps to claim status via
`_OUTCOME_TO_STATUS` (`PASS`→`ACCEPTED`, `FAIL`→`REJECTED`, `NEEDS_REVIEW`→`NEEDS_REVIEW`).

New validators subclass `BaseValidator` (`app/validators/base.py`): implement `name` and
`async validate(ctx) -> ValidationResult`, **never raise** — return `NEEDS_REVIEW` instead. All
inputs come from the `ClaimContext` dataclass, which the pipeline populates up front so validators
never query the DB. If a validator needs new data, add a field to `ClaimContext` and fill it in
`claim_service._pipeline`.

Any failure of the RAG step falls back to `NEEDS_REVIEW` rather than deciding — keep that bias
(fail-safe to human review, never auto-decide) in new code.

### RAG / LLM

- `app/llm/base.py` defines the abstract `LLMClient` (Strategy); `groq_client.py` is the only
  implementation. Services depend on the ABC, so a new backend needs no service changes.
- Prompts are **versioned files** in `app/prompts/` (`extract_v1.txt`, `decision_v1.txt`), loaded by
  a `PROMPT_VERSION` constant in the consuming module and recorded on `Decision` / `ExtractedFields`
  / `AuditLog`. When changing a prompt, add `*_v2.txt` and bump the constant rather than editing in
  place — the stored version is what makes past decisions auditable.
- `services/rag_service.py` keeps a **module-level `_RAGCache` singleton** for the FAISS index,
  chunks, and SentenceTransformer, loaded lazily from the active `HandbookVersion`'s
  `faiss_index_path`. Ingesting a handbook must call `RAGService.invalidate_cache()`, or searches
  keep hitting the stale index. Embedding/search run via `run_in_executor` to keep the event loop
  free — preserve that for any new CPU-bound model work.
- Handbook ingestion (`services/handbook_service.py`): pdfplumber text → 1000-char chunks with
  200-char overlap → `all-MiniLM-L6-v2` embeddings → `faiss.IndexFlatIP` on normalised vectors
  (cosine) → `faiss_index/<version_id>/{index.faiss,chunks.json}`, plus seeding the `exclusions`
  table from the handbook's "General Exclusions" section. Exactly one `HandbookVersion` is active
  (`deactivate_all` then `activate`).
- Every LLM call is PII-masked first via `services/pii_masker.py`, and
  `CONFIDENCE_THRESHOLD` (default 0.70) forces `NEEDS_REVIEW` below threshold regardless of the
  LLM's stated outcome. Both behaviours are contractual — see `docs/RESPONSIBLE_AI.md`.

### Database

SQLAlchemy 2.0 async (`Mapped` / `mapped_column`), one `Base` in `app/core/database.py` re-exported
through `app/models/base.py`. New models **must** be imported in `app/models/__init__.py` or Alembic
autogenerate will miss them and `Base.metadata.create_all` in tests won't create their tables.

Models use Postgres-specific types (`postgresql.UUID(as_uuid=True)`, `JSONB`) and native
`Enum(...)` types. Two consequences to work around rather than "fix":

- The SQLite test DB works because SQLAlchemy renders these types acceptably for
  `create_all`, but anything relying on real JSONB operators or enum behaviour will not be
  exercised by tests.
- `analytics_service.py` / `db/analytics.sql` use `DATE_TRUNC`, `FILTER (WHERE ...)`, `RANK() OVER`
  and CTEs — **Postgres only**. Analytics cannot be tested against the SQLite fixture; verify
  against a real Postgres (e.g. via `docker compose`).

Claim status values (`PENDING`, `PROCESSING`, `ACCEPTED`, `REJECTED`, `NEEDS_REVIEW`) appear in the
`claim_status_enum` DB type, `ClaimStatus` in `models/claim.py`, and string literals across
services — changing the set requires a migration plus updates in all three places.

Repositories extend `BaseRepository` (generic CRUD, `flush`-based). **Repositories flush; services
commit** — `create()` does not commit, so a service that forgets `await session.commit()` silently
discards work.

## Reference docs

- `docs/ARCHITECTURE.md` — component diagram, claim-submission data flow, design decisions
- `docs/RESPONSIBLE_AI.md` — PII masking, deterministic-before-LLM rationale, audit, prompt-injection
  defence (bill text is wrapped in delimiters with instructions to ignore embedded commands)
- `docs/ER_DIAGRAM.md`, `docs/INTERVIEW_NOTES.md` — schema; trade-offs, known limits, scaling plan
- `README.md` — phase roadmap (phases 2–9 are marked pending there, though much of that code is
  present; treat the code as the source of truth)
