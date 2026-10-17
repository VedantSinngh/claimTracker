"""
tests/unit/test_amount_check_validator.py
──────────────────────────────────────────
"""
import pytest

from app.validators.base import ClaimContext, ValidationOutcome
from app.validators.amount_check import AmountCheckValidator


@pytest.fixture
def validator():
    return AmountCheckValidator()


class TestAmountCheckValidator:
    @pytest.mark.asyncio
    async def test_pass_amount_under_total(self, validator):
        ctx = ClaimContext(claim_amount=5000, extracted_total_amount=10000)
        result = await validator.validate(ctx)
        assert result.outcome == ValidationOutcome.PASS

    @pytest.mark.asyncio
    async def test_pass_amount_equals_total(self, validator):
        ctx = ClaimContext(claim_amount=10000, extracted_total_amount=10000)
        result = await validator.validate(ctx)
        assert result.outcome == ValidationOutcome.PASS

    @pytest.mark.asyncio
    async def test_pass_within_tolerance(self, validator):
        # 5% tolerance: 10000 * 1.05 = 10500
        ctx = ClaimContext(claim_amount=10400, extracted_total_amount=10000)
        result = await validator.validate(ctx)
        assert result.outcome == ValidationOutcome.PASS

    @pytest.mark.asyncio
    async def test_fail_exceeds_total(self, validator):
        ctx = ClaimContext(claim_amount=15000, extracted_total_amount=10000)
        result = await validator.validate(ctx)
        assert result.outcome == ValidationOutcome.FAIL
        assert "exceeds" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_fail_just_over_tolerance(self, validator):
        # 5% tolerance: 10000 * 1.05 = 10500. 10501 should fail.
        ctx = ClaimContext(claim_amount=10501, extracted_total_amount=10000)
        result = await validator.validate(ctx)
        assert result.outcome == ValidationOutcome.FAIL

    @pytest.mark.asyncio
    async def test_needs_review_no_extracted_amount(self, validator):
        ctx = ClaimContext(claim_amount=5000, extracted_total_amount=None)
        result = await validator.validate(ctx)
        assert result.outcome == ValidationOutcome.NEEDS_REVIEW

    @pytest.mark.asyncio
    async def test_needs_review_zero_extracted_amount(self, validator):
        ctx = ClaimContext(claim_amount=5000, extracted_total_amount=0)
        result = await validator.validate(ctx)
        assert result.outcome == ValidationOutcome.NEEDS_REVIEW

    @pytest.mark.asyncio
    async def test_details_include_amounts(self, validator):
        ctx = ClaimContext(claim_amount=15000, extracted_total_amount=10000)
        result = await validator.validate(ctx)
        assert result.details["claim_amount"] == 15000
        assert result.details["extracted_total"] == 10000
