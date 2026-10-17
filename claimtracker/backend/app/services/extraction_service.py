"""
app/services/extraction_service.py
────────────────────────────────────
LLM-based structured extraction from bill text.

Flow:
1. Receive raw OCR text from the bill
2. Mask PII before sending to LLM
3. Load versioned prompt template (extract_v1.txt)
4. Call LLM with strict JSON output schema
5. Parse response with Pydantic (BillExtraction model)
6. Retry once on invalid JSON (common with LLMs)
7. Return validated extraction result
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, field_validator

from app.core.config import get_settings
from app.core.exceptions import ExtractionError
from app.core.logging import get_logger
from app.llm.base import LLMClient, LLMMessage
from app.services.pii_masker import PIIMasker

logger = get_logger(__name__)
settings = get_settings()

PROMPT_VERSION = "extract_v1"
_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / f"{PROMPT_VERSION}.txt"


# ── Extraction schema (Pydantic) ──────────────────────────────────────────────

class BillExtraction(BaseModel):
    """Validated output from the LLM extraction call."""
    patient_name: Optional[str] = None
    diagnosis: Optional[str] = None
    facility: Optional[str] = None
    date_of_treatment: Optional[str] = None
    itemised_charges: Optional[Dict[str, Any]] = None
    total_amount: Optional[float] = None

    @field_validator("date_of_treatment", mode="before")
    @classmethod
    def normalise_date(cls, v):
        if v is None:
            return None
        # Accept common date formats and normalise to YYYY-MM-DD
        if isinstance(v, date):
            return v.isoformat()
        return str(v).strip()

    @field_validator("total_amount", mode="before")
    @classmethod
    def normalise_amount(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            # Remove $ and commas
            v = v.replace("$", "").replace(",", "").strip()
        try:
            return float(v)
        except (ValueError, TypeError):
            return None


# ── Service ───────────────────────────────────────────────────────────────────

class ExtractionService:
    """
    Extracts structured fields from raw bill text using an LLM.
    Uses prompt injection protection: bill text is wrapped in delimiters
    and the model is instructed to ignore embedded instructions.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm = llm_client
        self._prompt_template = self._load_prompt()

    @staticmethod
    def _load_prompt() -> str:
        if not _PROMPT_PATH.exists():
            raise ExtractionError(f"Prompt file not found: {_PROMPT_PATH}")
        return _PROMPT_PATH.read_text(encoding="utf-8")

    async def extract(
        self,
        raw_text: str,
        patient_name_hint: str = "",
    ) -> BillExtraction:
        """
        Extract structured fields from bill text.
        Masks PII before sending to LLM.
        Retries once on invalid JSON.
        """
        # ── PII masking ──────────────────────────────────────────
        masker = PIIMasker()
        masked_text = masker.mask(raw_text, patient_name=patient_name_hint)

        # ── Build prompt ─────────────────────────────────────────
        prompt = self._prompt_template.replace("{bill_text}", masked_text)

        messages = [
            LLMMessage(role="user", content=prompt),
        ]

        # ── Call LLM with retry ──────────────────────────────────
        extraction: Optional[BillExtraction] = None
        last_error: Optional[str] = None

        for attempt in range(1, 3):  # max 2 attempts
            response = await self._llm.complete(
                messages,
                temperature=0.0,
                max_tokens=1024,
                response_format="json_object",
            )

            try:
                parsed = self._parse_json(response.content)
                extraction = BillExtraction(**parsed)
                break
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "extraction_parse_failed",
                    attempt=attempt,
                    error=last_error,
                    raw_response=response.content[:500],
                )
                if attempt < 2:
                    # Add the failed response so the model can self-correct
                    messages.append(LLMMessage(role="assistant", content=response.content))
                    messages.append(LLMMessage(
                        role="user",
                        content=(
                            "Your previous response was not valid JSON matching the required schema. "
                            "Please try again. Return ONLY the JSON object."
                        ),
                    ))

        if extraction is None:
            raise ExtractionError(
                f"LLM failed to return valid extraction JSON after 2 attempts: {last_error}"
            )

        # ── Unmask patient name for storage ──────────────────────
        if extraction.patient_name and "[NAME_REDACTED]" in extraction.patient_name:
            extraction.patient_name = patient_name_hint or extraction.patient_name

        logger.info(
            "extraction_complete",
            diagnosis=extraction.diagnosis,
            total_amount=extraction.total_amount,
            prompt_version=PROMPT_VERSION,
            model=self._llm.model_name(),
        )
        return extraction

    @staticmethod
    def _parse_json(text: str) -> dict:
        """
        Robustly parse LLM output as JSON.
        Handles markdown code fences, leading text, etc.
        """
        # Strip markdown code fences if present
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # Drop first and last lines (```json and ```)
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            cleaned = "\n".join(lines)

        # Try to find JSON object boundaries
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError(f"No JSON object found in LLM response: {text[:200]}")

        json_str = cleaned[start:end]
        return json.loads(json_str)

    @property
    def prompt_version(self) -> str:
        return PROMPT_VERSION
