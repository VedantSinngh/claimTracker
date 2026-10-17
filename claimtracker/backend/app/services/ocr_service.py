"""
app/services/ocr_service.py
─────────────────────────────
OCR service: extract text from uploaded bills (PDF, JPG, PNG).

Strategy:
1. For PDFs: try pdfplumber first (digital PDF — fast, accurate).
   If text is too short (< 50 chars), fall back to pytesseract via pdf2image.
2. For images (JPG/PNG): use pytesseract directly.

This service is stateless and does not touch the database.
"""
from __future__ import annotations

from pathlib import Path

import pdfplumber
import pytesseract
from pdf2image import convert_from_path
from PIL import Image

from app.core.config import get_settings
from app.core.exceptions import OCRError
from app.core.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()

# Minimum characters to consider a digital extraction "successful"
_MIN_DIGITAL_TEXT_LEN = 50

# Tesseract config: page segmentation mode 3 (auto), English
_TESS_CONFIG = "--psm 3 -l eng"


class OCRService:
    """
    Extracts raw text from bill documents.
    Handles PDF (digital and scanned) and image files (JPG/PNG).
    """

    def __init__(self) -> None:
        pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD

    def extract_text(self, file_path: str, mime_type: str) -> str:
        """
        Main entry point. Returns the full extracted text from the document.
        Raises OCRError if extraction fails completely.
        """
        path = Path(file_path)
        if not path.exists():
            raise OCRError(f"File not found: {file_path}")

        try:
            if mime_type == "application/pdf":
                return self._extract_from_pdf(path)
            elif mime_type in ("image/jpeg", "image/png"):
                return self._extract_from_image(path)
            else:
                raise OCRError(f"Unsupported MIME type for OCR: {mime_type}")
        except OCRError:
            raise
        except Exception as exc:
            logger.error("ocr_failed", path=file_path, error=str(exc))
            raise OCRError(f"OCR extraction failed: {exc}") from exc

    def _extract_from_pdf(self, path: Path) -> str:
        """
        Try pdfplumber (digital text) first.
        Falls back to pdf2image + pytesseract for scanned PDFs.
        """
        # ── Fast path: digital PDF ──────────────────────────────
        text = self._pdfplumber_extract(path)
        if len(text) >= _MIN_DIGITAL_TEXT_LEN:
            logger.info("ocr_digital_pdf", path=str(path), chars=len(text))
            return text

        # ── Fallback: scanned PDF via OCR ───────────────────────
        logger.info("ocr_scanned_pdf_fallback", path=str(path))
        return self._tesseract_pdf_extract(path)

    def _pdfplumber_extract(self, path: Path) -> str:
        """Extract text from a digital (text-based) PDF."""
        pages = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    pages.append(page_text.strip())
        return "\n\n".join(pages)

    def _tesseract_pdf_extract(self, path: Path) -> str:
        """
        Convert PDF pages to images, then OCR each page with pytesseract.
        Uses pdf2image (poppler) for conversion.
        """
        images = convert_from_path(str(path), dpi=300)
        pages = []
        for i, img in enumerate(images):
            page_text = pytesseract.image_to_string(img, config=_TESS_CONFIG)
            if page_text and page_text.strip():
                pages.append(page_text.strip())
            logger.debug("ocr_page_processed", page=i + 1, chars=len(page_text or ""))
        full_text = "\n\n".join(pages)
        if not full_text.strip():
            raise OCRError("OCR could not extract any text from the scanned PDF.")
        logger.info("ocr_scanned_pdf_done", path=str(path), chars=len(full_text))
        return full_text

    def _extract_from_image(self, path: Path) -> str:
        """OCR a single image (JPG/PNG) with pytesseract."""
        img = Image.open(str(path))
        text = pytesseract.image_to_string(img, config=_TESS_CONFIG)
        if not text or not text.strip():
            raise OCRError("OCR could not extract any text from the image.")
        logger.info("ocr_image_done", path=str(path), chars=len(text))
        return text.strip()
