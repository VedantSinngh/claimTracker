# Known Issues

Status as of the `feat/backend-closeout` branch. Each entry says what is wrong,
how it was found, what it breaks, and the recommended fix.

Everything in **Open** below was found by tests written during the close-out.
The tests are committed as-is and currently fail — they are the reproduction
case, so they should stay red until the bug is fixed rather than be skipped.

---

## OPEN — must fix before the demo

### 1. `parse_general_exclusions` seeds *covered benefits* as exclusions ⚠️ CRITICAL

**The bug.** `app/services/handbook_service.py::parse_general_exclusions` finds
its section with `_EXCLUSION_HEADER_RE.search(text)`, which returns the **first**
match. In the sample handbook that first match is the line in the **table of
contents** on page 1:

```
TABLE OF CONTENTS
1. Introduction
2. Covered Benefits
3. Claim Submission Process
4. General Exclusions          ← matches here
```

It then takes the next 3000 characters, which is Sections 1–3 — *Introduction*,
*Covered Benefits* and *Claim Submission* — and parses their bullets as
exclusions. The real Section 4 is never reached.

**Observed result.** 32 terms are seeded, and they are the wrong ones:

```
"contact information", "1 hospitalisation", "room rent up to $500 per day",
"surgeon fees up to $10,000 per procedure", "anaesthesia charges",
"icu charges up to $1,500 per day", "operation theatre charges",
"2 day care procedures", ...
```

**Why it is critical.** The exclusions table is the deterministic safety net
that runs *before* the LLM. Seeded with inverted data, it rejects exactly the
claims it should approve. The `bill_accepted.pdf` scenario — a covered
emergency appendectomy — is rejected like this:

```
matched_exclusion: "1 hospitalisation"
match_method:      "exact_substring"
match_score:       100.0
diagnosis:         "acute appendicitis"
```

The claim form's `claim_item` is "Hospitalisation", which is a substring of the
bogus exclusion term "1 hospitalisation", so `ExclusionCheckValidator` fails the
claim at step 4 and the chain never reaches the RAG policy check. **Every
hospitalisation claim is auto-rejected.**

**Tests that reproduce it** (5 failures, all this one cause):

- `tests/integration/test_sample_claims_pipeline.py::test_sample_reaches_expected_outcome[normal_illness_accepted]`
- `…::test_chain_short_circuits_before_the_llm[normal_illness_accepted]`
- `…::test_accepted_claim_carries_citations_and_confidence`
- `…::test_accepted_claim_passes_all_deterministic_validators`
- `…::test_decision_prompt_masks_pii_and_fences_bill_text`

Also the pre-existing `tests/unit/test_handbook_chunking.py::TestParseGeneralExclusions::test_stops_at_next_section_header`,
which asserts the parser stops at the next section — it does not. The existing
stop check only matches `^[A-Z][A-Z\s]{5,}:`, and because it is applied to text
*already captured by the bullet regex*, a line like `SECTION 5: CONTACT
INFORMATION` is never tested against it.

**Recommended fix** (three parts):

1. Anchor on the real section, not the first mention. Prefer the **last** match,
   or require the header to be at the start of a line and not followed on the
   same line by a page number / dotted leader. A section-numbered form such as
   `SECTION\s+\d+\s*:?\s*GENERAL\s+EXCLUSIONS` would skip the ToC entry outright.
2. Bound the section by the **next section header** rather than a fixed 3000-char
   window — scan forward for `^\s*SECTION\s+\d+` (or end of text) and slice there.
3. Make the bullet loop break on a section header before stripping it to a term.

Add a regression test asserting the seeded terms *include* "obesity treatment
including bariatric surgery" and *exclude* anything from Section 2 (Covered
Benefits) — the current `test_handbook_ingestion.py::test_ingest_seeds_exclusions_from_the_handbook`
passes only because it checks for substrings like "obesity" that happen to
appear; it should also assert the absence of "hospitalisation".

### 2. Synonym expansion is dead for handbook-derived terms

**The bug.** `app/validators/exclusion_check.py::_SYNONYMS` is keyed on short
canonical terms (`"obesity"`, `"cosmetic surgery"`). The lookup is
`_SYNONYMS.get(excl_term)`, where `excl_term` is whatever came out of the
handbook — long phrases like `"obesity treatment including bariatric surgery"`.
Those never match a key, so step 3 of the matcher (synonym expansion) never
fires on real data. It only works when exclusions are typed in by hand via the
admin endpoint using exactly the canonical wording.

**Test that reproduces it:** `tests/unit/test_exclusion_check_validator.py::TestExclusionCheckValidator::test_fail_synonym_match_bariatric`
(pre-existing, asserts `"obesity"` is matched but gets `"cosmetic surgery"`).

**Recommended fix.** Invert the mapping: build `synonym → canonical` once at
module load, then for each search target check whether any synonym appears in
it, and separately fuzzy-match the target against the *keys*. Match the
canonical term against the stored exclusion with `token_set_ratio` so a long
handbook phrase containing "obesity" still resolves.

---

## RESOLVED during this close-out

These were all live bugs found while getting the suite to run. None had ever
been caught, because **the CI workflow was in a directory GitHub does not read**
(see #3), so the test suite had apparently never been executed.

### 3. CI workflow was never discovered by GitHub Actions

`.github/workflows/ci.yml` lived at `claimtracker/.github/workflows/ci.yml`, but
Actions only reads `<repo-root>/.github/workflows/`. This repository's root is
one level *above* the project directory. The workflow has therefore never run.

**Fixed:** moved to `<repo-root>/.github/workflows/ci.yml` with every path
prefixed `claimtracker/`. If the project is ever hoisted to the repo root, drop
that prefix. (Hoisting is the tidier long-term layout — the README's
`git clone … claimtracker && cd claimtracker` assumes the repo root *is* the
project root — but it rewrites all 94 tracked paths, so it was left alone.)

### 4. `JSONB` columns broke every SQLite code path

Models and migration 0001 used `postgresql.JSONB` directly. SQLite's type
compiler cannot render it, so both `Base.metadata.create_all` (the whole test
suite) and `alembic upgrade head` on the documented SQLite dev path failed with
`CompileError: … can't render element of type JSONB`.

**Fixed:** added `app/models/types.py` with
`JSONColumn = JSON().with_variant(JSONB(), "postgresql")` — JSONB on Postgres,
JSON on SQLite — and used it in the three models and migration 0001.

### 5. Engine pool options crashed on SQLite

`app/core/database.py` passed `pool_size` / `max_overflow` unconditionally, with
a comment claiming SQLite ignores them. It does not: SQLAlchemy selects
StaticPool for aiosqlite and raises
`TypeError: Invalid argument(s) 'pool_size','max_overflow'`. The app could never
start against SQLite.

**Fixed:** `_engine_kwargs()` only adds the QueuePool options for
`postgresql://` URLs.

### 6. `GET /claims` failed for every claim (MissingGreenlet)

`ClaimRepository.list_claims` eager-loaded `documents` and `decisions` but not
`extracted_fields`, which `ClaimResponse` serialises. Pydantic then touched a
lazy relationship during response validation, outside the greenlet:

```
MissingGreenlet: greenlet_spawn has not been called; can't call await_only() here
```

**Fixed:** added `selectinload(Claim.extracted_fields)`. This one blocked the
Phase 7 "My claims" page, so it was fixed rather than deferred.

### 7. Four unpinned dependencies resolved to incompatible versions

`requirements.txt` pinned its direct dependencies but not these, so a fresh
install picked up releases that break the pinned stack:

| Package | Resolved to | Breakage | Pinned to |
|---|---|---|---|
| `numpy` | 2.5.4 | `import faiss` → `numpy.core.multiarray failed to import` (faiss-cpu 1.8.0 and torch 2.3.0 are NumPy 1.x ABI) | `1.26.4` |
| `scipy` | 1.18.1 | requires NumPy ≥ 2, pulling it back in transitively | `1.13.1` |
| `scikit-learn` | 1.9.1 | same | `1.5.0` |
| `transformers` | 4.57.6 | `cannot import name 'GenerationMixin' from 'transformers.generation'` with sentence-transformers 3.0.1 | `4.41.2` (+ `tokenizers==0.19.1`, `huggingface-hub==0.23.4`) |
| `bcrypt` | 5.0.0 | passlib 1.7.4 reads the removed `bcrypt.__about__`; its backend probe then fails, so **all password hashing raised** | `4.0.1` |

**Fixed:** all pinned in `requirements.txt` with the reason in a comment.

### 8. Tests leaked state into each other

The `db_session` fixture rolled back, but the services under test call
`commit()` themselves (`ClaimService`, `HandbookService`, `ReviewService`), so
their writes survived into later tests. A handbook ingested by one test left
`is_active=True`, which made the "no active handbook" RAG tests pass vacuously,
and committed claims skewed the pagination counts. 14 failures.

**Fixed:** `tests/conftest.py::reset_database` empties every table
(child-first via `sorted_tables`) and re-seeds roles before each test.

---

## Environment notes (not bugs)

- **Python version.** The project targets 3.11; this machine has only 3.13 and
  Anaconda 3.12, so `backend/.venv` is 3.12.7. CI still uses 3.11. The pinned
  stack installs cleanly on both, but 3.11 is what the Dockerfile and CI use.
- **`alembic.ini`** still carries a hardcoded
  `sqlalchemy.url = postgresql+asyncpg://…@localhost:5432/claimtracker`. It is
  harmless because `alembic/env.py` overwrites it from `settings.DATABASE_URL`,
  but it is misleading and could be removed.
- **Postgres-backed tests** (`tests/integration/test_analytics_postgres.py`)
  need Docker for testcontainers, or `POSTGRES_TEST_URL` as CI sets it. They
  skip automatically otherwise — they have **not** been executed on this
  machine yet, so the analytics assertions are unverified against a real
  Postgres. `analytics_service.py` sits at 47% coverage for that reason.
- **`passlib` emits a harmless warning** on every hash
  (`error reading bcrypt version`) even on bcrypt 4.0.1. Cosmetic.
