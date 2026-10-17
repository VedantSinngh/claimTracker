"""
tests/integration/test_handbook_ingestion.py
─────────────────────────────────────────────
`HandbookService.ingest` — the admin flow from PDF upload to an active,
searchable handbook version.

Real: PDF text extraction (pdfplumber over the committed sample handbook),
chunking, FAISS index construction and persistence, the General Exclusions
parser, exclusion seeding, and version activation.

Faked: the embedding model only. `all-MiniLM-L6-v2` is an 80MB download and
its vector values are irrelevant to the ingestion contract; `FakeEncoder`
produces deterministic unit vectors of the same shape.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import List

import faiss
import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers, UploadFile

from app.core.exceptions import ValidationError
from app.models.exclusion import Exclusion
from app.models.handbook import HandbookVersion
from app.models.role import RoleName
from app.models.user import User
from app.services import handbook_service as hb_module
from app.services.handbook_service import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    HandbookService,
    parse_general_exclusions,
)

SAMPLES_DIR = Path(__file__).resolve().parents[3] / "samples"
HANDBOOK_PDF = SAMPLES_DIR / "policy_handbook.pdf"

pytestmark = pytest.mark.asyncio

EMBED_DIM = 16


class FakeEncoder:
    """Deterministic stand-in for SentenceTransformer."""

    def __init__(self, *args, **kwargs) -> None:
        self.encoded_batches: List[List[str]] = []

    def encode(
        self,
        sentences,
        batch_size: int = 32,
        show_progress_bar: bool = False,
        normalize_embeddings: bool = False,
        convert_to_numpy: bool = False,
        **kwargs,
    ) -> np.ndarray:
        if isinstance(sentences, str):
            sentences = [sentences]
        self.encoded_batches.append(list(sentences))

        rows = []
        for text in sentences:
            # Hash the text into a stable vector, then L2-normalise.
            rng = np.random.default_rng(abs(hash(text)) % (2**32))
            vec = rng.standard_normal(EMBED_DIM).astype("float32")
            rows.append(vec / np.linalg.norm(vec))
        return np.vstack(rows).astype("float32")


@pytest.fixture
def fake_encoder(monkeypatch) -> FakeEncoder:
    encoder = FakeEncoder()
    monkeypatch.setattr(hb_module, "_get_embedding_model", lambda: encoder)
    return encoder


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    """Keep uploads and FAISS artefacts inside tmp_path."""
    uploads = tmp_path / "uploads"
    faiss_dir = tmp_path / "faiss_index"
    monkeypatch.setattr(hb_module.settings, "UPLOAD_DIR", uploads)
    monkeypatch.setattr(hb_module.settings, "FAISS_INDEX_DIR", faiss_dir)
    return uploads, faiss_dir


@pytest.fixture
def handbook_bytes() -> bytes:
    if not HANDBOOK_PDF.exists():
        pytest.skip(
            f"{HANDBOOK_PDF.name} not generated — "
            "run `python samples/create_sample_pdfs.py`"
        )
    return HANDBOOK_PDF.read_bytes()


@pytest.fixture
async def admin(db_session: AsyncSession, roles) -> User:
    from app.repositories.role_repo import RoleRepository

    role = await RoleRepository(db_session).get_by_name(RoleName.ADMIN)
    user = User(
        id=uuid.uuid4(),
        email=f"admin-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Admin Person",
        role_id=role.id,
    )
    user.role_obj = role
    db_session.add(user)
    await db_session.commit()
    return user


def _upload(content: bytes, filename: str = "handbook.pdf") -> UploadFile:
    from io import BytesIO

    return UploadFile(
        file=BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": "application/pdf"}),
    )


# ── Guard rails ───────────────────────────────────────────────────────────────

async def test_empty_upload_is_rejected(
    db_session: AsyncSession, admin: User, isolated_dirs, fake_encoder
):
    with pytest.raises(ValidationError, match="empty"):
        await HandbookService(db_session).ingest(
            file=_upload(b""), version_tag="v0", uploaded_by=admin.id
        )


async def test_unreadable_pdf_is_rejected(
    db_session: AsyncSession, admin: User, isolated_dirs, fake_encoder
):
    """
    A PDF pdfplumber cannot read text from (e.g. a pure scan) must fail loudly
    rather than building an index over an empty string.
    """
    with pytest.raises(ValidationError, match="Could not extract meaningful text"):
        await HandbookService(db_session).ingest(
            file=_upload(b"%PDF-1.4\nnot really a pdf\n%%EOF"),
            version_tag="v0",
            uploaded_by=admin.id,
        )


# ── Happy path ────────────────────────────────────────────────────────────────

async def test_ingest_builds_index_and_activates_version(
    db_session: AsyncSession,
    admin: User,
    isolated_dirs,
    fake_encoder,
    handbook_bytes: bytes,
):
    uploads, faiss_dir = isolated_dirs

    handbook = await HandbookService(db_session).ingest(
        file=_upload(handbook_bytes), version_tag="2024-01", uploaded_by=admin.id
    )

    assert handbook.is_active is True
    assert handbook.version_tag == "2024-01"
    assert handbook.uploaded_by == admin.id
    assert handbook.chunk_count and handbook.chunk_count > 0

    # ── The PDF was saved ───────────────────────────────────────
    saved = list(uploads.glob("handbook_*.pdf"))
    assert len(saved) == 1
    assert saved[0].read_bytes() == handbook_bytes

    # ── FAISS artefacts exist and are loadable ──────────────────
    version_dir = Path(handbook.faiss_index_path)
    assert version_dir.is_relative_to(faiss_dir)
    index_path = version_dir / "index.faiss"
    chunks_path = version_dir / "chunks.json"
    assert index_path.exists() and chunks_path.exists()

    index = faiss.read_index(str(index_path))
    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    assert index.ntotal == handbook.chunk_count == len(chunks)
    assert index.d == EMBED_DIM

    # ── Every chunk was embedded exactly once ───────────────────
    embedded = [text for batch in fake_encoder.encoded_batches for text in batch]
    assert len(embedded) == len(chunks)


async def test_ingest_seeds_exclusions_from_the_handbook(
    db_session: AsyncSession,
    admin: User,
    isolated_dirs,
    fake_encoder,
    handbook_bytes: bytes,
):
    await HandbookService(db_session).ingest(
        file=_upload(handbook_bytes), version_tag="2024-01", uploaded_by=admin.id
    )

    rows = (await db_session.execute(select(Exclusion))).scalars().all()
    assert rows, "the General Exclusions section should have seeded terms"

    terms = " | ".join(r.term for r in rows)
    for expected in ("obesity", "cosmetic surgery", "hiv/aids", "infertility"):
        assert expected in terms.lower(), f"{expected!r} not seeded"

    assert all(r.is_active for r in rows)
    assert all(r.created_by == admin.id for r in rows)


async def test_reingesting_is_idempotent_for_exclusions(
    db_session: AsyncSession,
    admin: User,
    isolated_dirs,
    fake_encoder,
    handbook_bytes: bytes,
):
    """Uploading the same handbook twice must not duplicate exclusion rows."""
    svc = HandbookService(db_session)
    await svc.ingest(
        file=_upload(handbook_bytes), version_tag="2024-01", uploaded_by=admin.id
    )
    first_count = len((await db_session.execute(select(Exclusion))).scalars().all())

    await svc.ingest(
        file=_upload(handbook_bytes), version_tag="2024-02", uploaded_by=admin.id
    )
    second_count = len((await db_session.execute(select(Exclusion))).scalars().all())

    assert second_count == first_count


async def test_only_the_newest_handbook_stays_active(
    db_session: AsyncSession,
    admin: User,
    isolated_dirs,
    fake_encoder,
    handbook_bytes: bytes,
):
    """
    Exactly one handbook is active at a time — RAGService resolves the index
    path through `get_active()`, so two actives would be ambiguous.
    """
    svc = HandbookService(db_session)
    first = await svc.ingest(
        file=_upload(handbook_bytes), version_tag="2024-01", uploaded_by=admin.id
    )
    second = await svc.ingest(
        file=_upload(handbook_bytes), version_tag="2024-02", uploaded_by=admin.id
    )

    rows = (await db_session.execute(select(HandbookVersion))).scalars().all()
    active = [r for r in rows if r.is_active]
    assert len(rows) == 2
    assert len(active) == 1
    assert active[0].id == second.id

    # Each version keeps its own artefacts, so rollback is a single UPDATE.
    assert first.faiss_index_path != second.faiss_index_path
    assert Path(first.faiss_index_path, "index.faiss").exists()


async def test_ingest_invalidates_the_rag_cache(
    db_session: AsyncSession,
    admin: User,
    isolated_dirs,
    fake_encoder,
    handbook_bytes: bytes,
    monkeypatch,
):
    """
    Without this, searches would keep answering from the superseded index.
    """
    from app.services import rag_service as rag_module

    calls: List[int] = []
    monkeypatch.setattr(
        rag_module.RAGService, "invalidate_cache", staticmethod(lambda: calls.append(1))
    )

    await HandbookService(db_session).ingest(
        file=_upload(handbook_bytes), version_tag="2024-01", uploaded_by=admin.id
    )
    assert calls == [1]


# ── Chunking contract ─────────────────────────────────────────────────────────

async def test_chunks_respect_size_and_overlap(
    db_session: AsyncSession,
    admin: User,
    isolated_dirs,
    fake_encoder,
    handbook_bytes: bytes,
):
    handbook = await HandbookService(db_session).ingest(
        file=_upload(handbook_bytes), version_tag="2024-01", uploaded_by=admin.id
    )
    chunks = json.loads(
        (Path(handbook.faiss_index_path) / "chunks.json").read_text(encoding="utf-8")
    )

    assert all(len(c) <= CHUNK_SIZE for c in chunks), "no chunk may exceed CHUNK_SIZE"
    assert len(chunks) > 1, "the sample handbook is longer than one chunk"

    # Consecutive chunks must share text — that is what the overlap is for.
    first, second = chunks[0], chunks[1]
    tail = first[-CHUNK_OVERLAP:]
    assert any(
        token and token in second
        for token in tail.split()[:5]
    ), "expected the overlap window to carry context into the next chunk"


# ── Exclusion parser, in isolation ────────────────────────────────────────────

def test_parser_returns_nothing_without_the_section():
    assert parse_general_exclusions("Section 1: Introduction\nNothing here.") == []


def test_parser_handles_numbered_and_bulleted_lists():
    text = """
    SECTION 4: GENERAL EXCLUSIONS

    1. Cosmetic surgery and aesthetic procedures
    2. HIV/AIDS and related infections;
    - Dental treatment unless accidental
    • Experimental treatments
    """
    terms = parse_general_exclusions(text)

    assert "cosmetic surgery and aesthetic procedures" in terms
    # Trailing punctuation is stripped and terms are lowercased.
    assert "hiv/aids and related infections" in terms
    assert "dental treatment unless accidental" in terms
    assert "experimental treatments" in terms


def test_parser_lowercases_and_trims():
    terms = parse_general_exclusions(
        "GENERAL EXCLUSIONS\n1.   Pregnancy And Childbirth   ;\n"
    )
    assert terms == ["pregnancy and childbirth"]
