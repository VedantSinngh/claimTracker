"""
tests/unit/test_completeness_validator.py
──────────────────────────────────────────
"""
import pytest

from app.validators.base import ClaimContext, ValidationOutcome
from app.validators.completeness import CompletenessValidator


@pytest.fixture
def validator():
    return CompletenessValidator()


@pytest.fixture
def valid_ctx():
    return ClaimContext(
        patient_name="John Smith",
        claim_item="Appendectomy",
        reason="Acute appendicitis",
        address="123 Main St, New York, NY 10001",
        date_of_treatment="2024-03-15",
        medical_facility="Metropolitan General Hospital",
        claim_amount=9860.00,
        raw_ocr_text="This is a valid bill with enough text to pass the check " * 3,
    )


class TestCompletenessValidator:
    @pytest.mark.asyncio
    async def test_pass_with_all_fields(self, validator, valid_ctx):
        result = await validator.validate(valid_ctx)
        assert result.outcome == ValidationOutcome.PASS

    @pytest.mark.asyncio
    async def test_fail_missing_patient_name(self, validator, valid_ctx):
        valid_ctx.patient_name = ""
        result = await validator.validate(valid_ctx)
        assert result.outcome == ValidationOutcome.FAIL
        assert "patient_name" in result.reason

    @pytest.mark.asyncio
    async def test_fail_missing_date(self, validator, valid_ctx):
        valid_ctx.date_of_treatment = None
        result = await validator.validate(valid_ctx)
        assert result.outcome == ValidationOutcome.FAIL
        assert "date_of_treatment" in result.reason

    @pytest.mark.asyncio
    async def test_fail_zero_amount(self, validator, valid_ctx):
        valid_ctx.claim_amount = 0
        result = await validator.validate(valid_ctx)
        assert result.outcome == ValidationOutcome.FAIL

    @pytest.mark.asyncio
    async def test_fail_unreadable_bill(self, validator, valid_ctx):
        valid_ctx.raw_ocr_text = ""
        result = await validator.validate(valid_ctx)
        assert result.outcome == ValidationOutcome.FAIL
        assert "bill_text" in result.reason

    @pytest.mark.asyncio
    async def test_fail_short_address(self, validator, valid_ctx):
        valid_ctx.address = "Hi"
        result = await validator.validate(valid_ctx)
        assert result.outcome == ValidationOutcome.FAIL

    @pytest.mark.asyncio
    async def test_reports_all_missing_fields(self, validator):
        ctx = ClaimContext()
        result = await validator.validate(ctx)
        assert result.outcome == ValidationOutcome.FAIL
        assert len(result.details.get("missing_fields", [])) >= 5
