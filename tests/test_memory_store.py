"""The memory store's writer contracts, held at their boundaries."""

import json

import pytest

from core.memory import store as store_module
from core.memory.records import MemoryRecord, anonymize_target
from core.memory.store import MemoryStore, MemoryStoreError


def chapter_claim(chapter, *sentences):
    """Anchor a test to the verbatim lesson sentence(s) it backs;
    scripts/verify_claims.sh compares each declared sentence with its chapter."""
    def deco(fn):
        return fn
    return deco


PROFILE = "python:postgresql:waf_present:generic_waf:rest:flask"


def tactic_keys(**overrides):
    keys = dict(profile_hash=PROFILE, tool="test_sqli",
                endpoint="/api/7/items", param="id", technique="union_select")
    keys.update(overrides)
    return keys


@chapter_claim(
    "handbook/course/06-retrieval-and-memory.md",
    "a repeated success lands on the existing tactic row as an increment, not a duplicate",
)
def test_a_repeat_success_lands_on_the_existing_row():
    store = MemoryStore()
    first = store.record_success(**tactic_keys(), now=1.0)
    second = store.record_success(**tactic_keys(), now=2.0)
    assert first == second
    rows = store.fetch(tier="longterm")
    assert len(rows) == 1
    meta = json.loads(rows[0]["metadata"])
    assert meta["total_attempts"] == 2
    assert meta["total_successes"] == 2


@chapter_claim(
    "handbook/course/06-retrieval-and-memory.md",
    "The evidence grade only moves up on new proof, and only a refutation moves it back down.",
)
def test_the_evidence_grade_only_moves_up_on_new_proof():
    store = MemoryStore()
    store.record_success(**tactic_keys(), now=1.0)
    grade = lambda: json.loads(store.fetch(tier="longterm",
                                           include_refuted=True)[0]["metadata"])["evidence_grade"]
    assert grade() == "hypothesis"
    store.record_success(**tactic_keys(), proof="rows came back", now=2.0)
    assert grade() == "proven"
    store.record_success(**tactic_keys(), now=3.0)  # no proof: stays proven
    assert grade() == "proven"
    store.record_refuted(**tactic_keys())
    assert grade() == "hypothesis"


@chapter_claim(
    "handbook/course/06-retrieval-and-memory.md",
    "A recorded failure updates an existing tactic's counters and creates nothing.",
)
def test_record_failure_updates_and_creates_nothing():
    store = MemoryStore()
    assert store.record_failure(**tactic_keys()) is False
    assert store.fetch(tier="longterm") == []
    store.record_success(**tactic_keys(), now=1.0)
    assert store.record_failure(**tactic_keys()) is True
    meta = json.loads(store.fetch(tier="longterm")[0]["metadata"])
    assert meta["total_attempts"] == 2
    assert meta["total_successes"] == 1
    assert meta["success_rate"] == 0.5


@chapter_claim(
    "handbook/course/06-retrieval-and-memory.md",
    "a refutation is an in-place flag: the row stays, the grade returns to hypothesis, the confidence drops, and default reads exclude it",
)
def test_a_refuted_tactic_keeps_its_row_and_loses_its_standing():
    store = MemoryStore()
    store.record_success(**tactic_keys(), proof="proof text", now=1.0)
    assert store.record_refuted(**tactic_keys()) is True
    assert store.fetch(tier="longterm") == []
    kept = store.fetch(tier="longterm", include_refuted=True)
    assert len(kept) == 1
    meta = json.loads(kept[0]["metadata"])
    assert meta["refuted"] is True
    assert meta["evidence_grade"] == "hypothesis"
    assert kept[0]["confidence"] == 0.0


@chapter_claim(
    "handbook/course/06-retrieval-and-memory.md",
    "Deletion is a separate operation that removes the row and its index entry outright.",
)
def test_deletion_is_a_separate_harder_operation():
    store = MemoryStore()
    record_id = store.record_success(**tactic_keys(), now=1.0)
    assert store.delete(record_id) is True
    assert store.fetch(tier="longterm", include_refuted=True) == []
    fts = store.connection.execute(
        "SELECT count(*) FROM memory_fts WHERE memory_fts MATCH 'items'").fetchone()[0]
    assert fts == 0
    assert store.delete(record_id) is False


@chapter_claim(
    "handbook/course/06-retrieval-and-memory.md",
    "target domains are stored only as short one-way hashes, in tactics that travel across engagements",
)
def test_targets_are_stored_anonymized():
    store = MemoryStore()
    store.record_success(**tactic_keys(), target_domain="shop.example", now=1.0)
    meta = json.loads(store.fetch(tier="longterm")[0]["metadata"])
    assert meta["targets_seen"] == [anonymize_target("shop.example")]
    assert "shop.example" not in json.dumps(store.fetch(tier="longterm"))


@chapter_claim(
    "handbook/course/06-retrieval-and-memory.md",
    "An unknown scope filter is refused loudly instead of being ignored",
)
def test_an_unknown_scope_filter_is_refused():
    store = MemoryStore()
    with pytest.raises(MemoryStoreError):
        store.fetch(hostname="shop.example")


@chapter_claim(
    "handbook/course/06-retrieval-and-memory.md",
    "When the interpreter's SQLite lacks FTS5 the store refuses to start "
    "rather than index nothing.",
)
def test_the_store_refuses_to_start_without_fts5(monkeypatch):
    monkeypatch.setattr(store_module, "_fts5_available", lambda: False)
    with pytest.raises(MemoryStoreError):
        MemoryStore()


@chapter_claim(
    "handbook/course/06-retrieval-and-memory.md",
    "all four tiers share one storage shape, so provenance, scope and "
    "retention are uniform rather than per-tier afterthoughts",
)
def test_every_tier_shares_the_storage_shape():
    store = MemoryStore()
    for tier in ("working", "episodic", "longterm", "knowledge"):
        store.add(MemoryRecord(record_id=f"r-{tier}", tier=tier,
                               record_type="note", content=f"a {tier} note",
                               engagement="engagement-a", created_at=1.0))
    rows = store.fetch(engagement="engagement-a")
    assert {row["tier"] for row in rows} == {"working", "episodic",
                                             "longterm", "knowledge"}
    assert all(row["schema_version"] == "memory-v1" for row in rows)
