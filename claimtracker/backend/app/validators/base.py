"""
app/validators/base.py
───────────────────────
Abstract base for the Chain of Responsibility pattern.

Each validator:
1. Checks one aspect of the claim
2. Returns a ValidationResult (pass, fail, or needs_review)
3. If it fails, the chain stops — no later validators run

This gives deterministic ordering control (e.g. exclusion check
runs BEFORE the LLM to prevent hallucinated approvals).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ValidationOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NEEDS_REVIEW = "NEEDS_REVIEW"


@dataclass
class ValidationResult:
    """Result of a single validation step."""
    outcome: ValidationOutcome
    validator_name: str
    reason: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ClaimContext:
    """
    All data needed by validators, passed through the chain.
    Avoids each validator needing to re-query the DB.
    """
    # From the claim form
    patient_name: str = ""
    claim_item: str = ""
    reason: str = ""
    address: str = ""
    date_of_treatment: Optional[str] = None
    medical_facility: str = ""
    claim_amount: float = 0.0
    description: str = ""

    # From OCR
    raw_ocr_text: str = ""

    # From LLM extraction
    extracted_patient_name: Optional[str] = None
    extracted_diagnosis: Optional[str] = None
    extracted_facility: Optional[str] = None
    extracted_date: Optional[str] = None
    extracted_total_amount: Optional[float] = None
    itemised_charges: Optional[Dict[str, Any]] = None

    # For the exclusion check
    exclusion_terms: List[str] = field(default_factory=list)

    # For the RAG check (filled by the pipeline before calling the RAG validator)
    retrieved_clauses: str = ""


class BaseValidator(ABC):
    """
    Abstract validator in the Chain of Responsibility.
    Subclasses implement `validate()` with their specific logic.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name for logging and audit."""
        ...

    @abstractmethod
    async def validate(self, ctx: ClaimContext) -> ValidationResult:
        """
        Validate one aspect of the claim.
        Must return a ValidationResult, never raise exceptions.
        """
        ...
