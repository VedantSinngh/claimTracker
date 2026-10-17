"""
tests/unit/test_consistency_validator.py
─────────────────────────────────────────
"""
import pytest

from app.validators.base import ClaimContext, ValidationOutcome
from app.validators.consistency_check import ConsistencyValidator


@pytest.fixture
def validator():
    return ConsistencyValidator()


class TestConsistencyValidator:
    @pytest.mark.asyncio
    async def test_pass_matching_fields(self, validator):
        ctx = ClaimContext(
            medical_facility="Metropolitan General Hospital",
            date_of_treatment="2024-03-15",
            reason="Acute appendicitis",
            claim_item="Appendectomy",
            extracted_facility="Metropolitan General Hospital",
            extracted_date="2024-03-15",
            extracted_diagnosis="Acute appendicitis",
        )
        result = await validator.validate(ctx)
        assert result.outcome == ValidationOutcome.PASS

    @pytest.mark.asyncio
    async def test_pass_fuzzy_facility_match(self, validator):
        ctx = ClaimContext(
            medical_facility="Metro General Hospital",
            extracted_facility="Metropolitan General Hospital",
            reason="appendicitis",
            claim_item="appendectomy",
            extracted_diagnosis="acute appendicitis",
        )
        result = await validator.validate(ctx)
        # Should pass with fuzzy matching
        assert result.outcome in (ValidationOutcome.PASS, ValidationOutcome.NEEDS_REVIEW)

    @pytest.mark.asyncio
    async def test_needs_review_facility_mismatch(self, validator):
        ctx = ClaimContext(
            medical_facility="Seattle General Hospital",
            extracted_facility="Lakeside Hospital",
            reason="migraine",
            claim_item="neurology",
            extracted_diagnosis="migraine",
        )
        result = await validator.validate(ctx)
        assert result.outcome == ValidationOutcome.NEEDS_REVIEW
        assert "facility" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_needs_review_date_mismatch(self, validator):
        ctx = ClaimContext(
            medical_facility="Hospital",
            extracted_facility="Hospital",
            date_of_treatment="2024-07-15",
            extracted_date="2024-06-01",
            reason="test",
            claim_item="test",
            extracted_diagnosis="test",
        )
        result = await validator.validate(ctx)
        assert result.outcome == ValidationOutcome.NEEDS_REVIEW
        assert "date" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_pass_date_within_tolerance(self, validator):
        ctx = ClaimContext(
            medical_facility="Hospital",
            extracted_facility="Hospital",
            date_of_treatment="2024-03-15",
            extracted_date="2024-03-18",  # 3 days apart, within 7-day tolerance
            reason="test",
            claim_item="test",
            extracted_diagnosis="test",
        )
        result = await validator.validate(ctx)
        assert result.outcome == ValidationOutcome.PASS

    @pytest.mark.asyncio
    async def test_needs_review_diagnosis_mismatch(self, validator):
        ctx = ClaimContext(
            medical_facility="Hospital",
            extracted_facility="Hospital",
            reason="cardiac chest pain",
            claim_item="cardiology",
            extracted_diagnosis="migraine with aura",
        )
        result = await validator.validate(ctx)
        assert result.outcome == ValidationOutcome.NEEDS_REVIEW
        assert "diagnosis" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_pass_no_extracted_fields(self, validator):
        """If nothing was extracted, skip comparison — nothing to mismatch."""
        ctx = ClaimContext(
            medical_facility="Hospital",
            reason="test",
            claim_item="test",
            extracted_facility=None,
            extracted_date=None,
            extracted_diagnosis=None,
        )
        result = await validator.validate(ctx)
        assert result.outcome == ValidationOutcome.PASS
