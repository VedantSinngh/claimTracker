"""
app/validators/completeness.py
────────────────────────────────
Step 1 in the chain: are all required fields present and is the bill readable?
"""
from app.validators.base import (
    BaseValidator,
    ClaimContext,
    ValidationOutcome,
    ValidationResult,
)


class CompletenessValidator(BaseValidator):
    """Checks that all required form fields exist and OCR text is non-empty."""

    @property
    def name(self) -> str:
        return "completeness_check"

    async def validate(self, ctx: ClaimContext) -> ValidationResult:
        missing: list[str] = []

        if not ctx.patient_name or len(ctx.patient_name.strip()) < 2:
            missing.append("patient_name")
        if not ctx.claim_item or len(ctx.claim_item.strip()) < 2:
            missing.append("claim_item")
        if not ctx.reason or len(ctx.reason.strip()) < 2:
            missing.append("reason")
        if not ctx.address or len(ctx.address.strip()) < 5:
            missing.append("address")
        if not ctx.date_of_treatment:
            missing.append("date_of_treatment")
        if not ctx.medical_facility or len(ctx.medical_facility.strip()) < 2:
            missing.append("medical_facility")
        if ctx.claim_amount <= 0:
            missing.append("claim_amount (must be > 0)")

        # Bill must have produced readable text
        if not ctx.raw_ocr_text or len(ctx.raw_ocr_text.strip()) < 20:
            missing.append("bill_text (OCR failed or unreadable)")

        if missing:
            return ValidationResult(
                outcome=ValidationOutcome.FAIL,
                validator_name=self.name,
                reason=f"Missing or incomplete fields: {', '.join(missing)}",
                details={"missing_fields": missing},
            )

        return ValidationResult(
            outcome=ValidationOutcome.PASS,
            validator_name=self.name,
            reason="All required fields are present.",
        )
