"""
tests/unit/test_ocr_service.py
───────────────────────────────
`OCRService`: the digital-PDF fast path, the scanned-PDF fallback, image
handling, and the error paths.

pdfplumber runs for real against PDFs generated in-process by reportlab.
pytesseract is stubbed for the fallback tests — tesseract is a system binary
that may not be installed on a dev machine, and asserting on OCR'd pixels
would be testing tesseract rather than our routing logic. The one test that
needs the real binary skips itself when it is absent.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.core.exceptions import OCRError
from app.services import ocr_service as ocr_module
from app.services.ocr_service import OCRService

reportlab = pytest.importorskip(
    "reportlab", reason="reportlab is needed to build test PDFs (requirements-dev.txt)"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_pdf(path: Path, lines: list[str]) -> Path:
    """Write a digital (text-bearing) PDF."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    _, height = A4
    y = height - 50
    c.setFont("Helvetica", 11)
    for line in lines:
        c.drawString(50, y, line)
        y -= 16
    c.showPage()
    c.save()
    return path


def _make_blank_pdf(path: Path, pages: int = 1) -> Path:
    """A PDF with no extractable text — stands in for a scan."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    for _ in range(pages):
        c.showPage()
    c.save()
    return path


BILL_LINES = [
    "METROPOLITAN GENERAL HOSPITAL",
    "Patient Name:    John Smith",
    "Date of Service: 2024-03-15",
    "Diagnosis:       Acute appendicitis",
    "Appendectomy (Laparoscopic)      $5,500.00",
    "TOTAL BILLED TO INSURANCE        $9,860.00",
]


# ── Digital PDF fast path ─────────────────────────────────────────────────────

def test_reads_a_digital_pdf_without_tesseract(tmp_path: Path, monkeypatch):
    """
    The fast path must not touch tesseract at all — that is the point of
    trying pdfplumber first.
    """
    def _boom(*args, **kwargs):
        raise AssertionError("tesseract must not be called for a digital PDF")

    monkeypatch.setattr(ocr_module.pytesseract, "image_to_string", _boom)
    monkeypatch.setattr(ocr_module, "convert_from_path", _boom)

    pdf = _make_pdf(tmp_path / "bill.pdf", BILL_LINES)
    text = OCRService().extract_text(str(pdf), "application/pdf")

    assert "METROPOLITAN GENERAL HOSPITAL" in text
    assert "Acute appendicitis" in text
    assert "$9,860.00" in text


def test_multi_page_pdf_pages_are_joined(tmp_path: Path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    pdf = tmp_path / "multi.pdf"
    c = canvas.Canvas(str(pdf), pagesize=A4)
    _, height = A4
    for page_no in (1, 2, 3):
        c.setFont("Helvetica", 11)
        c.drawString(50, height - 50, f"This is page {page_no} of the itemised bill.")
        c.showPage()
    c.save()

    text = OCRService().extract_text(str(pdf), "application/pdf")

    for page_no in (1, 2, 3):
        assert f"page {page_no}" in text
    assert "\n\n" in text, "pages are separated by a blank line"


# ── Scanned PDF fallback ──────────────────────────────────────────────────────

def test_falls_back_to_tesseract_when_there_is_no_digital_text(
    tmp_path: Path, monkeypatch
):
    calls = {"convert": 0, "ocr": 0}

    def _fake_convert(path, dpi=300):
        calls["convert"] += 1
        return ["page-image-1", "page-image-2"]

    def _fake_ocr(image, config=""):
        calls["ocr"] += 1
        return f"OCR text from {image}"

    monkeypatch.setattr(ocr_module, "convert_from_path", _fake_convert)
    monkeypatch.setattr(ocr_module.pytesseract, "image_to_string", _fake_ocr)

    pdf = _make_blank_pdf(tmp_path / "scan.pdf", pages=2)
    text = OCRService().extract_text(str(pdf), "application/pdf")

    assert calls["convert"] == 1
    assert calls["ocr"] == 2, "one OCR pass per page image"
    assert "OCR text from page-image-1" in text
    assert "OCR text from page-image-2" in text


def test_short_digital_text_still_triggers_the_fallback(tmp_path: Path, monkeypatch):
    """
    A PDF with a few stray characters (a scan with a header stamp, say) is
    below _MIN_DIGITAL_TEXT_LEN and must not be trusted as a digital read.
    """
    monkeypatch.setattr(ocr_module, "convert_from_path", lambda p, dpi=300: ["img"])
    monkeypatch.setattr(
        ocr_module.pytesseract, "image_to_string", lambda i, config="": "FULL OCR TEXT"
    )

    pdf = _make_pdf(tmp_path / "stamp.pdf", ["x"])  # well under 50 chars
    text = OCRService().extract_text(str(pdf), "application/pdf")

    assert text == "FULL OCR TEXT"


def test_fallback_producing_nothing_raises(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ocr_module, "convert_from_path", lambda p, dpi=300: ["img"])
    monkeypatch.setattr(
        ocr_module.pytesseract, "image_to_string", lambda i, config="": "   "
    )

    pdf = _make_blank_pdf(tmp_path / "empty-scan.pdf")
    with pytest.raises(OCRError, match="could not extract any text from the scanned PDF"):
        OCRService().extract_text(str(pdf), "application/pdf")


# ── Images ────────────────────────────────────────────────────────────────────

def test_image_is_ocrd(tmp_path: Path, monkeypatch):
    from PIL import Image

    monkeypatch.setattr(
        ocr_module.pytesseract,
        "image_to_string",
        lambda img, config="": "  Diagnosis: Migraine  ",
    )

    img_path = tmp_path / "bill.png"
    Image.new("RGB", (40, 40), "white").save(img_path)

    text = OCRService().extract_text(str(img_path), "image/png")
    assert text == "Diagnosis: Migraine", "result is stripped"


def test_blank_image_raises(tmp_path: Path, monkeypatch):
    from PIL import Image

    monkeypatch.setattr(
        ocr_module.pytesseract, "image_to_string", lambda img, config="": ""
    )

    img_path = tmp_path / "blank.jpg"
    Image.new("RGB", (40, 40), "white").save(img_path)

    with pytest.raises(OCRError, match="could not extract any text from the image"):
        OCRService().extract_text(str(img_path), "image/jpeg")


@pytest.mark.skipif(
    shutil.which("tesseract") is None,
    reason="tesseract binary not installed on this machine",
)
def test_real_tesseract_reads_rendered_text(tmp_path: Path):
    """
    The one test that exercises the actual binary, so a broken
    TESSERACT_CMD/poppler setup is caught rather than mocked over.
    """
    from PIL import Image, ImageDraw

    img_path = tmp_path / "typed.png"
    img = Image.new("RGB", (600, 120), "white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 40), "TOTAL BILLED 9860", fill="black")
    img.save(img_path)

    text = OCRService().extract_text(str(img_path), "image/png")
    assert "9860" in text.replace(",", "").replace(" ", "")


# ── Error paths ───────────────────────────────────────────────────────────────

def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(OCRError, match="File not found"):
        OCRService().extract_text(str(tmp_path / "nope.pdf"), "application/pdf")


@pytest.mark.parametrize(
    "mime", ["text/plain", "application/msword", "image/gif", "image/webp", ""]
)
def test_unsupported_mime_raises(tmp_path: Path, mime: str):
    pdf = _make_pdf(tmp_path / "bill.pdf", BILL_LINES)
    with pytest.raises(OCRError, match="Unsupported MIME type"):
        OCRService().extract_text(str(pdf), mime)


def test_corrupt_pdf_is_wrapped_in_ocr_error(tmp_path: Path):
    """Third-party exceptions must surface as our own error type."""
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"%PDF-1.4\nthis is not a real pdf body\n%%EOF")

    with pytest.raises(OCRError, match="OCR extraction failed"):
        OCRService().extract_text(str(corrupt), "application/pdf")


def test_tesseract_cmd_is_configured_from_settings(monkeypatch):
    """The Windows/Linux binary path difference is settings-driven."""
    monkeypatch.setattr(
        ocr_module.settings, "TESSERACT_CMD", "/custom/path/to/tesseract"
    )
    OCRService()
    assert ocr_module.pytesseract.pytesseract.tesseract_cmd == "/custom/path/to/tesseract"
