"""
tests/integration/test_rag_service.py
──────────────────────────────────────
RAGService: index loading, the module-level cache, top-k search and the
prompt-ready formatting.

A real FAISS `IndexFlatIP` is built on disk, but the embedding model is faked.
`all-MiniLM-L6-v2` is an 80MB download and its exact vectors are not what these
tests are about — the cache lifecycle, the cosine ordering and the formatting
contract are. `FakeEncoder` maps each known sentence to a fixed unit vector, so
similarity ordering is deterministic and the assertions are exact.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import List

import faiss
import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import RAGIndexNotFound
from app.models.handbook import HandbookVersion
from app.services import rag_service as rag_module
from app.services.rag_service import RAGService

pytestmark = pytest.mark.asyncio


# ── Fake embedding model ──────────────────────────────────────────────────────

# Three orthogonal "topics" in a 4-dimensional space. A query vector is built
# from whichever topic keywords it mentions, so cosine similarity is predictable.
_TOPICS = {
    "hospitalisation": np.array([1.0, 0.0, 0.0, 0.0], dtype="float32"),
    "exclusion": np.array([0.0, 1.0, 0.0, 0.0], dtype="float32"),
    "maternity": np.array([0.0, 0.0, 1.0, 0.0], dtype="float32"),
}
_UNKNOWN = np.array([0.0, 0.0, 0.0, 1.0], dtype="float32")

CHUNKS: List[str] = [
    "SECTION 2.1 Hospitalisation — in-patient expenses, room rent and surgeon fees are covered.",
    "SECTION 4 General Exclusions — cosmetic surgery and bariatric surgery are not covered.",
    "SECTION 2.5 Maternity — available only with the optional maternity rider.",
]

# chunk i is built from the i-th topic, in the order above.
_CHUNK_TOPICS = ["hospitalisation", "exclusion", "maternity"]


def _vector_for(text: str) -> np.ndarray:
    """Sum the topic vectors whose keyword appears, then L2-normalise."""
    lowered = text.lower()
    vec = np.zeros(4, dtype="float32")
    for keyword, topic_vec in _TOPICS.items():
        if keyword in lowered:
            vec = vec + topic_vec
    if not vec.any():
        vec = _UNKNOWN.copy()
    norm = float(np.linalg.norm(vec))
    return vec / norm


class FakeEncoder:
    """Mimics the SentenceTransformer surface RAGService actually uses."""

    def __init__(self, *args, **kwargs) -> None:
        self.calls: List[List[str]] = []

    def encode(
        self,
        sentences,
        normalize_embeddings: bool = False,
        convert_to_numpy: bool = False,
        **kwargs,
    ) -> np.ndarray:
        if isinstance(sentences, str):
            sentences = [sentences]
        self.calls.append(list(sentences))
        return np.vstack([_vector_for(s) for s in sentences]).astype("float32")


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def fake_embedding_model(monkeypatch):
    """Swap SentenceTransformer for FakeEncoder and reset the module cache."""
    monkeypatch.setattr(rag_module, "SentenceTransformer", FakeEncoder)
    rag_module._cache.invalidate()
    rag_module._cache._model = None
    yield
    rag_module._cache.invalidate()
    rag_module._cache._model = None


@pytest.fixture
def index_dir(tmp_path: Path) -> Path:
    """A real FAISS IndexFlatIP plus chunks.json, laid out as the service expects."""
    vectors = np.vstack(
        [_vector_for(f"{topic} {chunk}") for topic, chunk in zip(_CHUNK_TOPICS, CHUNKS)]
    ).astype("float32")

    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)

    out = tmp_path / "faiss_index" / "v1"
    out.mkdir(parents=True)
    faiss.write_index(index, str(out / "index.faiss"))
    (out / "chunks.json").write_text(json.dumps(CHUNKS), encoding="utf-8")
    return out


async def _activate_handbook(session: AsyncSession, index_dir: Path) -> HandbookVersion:
    handbook = HandbookVersion(
        id=uuid.uuid4(),
        version_tag="test-v1",
        file_path=str(index_dir / "handbook.pdf"),
        chunk_count=len(CHUNKS),
        faiss_index_path=str(index_dir),
        is_active=True,
    )
    session.add(handbook)
    await session.flush()
    return handbook


# ── No active handbook ────────────────────────────────────────────────────────

async def test_retrieve_without_handbook_raises(db_session: AsyncSession):
    with pytest.raises(RAGIndexNotFound, match="No active handbook"):
        await RAGService(db_session).retrieve("appendicitis")


async def test_retrieve_with_handbook_missing_index_path_raises(db_session: AsyncSession):
    handbook = HandbookVersion(
        id=uuid.uuid4(),
        version_tag="no-index",
        file_path="/tmp/handbook.pdf",
        chunk_count=0,
        faiss_index_path=None,
        is_active=True,
    )
    db_session.add(handbook)
    await db_session.flush()

    with pytest.raises(RAGIndexNotFound):
        await RAGService(db_session).retrieve("appendicitis")


async def test_load_from_missing_directory_raises(db_session: AsyncSession, tmp_path: Path):
    await _activate_handbook(db_session, tmp_path / "does-not-exist")

    with pytest.raises(RAGIndexNotFound, match="FAISS artefacts not found"):
        await RAGService(db_session).retrieve("appendicitis")


# ── Retrieval ─────────────────────────────────────────────────────────────────

async def test_retrieve_ranks_the_relevant_clause_first(
    db_session: AsyncSession, index_dir: Path
):
    await _activate_handbook(db_session, index_dir)

    results = await RAGService(db_session).retrieve("exclusion for bariatric surgery")

    assert results, "expected at least one hit"
    top_chunk, top_score = results[0]
    assert "General Exclusions" in top_chunk
    # Identical unit vectors → cosine similarity 1.0
    assert top_score == pytest.approx(1.0, abs=1e-5)

    # Scores must be non-increasing.
    scores = [score for _, score in results]
    assert scores == sorted(scores, reverse=True)


async def test_retrieve_respects_top_k(db_session: AsyncSession, index_dir: Path):
    await _activate_handbook(db_session, index_dir)
    svc = RAGService(db_session)

    assert len(await svc.retrieve("hospitalisation", top_k=1)) == 1
    assert len(await svc.retrieve("hospitalisation", top_k=2)) == 2


async def test_retrieve_never_returns_more_than_the_index_holds(
    db_session: AsyncSession, index_dir: Path
):
    """
    FAISS pads short result sets with index -1; the service must drop those
    rather than hand back a bogus chunk.
    """
    await _activate_handbook(db_session, index_dir)

    results = await RAGService(db_session).retrieve("hospitalisation", top_k=50)
    assert len(results) == len(CHUNKS)
    assert all(chunk in CHUNKS for chunk, _ in results)


async def test_unrelated_query_scores_zero(db_session: AsyncSession, index_dir: Path):
    """An orthogonal query vector gives cosine 0 — retrieval still returns rows."""
    await _activate_handbook(db_session, index_dir)

    results = await RAGService(db_session).retrieve("something entirely unrelated")
    assert all(score == pytest.approx(0.0, abs=1e-5) for _, score in results)


# ── Formatting for the prompt ─────────────────────────────────────────────────

async def test_retrieve_formatted_numbers_and_scores_the_clauses(
    db_session: AsyncSession, index_dir: Path
):
    await _activate_handbook(db_session, index_dir)

    formatted = await RAGService(db_session).retrieve_formatted(
        "hospitalisation cover", top_k=2
    )

    assert "[Clause 1]" in formatted
    assert "[Clause 2]" in formatted
    assert "relevance: 1.000" in formatted
    assert "\n\n---\n\n" in formatted, "clauses must be separated for the prompt"
    assert "SECTION 2.1 Hospitalisation" in formatted


async def test_retrieve_formatted_on_empty_index_says_so(
    db_session: AsyncSession, tmp_path: Path
):
    """
    An index with zero vectors must produce the explicit placeholder, because
    RAGPolicyCheckValidator keys off an empty string to route to NEEDS_REVIEW.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    faiss.write_index(faiss.IndexFlatIP(4), str(empty / "index.faiss"))
    (empty / "chunks.json").write_text("[]", encoding="utf-8")

    await _activate_handbook(db_session, empty)

    formatted = await RAGService(db_session).retrieve_formatted("anything")
    assert formatted == "(No relevant handbook clauses found)"


# ── Cache lifecycle ───────────────────────────────────────────────────────────

async def test_index_is_loaded_once_and_cached(
    db_session: AsyncSession, index_dir: Path, monkeypatch
):
    await _activate_handbook(db_session, index_dir)
    svc = RAGService(db_session)

    load_calls: List[str] = []
    original_load = rag_module._cache.load

    def counting_load(path: str) -> None:
        load_calls.append(path)
        original_load(path)

    monkeypatch.setattr(rag_module._cache, "load", counting_load)

    await svc.retrieve("hospitalisation")
    await svc.retrieve("exclusion")
    await svc.retrieve("maternity")

    assert len(load_calls) == 1, "the FAISS index must not be re-read per query"


async def test_invalidate_cache_forces_a_reload(
    db_session: AsyncSession, index_dir: Path, monkeypatch
):
    """
    HandbookService calls invalidate_cache() after ingesting a new handbook.
    Without it, searches would keep hitting the superseded index.
    """
    await _activate_handbook(db_session, index_dir)
    svc = RAGService(db_session)

    load_calls: List[str] = []
    original_load = rag_module._cache.load

    def counting_load(path: str) -> None:
        load_calls.append(path)
        original_load(path)

    monkeypatch.setattr(rag_module._cache, "load", counting_load)

    await svc.retrieve("hospitalisation")
    assert len(load_calls) == 1

    RAGService.invalidate_cache()
    assert rag_module._cache.is_loaded is False

    await svc.retrieve("hospitalisation")
    assert len(load_calls) == 2


async def test_cache_reports_loaded_state(db_session: AsyncSession, index_dir: Path):
    await _activate_handbook(db_session, index_dir)

    assert rag_module._cache.is_loaded is False
    await RAGService(db_session).retrieve("hospitalisation")
    assert rag_module._cache.is_loaded is True
