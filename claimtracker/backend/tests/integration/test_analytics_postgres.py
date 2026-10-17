"""
tests/integration/test_analytics_postgres.py
─────────────────────────────────────────────
Analytics SQL against a real PostgreSQL.

These queries cannot run on the SQLite fixture used by the rest of the suite:
`DATE_TRUNC`, `FILTER (WHERE …)`, `EXTRACT(EPOCH FROM …)`, `RANK() OVER`,
`::NUMERIC` casts and CTEs are all Postgres. So every test here uses the
`pg_session` fixture, which starts a throwaway `postgres:16-alpine` via
testcontainers (or honours `POSTGRES_TEST_URL` in CI) and skips when Docker is
unavailable.

The queries are read from `db/analytics.sql` rather than copied, so the file
that ships as the deliverable is the file under test — if someone edits a query
and breaks it, these tests fail.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.claim import Claim
from app.models.role import RoleName
from app.models.user import User
from app.services.analytics_service import AnalyticsService

ANALYTICS_SQL = Path(__file__).resolve().parents[3] / "db" / "analytics.sql"

pytestmark = pytest.mark.asyncio


# ── Loading the shipped SQL file ───────────────────────────────────────────────

def _load_queries() -> Dict[str, str]:
    """
    Split db/analytics.sql into {label: sql}.

    Each query is preceded by a banner comment whose first line is
    `-- N. Title` or `-- Na. Title`; that number is the key ("1", "2a", …).
    """
    raw = ANALYTICS_SQL.read_text(encoding="utf-8")
    # Statements are separated by semicolons at end of line.
    statements = [s.strip() for s in raw.split(";") if s.strip()]

    queries: Dict[str, str] = {}
    for stmt in statements:
        label = None
        for line in stmt.splitlines():
            match = re.match(r"^--\s*([0-9]+[a-z]?)\.\s", line.strip())
            if match:
                label = match.group(1)
                break
        if label is None:
            continue
        # Strip leading comment lines so what executes is just the SQL.
        sql_lines = [
            line for line in stmt.splitlines()
            if not line.strip().startswith("--") and line.strip()
        ]
        queries[label] = "\n".join(sql_lines)
    return queries


QUERIES = _load_queries()


def test_sql_file_parsed():
    """Sanity check on the loader before the DB tests rely on it."""
    assert set(QUERIES) == {"1", "2a", "2b", "3", "4", "5"}, sorted(QUERIES)
    for label, sql in QUERIES.items():
        assert sql.upper().lstrip().startswith(("SELECT", "WITH")), label


# ── Fixture data ──────────────────────────────────────────────────────────────

# Two claimants, one reviewer (who files nothing), and a spread of statuses
# and rejection reasons with known counts so every aggregate is predictable.
#
#  alice   → 2 ACCEPTED, 2 REJECTED ("Excluded condition"), 1 NEEDS_REVIEW  = 5
#  bob     → 1 ACCEPTED, 1 REJECTED ("Amount exceeds bill"),               = 2
#  carol   → reviewer, 0 claims
#
# Rejection reasons overall: "Excluded condition" ×2, "Amount exceeds bill" ×1

BASE_MONTH = datetime(2024, 3, 10, 12, 0, 0, tzinfo=timezone.utc)


async def _seed(session: AsyncSession) -> Dict[str, Any]:
    """Insert the fixture users and claims; return handles for assertions."""
    from app.repositories.role_repo import RoleRepository

    role_repo = RoleRepository(session)
    user_role = await role_repo.get_by_name(RoleName.USER)
    reviewer_role = await role_repo.get_by_name(RoleName.REVIEWER)
    assert user_role is not None and reviewer_role is not None

    alice = User(
        id=uuid.uuid4(), email="alice@example.com", hashed_password="x",
        full_name="Alice Adams", role_id=user_role.id,
    )
    bob = User(
        id=uuid.uuid4(), email="bob@example.com", hashed_password="x",
        full_name="Bob Brown", role_id=user_role.id,
    )
    carol = User(
        id=uuid.uuid4(), email="carol@example.com", hashed_password="x",
        full_name="Carol Clark", role_id=reviewer_role.id,
    )
    session.add_all([alice, bob, carol])
    await session.flush()

    def claim(
        owner: User,
        status: str,
        reason: str,
        *,
        amount: str,
        confidence: float | None,
        processing_seconds: int,
        month_offset: int = 0,
    ) -> Claim:
        created = BASE_MONTH + timedelta(days=31 * month_offset)
        return Claim(
            id=uuid.uuid4(),
            user_id=owner.id,
            patient_name=owner.full_name,
            claim_item="Hospitalisation",
            reason=reason,
            address="1 Test Street",
            date_of_treatment=created.date(),
            medical_facility="Test Hospital",
            claim_amount=Decimal(amount),
            description=None,
            status=status,
            confidence_score=confidence,
            created_at=created,
            updated_at=created + timedelta(seconds=processing_seconds),
        )

    claims = [
        # Alice — March
        claim(alice, "ACCEPTED", "Covered illness", amount="1000.00", confidence=0.95, processing_seconds=10),
        claim(alice, "ACCEPTED", "Covered illness", amount="2000.00", confidence=0.90, processing_seconds=20),
        claim(alice, "REJECTED", "Excluded condition", amount="3000.00", confidence=0.88, processing_seconds=30),
        claim(alice, "REJECTED", "Excluded condition", amount="4000.00", confidence=0.86, processing_seconds=40),
        claim(alice, "NEEDS_REVIEW", "Low confidence", amount="5000.00", confidence=0.40, processing_seconds=100),
        # Bob — April (different month, so query 1 has two buckets)
        claim(bob, "ACCEPTED", "Covered illness", amount="600.00", confidence=0.92, processing_seconds=15, month_offset=1),
        claim(bob, "REJECTED", "Amount exceeds bill", amount="900.00", confidence=0.80, processing_seconds=25, month_offset=1),
    ]
    session.add_all(claims)
    await session.commit()

    return {"alice": alice, "bob": bob, "carol": carol, "claims": claims}


async def _rows(session: AsyncSession, sql: str) -> List[Dict[str, Any]]:
    result = await session.execute(text(sql))
    return [dict(row) for row in result.mappings().all()]


# ── Query 1: approval vs rejection rate per month ─────────────────────────────

async def test_query_1_monthly_rates(pg_session: AsyncSession):
    await _seed(pg_session)
    rows = await _rows(pg_session, QUERIES["1"])

    assert len(rows) == 2, "one row per month present in the data"
    # ORDER BY month DESC → April first.
    april, march = rows
    assert april["month"].month == 4
    assert march["month"].month == 3

    assert (march["accepted"], march["rejected"], march["needs_review"]) == (2, 2, 1)
    assert march["total"] == 5
    assert march["acceptance_rate_pct"] == Decimal("40.00")  # 2 of 5

    assert (april["accepted"], april["rejected"], april["needs_review"]) == (1, 1, 0)
    assert april["total"] == 2
    assert april["acceptance_rate_pct"] == Decimal("50.00")


# ── Query 2a / 2b: top rejection reasons, window function vs CTE ──────────────

async def test_query_2a_window_function_ranking(pg_session: AsyncSession):
    await _seed(pg_session)
    rows = await _rows(pg_session, QUERIES["2a"])

    assert [(r["reason"], r["rejection_count"], r["rank"]) for r in rows] == [
        ("Excluded condition", 2, 1),
        ("Amount exceeds bill", 1, 2),
    ]


async def test_query_2b_cte_ranking(pg_session: AsyncSession):
    await _seed(pg_session)
    rows = await _rows(pg_session, QUERIES["2b"])

    assert [(r["reason"], r["rejection_count"], r["rank"]) for r in rows] == [
        ("Excluded condition", 2, 1),
        ("Amount exceeds bill", 1, 2),
    ]


async def test_query_2a_and_2b_are_equivalent(pg_session: AsyncSession):
    """
    The point of shipping both forms is that they are interchangeable.
    This asserts it rather than claiming it in a comment.
    """
    await _seed(pg_session)
    subquery_rows = await _rows(pg_session, QUERIES["2a"])
    cte_rows = await _rows(pg_session, QUERIES["2b"])

    def normalise(rows: List[Dict[str, Any]]):
        return [
            (r["reason"], int(r["rejection_count"]), int(r["rank"])) for r in rows
        ]

    assert normalise(subquery_rows) == normalise(cte_rows)


async def test_query_2_ties_share_a_rank(pg_session: AsyncSession):
    """RANK() (not ROW_NUMBER) must give tied reasons the same rank."""
    seeded = await _seed(pg_session)
    # Add a second "Amount exceeds bill" rejection → 2 vs 2, a tie at rank 1.
    extra = Claim(
        id=uuid.uuid4(),
        user_id=seeded["bob"].id,
        patient_name="Bob Brown",
        claim_item="Hospitalisation",
        reason="Amount exceeds bill",
        address="1 Test Street",
        date_of_treatment=BASE_MONTH.date(),
        medical_facility="Test Hospital",
        claim_amount=Decimal("100.00"),
        description=None,
        status="REJECTED",
        confidence_score=0.7,
        created_at=BASE_MONTH,
        updated_at=BASE_MONTH + timedelta(seconds=5),
    )
    pg_session.add(extra)
    await pg_session.commit()

    for label in ("2a", "2b"):
        rows = await _rows(pg_session, QUERIES[label])
        ranks = {r["reason"]: r["rank"] for r in rows}
        assert ranks == {"Excluded condition": 1, "Amount exceeds bill": 1}, label


# ── Query 3: average processing time per status (CTE) ─────────────────────────

async def test_query_3_processing_time_cte(pg_session: AsyncSession):
    await _seed(pg_session)
    rows = await _rows(pg_session, QUERIES["3"])

    by_status = {r["status"]: r for r in rows}
    assert set(by_status) == {"ACCEPTED", "REJECTED", "NEEDS_REVIEW"}

    # ACCEPTED: 10s, 20s, 15s → avg 15
    assert by_status["ACCEPTED"]["claim_count"] == 3
    assert by_status["ACCEPTED"]["avg_seconds"] == Decimal("15.00")
    assert by_status["ACCEPTED"]["min_seconds"] == Decimal("10.00")
    assert by_status["ACCEPTED"]["max_seconds"] == Decimal("20.00")

    # REJECTED: 30s, 40s, 25s → avg 31.67
    assert by_status["REJECTED"]["claim_count"] == 3
    assert by_status["REJECTED"]["avg_seconds"] == Decimal("31.67")

    # NEEDS_REVIEW: a single 100s claim
    assert by_status["NEEDS_REVIEW"]["claim_count"] == 1
    assert by_status["NEEDS_REVIEW"]["avg_seconds"] == Decimal("100.00")
    assert by_status["NEEDS_REVIEW"]["avg_minutes"] == Decimal("1.67")

    # ORDER BY avg_seconds DESC
    assert [r["status"] for r in rows] == ["NEEDS_REVIEW", "REJECTED", "ACCEPTED"]


async def test_query_3_excludes_unfinished_claims(pg_session: AsyncSession):
    """
    The CTE filters `updated_at > created_at`, so a PENDING claim that has
    never been touched must not drag the averages down.
    """
    seeded = await _seed(pg_session)
    pending = Claim(
        id=uuid.uuid4(),
        user_id=seeded["alice"].id,
        patient_name="Alice Adams",
        claim_item="Hospitalisation",
        reason="Covered illness",
        address="1 Test Street",
        date_of_treatment=BASE_MONTH.date(),
        medical_facility="Test Hospital",
        claim_amount=Decimal("10.00"),
        description=None,
        status="PENDING",
        confidence_score=None,
        created_at=BASE_MONTH,
        updated_at=BASE_MONTH,  # untouched
    )
    pg_session.add(pending)
    await pg_session.commit()

    rows = await _rows(pg_session, QUERIES["3"])
    assert "PENDING" not in {r["status"] for r in rows}
    assert sum(r["claim_count"] for r in rows) == 7


# ── Query 4 / 5: claims per user (JOIN vs subquery) ───────────────────────────

async def test_query_4_claims_per_user_join(pg_session: AsyncSession):
    await _seed(pg_session)
    rows = await _rows(pg_session, QUERIES["4"])

    # carol is a reviewer (WHERE r.name = 'user') and has no claims
    # (HAVING COUNT > 0), so she is excluded on both counts.
    assert [r["full_name"] for r in rows] == ["Alice Adams", "Bob Brown"]

    alice_row, bob_row = rows
    assert alice_row["role"] == "user"
    assert alice_row["total_claims"] == 5
    assert (alice_row["accepted"], alice_row["rejected"], alice_row["needs_review"]) == (2, 2, 1)
    assert alice_row["pending"] == 0
    assert alice_row["total_claimed_amount"] == Decimal("15000.00")
    # (0.95 + 0.90 + 0.88 + 0.86 + 0.40) / 5 = 0.798
    assert alice_row["avg_confidence"] == pytest.approx(0.798, abs=1e-6)

    assert bob_row["total_claims"] == 2
    assert bob_row["total_claimed_amount"] == Decimal("1500.00")


async def test_query_4_excludes_non_claimant_roles(pg_session: AsyncSession):
    """A reviewer with claims is still filtered out by `WHERE r.name = 'user'`."""
    seeded = await _seed(pg_session)
    reviewer_claim = Claim(
        id=uuid.uuid4(),
        user_id=seeded["carol"].id,
        patient_name="Carol Clark",
        claim_item="Hospitalisation",
        reason="Covered illness",
        address="1 Test Street",
        date_of_treatment=BASE_MONTH.date(),
        medical_facility="Test Hospital",
        claim_amount=Decimal("50.00"),
        description=None,
        status="ACCEPTED",
        confidence_score=0.99,
        created_at=BASE_MONTH,
        updated_at=BASE_MONTH + timedelta(seconds=5),
    )
    pg_session.add(reviewer_claim)
    await pg_session.commit()

    rows = await _rows(pg_session, QUERIES["4"])
    assert "Carol Clark" not in {r["full_name"] for r in rows}


async def test_query_5_subquery_matches_join_on_shared_columns(pg_session: AsyncSession):
    """
    Query 5 is the subquery rewrite of query 4. It has no role filter, so it
    agrees with query 4 on the columns both project for the claimant rows.
    """
    await _seed(pg_session)
    join_rows = await _rows(pg_session, QUERIES["4"])
    sub_rows = await _rows(pg_session, QUERIES["5"])

    def shared(rows):
        return {
            r["email"]: (int(r["total_claims"]), int(r["accepted"]), int(r["rejected"]))
            for r in rows
        }

    join_shared = shared(join_rows)
    sub_shared = shared(sub_rows)

    # Every claimant in the JOIN version appears identically in the subquery one.
    assert join_shared  # guard against both being empty
    for email, values in join_shared.items():
        assert sub_shared[email] == values, email

    # Ordering contract: most claims first.
    counts = [int(r["total_claims"]) for r in sub_rows]
    assert counts == sorted(counts, reverse=True)


# ── /analytics/summary service layer ──────────────────────────────────────────

async def test_analytics_service_summary(pg_session: AsyncSession):
    """
    AnalyticsService runs its own copies of these queries; this is the shape
    the /analytics/summary endpoint returns.
    """
    await _seed(pg_session)
    summary = await AnalyticsService(pg_session).get_summary()

    # Monthly buckets: 2 statuses in March, 2 in April (ACCEPTED + REJECTED only)
    months = summary.approval_rejection_by_month
    assert len(months) == 4
    assert {row["status"] for row in months} == {"ACCEPTED", "REJECTED"}
    march_accepted = next(
        row for row in months
        if row["month"].month == 3 and row["status"] == "ACCEPTED"
    )
    assert march_accepted["count"] == 2

    top = summary.top_rejection_reasons
    assert [(r["reason"], r["rejection_count"]) for r in top] == [
        ("Excluded condition", 2),
        ("Amount exceeds bill", 1),
    ]

    times = {r["status"]: r["avg_seconds"] for r in summary.avg_processing_time_by_status}
    assert times["ACCEPTED"] == Decimal("15.00")
    assert times["NEEDS_REVIEW"] == Decimal("100.00")

    per_user = {r["email"]: r for r in summary.claims_per_user}
    assert per_user["alice@example.com"]["total_claims"] == 5
    assert per_user["bob@example.com"]["total_claims"] == 2
    # The service's query has no role filter and uses a LEFT JOIN, so the
    # reviewer appears with zero claims.
    assert per_user["carol@example.com"]["total_claims"] == 0


async def test_analytics_summary_endpoint_requires_admin(pg_session: AsyncSession):
    """
    The endpoint is admin-only. Checked here because the route needs a DB that
    can actually execute the queries.
    """
    from httpx import ASGITransport, AsyncClient

    from app.core.dependencies import get_db
    from app.core.security import create_access_token
    from app.main import app

    await _seed(pg_session)

    async def _override_get_db():
        yield pg_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            # A plain user is refused.
            user_token = create_access_token(
                subject=str(uuid.uuid4()), role=RoleName.USER
            )
            r = await ac.get(
                "/analytics/summary",
                headers={"Authorization": f"Bearer {user_token}"},
            )
            assert r.status_code == 403

            # An admin gets the payload.
            admin_token = create_access_token(
                subject=str(uuid.uuid4()), role=RoleName.ADMIN
            )
            r = await ac.get(
                "/analytics/summary",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert r.status_code == 200
            body = r.json()
            assert set(body) == {
                "approval_rejection_by_month",
                "top_rejection_reasons",
                "avg_processing_time_by_status",
                "claims_per_user",
            }
            assert len(body["top_rejection_reasons"]) == 2
    finally:
        app.dependency_overrides.clear()
