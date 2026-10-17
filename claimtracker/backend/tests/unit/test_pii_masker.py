"""
tests/unit/test_pii_masker.py
──────────────────────────────
"""
from app.services.pii_masker import PIIMasker


class TestPIIMasker:
    def test_masks_patient_name(self):
        masker = PIIMasker()
        text = "Patient John Smith was admitted on March 15."
        result = masker.mask(text, patient_name="John Smith")
        assert "John Smith" not in result
        assert "[NAME_REDACTED]" in result

    def test_masks_phone_number(self):
        masker = PIIMasker()
        text = "Contact: (212) 555-0100 for inquiries."
        result = masker.mask(text)
        assert "(212) 555-0100" not in result
        assert "[PHONE_REDACTED]" in result

    def test_masks_email(self):
        masker = PIIMasker()
        text = "Send documents to claims@medicover.com"
        result = masker.mask(text)
        assert "claims@medicover.com" not in result
        assert "[EMAIL_REDACTED]" in result

    def test_masks_ssn(self):
        masker = PIIMasker()
        text = "SSN: 123-45-6789"
        result = masker.mask(text)
        assert "123-45-6789" not in result
        assert "[ID_REDACTED]" in result

    def test_masks_address(self):
        masker = PIIMasker()
        text = "Facility at 123 Medical Center Drive"
        result = masker.mask(text)
        assert "[ADDRESS_REDACTED]" in result

    def test_unmask_restores_name(self):
        masker = PIIMasker()
        original = "Patient John Smith was admitted."
        masked = masker.mask(original, patient_name="John Smith")
        unmasked = masker.unmask(masked)
        assert "John Smith" in unmasked

    def test_multiple_pii_types(self):
        masker = PIIMasker()
        text = (
            "Patient Jane Doe, SSN 987-65-4321, "
            "phone (555) 123-4567, email jane@example.com"
        )
        result = masker.mask(text, patient_name="Jane Doe")
        assert "Jane" not in result
        assert "987-65-4321" not in result
        assert "(555) 123-4567" not in result
        assert "jane@example.com" not in result

    def test_preserves_non_pii_text(self):
        masker = PIIMasker()
        text = "Diagnosis: acute appendicitis. Total: $9,860.00"
        result = masker.mask(text)
        assert "appendicitis" in result
        assert "$9,860.00" in result

    def test_empty_name_safe(self):
        masker = PIIMasker()
        text = "No name here"
        result = masker.mask(text, patient_name="")
        assert result == text

    def test_mappings_tracked(self):
        masker = PIIMasker()
        masker.mask("Call (555) 999-0000", patient_name="Test User")
        assert len(masker.mappings) >= 1
