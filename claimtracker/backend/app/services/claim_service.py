"""
app/services/claim_service.py
──────────────────────────────
Orchestrates the full claim lifecycle:

Submit:
  1. Validate upload (type, size)
  2. Save file to disk
  3. Persist Claim + ClaimDocument records
  4. Return (claim, pipeline_fn) — pipeline runs as a BackgroundTask

Pipeline (background):
  1. Set status → PROCESSING
  2. OCR: extract text from bill
  3. Extraction: LLM JSON extraction of structured fields
  4. Validator chain: 5 steps (completeness → amount → consistency → exclusions → RAG)
  5. Decision: persist Decision record, update claim status
  6. Audit log: log full AI call details
  7. n8n webhook: fire claim-decided event
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Callable, Optional, Tuple
from uuid import UUID

import httpx
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import FileTooLargeError, UnsupportedFileTypeError
from app.core.logging import get_logger
from app.models.audit_log import AuditLog
from app.models.claim import Claim, ClaimDocument, ExtractedFields
from app.models.decision import Decision
from app.models.role import RoleName
from app.repositories.claim_repo import ClaimRepository
from app.repositories.exclusion_repo import ExclusionRepository
from app.schemas.claim import ClaimListResponse

logger = get_logger(__name__)
settings = get_settings()

ALLOWED_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png"}


class ClaimService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = ClaimRepository(session)

    async def submit_claim(
        self,
        *,
        user_id: UUID,
        patient_name: str,
        claim_item: str,
        reason: str,
        address: str,
        date_of_treatment: str,
        medical_facility: str,
        claim_amount: float,
        description: Optional[str],
        bill_file: UploadFile,
    ) -> Tuple[Claim, Callable]:
        """
        Validate the upload, persist the claim + document record,
        and return (claim, pipeline_coroutine) to be run as a background task.
        """
        # ── Validate file ────────────────────────────────────────
        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        content = await bill_file.read()
        if len(content) > max_bytes:
            raise FileTooLargeError(
                f"File exceeds {settings.MAX_UPLOAD_SIZE_MB} MB limit."
            )
        mime = bill_file.content_type or ""
        if mime not in ALLOWED_MIME_TYPES:
            raise UnsupportedFileTypeError(
                f"File type '{mime}' is not allowed. Use PDF, JPG, or PNG."
            )

        # ── Save file to disk ─────────────────────────────────────
        settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        file_id = uuid.uuid4()
        suffix = bill_file.filename.rsplit(".", 1)[-1] if bill_file.filename else "bin"
        file_path = settings.UPLOAD_DIR / f"{file_id}.{suffix}"
        file_path.write_bytes(content)

        # ── Persist claim ─────────────────────────────────────────
        claim = Claim(
            user_id=user_id,
            patient_name=patient_name,
            claim_item=claim_item,
            reason=reason,
            address=address,
            date_of_treatment=date.fromisoformat(date_of_treatment),
            medical_facility=medical_facility,
            claim_amount=Decimal(str(claim_amount)).quantize(Decimal("0.01")),
            description=description,
            status="PENDING",
        )
        claim = await self._repo.create(claim)

        # ── Persist document record ───────────────────────────────
        doc = ClaimDocument(
            claim_id=claim.id,
            file_name=bill_file.filename or f"bill.{suffix}",
            file_path=str(file_path),
            mime_type=mime,
        )
        await self._repo.add_document(doc)
        await self._session.commit()

        logger.info("claim_submitted", claim_id=str(claim.id), user_id=str(user_id))

        # ── Capture IDs for background task closure ───────────────
        claim_id = claim.id
        doc_file_path = str(file_path)
        doc_mime_type = mime

        async def _pipeline():
            """
            Full AI pipeline — runs as a FastAPI BackgroundTask.
            Uses its own DB session (not the request session).
            """
            from app.core.database import AsyncSessionLocal
            from app.llm.groq_client import GroqClient
            from app.repositories.claim_repo import ClaimRepository
            from app.repositories.exclusion_repo import ExclusionRepository
            from app.services.decision_service import DecisionService
            from app.services.extraction_service import ExtractionService
            from app.services.ocr_service import OCRService
            from app.services.rag_service import RAGService
            from app.validators.base import ClaimContext

            async with AsyncSessionLocal() as bg_session:
                bg_repo = ClaimRepository(bg_session)
                excl_repo = ExclusionRepository(bg_session)

                try:
                    # ── 1. PROCESSING ─────────────────────────────
                    await bg_repo.update_status(claim_id, "PROCESSING")
                    await bg_session.commit()
                    logger.info("pipeline_started", claim_id=str(claim_id))

                    # ── 2. OCR ────────────────────────────────────
                    ocr_svc = OCRService()
                    raw_text = ocr_svc.extract_text(doc_file_path, doc_mime_type)

                    # Save raw OCR text to the document record
                    claim_obj = await bg_repo.get_with_details(claim_id)
                    if claim_obj and claim_obj.documents:
                        claim_obj.documents[0].raw_ocr_text = raw_text
                        await bg_session.flush()

                    logger.info("ocr_complete", claim_id=str(claim_id), chars=len(raw_text))

                    # ── 3. LLM Extraction ─────────────────────────
                    llm_client = GroqClient()
                    extraction_svc = ExtractionService(llm_client)
                    extraction = await extraction_svc.extract(
                        raw_text, patient_name_hint=patient_name
                    )

                    # Persist extracted fields
                    extracted = ExtractedFields(
                        claim_id=claim_id,
                        patient_name_extracted=extraction.patient_name,
                        diagnosis=extraction.diagnosis,
                        facility_extracted=extraction.facility,
                        date_extracted=(
                            date.fromisoformat(extraction.date_of_treatment)
                            if extraction.date_of_treatment
                            else None
                        ),
                        itemised_charges=extraction.itemised_charges,
                        total_amount_extracted=(
                            Decimal(str(extraction.total_amount)).quantize(Decimal("0.01"))
                            if extraction.total_amount
                            else None
                        ),
                        llm_model=llm_client.model_name(),
                        prompt_version=extraction_svc.prompt_version,
                    )
                    await bg_repo.set_extracted_fields(extracted)
                    await bg_session.commit()
                    logger.info(
                        "extraction_complete",
                        claim_id=str(claim_id),
                        diagnosis=extraction.diagnosis,
                    )

                    # ── 4. Build validator context ─────────────────
                    excl_terms = await excl_repo.get_active_terms()

                    ctx = ClaimContext(
                        patient_name=patient_name,
                        claim_item=claim_item,
                        reason=reason,
                        address=address,
                        date_of_treatment=date_of_treatment,
                        medical_facility=medical_facility,
                        claim_amount=claim_amount,
                        description=description or "",
                        raw_ocr_text=raw_text,
                        extracted_patient_name=extraction.patient_name,
                        extracted_diagnosis=extraction.diagnosis,
                        extracted_facility=extraction.facility,
                        extracted_date=extraction.date_of_treatment,
                        extracted_total_amount=extraction.total_amount,
                        itemised_charges=extraction.itemised_charges,
                        exclusion_terms=excl_terms,
                    )

                    # ── 5. Decision engine (validator chain) ──────
                    rag_svc = RAGService(bg_session)
                    decision_svc = DecisionService(llm_client, rag_svc)
                    decision_result = await decision_svc.evaluate(ctx)

                    # ── 6. Persist decision ───────────────────────
                    decision = Decision(
                        claim_id=claim_id,
                        outcome=decision_result.status,
                        reason=decision_result.final_reason,
                        cited_clauses=decision_result.cited_clauses,
                        executive_summary=decision_result.executive_summary,
                        confidence_score=decision_result.confidence,
                        model_name=decision_result.model_name,
                        prompt_version=decision_result.prompt_version,
                        retrieved_chunks=[
                            {"validator": r.validator_name, "details": r.details}
                            for r in decision_result.results
                        ],
                    )
                    bg_session.add(decision)

                    # Update claim status
                    await bg_repo.update_status(
                        claim_id,
                        decision_result.status,
                        confidence=decision_result.confidence,
                    )

                    # ── 7. Audit log ──────────────────────────────
                    audit = AuditLog(
                        claim_id=claim_id,
                        user_id=user_id,
                        action="AI_DECISION",
                        payload={
                            "outcome": decision_result.status,
                            "confidence": decision_result.confidence,
                            "model_name": decision_result.model_name,
                            "prompt_version": decision_result.prompt_version,
                            "cited_clauses": decision_result.cited_clauses,
                            "validator_results": [
                                {
                                    "name": r.validator_name,
                                    "outcome": r.outcome.value,
                                    "reason": r.reason,
                                }
                                for r in decision_result.results
                            ],
                        },
                    )
                    bg_session.add(audit)
                    await bg_session.commit()

                    logger.info(
                        "pipeline_complete",
                        claim_id=str(claim_id),
                        status=decision_result.status,
                        confidence=decision_result.confidence,
                    )

                    # ── 8. Fire n8n webhook ───────────────────────
                    await _fire_webhook(claim_id, decision_result.status, patient_name)

                except Exception as exc:
                    logger.error(
                        "pipeline_failed",
                        claim_id=str(claim_id),
                        error=str(exc),
                    )
                    try:
                        await bg_repo.update_status(claim_id, "NEEDS_REVIEW")
                        audit = AuditLog(
                            claim_id=claim_id,
                            user_id=user_id,
                            action="PIPELINE_ERROR",
                            payload={"error": str(exc)},
                        )
                        bg_session.add(audit)
                        await bg_session.commit()
                    except Exception:
                        logger.error("failed_to_record_pipeline_error", claim_id=str(claim_id))

        return claim, _pipeline

    async def list_claims(
        self,
        *,
        user_id: Optional[UUID],
        status: Optional[str],
        page: int,
        page_size: int,
    ) -> ClaimListResponse:
        skip = (page - 1) * page_size
        items, total = await self._repo.list_claims(
            user_id=user_id, status=status, skip=skip, limit=page_size
        )
        return ClaimListResponse(items=items, total=total, page=page, page_size=page_size)

    async def get_claim(self, *, claim_id: UUID, requesting_user) -> Optional[Claim]:
        claim = await self._repo.get_with_details(claim_id)
        if claim is None:
            return None
        # Regular users can only see their own claims
        if requesting_user.role == RoleName.USER and claim.user_id != requesting_user.user_id:
            return None
        return claim


async def _fire_webhook(claim_id: UUID, status: str, patient_name: str) -> None:
    """Fire the n8n webhook for claim-decided events. Best-effort, never raises."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                settings.N8N_WEBHOOK_URL,
                json={
                    "claim_id": str(claim_id),
                    "status": status,
                    "patient_name": patient_name,
                    "timestamp": str(__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()),
                },
            )
        logger.info("webhook_fired", claim_id=str(claim_id), status=status)
    except Exception as exc:
        logger.warning("webhook_failed", claim_id=str(claim_id), error=str(exc))
