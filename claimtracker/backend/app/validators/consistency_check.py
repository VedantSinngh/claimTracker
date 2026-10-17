"""
app/validators/consistency_check.py
─────────────────────────────────────
Step 3: form facility, date, and diagnosis must fuzzy-match the bill.
Uses rapidfuzz for fuzzy string matching (not exact match).
"""
from datetime import date, datetime
from typing import Optional

from rapidfuzz import fuzz

from app.validators.base import (
    BaseValidator,
    ClaimContext,
    ValidationOutcome,
    ValidationResult,
)


# Minimum fuzzy ratio to consider a match
_FACILITY_THRESHOLD = 60
_DIAGNOSIS_THRESHOLD = 55
_DATE_THRESHOLD_DAYS = 7  # allow up to 7 days difference


class ConsistencyValidator(BaseValidator):
    """
    Fuzzy-matches form fields against extracted bill fields:
    - Medical facility name
    - Date of treatment
    - Diagnosis / reason vs extracted diagnosis

    Any mismatch → NEEDS_REVIEW (not auto-reject — could be OCR noise).
    """

    @property
    def name(self) -> str:
        return "consistency_check"

    async def validate(self, ctx: ClaimContext) -> ValidationResult:
        mismatches: list[str] = []
        details: dict = {}

        # ── Facility match ────────────────────────────────────────
        if ctx.extracted_facility:
            ratio = fuzz.token_sort_ratio(
                ctx.medical_facility.lower(),
                ctx.extracted_facility.lower(),
            )
            details["facility_match_score"] = ratio
            if ratio < _FACILITY_THRESHOLD:
                mismatches.append(
                    f"Facility mismatch (form: '{ctx.medical_facility}', "
                    f"bill: '{ctx.extracted_facility}', score: {ratio})"
                )

        # ── Date match ────────────────────────────────────────────
        if ctx.extracted_date and ctx.date_of_treatment:
            form_date = self._parse_date(ctx.date_of_treatment)
            bill_date = self._parse_date(ctx.extracted_date)
            if form_date and bill_date:
                delta = abs((form_date - bill_date).days)
                details["date_difference_days"] = delta
                if delta > _DATE_THRESHOLD_DAYS:
                    mismatches.append(
                        f"Date mismatch: form date {form_date.isoformat()} vs "
                        f"bill date {bill_date.isoformat()} ({delta} days apart)"
                    )

        # ── Diagnosis / reason match ──────────────────────────────
        if ctx.extracted_diagnosis:
            # Compare both the form "reason" and "claim_item" against extracted diagnosis
            reason_score = fuzz.token_sort_ratio(
                ctx.reason.lower(), ctx.extracted_diagnosis.lower()
            )
            item_score = fuzz.token_sort_ratio(
                ctx.claim_item.lower(), ctx.extracted_diagnosis.lower()
            )
            best_score = max(reason_score, item_score)
            details["diagnosis_match_score"] = best_score
            if best_score < _DIAGNOSIS_THRESHOLD:
                mismatches.append(
                    f"Diagnosis mismatch (form reason: '{ctx.reason}', "
                    f"form item: '{ctx.claim_item}', "
                    f"bill diagnosis: '{ctx.extracted_diagnosis}', "
                    f"best score: {best_score})"
                )

        if mismatches:
            return ValidationResult(
                outcome=ValidationOutcome.NEEDS_REVIEW,
                validator_name=self.name,
                reason=f"Consistency mismatches found: {'; '.join(mismatches)}",
                details=details,
            )

        return ValidationResult(
            outcome=ValidationOutcome.PASS,
            validator_name=self.name,
            reason="Form fields are consistent with the bill.",
            details=details,
        )

    @staticmethod
    def _parse_date(date_str: str) -> Optional[date]:
        """Try common date formats."""
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(date_str.strip(), fmt).date()
            except ValueError:
                continue
        return None
