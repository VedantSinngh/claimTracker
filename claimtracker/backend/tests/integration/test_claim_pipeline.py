"""
tests/integration/test_claim_pipeline.py
─────────────────────────────────────────
`ClaimService.submit_claim` and the background pipeline it returns.

This is the orchestration test: upload validation, the records written at each
stage, the status transitions, the audit row, the webhook fire, and the
failure path that must never leave a claim stuck in PROCESSING.

Faked, because this test is about orchestration rather than about any one
stage: the LLM (`GroqClient`), FAISS retrieval (`RAGService`), OCR
(`OCRService` — real OCR is covered in `test_sample_claims_pipeline.py`) and
the outbound n8n webhook. The database, repositories, validator chain and
`DecisionService` are all real.

The pipeline opens its own session via `AsyncSessionLocal`, which normally
binds to `DATABASE_URL`. `_patch_session_factory` repoints it at the test
engine; the closure imports it at call time, so patching the module attribute
is enough.
"""
from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Any, Dict, List, Optional

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers, UploadFile

from app.core.exceptions import FileTooLargeError, UnsupportedFileTypeError
from app.llm.base import LLMClient, LLMMessage, LLMResponse
from app.models.audit_log import AuditLog
from app.models.claim import Claim, ClaimDocument, ExtractedFields
from app.models.decision import Decision
from app.models.role import RoleName
from app.models.user import User
from app.services.claim_service import ClaimService

pytestmark = pytest.mark.asyncio


BILL_TEXT = """
METROPOLITAN GENERAL HOSPITAL
Patient Name:    John Smith
Date of Service: 2024-03-15
Diagnosis:       Acute appendicitis
Appendectomy (Laparoscopic)   $5,500.00
TOTAL BILLED TO INSURANCE     $9,860.00
"""

EXTRACTION_JSON = json.dumps(
    {
        "patient_name": "John Smith",
        "diagnosis": "Acute appendicitis",
        "facility": "Metropolitan General Hospital",
        "date_of_treatment": "2024-03-15",
        "itemised_charges": {"Appendectomy (Laparoscopic)": 5500.00},
        "total_amount": 9860.00,
    }
)

DECISION_JSON = json.dumps(
    {
        "outcome": "ACCEPTED",
        "confidence": 0.91,
        "reason": "Covered in-patient procedure under Section 2.1.",
        "cited_clauses": [
            {"clause": "SECTION 2.1", "text": "In-patient hospitalisation is covered."}
        ],
        "executive_summary": {
            "introduction": "Emergency appendectomy claim.",
            "claim_details": "Metropolitan General Hospital, 2024-03-15.",
            "document_verification": "Itemised bill present.",
            "decision_reason": "No exclusion matched; clause 2.1 applies.",
            "clauses_applied": "Section 2.1",
        },
    }
)


# ── Test doubles ──────────────────────────────────────────────────────────────

class _ScriptedLLM(LLMClient):
    """Returns the extraction JSON first, then the decision JSON."""

    def __init__(self) -> None:
        self._queue = [EXTRACTION_JSON, DECISION_JSON]
        self.prompts: List[str] = []

    def model_name(self) -> str:
        return "fake-llama-3"

    async def complete(
        self,
        messages: List[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        response_format: Optional[str] = None,
    ) -> LLMResponse:
        self.prompts.append("\n".join(m.content for m in messages))
        body = self._queue.pop(0) if self._queue else "{}"
        return LLMResponse(content=body, model=self.model_name())


class _FailingLLM(LLMClient):
    """Blows up on the first call — used for the failure-path test."""

    def model_name(self) -> str:
        return "broken-llm"

    async def complete(self, messages, **kwargs) -> LLMResponse:
        raise RuntimeError("upstream LLM is down")


class _StubOCR:
    def __init__(self, text: str = BILL_TEXT) -> None:
        self._text = text

    def extract_text(self, file_path: str, mime_type: str) -> str:
        return self._text


class _StubRAG:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def retrieve_formatted(self, query: str, top_k: Optional[int] = None) -> str:
        return "[Clause 1] SECTION 2.1 — In-patient hospitalisation is covered."


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def uploads_dir(tmp_path, monkeypatch):
    """Keep uploaded bytes out of the repo's ./uploads during tests."""
    from app.services import claim_service as module

    target = tmp_path / "uploads"
    monkeypatch.setattr(module.settings, "UPLOAD_DIR", target)
    return target


@pytest.fixture
def patch_session_factory(monkeypatch):
    """Point the pipeline's own session factory at the test engine."""
    from app.core import database as db_module

    from tests.conftest import TestSessionLocal

    monkeypatch.setattr(db_module, "AsyncSessionLocal", TestSessionLocal)


@pytest.fixture
def webhook_calls(monkeypatch) -> List[Dict[str, Any]]:
    """Capture webhook fires instead of making a real HTTP request."""
    from app.services import claim_service as module

    calls: List[Dict[str, Any]] = []

    async def _recorder(claim_id, status, patient_name):
        calls.append(
            {"claim_id": claim_id, "status": status, "patient_name": patient_name}
        )

    monkeypatch.setattr(module, "_fire_webhook", _recorder)
    return calls


@pytest.fixture
def scripted_llm(monkeypatch) -> _ScriptedLLM:
    from app.llm import groq_client as groq_module

    llm = _ScriptedLLM()
    monkeypatch.setattr(groq_module, "GroqClient", lambda *a, **k: llm)
    return llm


@pytest.fixture
def stub_pipeline_deps(monkeypatch):
    """Replace OCR and RAG inside the pipeline."""
    from app.services import ocr_service as ocr_module
    from app.services import rag_service as rag_module

    monkeypatch.setattr(ocr_module, "OCRService", lambda *a, **k: _StubOCR())
    monkeypatch.setattr(rag_module, "RAGService", _StubRAG)


@pytest.fixture
async def claimant(db_session: AsyncSession, roles) -> User:
    from app.repositories.role_repo import RoleRepository

    role = await RoleRepository(db_session).get_by_name(RoleName.USER)
    user = User(
        id=uuid.uuid4(),
        email=f"claimant-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="John Smith",
        role_id=role.id,
    )
    user.role_obj = role
    db_session.add(user)
    await db_session.commit()
    return user


def _upload(
    content: bytes = b"%PDF-1.4 fake bill bytes",
    filename: str = "bill.pdf",
    content_type: str = "application/pdf",
) -> UploadFile:
    return UploadFile(
        file=BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


FORM = {
    "patient_name": "John Smith",
    "claim_item": "Hospitalisation",
    "reason": "Acute appendicitis",
    "address": "45 Maple Avenue, New York, NY 10002",
    "date_of_treatment": "2024-03-15",
    "medical_facility": "Metropolitan General Hospital",
    "claim_amount": 9860.00,
    "description": "Emergency laparoscopic appendectomy.",
}


# ── Upload validation ─────────────────────────────────────────────────────────

async def test_submit_rejects_oversized_file(
    db_session: AsyncSession, claimant: User, uploads_dir, monkeypatch
):
    from app.services import claim_service as module

    monkeypatch.setattr(module.settings, "MAX_UPLOAD_SIZE_MB", 1)
    oversized = _upload(content=b"x" * (2 * 1024 * 1024))

    with pytest.raises(FileTooLargeError, match="exceeds 1 MB"):
        await ClaimService(db_session).submit_claim(
            user_id=claimant.id, bill_file=oversized, **FORM
        )


@pytest.mark.parametrize(
    "content_type", ["text/plain", "application/msword", "image/gif", ""]
)
async def test_submit_rejects_unsupported_types(
    db_session: AsyncSession, claimant: User, uploads_dir, content_type: str
):
    with pytest.raises(UnsupportedFileTypeError):
        await ClaimService(db_session).submit_claim(
            user_id=claimant.id,
            bill_file=_upload(content_type=content_type),
            **FORM,
        )


@pytest.mark.parametrize(
    "content_type,filename",
    [
        ("application/pdf", "bill.pdf"),
        ("image/jpeg", "bill.jpg"),
        ("image/png", "bill.png"),
    ],
)
async def test_submit_accepts_pdf_and_images(
    db_session: AsyncSession, claimant: User, uploads_dir, content_type, filename
):
    claim, _ = await ClaimService(db_session).submit_claim(
        user_id=claimant.id,
        bill_file=_upload(filename=filename, content_type=content_type),
        **FORM,
    )
    assert claim.status == "PENDING"


async def test_submit_persists_claim_and_document(
    db_session: AsyncSession, claimant: User, uploads_dir
):
    claim, pipeline = await ClaimService(db_session).submit_claim(
        user_id=claimant.id, bill_file=_upload(), **FORM
    )

    assert callable(pipeline), "the pipeline is returned for BackgroundTasks"
    assert claim.status == "PENDING"
    assert claim.claim_amount == Decimal("9860.00")
    assert claim.date_of_treatment == date(2024, 3, 15)

    docs = (
        await db_session.execute(
            select(ClaimDocument).where(ClaimDocument.claim_id == claim.id)
        )
    ).scalars().all()
    assert len(docs) == 1
    assert docs[0].file_name == "bill.pdf"
    assert docs[0].mime_type == "application/pdf"

    # The bytes landed on disk under a UUID name, not the user's filename.
    written = list(uploads_dir.iterdir())
    assert len(written) == 1
    assert written[0].name != "bill.pdf"
    assert written[0].read_bytes() == b"%PDF-1.4 fake bill bytes"


# ── Happy-path pipeline ───────────────────────────────────────────────────────

async def test_pipeline_runs_through_to_a_decision(
    db_session: AsyncSession,
    claimant: User,
    uploads_dir,
    patch_session_factory,
    stub_pipeline_deps,
    scripted_llm,
    webhook_calls,
):
    claim, pipeline = await ClaimService(db_session).submit_claim(
        user_id=claimant.id, bill_file=_upload(), **FORM
    )
    await pipeline()

    # ── Claim reached a terminal status with a confidence score ──
    refreshed = await db_session.get(Claim, claim.id)
    await db_session.refresh(refreshed)
    assert refreshed.status == "ACCEPTED"
    assert refreshed.confidence_score == pytest.approx(0.91)

    # ── OCR text was stored on the document ─────────────────────
    doc = (
        await db_session.execute(
            select(ClaimDocument).where(ClaimDocument.claim_id == claim.id)
        )
    ).scalar_one()
    assert "Acute appendicitis" in doc.raw_ocr_text

    # ── Extracted fields were persisted with provenance ─────────
    extracted = (
        await db_session.execute(
            select(ExtractedFields).where(ExtractedFields.claim_id == claim.id)
        )
    ).scalar_one()
    assert extracted.diagnosis == "Acute appendicitis"
    assert extracted.total_amount_extracted == Decimal("9860.00")
    assert extracted.llm_model == "fake-llama-3"
    assert extracted.prompt_version == "extract_v1"

    # ── Decision row carries the evidence ───────────────────────
    decision = (
        await db_session.execute(
            select(Decision).where(Decision.claim_id == claim.id)
        )
    ).scalar_one()
    assert decision.outcome == "ACCEPTED"
    assert decision.confidence_score == pytest.approx(0.91)
    assert decision.model_name == "fake-llama-3"
    assert decision.prompt_version == "decision_v1"
    assert decision.cited_clauses, "a decision must cite clauses"
    assert "Decision Reason" in decision.executive_summary
    # retrieved_chunks records what each validator concluded.
    validators = {row["validator"] for row in decision.retrieved_chunks}
    assert validators == {
        "completeness_check",
        "amount_check",
        "consistency_check",
        "exclusion_check",
        "rag_policy_check",
    }

    # ── Audit log ───────────────────────────────────────────────
    audits = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.claim_id == claim.id)
        )
    ).scalars().all()
    assert len(audits) == 1
    assert audits[0].action == "AI_DECISION"
    assert audits[0].payload["outcome"] == "ACCEPTED"
    assert audits[0].payload["model_name"] == "fake-llama-3"
    assert len(audits[0].payload["validator_results"]) == 5

    # ── n8n webhook fired once with the outcome ─────────────────
    assert len(webhook_calls) == 1
    assert webhook_calls[0]["status"] == "ACCEPTED"
    assert webhook_calls[0]["claim_id"] == claim.id


async def test_pipeline_masks_pii_before_calling_the_llm(
    db_session: AsyncSession,
    claimant: User,
    uploads_dir,
    patch_session_factory,
    stub_pipeline_deps,
    scripted_llm,
    webhook_calls,
):
    """The patient's name must not appear in any prompt sent upstream."""
    _, pipeline = await ClaimService(db_session).submit_claim(
        user_id=claimant.id, bill_file=_upload(), **FORM
    )
    await pipeline()

    assert scripted_llm.prompts, "the LLM should have been called"
    for prompt in scripted_llm.prompts:
        assert "John Smith" not in prompt
        assert "[NAME_REDACTED]" in prompt


# ── Failure path ──────────────────────────────────────────────────────────────

async def test_pipeline_failure_routes_to_needs_review_and_is_audited(
    db_session: AsyncSession,
    claimant: User,
    uploads_dir,
    patch_session_factory,
    stub_pipeline_deps,
    webhook_calls,
    monkeypatch,
):
    """
    A crash mid-pipeline must never leave the claim in PROCESSING — it falls
    back to NEEDS_REVIEW so a human picks it up, and the error is recorded.
    """
    from app.llm import groq_client as groq_module

    monkeypatch.setattr(groq_module, "GroqClient", lambda *a, **k: _FailingLLM())

    claim, pipeline = await ClaimService(db_session).submit_claim(
        user_id=claimant.id, bill_file=_upload(), **FORM
    )
    # The pipeline swallows its own exceptions by design.
    await pipeline()

    refreshed = await db_session.get(Claim, claim.id)
    await db_session.refresh(refreshed)
    assert refreshed.status == "NEEDS_REVIEW"

    audits = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.claim_id == claim.id)
        )
    ).scalars().all()
    assert len(audits) == 1
    assert audits[0].action == "PIPELINE_ERROR"
    assert "error" in audits[0].payload

    # No decision was reached, so no webhook should have fired.
    assert webhook_calls == []


# ── Listing and ownership ─────────────────────────────────────────────────────

async def test_list_claims_paginates(
    db_session: AsyncSession, claimant: User, uploads_dir
):
    svc = ClaimService(db_session)
    for _ in range(3):
        await svc.submit_claim(user_id=claimant.id, bill_file=_upload(), **FORM)

    page1 = await svc.list_claims(
        user_id=claimant.id, status=None, page=1, page_size=2
    )
    assert page1.total == 3
    assert len(page1.items) == 2
    assert page1.page == 1

    page2 = await svc.list_claims(
        user_id=claimant.id, status=None, page=2, page_size=2
    )
    assert len(page2.items) == 1


async def test_list_claims_filters_by_status(
    db_session: AsyncSession, claimant: User, uploads_dir
):
    svc = ClaimService(db_session)
    await svc.submit_claim(user_id=claimant.id, bill_file=_upload(), **FORM)

    pending = await svc.list_claims(
        user_id=claimant.id, status="PENDING", page=1, page_size=10
    )
    assert pending.total == 1

    accepted = await svc.list_claims(
        user_id=claimant.id, status="ACCEPTED", page=1, page_size=10
    )
    assert accepted.total == 0


async def test_user_cannot_read_another_users_claim(
    db_session: AsyncSession, claimant: User, uploads_dir, roles
):
    """Ownership is enforced in the service, not just in the router."""
    from app.core.dependencies import CurrentUser
    from app.repositories.role_repo import RoleRepository

    svc = ClaimService(db_session)
    claim, _ = await svc.submit_claim(
        user_id=claimant.id, bill_file=_upload(), **FORM
    )

    role = await RoleRepository(db_session).get_by_name(RoleName.USER)
    intruder = User(
        id=uuid.uuid4(),
        email=f"intruder-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Nosy Parker",
        role_id=role.id,
    )
    intruder.role_obj = role
    db_session.add(intruder)
    await db_session.commit()

    # The owner can read it.
    owner_view = await svc.get_claim(
        claim_id=claim.id,
        requesting_user=CurrentUser(user_id=claimant.id, role=RoleName.USER),
    )
    assert owner_view is not None

    # Another plain user cannot.
    assert (
        await svc.get_claim(
            claim_id=claim.id,
            requesting_user=CurrentUser(user_id=intruder.id, role=RoleName.USER),
        )
        is None
    )

    # A reviewer can.
    assert (
        await svc.get_claim(
            claim_id=claim.id,
            requesting_user=CurrentUser(user_id=intruder.id, role=RoleName.REVIEWER),
        )
        is not None
    )


async def test_get_unknown_claim_returns_none(db_session: AsyncSession, roles):
    from app.core.dependencies import CurrentUser

    result = await ClaimService(db_session).get_claim(
        claim_id=uuid.uuid4(),
        requesting_user=CurrentUser(user_id=uuid.uuid4(), role=RoleName.ADMIN),
    )
    assert result is None
