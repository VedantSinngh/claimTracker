"""
tests/unit/test_decision_service.py
────────────────────────────────────
`DecisionService` chain orchestration and `RAGPolicyCheckValidator`, with a
scripted LLM and a stub retriever.

Covered here rather than in the sample-PDF test: the branches that need an
unusual LLM response — low confidence, malformed JSON, a retrieval failure —
and the default executive summary used when the model supplies none.
"""
from __future__ import annotations

import json
from typing import List, Optional

import pytest

from app.core.config import get_settings
from app.llm.base import LLMClient, LLMMessage, LLMResponse
from app.services.decision_service import DecisionService
from app.validators.base import ClaimContext, ValidationOutcome

pytestmark = pytest.mark.asyncio

settings = get_settings()


# ── Doubles ───────────────────────────────────────────────────────────────────

class ScriptedLLM(LLMClient):
    def __init__(self, *bodies: str) -> None:
        self._bodies = list(bodies)
        self.calls: List[List[LLMMessage]] = []

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
        self.calls.append(list(messages))
        body = self._bodies.pop(0) if self._bodies else "{}"
        return LLMResponse(content=body, model=self.model_name())


class StubRAG:
    def __init__(self, clauses: str = "[Clause 1] SECTION 2.1 — hospitalisation is covered.") -> None:
        self._clauses = clauses
        self.queries: List[str] = []

    async def retrieve_formatted(self, query: str, top_k: Optional[int] = None) -> str:
        self.queries.append(query)
        return self._clauses


class ExplodingRAG:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.queries: List[str] = []

    async def retrieve_formatted(self, query: str, top_k: Optional[int] = None) -> str:
        self.queries.append(query)
        raise self._exc


def _clean_context(**overrides) -> ClaimContext:
    """A claim that passes all four deterministic validators."""
    base = dict(
        patient_name="John Smith",
        claim_item="Hospitalisation",
        reason="Acute appendicitis",
        address="45 Maple Avenue, New York, NY 10002",
        date_of_treatment="2024-03-15",
        medical_facility="Metropolitan General Hospital",
        claim_amount=9860.0,
        description="Emergency laparoscopic appendectomy.",
        raw_ocr_text="Diagnosis: Acute appendicitis. TOTAL $9,860.00",
        extracted_patient_name="John Smith",
        extracted_diagnosis="Acute appendicitis",
        extracted_facility="Metropolitan General Hospital",
        extracted_date="2024-03-15",
        extracted_total_amount=9860.0,
        itemised_charges={"Appendectomy": 5500.0},
        exclusion_terms=["cosmetic surgery", "obesity treatment including bariatric surgery"],
    )
    base.update(overrides)
    return ClaimContext(**base)


def _decision_body(outcome: str = "ACCEPTED", confidence: float = 0.95, **extra) -> str:
    payload = {
        "outcome": outcome,
        "confidence": confidence,
        "reason": f"Decided {outcome} against the retrieved clauses.",
        "cited_clauses": [{"clause": "SECTION 2.1", "text": "Hospitalisation is covered."}],
    }
    payload.update(extra)
    return json.dumps(payload)


# ── Outcome mapping ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "llm_outcome,expected_status",
    [
        ("ACCEPTED", "ACCEPTED"),
        ("REJECTED", "REJECTED"),
        ("NEEDS_REVIEW", "NEEDS_REVIEW"),
    ],
)
async def test_llm_outcome_maps_to_claim_status(llm_outcome, expected_status):
    llm = ScriptedLLM(_decision_body(outcome=llm_outcome, confidence=0.95))
    result = await DecisionService(llm, StubRAG()).evaluate(_clean_context())

    assert result.status == expected_status
    assert result.confidence == 0.95


async def test_unrecognised_llm_outcome_falls_back_to_review():
    """An out-of-schema outcome must never be read as an approval."""
    llm = ScriptedLLM(_decision_body(outcome="DEFINITELY_PAY_IT", confidence=0.99))
    result = await DecisionService(llm, StubRAG()).evaluate(_clean_context())

    assert result.status == "NEEDS_REVIEW"


# ── Confidence threshold ──────────────────────────────────────────────────────

async def test_low_confidence_forces_review_despite_an_approval():
    below = settings.CONFIDENCE_THRESHOLD - 0.2
    llm = ScriptedLLM(_decision_body(outcome="ACCEPTED", confidence=below))

    result = await DecisionService(llm, StubRAG()).evaluate(_clean_context())

    assert result.status == "NEEDS_REVIEW"
    assert "below threshold" in result.final_reason
    # The model's own call is preserved for the reviewer to see.
    assert result.results[-1].details["llm_outcome"] == "ACCEPTED"
    assert result.results[-1].details["confidence"] == below


async def test_low_confidence_also_overrides_a_rejection():
    """Symmetry: a low-confidence rejection is not auto-applied either."""
    below = settings.CONFIDENCE_THRESHOLD - 0.3
    llm = ScriptedLLM(_decision_body(outcome="REJECTED", confidence=below))

    result = await DecisionService(llm, StubRAG()).evaluate(_clean_context())
    assert result.status == "NEEDS_REVIEW"


async def test_confidence_exactly_at_threshold_is_accepted():
    """The guard is `< threshold`, so the boundary value passes."""
    llm = ScriptedLLM(
        _decision_body(outcome="ACCEPTED", confidence=settings.CONFIDENCE_THRESHOLD)
    )
    result = await DecisionService(llm, StubRAG()).evaluate(_clean_context())
    assert result.status == "ACCEPTED"


# ── Retrieval failures ────────────────────────────────────────────────────────

async def test_retrieval_failure_routes_to_review_not_rejection():
    """
    A broken index must not look like a policy decision. The fallback is
    NEEDS_REVIEW with a reason that names the cause.
    """
    from app.core.exceptions import RAGIndexNotFound

    llm = ScriptedLLM(_decision_body())
    rag = ExplodingRAG(RAGIndexNotFound("No active handbook found."))

    result = await DecisionService(llm, rag).evaluate(_clean_context())

    assert result.status == "NEEDS_REVIEW"
    assert "RAG policy check failed" in result.final_reason
    assert "No active handbook" in result.final_reason
    assert llm.calls == [], "the LLM must not be called without clauses"
    # A summary is still produced so the reviewer has context.
    assert result.executive_summary
    assert "Validation Results" in result.executive_summary


async def test_empty_clause_set_routes_to_review():
    """No clauses retrieved → no evidence → no decision."""
    llm = ScriptedLLM(_decision_body())
    result = await DecisionService(llm, StubRAG(clauses="")).evaluate(_clean_context())

    assert result.status == "NEEDS_REVIEW"
    assert "No handbook clauses retrieved" in result.final_reason
    assert llm.calls == []


# ── Malformed LLM output ──────────────────────────────────────────────────────

async def test_malformed_decision_json_retries_then_reviews():
    llm = ScriptedLLM("not json", "still not json")

    result = await DecisionService(llm, StubRAG()).evaluate(_clean_context())

    assert result.status == "NEEDS_REVIEW"
    assert "valid decision after 2 attempts" in result.final_reason
    assert len(llm.calls) == 2


async def test_malformed_then_valid_json_succeeds():
    llm = ScriptedLLM("```not json```", _decision_body(outcome="ACCEPTED"))

    result = await DecisionService(llm, StubRAG()).evaluate(_clean_context())

    assert result.status == "ACCEPTED"
    assert len(llm.calls) == 2


# ── Short-circuiting ──────────────────────────────────────────────────────────

async def test_deterministic_failure_skips_retrieval_and_the_llm():
    llm = ScriptedLLM(_decision_body())
    rag = StubRAG()
    # Claim more than the bill → amount_check FAILs at step 2.
    ctx = _clean_context(claim_amount=50_000.0)

    result = await DecisionService(llm, rag).evaluate(ctx)

    assert result.status == "REJECTED"
    assert [r.validator_name for r in result.results] == [
        "completeness_check",
        "amount_check",
    ]
    assert rag.queries == []
    assert llm.calls == []
    # No LLM call means no model/prompt provenance to record.
    assert result.model_name is None
    assert result.prompt_version is None


async def test_exclusion_match_stops_before_the_llm():
    llm = ScriptedLLM(_decision_body())
    rag = StubRAG()
    ctx = _clean_context(
        reason="Obesity",
        claim_item="Bariatric surgery",
        extracted_diagnosis="Obesity - bariatric surgery",
    )

    result = await DecisionService(llm, rag).evaluate(ctx)

    assert result.status == "REJECTED"
    assert result.results[-1].validator_name == "exclusion_check"
    assert llm.calls == [], "the deterministic check must pre-empt the LLM"


# ── Provenance and summaries ──────────────────────────────────────────────────

async def test_model_and_prompt_version_are_recorded():
    llm = ScriptedLLM(_decision_body())
    result = await DecisionService(llm, StubRAG()).evaluate(_clean_context())

    assert result.model_name == "fake-llama-3"
    assert result.prompt_version == "decision_v1"


async def test_llm_executive_summary_is_formatted_into_sections():
    body = _decision_body(
        executive_summary={
            "introduction": "Intro text.",
            "claim_details": "Details text.",
            "document_verification": "Verification text.",
            "decision_reason": "Reason text.",
            "clauses_applied": "Section 2.1.",
        }
    )
    result = await DecisionService(ScriptedLLM(body), StubRAG()).evaluate(_clean_context())

    summary = result.executive_summary
    assert "**Introduction**\nIntro text." in summary
    assert "**Claim Details**\nDetails text." in summary
    assert "**Document Verification**\nVerification text." in summary
    assert "**Decision Reason**\nReason text." in summary
    assert "**Handbook Clauses Applied**\nSection 2.1." in summary


async def test_default_summary_is_built_when_the_llm_omits_one():
    """A decision always carries a summary, even if the model skipped it."""
    llm = ScriptedLLM(_decision_body())  # no executive_summary key
    result = await DecisionService(llm, StubRAG()).evaluate(_clean_context())

    summary = result.executive_summary
    assert "**Introduction**" in summary
    assert "Hospitalisation" in summary
    assert "$9,860.00" in summary
    assert "Metropolitan General Hospital" in summary
    assert "**Validation Results**" in summary
    # Every validator that ran is listed with a status marker.
    for validator in (
        "completeness_check",
        "amount_check",
        "consistency_check",
        "exclusion_check",
    ):
        assert validator in summary


async def test_rag_query_is_built_from_diagnosis_and_claim_item():
    rag = StubRAG()
    await DecisionService(ScriptedLLM(_decision_body()), rag).evaluate(_clean_context())

    assert len(rag.queries) == 1
    query = rag.queries[0]
    assert "Acute appendicitis" in query
    assert "Hospitalisation" in query


async def test_cited_clauses_survive_to_the_result():
    llm = ScriptedLLM(_decision_body())
    result = await DecisionService(llm, StubRAG()).evaluate(_clean_context())

    assert result.cited_clauses == [
        {"clause": "SECTION 2.1", "text": "Hospitalisation is covered."}
    ]


async def test_all_validator_results_are_retained_for_the_audit_log():
    llm = ScriptedLLM(_decision_body())
    result = await DecisionService(llm, StubRAG()).evaluate(_clean_context())

    assert [r.validator_name for r in result.results] == [
        "completeness_check",
        "amount_check",
        "consistency_check",
        "exclusion_check",
        "rag_policy_check",
    ]
    assert all(r.outcome == ValidationOutcome.PASS for r in result.results)
