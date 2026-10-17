"""
app/services/pii_masker.py
───────────────────────────
PII masking utilities.

Masks personally identifiable information BEFORE sending text to the LLM.
Only unmasked for display in the frontend (the DB stores masked versions in audit logs).

Patterns masked:
- Full names      → [NAME_REDACTED]
- Phone numbers   → [PHONE_REDACTED]
- Email addresses → [EMAIL_REDACTED]
- SSN / ID nums   → [ID_REDACTED]
- Street addresses (partial) → [ADDRESS_REDACTED]
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple


# ── Compiled regex patterns ────────────────────────────────────────────────────

_PHONE_RE = re.compile(
    r"\b(?:\+?1[-.\s]?)?"
    r"(?:\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})"
    r"\b"
)

_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
)

_SSN_RE = re.compile(
    r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b"
)

_ID_RE = re.compile(
    r"\b(?:ID|id|Id|MRN|mrn|Mrn|Policy\s*#?|Member\s*#?)[\s:]*([A-Z0-9]{4,20})\b"
)

# Simple address pattern: number + street name + type
_ADDRESS_RE = re.compile(
    r"\b\d{1,6}\s+[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*"
    r"\s+(?:St|Street|Ave|Avenue|Blvd|Boulevard|Dr|Drive|Rd|Road|Ln|Lane|Way|Ct|Court|Pl|Place)"
    r"(?:\s*,?\s*(?:Suite|Apt|Unit)\s*#?\s*\d+)?"
    r"\b",
    re.IGNORECASE,
)


class PIIMasker:
    """
    Stateful masker: tracks original → masked mappings so we can
    unmask for display if needed.
    """

    def __init__(self) -> None:
        self._mappings: Dict[str, str] = {}

    def mask(self, text: str, patient_name: str = "") -> str:
        """
        Apply all PII masks to `text`.
        If `patient_name` is provided, it is also masked.
        Returns the masked text.
        """
        result = text

        # ── Mask the known patient name first ──────────────────────
        if patient_name and len(patient_name) >= 2:
            for name_part in _name_variants(patient_name):
                if name_part in result:
                    self._mappings[name_part] = "[NAME_REDACTED]"
                    result = result.replace(name_part, "[NAME_REDACTED]")

        # ── Regex-based masking ────────────────────────────────────
        result = self._apply_pattern(result, _EMAIL_RE, "[EMAIL_REDACTED]")
        result = self._apply_pattern(result, _SSN_RE, "[ID_REDACTED]")
        result = self._apply_pattern(result, _PHONE_RE, "[PHONE_REDACTED]")
        result = self._apply_pattern(result, _ID_RE, "[ID_REDACTED]")
        result = self._apply_pattern(result, _ADDRESS_RE, "[ADDRESS_REDACTED]")

        return result

    def unmask(self, text: str) -> str:
        """Reverse mask for display purposes only."""
        result = text
        for original, masked in self._mappings.items():
            result = result.replace(masked, original, 1)
        return result

    @property
    def mappings(self) -> Dict[str, str]:
        return dict(self._mappings)

    def _apply_pattern(self, text: str, pattern: re.Pattern, replacement: str) -> str:
        for match in pattern.finditer(text):
            original = match.group(0)
            if original not in self._mappings:
                self._mappings[original] = replacement
        return pattern.sub(replacement, text)


def _name_variants(full_name: str) -> List[str]:
    """
    Generate variants to match: full name, first+last, individual parts.
    Sorted by length descending so longest matches are replaced first.
    """
    parts = full_name.strip().split()
    variants = {full_name.strip()}
    if len(parts) >= 2:
        variants.add(f"{parts[0]} {parts[-1]}")
    for part in parts:
        if len(part) >= 3:
            variants.add(part)
    return sorted(variants, key=len, reverse=True)
