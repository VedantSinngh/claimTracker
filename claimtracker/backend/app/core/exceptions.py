"""
app/core/exceptions.py
──────────────────────
Custom exception hierarchy for ClaimTracker.
Handlers are registered in main.py so every layer can raise without
knowing about HTTP status codes.
"""
from typing import Any, Dict, Optional


class ClaimTrackerError(Exception):
    """Base exception for all application errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


# ─── Auth ──────────────────────────────────────────────────────────────────────

class AuthenticationError(ClaimTrackerError):
    """Invalid credentials or missing token."""


class AuthorizationError(ClaimTrackerError):
    """Valid token but insufficient role."""


# ─── Resource ──────────────────────────────────────────────────────────────────

class NotFoundError(ClaimTrackerError):
    """Requested resource does not exist."""


class ConflictError(ClaimTrackerError):
    """Unique constraint violation (e.g. email already registered)."""


# ─── Validation ────────────────────────────────────────────────────────────────

class ValidationError(ClaimTrackerError):
    """Business-rule validation failed (not the same as Pydantic validation)."""


class FileTooLargeError(ClaimTrackerError):
    """Uploaded file exceeds MAX_UPLOAD_SIZE_MB."""


class UnsupportedFileTypeError(ClaimTrackerError):
    """File MIME type is not in the accepted list."""


# ─── OCR / Extraction ──────────────────────────────────────────────────────────

class OCRError(ClaimTrackerError):
    """Could not extract text from the uploaded document."""


class ExtractionError(ClaimTrackerError):
    """LLM returned invalid JSON or failed schema validation after retry."""


# ─── RAG / LLM ─────────────────────────────────────────────────────────────────

class LLMError(ClaimTrackerError):
    """Upstream LLM API call failed."""


class RAGIndexNotFound(ClaimTrackerError):
    """No active handbook has been ingested yet."""


# ─── Pipeline ──────────────────────────────────────────────────────────────────

class PipelineError(ClaimTrackerError):
    """Generic pipeline orchestration error."""
