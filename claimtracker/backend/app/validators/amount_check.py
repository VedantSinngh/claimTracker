"""
app/validators/amount_check.py
───────────────────────────────
Step 2: claimed amount must not exceed the bill total.
"""
from app.validators.base import (
    BaseValidator,
    ClaimContext,
    ValidationOutcome,
    ValidationResult,
)


class AmountCheckValidator(BaseValidator):
    """
    Rejects if the user-submitted claim amount exceeds
    the total amount extracted from the bill by more than 5%.
    The 5% tolerance handles rounding differences between
    OCR and user input.
    """

    TOLERANCE_PERCENT = 5.0

    @property
    def name(self) -> str:
        return "amount_check"

    async def validate(self, ctx: ClaimContext) -> ValidationResult:
        if ctx.extracted_total_amount is None:
            return ValidationResult(
                outcome=ValidationOutcome.NEEDS_REVIEW,
                validator_name=self.name,
                reason="Could not extract total amount from the bill — manual review required.",
                details={"claim_amount": ctx.claim_amount, "extracted_total": None},
            )

        if ctx.extracted_total_amount <= 0:
            return ValidationResult(
                outcome=ValidationOutcome.NEEDS_REVIEW,
                validator_name=self.name,
                reason="Extracted bill total is zero or negative — likely an OCR error.",
                details={
                    "claim_amount": ctx.claim_amount,
                    "extracted_total": ctx.extracted_total_amount,
                },
            )

        max_allowed = ctx.extracted_total_amount * (1 + self.TOLERANCE_PERCENT / 100)
        if ctx.claim_amount > max_allowed:
            overage = ctx.claim_amount - ctx.extracted_total_amount
            return ValidationResult(
                outcome=ValidationOutcome.FAIL,
                validator_name=self.name,
                reason=(
                    f"Claimed amount (${ctx.claim_amount:,.2f}) exceeds the bill total "
                    f"(${ctx.extracted_total_amount:,.2f}) by ${overage:,.2f}."
                ),
                details={
                    "claim_amount": ctx.claim_amount,
                    "extracted_total": ctx.extracted_total_amount,
                    "overage": overage,
                    "tolerance_percent": self.TOLERANCE_PERCENT,
                },
            )

        return ValidationResult(
            outcome=ValidationOutcome.PASS,
            validator_name=self.name,
            reason=(
                f"Claimed amount (${ctx.claim_amount:,.2f}) is within the bill total "
                f"(${ctx.extracted_total_amount:,.2f})."
            ),
        )
