"""
app/validators/rag_policy_check.py
────────────────────────────────────
Step 5 (LAST in chain): LLM-powered policy check using RAG.

This runs AFTER all deterministic checks have passed.
Uses the decision prompt to ask the LLM to:
1. Evaluate the claim against retrieved handbook clauses
2. Return ACCEPTED / REJECTED / NEEDS_REVIEW with cited clauses
3. Provide a confidence score

Below-threshold confidence → forces NEEDS_REVIEW regardless of LLM outcome.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.core.config import get_settings
from app.core.exceptions import LLMError
from app.core.logging import get_logger
from app.llm.base import LLMClient, LLMMessage
from app.services.pii_masker import PIIMasker
from app.validators.base import (
    BaseValidator,
    ClaimContext,
    ValidationOutcome,
    ValidationResult,
)

logger = get_logger(__name__)
settings = get_settings()

PROMPT_VERSION = "decision_v1"
_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / f"{PROMPT_VERSION}.txt"


class LLMDecisionOutput(BaseModel):
    """Pydantic model for the LLM's JSON response."""
    outcome: str
    confidence: float = 0.5
    reason: str = ""
    cited_clauses: List[Dict[str, str]] = []
    executive_summary: Optional[Dict[str, str]] = None


class RAGPolicyCheckValidator(BaseValidator):
    """
    Uses the LLM + retrieved handbook clauses to make the final decision.
    Masks PII before sending to the LLM.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm = llm_client
        self._prompt_template = self._load_prompt()

    @property
    def name(self) -> str:
        return "rag_policy_check"

    @staticmethod
    def _load_prompt() -> str:
        if not _PROMPT_PATH.exists():
            raise FileNotFoundError(f"Prompt not found: {_PROMPT_PATH}")
        return _PROMPT_PATH.read_text(encoding="utf-8")

    async def validate(self, ctx: ClaimContext) -> ValidationResult:
        if not ctx.retrieved_clauses:
            return ValidationResult(
                outcome=ValidationOutcome.NEEDS_REVIEW,
                validator_name=self.name,
                reason="No handbook clauses retrieved — cannot perform policy check.",
            )

        # ── Mask PII ─────────────────────────────────────────────
        masker = PIIMasker()
        claim_data = self._build_claim_data(ctx)
        masked_claim_data = masker.mask(
            json.dumps(claim_data, indent=2, default=str),
            patient_name=ctx.patient_name,
        )
        masked_clauses = masker.mask(ctx.retrieved_clauses, patient_name=ctx.patient_name)

        # ── Build prompt ─────────────────────────────────────────
        prompt = self._prompt_template.replace(
            "{retrieved_clauses}", masked_clauses
        ).replace(
            "{claim_data}", masked_claim_data
        )

        messages = [LLMMessage(role="user", content=prompt)]

        # ── Call LLM with retry ──────────────────────────────────
        decision: Optional[LLMDecisionOutput] = None
        for attempt in range(1, 3):
            try:
                response = await self._llm.complete(
                    messages,
                    temperature=0.0,
                    max_tokens=2048,
                    response_format="json_object",
                )
                parsed = self._parse_json(response.content)
                decision = LLMDecisionOutput(**parsed)
                break
            except Exception as exc:
                logger.warning(
                    "rag_decision_parse_failed",
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt < 2:
                    messages.append(LLMMessage(role="assistant", content=response.content))
                    messages.append(LLMMessage(
                        role="user",
                        content="Invalid JSON. Return ONLY the JSON object matching the schema.",
                    ))

        if decision is None:
            return ValidationResult(
                outcome=ValidationOutcome.NEEDS_REVIEW,
                validator_name=self.name,
                reason="LLM failed to return a valid decision after 2 attempts.",
            )

        # ── Apply confidence threshold ───────────────────────────
        if decision.confidence < settings.CONFIDENCE_THRESHOLD:
            logger.info(
                "low_confidence_override",
                llm_outcome=decision.outcome,
                confidence=decision.confidence,
                threshold=settings.CONFIDENCE_THRESHOLD,
            )
            return ValidationResult(
                outcome=ValidationOutcome.NEEDS_REVIEW,
                validator_name=self.name,
                reason=(
                    f"LLM confidence ({decision.confidence:.2f}) is below threshold "
                    f"({settings.CONFIDENCE_THRESHOLD}). Routing to human review."
                ),
                details={
                    "llm_outcome": decision.outcome,
                    "confidence": decision.confidence,
                    "cited_clauses": [dict(c) for c in decision.cited_clauses],
                    "executive_summary": decision.executive_summary,
                    "model": self._llm.model_name(),
                    "prompt_version": PROMPT_VERSION,
                },
            )

        # ── Map LLM outcome to validation outcome ───────────────
        outcome_map = {
            "ACCEPTED": ValidationOutcome.PASS,
            "REJECTED": ValidationOutcome.FAIL,
            "NEEDS_REVIEW": ValidationOutcome.NEEDS_REVIEW,
        }
        outcome = outcome_map.get(
            decision.outcome.upper(), ValidationOutcome.NEEDS_REVIEW
        )

        return ValidationResult(
            outcome=outcome,
            validator_name=self.name,
            reason=decision.reason,
            details={
                "llm_outcome": decision.outcome,
                "confidence": decision.confidence,
                "cited_clauses": [dict(c) for c in decision.cited_clauses],
                "executive_summary": decision.executive_summary,
                "model": self._llm.model_name(),
                "prompt_version": PROMPT_VERSION,
            },
        )

    @staticmethod
    def _build_claim_data(ctx: ClaimContext) -> Dict[str, Any]:
        return {
            "patient_name": ctx.patient_name,
            "claim_item": ctx.claim_item,
            "reason": ctx.reason,
            "date_of_treatment": ctx.date_of_treatment,
            "medical_facility": ctx.medical_facility,
            "claim_amount": ctx.claim_amount,
            "description": ctx.description,
            "extracted_diagnosis": ctx.extracted_diagnosis,
            "extracted_facility": ctx.extracted_facility,
            "extracted_date": ctx.extracted_date,
            "extracted_total_amount": ctx.extracted_total_amount,
            "itemised_charges": ctx.itemised_charges,
        }

    @staticmethod
    def _parse_json(text: str) -> dict:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError(f"No JSON object found: {text[:200]}")
        return json.loads(cleaned[start:end])
