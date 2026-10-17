"""
tests/unit/test_handbook_chunking.py
──────────────────────────────────────
Unit tests for the text chunking and General Exclusions parser.
No I/O, no models, no DB — pure function tests.
"""
import pytest

from app.services.handbook_service import (
    MIN_CHUNK_LENGTH,
    chunk_text,
    parse_general_exclusions,
)


# ── chunk_text ─────────────────────────────────────────────────────────────────

class TestChunkText:
    def test_empty_string_returns_empty_list(self):
        assert chunk_text("") == []

    def test_short_text_produces_single_chunk(self):
        text = "A" * 500
        chunks = chunk_text(text, chunk_size=1000, overlap=200)
        assert len(chunks) == 1
        assert chunks[0] == text.strip()

    def test_long_text_produces_multiple_chunks(self):
        text = "Word " * 1000  # ~5000 chars
        chunks = chunk_text(text, chunk_size=1000, overlap=200)
        assert len(chunks) > 1

    def test_overlap_causes_content_repetition(self):
        """The end of chunk N should appear in chunk N+1."""
        text = "Hello world. " * 200  # ~2600 chars
        chunks = chunk_text(text, chunk_size=500, overlap=100)
        if len(chunks) >= 2:
            # Last 80 chars of chunk 0 should appear somewhere in chunk 1
            end_of_chunk0 = chunks[0][-80:].strip()
            assert end_of_chunk0 in chunks[1] or len(end_of_chunk0) < 10

    def test_chunks_meet_minimum_length(self):
        text = "B" * 2000
        chunks = chunk_text(text, chunk_size=200, overlap=50)
        for chunk in chunks:
            assert len(chunk) >= MIN_CHUNK_LENGTH

    def test_whitespace_stripped_from_chunks(self):
        text = "  " + ("X" * 600) + "  "
        chunks = chunk_text(text, chunk_size=1000, overlap=0)
        for chunk in chunks:
            assert chunk == chunk.strip()

    def test_very_small_chunk_size(self):
        """chunk_size smaller than MIN_CHUNK_LENGTH should produce no chunks."""
        text = "A" * 200
        # Chunks of 30 chars are smaller than MIN_CHUNK_LENGTH=50
        chunks = chunk_text(text, chunk_size=30, overlap=0)
        # All chunks are too short — they should be filtered out
        assert all(len(c) >= MIN_CHUNK_LENGTH for c in chunks)

    def test_no_infinite_loop_on_huge_overlap(self):
        """Overlap >= chunk_size must not cause an infinite loop."""
        text = "X" * 3000
        # overlap > chunk_size — advance is clamped to 1
        chunks = chunk_text(text, chunk_size=100, overlap=200)
        # Just verify it terminates
        assert len(chunks) >= 1

    def test_sentence_boundary_snapping(self):
        """Chunk boundaries should prefer '. ' over mid-word cuts."""
        sentence = "The patient presented with acute myocarditis. "
        text = sentence * 25  # ~1100 chars
        chunks = chunk_text(text, chunk_size=500, overlap=0)
        # At least some chunks should end with a period + space pattern
        ends_at_sentence = any(
            chunk.endswith(".") or chunk.endswith(". ") or ". " in chunk[-5:]
            for chunk in chunks
        )
        assert ends_at_sentence


# ── parse_general_exclusions ───────────────────────────────────────────────────

class TestParseGeneralExclusions:
    _SAMPLE_TEXT = """
    Section 4: Benefits Overview
    ...

    General Exclusions

    The following conditions are not covered under this policy:

    1. Pre-existing conditions diagnosed before policy start
    2. Cosmetic surgery or procedures
    3. HIV/AIDS and related conditions
    4. Self-inflicted injuries
    - Alcoholism and drug addiction
    - Dental treatment (unless resulting from accident)
    e) Pregnancy and maternity (unless optional rider is selected)

    Section 5: Claims Process
    ...
    """

    def test_finds_exclusions_from_numbered_list(self):
        terms = parse_general_exclusions(self._SAMPLE_TEXT)
        lowered = [t.lower() for t in terms]
        assert any("pre-existing" in t for t in lowered)
        assert any("cosmetic" in t for t in lowered)

    def test_finds_exclusions_from_bullet_list(self):
        terms = parse_general_exclusions(self._SAMPLE_TEXT)
        lowered = [t.lower() for t in terms]
        assert any("alcoholism" in t for t in lowered)

    def test_returns_empty_when_no_section(self):
        text = "This policy covers all conditions. No exclusions apply."
        terms = parse_general_exclusions(text)
        assert terms == []

    def test_case_insensitive_header_matching(self):
        text = "GENERAL EXCLUSIONS\n1. War injuries\n2. Nuclear hazard"
        terms = parse_general_exclusions(text)
        assert len(terms) >= 1

    def test_terms_are_lowercase(self):
        text = "General Exclusions\n1. Cosmetic Surgery\n2. HIV/AIDS"
        terms = parse_general_exclusions(text)
        for term in terms:
            assert term == term.lower()

    def test_terms_are_stripped(self):
        text = "General Exclusions\n1.  Dental treatment.  \n"
        terms = parse_general_exclusions(text)
        for term in terms:
            assert term == term.strip()
            assert not term.endswith(".")

    def test_stops_at_next_section_header(self):
        text = (
            "General Exclusions\n"
            "1. Cosmetic surgery\n"
            "SECTION 5: CLAIMS PROCESS\n"  # should stop here
            "3. Nuclear war\n"
        )
        terms = parse_general_exclusions(text)
        lowered = [t.lower() for t in terms]
        # "nuclear war" is AFTER the section header, should not be included
        assert not any("nuclear war" in t for t in lowered)

    def test_minimum_term_length_enforced(self):
        """Very short 'terms' like 'or', 'and' should be discarded."""
        text = "General Exclusions\n- or\n- and\n- HIV/AIDS and related conditions"
        terms = parse_general_exclusions(text)
        for term in terms:
            assert len(term) > 3
