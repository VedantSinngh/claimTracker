"""
app/services/handbook_service.py
──────────────────────────────────
Full handbook ingestion pipeline:

  1. Save PDF to disk
  2. Extract full text with pdfplumber (digital PDF) — fast path
  3. Slide a (1000 char, 200 overlap) window to produce chunks
  4. Embed each chunk with SentenceTransformer (all-MiniLM-L6-v2)
  5. Build FAISS IndexFlatIP on L2-normalised vectors (cosine similarity)
  6. Persist index + chunk metadata (JSON) under faiss_index/<version_id>/
  7. Parse the "General Exclusions" section → seed into the exclusions table
  8. Create/activate HandbookVersion record in the DB

The FAISS index is loaded once at startup and cached as a module-level singleton
(see RAGService). Re-ingesting a new handbook invalidates the cache.
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import List, Tuple
from uuid import UUID

import faiss
import numpy as np
import pdfplumber
from fastapi import UploadFile
from sentence_transformers import SentenceTransformer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.models.exclusion import Exclusion
from app.models.handbook import HandbookVersion
from app.repositories.exclusion_repo import ExclusionRepository
from app.repositories.handbook_repo import HandbookRepository
from app.schemas.handbook import HandbookListResponse

logger = get_logger(__name__)
settings = get_settings()

# ── Constants ──────────────────────────────────────────────────────────────────
CHUNK_SIZE = 1000       # characters
CHUNK_OVERLAP = 200     # characters
MIN_CHUNK_LENGTH = 50   # discard very short chunks (headers, page numbers)


def _get_embedding_model() -> SentenceTransformer:
    """
    Load the SentenceTransformer model.
    In production this would be cached as a module singleton.
    Deferred here so tests that don't need it won't download the model.
    """
    return SentenceTransformer(settings.EMBEDDING_MODEL)


# ── Text extraction ────────────────────────────────────────────────────────────

def extract_text_from_pdf(file_path: Path) -> str:
    """
    Extract full text from a digital PDF using pdfplumber.
    Falls back to empty string (not an error — OCR picks it up in Phase 3).
    """
    pages: List[str] = []
    try:
        with pdfplumber.open(str(file_path)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text.strip())
    except Exception as exc:
        logger.warning("pdfplumber_extraction_failed", path=str(file_path), error=str(exc))
    return "\n\n".join(pages)


# ── Chunking ──────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """
    Sliding-window character-level chunker.
    Tries to break at sentence boundaries ('. ') to avoid mid-sentence splits.
    Falls back to hard character cut if no boundary is found.
    """
    if not text:
        return []

    chunks: List[str] = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + chunk_size, text_len)

        if end < text_len:
            # Try to snap the end to a sentence boundary within the last 20% of the chunk
            snap_region = text[max(start, end - chunk_size // 5): end]
            last_period = snap_region.rfind(". ")
            if last_period != -1:
                snap_offset = max(start, end - chunk_size // 5)
                end = snap_offset + last_period + 2  # include the period and space

        chunk = text[start:end].strip()
        if len(chunk) >= MIN_CHUNK_LENGTH:
            chunks.append(chunk)

        # Advance by (chunk_size - overlap), but at least 1 char to avoid infinite loop
        advance = max(chunk_size - overlap, 1)
        start += advance

    return chunks


# ── FAISS index builder ───────────────────────────────────────────────────────

def build_faiss_index(
    chunks: List[str],
    model: SentenceTransformer,
) -> Tuple[faiss.Index, np.ndarray]:
    """
    Embed all chunks and return (faiss_index, embeddings_matrix).
    Uses IndexFlatIP on L2-normalised vectors → cosine similarity search.
    """
    logger.info("embedding_chunks", count=len(chunks))
    # batch_size=64 keeps memory usage reasonable for large handbooks
    embeddings: np.ndarray = model.encode(
        chunks,
        batch_size=64,
        show_progress_bar=False,
        normalize_embeddings=True,  # L2 normalise → dot product = cosine similarity
        convert_to_numpy=True,
    ).astype("float32")

    dimension = embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)  # Inner Product on unit vectors = cosine
    index.add(embeddings)
    logger.info("faiss_index_built", vectors=index.ntotal, dimension=dimension)
    return index, embeddings


def save_faiss_artefacts(
    index: faiss.Index,
    chunks: List[str],
    version_dir: Path,
) -> Tuple[Path, Path]:
    """
    Persist the FAISS binary index and chunk metadata (JSON) to disk.
    Returns (index_path, chunks_path).
    """
    version_dir.mkdir(parents=True, exist_ok=True)
    index_path = version_dir / "index.faiss"
    chunks_path = version_dir / "chunks.json"

    faiss.write_index(index, str(index_path))
    chunks_path.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("faiss_artefacts_saved", index=str(index_path), chunks=str(chunks_path))
    return index_path, chunks_path


# ── General Exclusions parser ─────────────────────────────────────────────────

_EXCLUSION_HEADER_RE = re.compile(
    r"general\s+exclusions?",
    re.IGNORECASE,
)
_BULLET_RE = re.compile(
    r"^\s*(?:\d+[\.\)]\s*|[a-z][\.\)]\s*|[-•*]\s+)(.+)",
    re.MULTILINE,
)


def parse_general_exclusions(text: str) -> List[str]:
    """
    Find the 'General Exclusions' section and extract individual terms.
    Returns a list of lowercase, stripped exclusion terms.
    Strategy: find the section header, take the next 3000 chars, extract bullet items.
    """
    match = _EXCLUSION_HEADER_RE.search(text)
    if not match:
        logger.warning("exclusions_section_not_found")
        return []

    # Take up to 3000 characters after the header
    section = text[match.end(): match.end() + 3000]

    terms: List[str] = []
    for m in _BULLET_RE.finditer(section):
        term = m.group(1).strip()
        # Stop if we hit a new section header (e.g. "Section X:")
        if re.match(r"^[A-Z][A-Z\s]{5,}:", term):
            break
        if len(term) > 3:
            # Clean: strip trailing punctuation, lowercase
            term = re.sub(r"[;:,\.]+$", "", term).strip().lower()
            terms.append(term)

    logger.info("exclusions_parsed", count=len(terms))
    return terms


# ── Main service ──────────────────────────────────────────────────────────────

class HandbookService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = HandbookRepository(session)
        self._excl_repo = ExclusionRepository(session)

    async def ingest(
        self,
        *,
        file: UploadFile,
        version_tag: str,
        uploaded_by: UUID,
    ) -> HandbookVersion:
        """
        Full ingestion pipeline:
        save → extract → chunk → embed → faiss → exclusions → DB record → activate.
        """
        # ── 1. Save file ─────────────────────────────────────────
        settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        content = await file.read()
        if not content:
            raise ValidationError("Uploaded handbook file is empty.")

        file_id = uuid.uuid4()
        file_path = settings.UPLOAD_DIR / f"handbook_{file_id}.pdf"
        file_path.write_bytes(content)
        logger.info("handbook_file_saved", path=str(file_path), size_bytes=len(content))

        # ── 2. Extract text ──────────────────────────────────────
        raw_text = extract_text_from_pdf(file_path)
        if len(raw_text) < 100:
            raise ValidationError(
                "Could not extract meaningful text from the handbook PDF. "
                "Ensure it is a digital (not scanned) PDF."
            )

        # ── 3. Chunk ─────────────────────────────────────────────
        chunks = chunk_text(raw_text)
        if not chunks:
            raise ValidationError("Chunking produced zero chunks from the handbook.")
        logger.info("handbook_chunked", chunk_count=len(chunks))

        # ── 4 & 5. Embed + build FAISS index ─────────────────────
        model = _get_embedding_model()
        faiss_index, _ = build_faiss_index(chunks, model)

        # ── 6. Save FAISS artefacts ──────────────────────────────
        version_dir = settings.FAISS_INDEX_DIR / str(file_id)
        index_path, _chunks_path = save_faiss_artefacts(faiss_index, chunks, version_dir)

        # ── 7. Parse & seed General Exclusions ───────────────────
        exclusion_terms = parse_general_exclusions(raw_text)
        await self._seed_exclusions(exclusion_terms, uploaded_by)

        # ── 8. Create DB record & activate ───────────────────────
        await self._repo.deactivate_all()

        hb = HandbookVersion(
            version_tag=version_tag,
            file_path=str(file_path),
            chunk_count=len(chunks),
            faiss_index_path=str(version_dir),
            is_active=True,
            uploaded_by=uploaded_by,
        )
        hb = await self._repo.create(hb)
        await self._session.commit()

        # Invalidate the RAGService in-memory cache so next request reloads
        from app.services.rag_service import RAGService
        RAGService.invalidate_cache()

        logger.info(
            "handbook_ingested",
            version_tag=version_tag,
            chunks=len(chunks),
            exclusions_seeded=len(exclusion_terms),
        )
        return hb

    async def _seed_exclusions(self, terms: List[str], created_by: UUID) -> None:
        """
        Insert exclusion terms that do not already exist in the DB.
        Existing terms are left untouched (idempotent).
        """
        inserted = 0
        for term in terms:
            existing = await self._excl_repo.get_by_term(term)
            if existing is None:
                exc = Exclusion(
                    term=term,
                    description="Auto-seeded from handbook ingestion",
                    created_by=created_by,
                    is_active=True,
                )
                self._session.add(exc)
                inserted += 1
        if inserted:
            await self._session.flush()
        logger.info("exclusions_seeded", new_terms=inserted)

    async def list_handbooks(self) -> HandbookListResponse:
        items = await self._repo.get_all(limit=50)
        return HandbookListResponse(items=items, total=len(items))
