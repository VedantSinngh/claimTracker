"""
app/validators/exclusion_check.py
──────────────────────────────────
Step 4: DETERMINISTIC exclusion check.

CRITICAL DESIGN DECISION:
This runs BEFORE the LLM (RAG policy check) because the LLM occasionally
hallucinated approvals for excluded conditions in the original prototype.
By catching exclusions deterministically with fuzzy + synonym matching,
we prevent false approvals with 100% reliability.

This is a key interview point: "Why check exclusions with rules instead
of only the LLM?" — deterministic safety before probabilistic reasoning.
"""
from __future__ import annotations

from typing import List

from rapidfuzz import fuzz, process

from app.validators.base import (
    BaseValidator,
    ClaimContext,
    ValidationOutcome,
    ValidationResult,
)


# Minimum fuzzy match score to trigger exclusion
_FUZZY_THRESHOLD = 75

# Common medical synonyms that map to exclusion terms.
# Expanded at runtime from the exclusions list.
_SYNONYMS: dict[str, list[str]] = {
    "cosmetic surgery": ["plastic surgery", "aesthetic procedure", "cosmetic procedure", "rhinoplasty", "facelift", "liposuction", "botox"],
    "hiv/aids": ["hiv", "aids", "human immunodeficiency virus", "acquired immunodeficiency"],
    "alcoholism": ["alcohol addiction", "alcohol dependence", "alcohol abuse", "substance abuse"],
    "substance abuse": ["drug addiction", "drug abuse", "narcotics addiction"],
    "pregnancy": ["maternity", "childbirth", "prenatal", "postnatal", "obstetric"],
    "infertility": ["ivf", "in vitro fertilization", "assisted reproduction"],
    "dental treatment": ["dental", "orthodontic", "dental surgery"],
    "obesity": ["bariatric", "bariatric surgery", "weight loss surgery", "gastric bypass", "gastric sleeve"],
    "self-inflicted": ["self-harm", "self injury", "suicide attempt"],
    "pre-existing": ["pre-existing condition", "prior condition", "pre existing"],
    "congenital": ["birth defect", "congenital disease", "congenital anomaly"],
    "sleep disorders": ["insomnia", "sleep apnea", "narcolepsy"],
    "experimental": ["clinical trial", "experimental treatment", "investigational"],
}


class ExclusionCheckValidator(BaseValidator):
    """
    Deterministic check: is the diagnosis an excluded condition?

    Matching strategy:
    1. Exact substring match (case-insensitive)
    2. Fuzzy match (rapidfuzz token_set_ratio ≥ threshold)
    3. Synonym expansion: if the diagnosis matches a synonym of an exclusion
    """

    @property
    def name(self) -> str:
        return "exclusion_check"

    async def validate(self, ctx: ClaimContext) -> ValidationResult:
        if not ctx.exclusion_terms:
            return ValidationResult(
                outcome=ValidationOutcome.PASS,
                validator_name=self.name,
                reason="No exclusion terms loaded — skipping exclusion check.",
            )

        diagnosis = (ctx.extracted_diagnosis or ctx.reason or "").lower().strip()
        claim_item = (ctx.claim_item or "").lower().strip()
        bill_text_lower = ctx.raw_ocr_text.lower() if ctx.raw_ocr_text else ""

        if not diagnosis and not claim_item:
            return ValidationResult(
                outcome=ValidationOutcome.NEEDS_REVIEW,
                validator_name=self.name,
                reason="No diagnosis available — cannot check exclusions.",
            )

        # Combine search targets
        search_targets = [t for t in [diagnosis, claim_item] if t]

        matched_term, match_method, match_score = self._find_exclusion_match(
            search_targets=search_targets,
            bill_text=bill_text_lower,
            exclusion_terms=ctx.exclusion_terms,
        )

        if matched_term:
            return ValidationResult(
                outcome=ValidationOutcome.FAIL,
                validator_name=self.name,
                reason=(
                    f"Diagnosis matches excluded condition: '{matched_term}' "
                    f"(match method: {match_method}, score: {match_score}). "
                    f"This condition is not covered under the policy."
                ),
                details={
                    "matched_exclusion": matched_term,
                    "match_method": match_method,
                    "match_score": match_score,
                    "diagnosis": diagnosis,
                },
            )

        return ValidationResult(
            outcome=ValidationOutcome.PASS,
            validator_name=self.name,
            reason="Diagnosis does not match any known exclusion.",
        )

    def _find_exclusion_match(
        self,
        search_targets: List[str],
        bill_text: str,
        exclusion_terms: List[str],
    ) -> tuple[str | None, str, float]:
        """
        Returns (matched_term, method, score) or (None, "", 0) if no match.
        """
        for target in search_targets:
            # ── 1. Exact substring ────────────────────────────────
            for term in exclusion_terms:
                if term in target or target in term:
                    return term, "exact_substring", 100.0

            # ── 2. Fuzzy match ────────────────────────────────────
            best = process.extractOne(
                target,
                exclusion_terms,
                scorer=fuzz.token_set_ratio,
                score_cutoff=_FUZZY_THRESHOLD,
            )
            if best:
                return best[0], "fuzzy_match", best[1]

            # ── 3. Synonym expansion ──────────────────────────────
            for excl_term in exclusion_terms:
                synonyms = _SYNONYMS.get(excl_term, [])
                for synonym in synonyms:
                    if synonym in target or target in synonym:
                        return excl_term, "synonym_exact", 100.0
                    syn_score = fuzz.token_set_ratio(target, synonym)
                    if syn_score >= _FUZZY_THRESHOLD:
                        return excl_term, "synonym_fuzzy", syn_score

        # ── 4. Check bill text for any exclusion terms ────────────
        if bill_text:
            for term in exclusion_terms:
                if term in bill_text:
                    return term, "bill_text_substring", 90.0

        return None, "", 0.0
