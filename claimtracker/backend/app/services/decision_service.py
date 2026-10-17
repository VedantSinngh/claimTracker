"""
app/services/decision_service.py
──────────────────────────────────
Orchestrates the validator chain and produces the final decision.

Chain of Responsibility (in order, stopping at first failure):
1. CompletenessValidator   — all fields present?
2. AmountCheckValidator    — claimed ≤ bill total?
3. ConsistencyValidator    — form matches bill (fuzzy)?
4. ExclusionCheckValidator — diagnosis not excluded? (DETERMINISTIC)
5. RAGPolicyCheckValidator — handbook says covered? (LLM)

Each step returns PASS, FAIL, or NEEDS_REVIEW.
On FAIL or NEEDS_REVIEW, the chain stops immediately.
On PASS, the next validator runs.

The final decision is:
- ACCEPTED if ALL validators pass
- REJECTED if any validator FAILs
- NEEDS_REVIEW if any validator returns NEEDS_REVIEW
"""
from __future__ import annotations

from typing import List, Optional

from app.core.logging import get_logger
from app.llm.base import LLMClient
from app.services.rag_service import RAGService
from app.validators.amount_check import AmountCheckValidator
from app.validators.base import (
    BaseValidator,
    ClaimContext,
    ValidationOutcome,
    ValidationResult,
)
from app.validators.completeness import CompletenessValidator
from app.validators.consistency_check import ConsistencyValidator
from app.validators.exclusion_check import ExclusionCheckValidator
from app.validators.rag_policy_check import RAGPolicyCheckValidator

logger = get_logger(__name__)


# ── Outcome mapping ───────────────────────────────────────────────────────────

_OUTCOME_TO_STATUS = {
    ValidationOutcome.PASS: "ACCEPTED",
    ValidationOutcome.FAIL: "REJECTED",
    ValidationOutcome.NEEDS_REVIEW: "NEEDS_REVIEW",
}


class DecisionResult:
    """Aggregate result from the full validator chain."""

    def __init__(
        self,
        status: str,
        results: List[ValidationResult],
        confidence: Optional[float] = None,
        cited_clauses: Optional[list] = None,
        executive_summary: Optional[str] = None,
    ) -> None:
        self.status = status
        self.results = results
        self.confidence = confidence
        self.cited_clauses = cited_clauses
        self.executive_summary = executive_summary

    @property
    def final_reason(self) -> str:
        """Reason from the last (deciding) validator."""
        if self.results:
            return self.results[-1].reason
        return ""

    @property
    def model_name(self) -> Optional[str]:
        for r in reversed(self.results):
            if "model" in r.details:
                return r.details["model"]
        return None

    @property
    def prompt_version(self) -> Optional[str]:
        for r in reversed(self.results):
            if "prompt_version" in r.details:
                return r.details["prompt_version"]
        return None


class DecisionService:
    """
    Builds the validator chain, runs it in order, returns DecisionResult.
    """

    def __init__(self, llm_client: LLMClient, rag_service: RAGService) -> None:
        self._llm = llm_client
        self._rag = rag_service

    async def evaluate(self, ctx: ClaimContext) -> DecisionResult:
        """
        Run the full validation chain.
        """
        # ── Build chain ──────────────────────────────────────────
        chain: List[BaseValidator] = [
            CompletenessValidator(),
            AmountCheckValidator(),
            ConsistencyValidator(),
            ExclusionCheckValidator(),
        ]

        results: List[ValidationResult] = []

        # ── Run deterministic validators (1–4) ───────────────────
        for validator in chain:
            logger.info("validator_running", name=validator.name)
            result = await validator.validate(ctx)
            results.append(result)
            logger.info(
                "validator_complete",
                name=validator.name,
                outcome=result.outcome.value,
                reason=result.reason[:100],
            )

            if result.outcome != ValidationOutcome.PASS:
                # Chain stops — return immediately
                return DecisionResult(
                    status=_OUTCOME_TO_STATUS[result.outcome],
                    results=results,
                )

        # ── Step 5: RAG Policy Check (LLM) ───────────────────────
        # Only runs if all deterministic checks passed
        try:
            # Retrieve handbook clauses
            query = self._build_rag_query(ctx)
            ctx.retrieved_clauses = await self._rag.retrieve_formatted(query)

            rag_validator = RAGPolicyCheckValidator(self._llm)
            logger.info("validator_running", name=rag_validator.name)
            rag_result = await rag_validator.validate(ctx)
            results.append(rag_result)
            logger.info(
                "validator_complete",
                name=rag_validator.name,
                outcome=rag_result.outcome.value,
            )

            # Extract structured data from RAG result
            confidence = rag_result.details.get("confidence")
            cited_clauses = rag_result.details.get("cited_clauses")
            exec_summary_data = rag_result.details.get("executive_summary")
            executive_summary = self._format_executive_summary(
                exec_summary_data, ctx, results
            ) if exec_summary_data else self._build_default_summary(ctx, results)

            return DecisionResult(
                status=_OUTCOME_TO_STATUS[rag_result.outcome],
                results=results,
                confidence=confidence,
                cited_clauses=cited_clauses,
                executive_summary=executive_summary,
            )
        except Exception as exc:
            logger.error("rag_policy_check_failed", error=str(exc))
            # RAG failure → NEEDS_REVIEW (safe fallback)
            results.append(
                ValidationResult(
                    outcome=ValidationOutcome.NEEDS_REVIEW,
                    validator_name="rag_policy_check",
                    reason=f"RAG policy check failed: {exc}. Routing to manual review.",
                )
            )
            return DecisionResult(
                status="NEEDS_REVIEW",
                results=results,
                executive_summary=self._build_default_summary(ctx, results),
            )

    @staticmethod
    def _build_rag_query(ctx: ClaimContext) -> str:
        """Build the search query for FAISS retrieval from claim details."""
        parts = [
            ctx.extracted_diagnosis or ctx.reason,
            ctx.claim_item,
            ctx.description or "",
        ]
        return " ".join(p for p in parts if p).strip()

    @staticmethod
    def _format_executive_summary(
        llm_summary: dict, ctx: ClaimContext, results: List[ValidationResult]
    ) -> str:
        """Format the LLM's executive summary into a readable string."""
        sections = []
        if llm_summary.get("introduction"):
            sections.append(f"**Introduction**\n{llm_summary['introduction']}")
        if llm_summary.get("claim_details"):
            sections.append(f"**Claim Details**\n{llm_summary['claim_details']}")
        if llm_summary.get("document_verification"):
            sections.append(f"**Document Verification**\n{llm_summary['document_verification']}")
        if llm_summary.get("decision_reason"):
            sections.append(f"**Decision Reason**\n{llm_summary['decision_reason']}")
        if llm_summary.get("clauses_applied"):
            sections.append(f"**Handbook Clauses Applied**\n{llm_summary['clauses_applied']}")
        return "\n\n".join(sections)

    @staticmethod
    def _build_default_summary(ctx: ClaimContext, results: List[ValidationResult]) -> str:
        """Build a summary when the LLM didn't produce one."""
        lines = [
            "**Introduction**",
            f"Claim for {ctx.claim_item} submitted by {ctx.patient_name}.",
            "",
            "**Claim Details**",
            f"- Amount: ${ctx.claim_amount:,.2f}",
            f"- Facility: {ctx.medical_facility}",
            f"- Date: {ctx.date_of_treatment}",
            f"- Diagnosis: {ctx.extracted_diagnosis or ctx.reason}",
            "",
            "**Validation Results**",
        ]
        for r in results:
            emoji = "✅" if r.outcome == ValidationOutcome.PASS else (
                "❌" if r.outcome == ValidationOutcome.FAIL else "⚠️"
            )
            lines.append(f"{emoji} {r.validator_name}: {r.reason}")
        return "\n".join(lines)
