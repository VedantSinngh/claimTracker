"""
app/services/rag_service.py
────────────────────────────
Retrieval-Augmented Generation service.

Maintains a module-level singleton cache of (faiss_index, chunks).
The cache is invalidated when a new handbook is ingested.

Search flow:
  1. Embed the query with the same SentenceTransformer used at index time
  2. L2-normalise (already done by encode(normalize_embeddings=True))
  3. FAISS IndexFlatIP.search → top-k results with cosine similarity scores
  4. Return list of (chunk_text, score) pairs

All embedding happens synchronously inside run_in_executor so the async
event loop is never blocked.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import List, Optional, Tuple

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import RAGIndexNotFound
from app.core.logging import get_logger
from app.repositories.handbook_repo import HandbookRepository

logger = get_logger(__name__)
settings = get_settings()


# ── Module-level singleton cache ──────────────────────────────────────────────

class _RAGCache:
    """Thread-safe, invalidatable cache for the FAISS index + chunks."""

    def __init__(self) -> None:
        self._index: Optional[faiss.Index] = None
        self._chunks: Optional[List[str]] = None
        self._model: Optional[SentenceTransformer] = None
        self._active_path: Optional[str] = None

    @property
    def is_loaded(self) -> bool:
        return self._index is not None and self._chunks is not None

    def load(self, index_dir: str) -> None:
        index_path = Path(index_dir) / "index.faiss"
        chunks_path = Path(index_dir) / "chunks.json"

        if not index_path.exists() or not chunks_path.exists():
            raise RAGIndexNotFound(
                f"FAISS artefacts not found at '{index_dir}'. "
                "Please ingest a handbook first."
            )
        self._index = faiss.read_index(str(index_path))
        self._chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
        if self._model is None:
            self._model = SentenceTransformer(settings.EMBEDDING_MODEL)
        self._active_path = index_dir
        logger.info(
            "rag_cache_loaded",
            path=index_dir,
            vectors=self._index.ntotal,
            chunks=len(self._chunks),
        )

    def invalidate(self) -> None:
        self._index = None
        self._chunks = None
        self._active_path = None
        logger.info("rag_cache_invalidated")

    def search(self, query: str, top_k: int) -> List[Tuple[str, float]]:
        """
        Embed the query and return top-k (chunk_text, cosine_score) pairs.
        Called inside run_in_executor to avoid blocking the event loop.
        """
        if self._index is None or self._chunks is None or self._model is None:
            raise RAGIndexNotFound("FAISS index is not loaded.")

        embedding: np.ndarray = self._model.encode(
            [query],
            normalize_embeddings=True,
            convert_to_numpy=True,
        ).astype("float32")

        scores, indices = self._index.search(embedding, top_k)
        results: List[Tuple[str, float]] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._chunks):
                continue  # FAISS returns -1 for padding
            results.append((self._chunks[idx], float(score)))

        return results


_cache = _RAGCache()


# ── Service ───────────────────────────────────────────────────────────────────

class RAGService:
    """
    Retrieval service.
    - Loads the active handbook index on first call (lazy init).
    - Returns top-k relevant chunks for a query.
    - `invalidate_cache()` is called by HandbookService after new ingestion.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = HandbookRepository(session)

    @staticmethod
    def invalidate_cache() -> None:
        _cache.invalidate()

    async def _ensure_loaded(self) -> None:
        """Load the active index if not already in memory."""
        if _cache.is_loaded:
            return

        active = await self._repo.get_active()
        if active is None or not active.faiss_index_path:
            raise RAGIndexNotFound(
                "No active handbook found. Please ask an admin to upload the policy handbook."
            )
        # Load is CPU-bound; run in executor to keep async loop free
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _cache.load, active.faiss_index_path)

    async def retrieve(
        self,
        query: str,
        *,
        top_k: Optional[int] = None,
    ) -> List[Tuple[str, float]]:
        """
        Return top-k handbook chunks most relevant to `query`.
        Each result is (chunk_text, cosine_similarity_score).
        Score range: 0.0 (unrelated) → 1.0 (identical).
        """
        await self._ensure_loaded()
        k = top_k or settings.RAG_TOP_K
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, _cache.search, query, k)
        logger.info(
            "rag_retrieved",
            query_preview=query[:80],
            top_k=k,
            results_found=len(results),
        )
        return results

    async def retrieve_formatted(self, query: str, top_k: Optional[int] = None) -> str:
        """
        Convenience method for prompt building.
        Returns a numbered, newline-separated string of the top-k chunks.
        """
        results = await self.retrieve(query, top_k=top_k)
        if not results:
            return "(No relevant handbook clauses found)"
        lines = [
            f"[Clause {i + 1}] (relevance: {score:.3f})\n{chunk}"
            for i, (chunk, score) in enumerate(results)
        ]
        return "\n\n---\n\n".join(lines)
