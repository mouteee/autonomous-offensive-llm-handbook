"""The hybrid search engine's lanes, merge and fallback, held at their edges."""

import pytest

from core.memory.records import MemoryRecord
from core.memory.search import HybridSearch, _normalize, sanitize_query
from core.memory.store import MemoryStore, MemoryStoreError


def chapter_claim(chapter, *sentences):
    """Anchor a test to the verbatim lesson sentence(s) it backs;
    scripts/verify_claims.sh compares each declared sentence with its chapter."""
    def deco(fn):
        return fn
    return deco


def embed(text):
    """A two-dimensional toy embedder: counts of two marker words."""
    lower = text.lower()
    return [float(lower.count("injection")), float(lower.count("header"))]


def seeded_store():
    store = MemoryStore()
    docs = {
        "d-sqli": "sql injection through the items api id parameter",
        "d-headers": "missing security header on every page",
        "d-mixed": "the header probe found an injection hint",
    }
    for record_id, content in docs.items():
        store.add(MemoryRecord(record_id=record_id, tier="knowledge",
                               record_type="note", content=content,
                               created_at=1.0),
                  embedding=embed(content))
    return store


@chapter_claim(
    "handbook/course/06-retrieval-and-memory.md",
    "Every result carries its component scores, and the final score recomputes "
    "from them and the recorded weights.",
)
def test_component_scores_recompute_the_final_score():
    results, trace = HybridSearch(seeded_store(), embedder=embed).search(
        "sql injection", limit=3)
    assert results
    for result in results:
        expected = (trace["weights"]["vector"] * result.vector_score
                    + trace["weights"]["keyword"] * result.keyword_score)
        assert result.score == pytest.approx(expected, abs=1e-6)


@chapter_claim(
    "handbook/course/06-retrieval-and-memory.md",
    "With no embedder configured, or an embedder that raises, the weights "
    "become zero and one and the trace says so.",
)
def test_keyword_only_fallback_is_flagged_not_silent():
    no_embedder = HybridSearch(seeded_store(), embedder=None)
    _, trace = no_embedder.search("sql injection", limit=3)
    assert trace["fallback"] is True
    assert trace["fallback_reason"] == "no embedder configured"
    assert trace["weights"] == {"vector": 0.0, "keyword": 1.0}

    def broken(text):
        raise RuntimeError("embedding service down")

    _, trace = HybridSearch(seeded_store(), embedder=broken).search(
        "sql injection", limit=3)
    assert trace["fallback"] is True
    assert "RuntimeError" in trace["fallback_reason"]


@chapter_claim(
    "handbook/course/06-retrieval-and-memory.md",
    "a candidate pool with no internal ordering maps every member to the same normalized score",
)
def test_a_degenerate_pool_scores_everyone_one():
    assert _normalize({"a": 2.5, "b": 2.5, "c": 2.5}) == {
        "a": 1.0, "b": 1.0, "c": 1.0}
    assert _normalize({}) == {}
    spread = _normalize({"a": 0.0, "b": 2.0, "c": 1.0})
    assert spread == {"a": 0.0, "b": 1.0, "c": 0.5}


@chapter_claim(
    "handbook/course/06-retrieval-and-memory.md",
    "sanitization strips operator characters to spaces, so quoted phrases are impossible by design",
)
def test_fts_specials_are_stripped_not_escaped():
    assert sanitize_query('"sql injection" NEAR(api)') == "sql injection near api"
    # Lowercasing neutralizes the bare-word operators the character strip
    # cannot see: AND, OR and NOT are case-sensitive in FTS5.
    assert sanitize_query("alpha OR bravo") == "alpha or bravo"
    assert sanitize_query("items*:^~") == "items"
    assert sanitize_query("(){}[]") == ""


@chapter_claim(
    "handbook/course/06-retrieval-and-memory.md",
    "A search filter outside the scope-key allowlist is refused.",
)
def test_search_filters_stay_inside_the_allowlist():
    with pytest.raises(MemoryStoreError):
        HybridSearch(seeded_store()).search("injection", hostname="x")


@chapter_claim(
    "handbook/course/06-retrieval-and-memory.md",
    "A refuted record stops surfacing in search as well as in the lanes.",
)
def test_refuted_records_do_not_surface_in_search():
    store = MemoryStore()
    store.record_success(profile_hash="p:q:r", tool="test_sqli",
                         endpoint="/api/items", param="id",
                         technique="union_select",
                         content="union injection on the items api", now=1.0)
    engine = HybridSearch(store, embedder=None)
    results, _ = engine.search("injection")
    assert [r.record_id for r in results]
    store.record_refuted(profile_hash="p:q:r", tool="test_sqli",
                         endpoint="/api/items", param="id",
                         technique="union_select")
    results, _ = engine.search("injection")
    assert results == []
