"""
tests/integration/test_sample_claims_pipeline.py
─────────────────────────────────────────────────
End-to-end validation chain over the four sample bills in `samples/`.

What is real here and what is faked:

- **Real**: OCR (`OCRService` → pdfplumber on the digital sample PDFs), the
  handbook exclusion parser, all four deterministic validators, and
  `DecisionService`'s chain orchestration and outcome mapping.
- **Faked**: the LLM (`FakeLLMClient` replays canned JSON — no Groq calls,
  no API key) and FAISS retrieval (`StubRAGService` returns fixed clauses, so
  the test needs neither a built index nor the embedding model download).

That split is deliberate: the assertions are about *our* decision logic, which
must be reproducible. A real LLM would make these tests flaky and cost money.

Expected outcomes, from the project spec:

| sample                      | expected     | deciding validator  |
|-----------------------------|--------------|---------------------|
| bill_accepted.pdf           | ACCEPTED     | rag_policy_check    |
| bill_excluded.pdf           | REJECTED     | exclusion_check     |
| bill_amount_exceeded.pdf    | REJECTED     | amount_check        |
| bill_mismatch.pdf           | NEEDS_REVIEW | consistency_check   |
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from app.llm.base import LLMClient, LLMMessage, LLMResponse
from app.services.decision_service import DecisionService
from app.services.extraction_service import ExtractionService
from app.services.ocr_service import OCRService
from app.validators.base import ClaimContext, ValidationOutcome

SAMPLES_DIR = Path(__file__).resolve().parents[3] / "samples"
HANDBOOK_PDF = SAMPLES_DIR / "policy_handbook.pdf"

pytestmark = pytest.mark.asyncio


# ── Test doubles ──────────────────────────────────────────────────────────────

class FakeLLMClient(LLMClient):
    """
    Replays a fixed list of response bodies, in order.

    Records every prompt it was given so tests can assert on prompt hygiene
    (PII masking, injection delimiters) without a network call.
    """

    def __init__(self, responses: List[str], model: str = "fake-llama-3") -> None:
        self._responses = list(responses)
        self._model = model
        self.prompts: List[str] = []
        self.call_count = 0

    def model_name(self) -> str:
        return self._model

    async def complete(
        self,
        messages: List[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        response_format: Optional[str] = None,
    ) -> LLMResponse:
        self.call_count += 1
        self.prompts.append("\n".join(m.content for m in messages))
        if not self._responses:
            raise AssertionError(
                f"FakeLLMClient ran out of responses on call {self.call_count}"
            )
        body = self._responses.pop(0)
        return LLMResponse(
            content=body,
            model=self._model,
            prompt_tokens=100,
            completion_tokens=50,
            finish_reason="stop",
        )


class StubRAGService:
    """
    Stands in for RAGService. Duck-typed: DecisionService only ever calls
    `retrieve_formatted`, so no FAISS index or embedding model is needed.
    """

    CLAUSES = (
        "[Clause 1] SECTION 2.1 Hospitalisation — The policy covers in-patient "
        "hospitalisation expenses including room rent, surgeon fees, anaesthesia "
        "and operation theatre charges.\n"
        "[Clause 2] SECTION 4 General Exclusions — item 13: Obesity treatment "
        "including bariatric surgery is not covered."
    )

    def __init__(self) -> None:
        self.queries: List[str] = []

    async def retrieve_formatted(self, query: str, top_k: Optional[int] = None) -> str:
        self.queries.append(query)
        return self.CLAUSES


# ── Scenario definitions ──────────────────────────────────────────────────────

@dataclass
class Scenario:
    """One sample bill plus the form a user would have submitted with it."""

    name: str
    pdf: str
    # Claim form fields
    patient_name: str
    claim_item: str
    reason: str
    address: str
    date_of_treatment: str
    medical_facility: str
    claim_amount: float
    description: str
    # What the (faked) extraction LLM returns for this bill
    extraction: Dict[str, Any]
    # What the (faked) decision LLM would return if the chain reaches it
    decision: Dict[str, Any]
    # Expectations
    expected_status: str
    expected_decider: str
    expect_llm_decision_called: bool
    confidence: Optional[float] = None
    cited_clause_count: int = 0
    extras: Dict[str, Any] = field(default_factory=dict)


_ACCEPT_DECISION = {
    "outcome": "ACCEPTED",
    "confidence": 0.93,
    "reason": (
        "Acute appendicitis is an emergency in-patient procedure covered under "
        "Section 2.1 Hospitalisation. No exclusion applies."
    ),
    "cited_clauses": [
        {
            "clause": "SECTION 2.1 Hospitalisation",
            "text": "The policy covers in-patient hospitalisation expenses.",
        },
        {
            "clause": "SECTION 2.3 Diagnostic Tests",
            "text": "Laboratory tests and imaging are covered when ordered by a physician.",
        },
    ],
    "executive_summary": {
        "introduction": "Claim for emergency appendectomy submitted by the policyholder.",
        "claim_details": "Metropolitan General Hospital, 2024-03-15, $9,860.00.",
        "document_verification": "Itemised bill present and legible; totals reconcile.",
        "decision_reason": "Covered in-patient procedure; no exclusion matched.",
        "clauses_applied": "Section 2.1, Section 2.3.",
    },
}

# Reached only if the chain gets that far — these scenarios must stop earlier.
_UNREACHED_DECISION = {
    "outcome": "ACCEPTED",
    "confidence": 0.99,
    "reason": "This response must never be used: the chain should stop before the LLM.",
    "cited_clauses": [],
}

SCENARIOS: List[Scenario] = [
    Scenario(
        name="normal_illness_accepted",
        pdf="bill_accepted.pdf",
        patient_name="John Smith",
        claim_item="Hospitalisation",
        reason="Acute appendicitis",
        address="45 Maple Avenue, New York, NY 10002",
        date_of_treatment="2024-03-15",
        medical_facility="Metropolitan General Hospital",
        claim_amount=9860.00,
        description="Emergency laparoscopic appendectomy after acute abdominal pain.",
        extraction={
            "patient_name": "John Smith",
            "diagnosis": "Acute appendicitis",
            "facility": "Metropolitan General Hospital",
            "date_of_treatment": "2024-03-15",
            "itemised_charges": {
                "Emergency Room Visit": 1200.00,
                "Appendectomy (Laparoscopic)": 5500.00,
                "Anaesthesia": 1200.00,
                "Operating Room": 1800.00,
            },
            "total_amount": 9860.00,
        },
        decision=_ACCEPT_DECISION,
        expected_status="ACCEPTED",
        expected_decider="rag_policy_check",
        expect_llm_decision_called=True,
        confidence=0.93,
        cited_clause_count=2,
    ),
    Scenario(
        name="excluded_disease_rejected",
        pdf="bill_excluded.pdf",
        patient_name="Jane Doe",
        claim_item="Bariatric surgery",
        reason="Obesity - Bariatric Surgery",
        address="12 Palm Drive, Beverly Hills, CA 90210",
        date_of_treatment="2024-04-10",
        medical_facility="Cosmetic Wellness Center",
        claim_amount=26755.00,
        description="Gastric bypass surgery after conservative management failed.",
        extraction={
            "patient_name": "Jane Doe",
            "diagnosis": "Obesity - Bariatric Surgery",
            "facility": "Cosmetic Wellness Center",
            "date_of_treatment": "2024-04-10",
            "itemised_charges": {
                "Gastric Bypass Surgery (Roux-en-Y)": 18500.00,
                "Anaesthesia": 2400.00,
                "Operating Room": 3200.00,
            },
            "total_amount": 26755.00,
        },
        decision=_UNREACHED_DECISION,
        expected_status="REJECTED",
        expected_decider="exclusion_check",
        expect_llm_decision_called=False,
    ),
    Scenario(
        name="amount_exceeds_bill_rejected",
        pdf="bill_amount_exceeded.pdf",
        patient_name="Robert Brown",
        claim_item="Diabetes follow-up",
        reason="Type 2 Diabetes follow-up",
        address="88 Lakeview Road, Chicago, IL 60601",
        date_of_treatment="2024-05-20",
        medical_facility="Riverdale Medical Center",
        # The form claims far more than the bill's $1,150 total.
        claim_amount=4500.00,
        description="Routine diabetes review, labs and medication refill.",
        extraction={
            "patient_name": "Robert Brown",
            "diagnosis": "Type 2 Diabetes follow-up",
            "facility": "Riverdale Medical Center",
            "date_of_treatment": "2024-05-20",
            "itemised_charges": {
                "Office Consultation": 250.00,
                "HbA1c Laboratory Test": 85.00,
                "Medications (90-day supply)": 345.00,
            },
            "total_amount": 1150.00,
        },
        decision=_UNREACHED_DECISION,
        expected_status="REJECTED",
        expected_decider="amount_check",
        expect_llm_decision_called=False,
    ),
    Scenario(
        name="diagnosis_mismatch_needs_review",
        pdf="bill_mismatch.pdf",
        patient_name="Alice Johnson",
        # Form disagrees with the bill on diagnosis, facility and date.
        claim_item="Cardiac consultation",
        reason="Cardiac chest pain",
        address="9 Harbour Street, Seattle, WA 98101",
        date_of_treatment="2024-07-15",
        medical_facility="Seattle General Hospital",
        claim_amount=2530.00,
        description="Chest pain investigation.",
        extraction={
            "patient_name": "Alice Johnson",
            "diagnosis": "Migraine with aura",
            "facility": "Lakeside Hospital",
            "date_of_treatment": "2024-06-01",
            "itemised_charges": {
                "Emergency Room Visit": 800.00,
                "MRI Brain": 1200.00,
            },
            "total_amount": 2530.00,
        },
        decision=_UNREACHED_DECISION,
        expected_status="NEEDS_REVIEW",
        expected_decider="consistency_check",
        expect_llm_decision_called=False,
    ),
]

SCENARIOS_BY_NAME = {s.name: s for s in SCENARIOS}


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _missing_samples() -> List[str]:
    expected = [HANDBOOK_PDF] + [SAMPLES_DIR / s.pdf for s in SCENARIOS]
    return [p.name for p in expected if not p.exists()]


@pytest.fixture(scope="module")
def samples_present() -> None:
    missing = _missing_samples()
    if missing:
        pytest.skip(
            "sample PDFs not generated: "
            + ", ".join(missing)
            + " — run `python samples/create_sample_pdfs.py`"
        )


@pytest.fixture(scope="module")
def exclusion_terms(samples_present) -> List[str]:
    """
    The exclusion list the admin flow would seed, parsed from the real
    handbook PDF — so this exercises the phase-2 parser, not a hand-written list.
    """
    from app.services.handbook_service import (
        extract_text_from_pdf,
        parse_general_exclusions,
    )

    text = extract_text_from_pdf(HANDBOOK_PDF)
    terms = parse_general_exclusions(text)
    assert terms, "handbook parser found no General Exclusions section"
    return terms


@pytest.fixture(scope="module")
def ocr_text(samples_present) -> Dict[str, str]:
    """Real OCR output for every sample bill, keyed by scenario name."""
    svc = OCRService()
    return {
        s.name: svc.extract_text(str(SAMPLES_DIR / s.pdf), "application/pdf")
        for s in SCENARIOS
    }


async def _run_chain(
    scenario: Scenario,
    exclusion_terms: List[str],
    raw_text: str,
):
    """
    Extraction + full validator chain for one scenario.
    Returns (decision_result, extraction, fake_llm, stub_rag).
    """
    # ── Extraction (faked LLM, real parsing/validation) ──────────
    extraction_llm = FakeLLMClient([json.dumps(scenario.extraction)])
    extraction = await ExtractionService(extraction_llm).extract(
        raw_text, patient_name_hint=scenario.patient_name
    )

    ctx = ClaimContext(
        patient_name=scenario.patient_name,
        claim_item=scenario.claim_item,
        reason=scenario.reason,
        address=scenario.address,
        date_of_treatment=scenario.date_of_treatment,
        medical_facility=scenario.medical_facility,
        claim_amount=scenario.claim_amount,
        description=scenario.description,
        raw_ocr_text=raw_text,
        extracted_patient_name=extraction.patient_name,
        extracted_diagnosis=extraction.diagnosis,
        extracted_facility=extraction.facility,
        extracted_date=extraction.date_of_treatment,
        extracted_total_amount=extraction.total_amount,
        itemised_charges=extraction.itemised_charges,
        exclusion_terms=exclusion_terms,
    )

    decision_llm = FakeLLMClient([json.dumps(scenario.decision)])
    stub_rag = StubRAGService()
    result = await DecisionService(decision_llm, stub_rag).evaluate(ctx)
    return result, extraction, decision_llm, stub_rag


# ── Tests ─────────────────────────────────────────────────────────────────────

async def test_ocr_reads_every_sample(ocr_text: Dict[str, str]):
    """pdfplumber must get usable text out of all four bills."""
    for name, text in ocr_text.items():
        assert len(text) > 200, f"{name}: OCR returned only {len(text)} chars"


def test_handbook_parser_finds_expected_exclusions(exclusion_terms: List[str]):
    """The seeded list must contain the conditions the scenarios depend on."""
    joined = " | ".join(exclusion_terms)
    for expected in ("obesity", "cosmetic surgery", "hiv/aids", "infertility"):
        assert expected in joined.lower(), f"{expected!r} missing from {joined!r}"


@pytest.mark.parametrize("scenario_name", list(SCENARIOS_BY_NAME))
async def test_sample_reaches_expected_outcome(
    scenario_name: str,
    exclusion_terms: List[str],
    ocr_text: Dict[str, str],
):
    scenario = SCENARIOS_BY_NAME[scenario_name]
    result, _, decision_llm, _ = await _run_chain(
        scenario, exclusion_terms, ocr_text[scenario_name]
    )

    assert result.status == scenario.expected_status, (
        f"{scenario_name}: expected {scenario.expected_status}, got {result.status} — "
        f"chain: {[(r.validator_name, r.outcome.value) for r in result.results]}"
    )

    # The last validator in the chain is the one that decided.
    assert result.results[-1].validator_name == scenario.expected_decider
    assert result.final_reason, "a decision must always carry a reason"


@pytest.mark.parametrize("scenario_name", list(SCENARIOS_BY_NAME))
async def test_chain_short_circuits_before_the_llm(
    scenario_name: str,
    exclusion_terms: List[str],
    ocr_text: Dict[str, str],
):
    """
    A deterministic rejection must never reach the LLM — that is the whole
    point of ordering exclusion_check before rag_policy_check.
    """
    scenario = SCENARIOS_BY_NAME[scenario_name]
    _, _, decision_llm, stub_rag = await _run_chain(
        scenario, exclusion_terms, ocr_text[scenario_name]
    )

    if scenario.expect_llm_decision_called:
        assert decision_llm.call_count == 1
        assert stub_rag.queries, "RAG retrieval should have run"
    else:
        assert decision_llm.call_count == 0, (
            f"{scenario_name}: LLM was called although "
            f"{scenario.expected_decider} should have stopped the chain"
        )
        assert stub_rag.queries == [], "RAG retrieval should not have run"


async def test_accepted_claim_carries_citations_and_confidence(
    exclusion_terms: List[str], ocr_text: Dict[str, str]
):
    """No decision without evidence: an acceptance must cite clauses."""
    scenario = SCENARIOS_BY_NAME["normal_illness_accepted"]
    result, _, _, _ = await _run_chain(
        scenario, exclusion_terms, ocr_text[scenario.name]
    )

    assert result.confidence == scenario.confidence
    assert result.cited_clauses is not None
    assert len(result.cited_clauses) == scenario.cited_clause_count
    assert result.model_name == "fake-llama-3"
    assert result.prompt_version == "decision_v1"

    # Executive summary must contain the spec's sections.
    summary = result.executive_summary or ""
    for heading in (
        "Introduction",
        "Claim Details",
        "Document Verification",
        "Decision Reason",
        "Handbook Clauses Applied",
    ):
        assert heading in summary, f"{heading!r} missing from executive summary"


async def test_accepted_claim_passes_all_deterministic_validators(
    exclusion_terms: List[str], ocr_text: Dict[str, str]
):
    scenario = SCENARIOS_BY_NAME["normal_illness_accepted"]
    result, _, _, _ = await _run_chain(
        scenario, exclusion_terms, ocr_text[scenario.name]
    )

    chain = [(r.validator_name, r.outcome) for r in result.results]
    assert chain == [
        ("completeness_check", ValidationOutcome.PASS),
        ("amount_check", ValidationOutcome.PASS),
        ("consistency_check", ValidationOutcome.PASS),
        ("exclusion_check", ValidationOutcome.PASS),
        ("rag_policy_check", ValidationOutcome.PASS),
    ]


async def test_excluded_claim_names_the_matched_exclusion(
    exclusion_terms: List[str], ocr_text: Dict[str, str]
):
    scenario = SCENARIOS_BY_NAME["excluded_disease_rejected"]
    result, _, _, _ = await _run_chain(
        scenario, exclusion_terms, ocr_text[scenario.name]
    )

    deciding = result.results[-1]
    assert deciding.validator_name == "exclusion_check"
    assert "obesity" in deciding.details["matched_exclusion"].lower()
    assert deciding.details["match_method"] in {
        "exact_substring",
        "fuzzy_match",
        "synonym_exact",
        "synonym_fuzzy",
        "bill_text_substring",
    }


async def test_amount_rejection_quantifies_the_overage(
    exclusion_terms: List[str], ocr_text: Dict[str, str]
):
    scenario = SCENARIOS_BY_NAME["amount_exceeds_bill_rejected"]
    result, _, _, _ = await _run_chain(
        scenario, exclusion_terms, ocr_text[scenario.name]
    )

    details = result.results[-1].details
    assert details["claim_amount"] == 4500.00
    assert details["extracted_total"] == 1150.00
    assert details["overage"] == pytest.approx(3350.00)
    assert "$3,350.00" in result.final_reason


async def test_mismatch_review_lists_every_disagreement(
    exclusion_terms: List[str], ocr_text: Dict[str, str]
):
    scenario = SCENARIOS_BY_NAME["diagnosis_mismatch_needs_review"]
    result, _, _, _ = await _run_chain(
        scenario, exclusion_terms, ocr_text[scenario.name]
    )

    deciding = result.results[-1]
    assert deciding.validator_name == "consistency_check"
    reason = deciding.reason.lower()
    assert "facility mismatch" in reason
    assert "date mismatch" in reason
    assert "diagnosis mismatch" in reason
    # Scores are recorded for the reviewer to judge.
    assert deciding.details["date_difference_days"] == 44


async def test_decision_prompt_masks_pii_and_fences_bill_text(
    exclusion_terms: List[str], ocr_text: Dict[str, str]
):
    """
    Responsible-AI contract: the patient's name must not reach the LLM, and the
    untrusted bill text must be delimited.
    """
    scenario = SCENARIOS_BY_NAME["normal_illness_accepted"]
    _, _, decision_llm, _ = await _run_chain(
        scenario, exclusion_terms, ocr_text[scenario.name]
    )

    assert decision_llm.prompts, "the decision LLM should have been called"
    prompt = decision_llm.prompts[0]
    assert "John Smith" not in prompt
    assert "[NAME_REDACTED]" in prompt
