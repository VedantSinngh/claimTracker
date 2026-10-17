"""
tests/unit/test_exclusion_check_validator.py
──────────────────────────────────────────────
Tests for the deterministic exclusion checker.
This is one of the most critical components — it prevents
the LLM from hallucinating approvals for excluded conditions.
"""
import pytest

from app.validators.base import ClaimContext, ValidationOutcome
from app.validators.exclusion_check import ExclusionCheckValidator


SAMPLE_EXCLUSIONS = [
    "cosmetic surgery",
    "hiv/aids",
    "alcoholism",
    "pregnancy",
    "dental treatment",
    "obesity",
    "self-inflicted injuries",
    "pre-existing conditions",
    "infertility",
    "congenital diseases",
    "sleep disorders",
]


@pytest.fixture
def validator():
    return ExclusionCheckValidator()


class TestExclusionCheckValidator:
    @pytest.mark.asyncio
    async def test_pass_non_excluded_condition(self, validator):
        ctx = ClaimContext(
            extracted_diagnosis="acute appendicitis",
            reason="Acute appendicitis",
            claim_item="Appendectomy",
            exclusion_terms=SAMPLE_EXCLUSIONS,
            raw_ocr_text="Patient treated for acute appendicitis.",
        )
        result = await validator.validate(ctx)
        assert result.outcome == ValidationOutcome.PASS

    @pytest.mark.asyncio
    async def test_fail_exact_match(self, validator):
        ctx = ClaimContext(
            extracted_diagnosis="cosmetic surgery",
            reason="Rhinoplasty",
            claim_item="Cosmetic Surgery",
            exclusion_terms=SAMPLE_EXCLUSIONS,
        )
        result = await validator.validate(ctx)
        assert result.outcome == ValidationOutcome.FAIL
        assert "cosmetic surgery" in result.details["matched_exclusion"]

    @pytest.mark.asyncio
    async def test_fail_fuzzy_match(self, validator):
        ctx = ClaimContext(
            extracted_diagnosis="cosmetic surgical procedure",
            reason="Cosmetic procedure",
            claim_item="Aesthetic surgery",
            exclusion_terms=SAMPLE_EXCLUSIONS,
        )
        result = await validator.validate(ctx)
        assert result.outcome == ValidationOutcome.FAIL

    @pytest.mark.asyncio
    async def test_fail_synonym_match_bariatric(self, validator):
        """'bariatric surgery' is a synonym for 'obesity' exclusion."""
        ctx = ClaimContext(
            extracted_diagnosis="bariatric surgery",
            reason="Weight loss surgery",
            claim_item="Gastric bypass",
            exclusion_terms=SAMPLE_EXCLUSIONS,
        )
        result = await validator.validate(ctx)
        assert result.outcome == ValidationOutcome.FAIL
        assert "obesity" in result.details.get("matched_exclusion", "")

    @pytest.mark.asyncio
    async def test_fail_synonym_match_ivf(self, validator):
        """'IVF' is a synonym for 'infertility' exclusion."""
        ctx = ClaimContext(
            extracted_diagnosis="in vitro fertilization",
            reason="IVF treatment",
            claim_item="Fertility treatment",
            exclusion_terms=SAMPLE_EXCLUSIONS,
        )
        result = await validator.validate(ctx)
        assert result.outcome == ValidationOutcome.FAIL

    @pytest.mark.asyncio
    async def test_fail_hiv_detection(self, validator):
        ctx = ClaimContext(
            extracted_diagnosis="HIV treatment",
            reason="Antiretroviral therapy",
            claim_item="HIV medication",
            exclusion_terms=SAMPLE_EXCLUSIONS,
        )
        result = await validator.validate(ctx)
        assert result.outcome == ValidationOutcome.FAIL

    @pytest.mark.asyncio
    async def test_pass_empty_exclusion_list(self, validator):
        ctx = ClaimContext(
            extracted_diagnosis="anything",
            reason="anything",
            claim_item="anything",
            exclusion_terms=[],
        )
        result = await validator.validate(ctx)
        assert result.outcome == ValidationOutcome.PASS

    @pytest.mark.asyncio
    async def test_needs_review_no_diagnosis(self, validator):
        ctx = ClaimContext(
            extracted_diagnosis=None,
            reason="",
            claim_item="",
            exclusion_terms=SAMPLE_EXCLUSIONS,
        )
        result = await validator.validate(ctx)
        assert result.outcome == ValidationOutcome.NEEDS_REVIEW

    @pytest.mark.asyncio
    async def test_fail_bill_text_contains_exclusion(self, validator):
        ctx = ClaimContext(
            extracted_diagnosis="elective procedure",
            reason="Surgery",
            claim_item="Surgery",
            exclusion_terms=SAMPLE_EXCLUSIONS,
            raw_ocr_text="Diagnosis: Obesity (E66.01) - Bariatric Surgery recommended",
        )
        result = await validator.validate(ctx)
        assert result.outcome == ValidationOutcome.FAIL

    @pytest.mark.asyncio
    async def test_fail_dental_treatment(self, validator):
        ctx = ClaimContext(
            extracted_diagnosis="dental surgery",
            reason="Tooth extraction",
            claim_item="Dental treatment",
            exclusion_terms=SAMPLE_EXCLUSIONS,
        )
        result = await validator.validate(ctx)
        assert result.outcome == ValidationOutcome.FAIL

    @pytest.mark.asyncio
    async def test_details_include_match_info(self, validator):
        ctx = ClaimContext(
            extracted_diagnosis="pregnancy",
            reason="Maternity care",
            claim_item="Prenatal visits",
            exclusion_terms=SAMPLE_EXCLUSIONS,
        )
        result = await validator.validate(ctx)
        assert result.outcome == ValidationOutcome.FAIL
        assert "matched_exclusion" in result.details
        assert "match_method" in result.details
        assert "match_score" in result.details
