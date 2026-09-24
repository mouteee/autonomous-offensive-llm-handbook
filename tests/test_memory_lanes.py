"""The structured lanes: ranking arithmetic, isolation, and negative evidence."""

import pytest

from core.memory.lanes import (host_history, learned_tactics, profile_priors,
                               profile_similarity, render_negative_evidence,
                               wilson_lower_bound)
from core.memory.store import MemoryStore


def chapter_claim(chapter, *sentences):
    """Anchor a test to the verbatim lesson sentence(s) it backs;
    scripts/verify_claims.sh compares each declared sentence with its chapter."""
    def deco(fn):
        return fn
    return deco


PROFILE = "python:postgresql:waf_present:generic_waf:rest:flask"
SIMILAR = "python:postgresql:waf_absent:none:rest:flask"
FOREIGN = "php:mysql:waf_absent:none:soap:laravel"


@chapter_claim(
    "handbook/course/06-retrieval-and-memory.md",
    "The Wilson lower bound ranks 1/1 below 12/23, which is the point of using it.",
)
def test_wilson_orders_small_perfect_below_large_partial():
    one_of_one = wilson_lower_bound(1, 1)
    twelve_of_twenty_three = wilson_lower_bound(12, 23)
    assert one_of_one == pytest.approx(0.206543, abs=1e-6)
    assert twelve_of_twenty_three == pytest.approx(0.329624, abs=1e-6)
    assert one_of_one < twelve_of_twenty_three
    assert 1 / 1 > 12 / 23  # the raw ratio orders them the other way
    assert wilson_lower_bound(0, 0) == 0.0


@chapter_claim(
    "handbook/course/06-retrieval-and-memory.md",
    "Components where either side is unknown are skipped, and a nearly-empty fingerprint cannot match at full confidence.",
)
def test_profile_similarity_skips_neutral_and_damps_thin_fingerprints():
    assert profile_similarity(PROFILE, PROFILE) == 1.0
    # The waf vendor "none" is neutral on the similar profile: four of the
    # five comparable components agree.
    assert profile_similarity(PROFILE, SIMILAR) == pytest.approx(0.8)
    assert profile_similarity(PROFILE, FOREIGN) < 0.5
    assert profile_similarity("a:b", "a") == 0.0  # unequal component counts
    # One comparable component agreeing is damped by min(1, 1/3).
    thin = profile_similarity("python:unknown:unknown", "python:unknown:unknown")
    assert thin == pytest.approx(1 / 3)


@chapter_claim(
    "handbook/course/06-retrieval-and-memory.md",
    "Another engagement's findings never surface in host history",
)
def test_host_history_is_engagement_isolated():
    store = MemoryStore()
    store.record_finding(finding_id="f-a", run_id="run-1",
                         engagement="engagement-a", severity="high",
                         title="SQLi", url="https://a.example/x", type="sqli",
                         now=1.0)
    store.record_finding(finding_id="f-b", run_id="run-9",
                         engagement="engagement-b", severity="critical",
                         title="SSRF", url="https://b.example/hooks",
                         type="ssrf", now=1.0)
    rows = host_history(store, "engagement-a")
    assert [r["ref"] for r in rows] == ["finding:f-a"]
    assert all("b.example" not in r["url"] for r in rows)


@chapter_claim(
    "handbook/course/06-retrieval-and-memory.md",
    "the current run, false positives and informational findings stay out of host history",
)
def test_host_history_excludes_the_current_run_fps_and_info():
    store = MemoryStore()
    common = dict(engagement="engagement-a", url="https://a.example/x",
                  type="sqli", now=1.0)
    store.record_finding(finding_id="f-old", run_id="run-1", severity="high",
                         title="SQLi", **common)
    store.record_finding(finding_id="f-current", run_id="run-2",
                         severity="high", title="SQLi current", **common)
    store.record_finding(finding_id="f-fp", run_id="run-1", severity="high",
                         title="FP", false_positive=True, **common)
    store.record_finding(finding_id="f-info", run_id="run-1", severity="info",
                         title="Info", **common)
    rows = host_history(store, "engagement-a", exclude_run_id="run-2")
    assert [r["ref"] for r in rows] == ["finding:f-old"]


@chapter_claim(
    "handbook/course/06-retrieval-and-memory.md",
    "proven tactics rank before hypotheses, and refuted tactics are excluded",
)
def test_learned_tactics_prefer_proven_and_exclude_refuted():
    store = MemoryStore()
    store.record_success(profile_hash=PROFILE, tool="test_idor",
                         endpoint="/api/9/orders", param="order_id",
                         now=1.0)  # hypothesis, rate 1.0
    store.record_success(profile_hash=PROFILE, tool="test_sqli",
                         endpoint="/api/7/items", param="id",
                         technique="union_select", proof="rows", now=1.0)
    store.record_failure(profile_hash=PROFILE, tool="test_sqli",
                         endpoint="/api/7/items", param="id",
                         technique="union_select")  # proven, rate 0.5
    tactics = learned_tactics(store, PROFILE)
    assert [t["evidence_grade"] for t in tactics] == ["proven", "hypothesis"]
    store.record_refuted(profile_hash=PROFILE, tool="test_idor",
                         endpoint="/api/9/orders", param="order_id")
    assert [t["tool"] for t in learned_tactics(store, PROFILE)] == ["test_sqli"]


@chapter_claim(
    "handbook/course/06-retrieval-and-memory.md",
    "Priors order work and are not plan entries",
    "the ranking confidence is the Wilson lower bound over the raw pooled counts",
)
def test_priors_aggregate_across_similar_profiles_with_wilson_confidence():
    store = MemoryStore()
    for i in range(23):
        store.record_tool_run(tool="test_sqli", profile_hash=PROFILE, hit=i < 12)
    for i in range(10):
        store.record_tool_run(tool="test_sqli", profile_hash=SIMILAR, hit=i < 2)
    for i in range(40):
        store.record_tool_run(tool="test_sqli", profile_hash=FOREIGN, hit=i < 1)
    rows = profile_priors(store, PROFILE)
    assert len(rows) == 1
    row = rows[0]
    assert row["n"] == 33 and row["hits"] == 14  # foreign profile excluded
    assert row["confidence"] == pytest.approx(wilson_lower_bound(14, 33), abs=1e-6)
    assert row["weighted_n"] == pytest.approx(23 + 10 * 0.8)


@chapter_claim(
    "handbook/course/06-retrieval-and-memory.md",
    "a zero-hit row appears in the negative-evidence section only when its denominator is big enough to mean something",
)
def test_negative_evidence_requires_a_real_denominator():
    store = MemoryStore()
    for _ in range(8):
        store.record_tool_run(tool="test_headers", profile_hash=PROFILE, hit=False)
    store.record_tool_run(tool="test_upload", profile_hash=PROFILE, hit=False)
    rendered = render_negative_evidence(profile_priors(store, PROFILE))
    assert "test_headers: 0 hits in 8 tries" in rendered
    assert "test_upload" not in rendered
    assert "deprioritize, do not skip" in rendered
