"""
tests/integration/test_review_flow.py
──────────────────────────────────────
Human-in-the-loop: reviewer approve / reject / override, and the audit trail
each one leaves behind.

Runs against the SQLite fixture — no LLM, no FAISS, no Docker.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.models.audit_log import AuditLog
from app.models.claim import Claim
from app.models.role import RoleName
from app.models.user import User
from app.schemas.review import ReviewCreateRequest
from app.services.review_service import ReviewService

pytestmark = pytest.mark.asyncio


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _make_user(session: AsyncSession, role_name: str, email: str) -> User:
    from app.repositories.role_repo import RoleRepository

    role = await RoleRepository(session).get_by_name(role_name)
    assert role is not None, f"role {role_name} not seeded"
    user = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password="not-a-real-hash",
        full_name=f"{role_name.title()} Person",
        role_id=role.id,
    )
    user.role_obj = role
    session.add(user)
    await session.flush()
    return user


async def _make_claim(
    session: AsyncSession,
    owner: User,
    status: str = "NEEDS_REVIEW",
    confidence: Optional[float] = 0.42,
) -> Claim:
    claim = Claim(
        id=uuid.uuid4(),
        user_id=owner.id,
        patient_name="Pat Patient",
        claim_item="Hospitalisation",
        reason="Acute appendicitis",
        address="1 Test Street",
        date_of_treatment=date(2024, 3, 15),
        medical_facility="Test Hospital",
        claim_amount=Decimal("1200.00"),
        description="Emergency admission.",
        status=status,
        confidence_score=confidence,
    )
    session.add(claim)
    await session.flush()
    return claim


async def _audit_rows(session: AsyncSession, claim_id: uuid.UUID) -> list[AuditLog]:
    result = await session.execute(
        select(AuditLog).where(AuditLog.claim_id == claim_id)
    )
    return list(result.scalars().all())


# ── Approve / reject ──────────────────────────────────────────────────────────

async def test_approve_moves_claim_to_accepted(db_session: AsyncSession, roles):
    claimant = await _make_user(db_session, RoleName.USER, f"u{uuid.uuid4().hex[:8]}@x.com")
    reviewer = await _make_user(db_session, RoleName.REVIEWER, f"r{uuid.uuid4().hex[:8]}@x.com")
    claim = await _make_claim(db_session, claimant, status="NEEDS_REVIEW")

    review = await ReviewService(db_session).submit_review(
        claim_id=claim.id,
        reviewer_id=reviewer.id,
        request=ReviewCreateRequest(
            outcome="APPROVED", comment="Verified against the original bill."
        ),
    )

    assert review is not None
    assert review.outcome == "APPROVED"
    assert review.previous_status == "NEEDS_REVIEW"
    assert review.new_status == "ACCEPTED"

    refreshed = await db_session.get(Claim, claim.id)
    assert refreshed.status == "ACCEPTED"


async def test_reject_moves_claim_to_rejected(db_session: AsyncSession, roles):
    claimant = await _make_user(db_session, RoleName.USER, f"u{uuid.uuid4().hex[:8]}@x.com")
    reviewer = await _make_user(db_session, RoleName.REVIEWER, f"r{uuid.uuid4().hex[:8]}@x.com")
    claim = await _make_claim(db_session, claimant, status="NEEDS_REVIEW")

    review = await ReviewService(db_session).submit_review(
        claim_id=claim.id,
        reviewer_id=reviewer.id,
        request=ReviewCreateRequest(outcome="REJECTED", comment="Excluded condition."),
    )

    assert review.new_status == "REJECTED"
    refreshed = await db_session.get(Claim, claim.id)
    assert refreshed.status == "REJECTED"


# ── Override ──────────────────────────────────────────────────────────────────

async def test_override_requires_new_status(db_session: AsyncSession, roles):
    claimant = await _make_user(db_session, RoleName.USER, f"u{uuid.uuid4().hex[:8]}@x.com")
    reviewer = await _make_user(db_session, RoleName.REVIEWER, f"r{uuid.uuid4().hex[:8]}@x.com")
    claim = await _make_claim(db_session, claimant, status="REJECTED")

    with pytest.raises(ValidationError, match="new_status is required"):
        await ReviewService(db_session).submit_review(
            claim_id=claim.id,
            reviewer_id=reviewer.id,
            request=ReviewCreateRequest(outcome="OVERRIDE", comment="Reopening."),
        )


async def test_override_can_reverse_an_ai_rejection(db_session: AsyncSession, roles):
    """The whole point of the override: a human can overturn the AI."""
    claimant = await _make_user(db_session, RoleName.USER, f"u{uuid.uuid4().hex[:8]}@x.com")
    reviewer = await _make_user(db_session, RoleName.REVIEWER, f"r{uuid.uuid4().hex[:8]}@x.com")
    claim = await _make_claim(db_session, claimant, status="REJECTED")

    review = await ReviewService(db_session).submit_review(
        claim_id=claim.id,
        reviewer_id=reviewer.id,
        request=ReviewCreateRequest(
            outcome="OVERRIDE",
            new_status="ACCEPTED",
            comment="Exclusion matched on a substring; the diagnosis is unrelated.",
        ),
    )

    assert review.previous_status == "REJECTED"
    assert review.new_status == "ACCEPTED"
    refreshed = await db_session.get(Claim, claim.id)
    assert refreshed.status == "ACCEPTED"


# ── Guards ────────────────────────────────────────────────────────────────────

async def test_review_of_unknown_claim_returns_none(db_session: AsyncSession, roles):
    reviewer = await _make_user(db_session, RoleName.REVIEWER, f"r{uuid.uuid4().hex[:8]}@x.com")

    result = await ReviewService(db_session).submit_review(
        claim_id=uuid.uuid4(),
        reviewer_id=reviewer.id,
        request=ReviewCreateRequest(outcome="APPROVED", comment="n/a"),
    )
    assert result is None


@pytest.mark.parametrize("status", ["PENDING", "PROCESSING"])
async def test_in_flight_claims_cannot_be_reviewed(
    db_session: AsyncSession, roles, status: str
):
    """
    Only a decided claim can be reviewed. Letting a reviewer act on a
    PROCESSING claim would race the background pipeline, which writes the
    status itself when it finishes.
    """
    claimant = await _make_user(db_session, RoleName.USER, f"u{uuid.uuid4().hex[:8]}@x.com")
    reviewer = await _make_user(db_session, RoleName.REVIEWER, f"r{uuid.uuid4().hex[:8]}@x.com")
    claim = await _make_claim(db_session, claimant, status=status)

    with pytest.raises(ValidationError, match="cannot be reviewed"):
        await ReviewService(db_session).submit_review(
            claim_id=claim.id,
            reviewer_id=reviewer.id,
            request=ReviewCreateRequest(outcome="APPROVED", comment="too early"),
        )


@pytest.mark.parametrize("status", ["NEEDS_REVIEW", "ACCEPTED", "REJECTED"])
async def test_decided_claims_are_reviewable(
    db_session: AsyncSession, roles, status: str
):
    claimant = await _make_user(db_session, RoleName.USER, f"u{uuid.uuid4().hex[:8]}@x.com")
    reviewer = await _make_user(db_session, RoleName.REVIEWER, f"r{uuid.uuid4().hex[:8]}@x.com")
    claim = await _make_claim(db_session, claimant, status=status)

    review = await ReviewService(db_session).submit_review(
        claim_id=claim.id,
        reviewer_id=reviewer.id,
        request=ReviewCreateRequest(outcome="APPROVED", comment="Checked."),
    )
    assert review is not None
    assert review.previous_status == status


# ── Audit trail ───────────────────────────────────────────────────────────────

async def test_every_override_is_audited(db_session: AsyncSession, roles):
    claimant = await _make_user(db_session, RoleName.USER, f"u{uuid.uuid4().hex[:8]}@x.com")
    reviewer = await _make_user(db_session, RoleName.REVIEWER, f"r{uuid.uuid4().hex[:8]}@x.com")
    claim = await _make_claim(db_session, claimant, status="NEEDS_REVIEW")

    await ReviewService(db_session).submit_review(
        claim_id=claim.id,
        reviewer_id=reviewer.id,
        request=ReviewCreateRequest(
            outcome="OVERRIDE", new_status="ACCEPTED", comment="Reviewed the scan myself."
        ),
    )

    rows = await _audit_rows(db_session, claim.id)
    assert len(rows) == 1
    audit = rows[0]
    assert audit.action == "HUMAN_OVERRIDE"
    assert audit.user_id == reviewer.id
    assert audit.payload["outcome"] == "OVERRIDE"
    assert audit.payload["previous_status"] == "NEEDS_REVIEW"
    assert audit.payload["new_status"] == "ACCEPTED"
    assert audit.payload["comment"] == "Reviewed the scan myself."


async def test_successive_reviews_accumulate_history(db_session: AsyncSession, roles):
    """
    A claim can be reviewed more than once; each decision is appended rather
    than replacing the last, so the AI's original call is never lost.
    """
    from app.repositories.review_repo import ReviewRepository

    claimant = await _make_user(db_session, RoleName.USER, f"u{uuid.uuid4().hex[:8]}@x.com")
    reviewer = await _make_user(db_session, RoleName.REVIEWER, f"r{uuid.uuid4().hex[:8]}@x.com")
    claim = await _make_claim(db_session, claimant, status="NEEDS_REVIEW")
    svc = ReviewService(db_session)

    await svc.submit_review(
        claim_id=claim.id,
        reviewer_id=reviewer.id,
        request=ReviewCreateRequest(outcome="REJECTED", comment="First pass: excluded."),
    )
    await svc.submit_review(
        claim_id=claim.id,
        reviewer_id=reviewer.id,
        request=ReviewCreateRequest(
            outcome="OVERRIDE", new_status="ACCEPTED", comment="Second pass: my error."
        ),
    )

    history = await ReviewRepository(db_session).list_for_claim(claim.id)
    assert len(history) == 2
    outcomes = {r.outcome for r in history}
    assert outcomes == {"REJECTED", "OVERRIDE"}

    # The transition chain is intact: NEEDS_REVIEW → REJECTED → ACCEPTED
    chain = sorted(history, key=lambda r: r.reviewed_at)
    assert chain[0].previous_status == "NEEDS_REVIEW"
    assert chain[0].new_status == "REJECTED"
    assert chain[1].previous_status == "REJECTED"
    assert chain[1].new_status == "ACCEPTED"

    assert len(await _audit_rows(db_session, claim.id)) == 2
