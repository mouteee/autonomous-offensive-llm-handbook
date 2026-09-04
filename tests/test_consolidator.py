"""Collapsing duplicates without losing them."""
import asyncio
import pytest
from core.consolidator import consolidation_signature, consolidate_scan


class FakeStore:
    """In-memory FindingStore double, built from the MEASURED store contract.

    Lives in tests, never in core/ -- a fake store inside core/ would invite a
    reader to mistake it for the write path, which is this handbook's argument.
    Note what consolidate_scan actually needs: `scan_id` as an attribute, a
    paging `get_findings`, and a SYNCHRONOUS `update_finding_governed`. It never
    calls `update_finding` and never passes a `scan_id` to `get_findings`.
    """

    def __init__(self, findings, scan_id="scan-1"):
        self._f = [dict(f) for f in findings]
        self.scan_id = scan_id
        self.governed_calls = []

    async def get_findings(self, severity=None, finding_type=None, validated_only=False,
                           exclude_fp=True, limit=100, offset=0):
        rows = [f for f in self._f if not (exclude_fp and f.get("false_positive"))]
        return [dict(r) for r in rows[offset:offset + limit]]

    def update_finding_governed(self, finding_id, severity, raw_data, false_positive=False):
        # Synchronous on purpose: both real callers invoke it without `await`.
        self.governed_calls.append((finding_id, severity, bool(false_positive)))
        for f in self._f:
            if f["id"] == finding_id:
                f["severity"] = severity
                f["raw_data"] = raw_data
                f["false_positive"] = bool(false_positive)

    async def add_finding(self, finding):
        raise AssertionError("consolidate_scan must not add findings")

    def rows(self):
        return [{k: f.get(k) for k in ("id", "severity", "false_positive")} for f in self._f]


def _pair():
    return [
        {"id": "1", "type": "idor", "title": "IDOR on order 1", "severity": "high",
         "url": "https://a.shop.example/o/1"},
        {"id": "2", "type": "idor", "title": "IDOR on order 2", "severity": "high",
         "url": "https://b.shop.example/o/2"},
    ]


def test_the_signature_strips_digits_and_case_but_not_meaning():
    a = {"type": "idor", "title": "IDOR on order 1041"}
    b = {"type": "idor", "title": "idor on order 99872"}
    c = {"type": "idor", "title": "IDOR on invoice 1041"}
    assert consolidation_signature(a) == consolidation_signature(b)
    assert consolidation_signature(a) != consolidation_signature(c)
    assert consolidation_signature(a) == ("idor", "idor on order")   # trailing space collapsed


def test_a_title_falls_back_to_name():
    assert consolidation_signature({"type": "x", "name": "Thing 7"}) == ("x", "thing")


def test_cross_host_duplicates_become_one_group_that_records_both_hosts():
    store = FakeStore(_pair())
    out = asyncio.run(consolidate_scan(store))
    assert len(out["groups"]) == 1
    group = out["groups"][0]
    assert group["primary_id"] == "1"
    assert group["absorbed_ids"] == ["2"]
    assert set(group["affected_hosts"]) == {"a.shop.example", "b.shop.example"}


def test_the_group_record_carries_the_pre_governance_severity():
    """The group is recorded before govern_scan runs, so the two disagree on
    purpose: the group says `high`, the stored finding ends up `medium` because
    the evidence ceiling capped it afterwards."""
    store = FakeStore(_pair())
    out = asyncio.run(consolidate_scan(store))
    assert out["groups"][0]["severity"] == "high"
    surviving = [r for r in store.rows() if not r["false_positive"]]
    assert surviving == [{"id": "1", "severity": "medium", "false_positive": False}]


def test_the_absorbed_member_is_hidden_rather_than_deleted():
    store = FakeStore(_pair())
    asyncio.run(consolidate_scan(store))
    absorbed = [r for r in store.rows() if r["false_positive"]]
    assert [r["id"] for r in absorbed] == ["2"]


def test_a_second_pass_absorbs_nothing_further():
    """The idempotence this module HAS: the store converges."""
    store = FakeStore(_pair())
    asyncio.run(consolidate_scan(store))
    rows_after_first = store.rows()
    calls_after_first = len(store.governed_calls)
    asyncio.run(consolidate_scan(store))
    assert store.rows() == rows_after_first
    assert not any(fp for (_, _, fp) in store.governed_calls[calls_after_first:])


def test_the_returned_record_is_not_idempotent_and_that_is_documented():
    """The idempotence this module does NOT have. Kept as a test so nobody
    'fixes' the one above by asserting record equality, which is false."""
    store = FakeStore(_pair())
    first = asyncio.run(consolidate_scan(store))
    second = asyncio.run(consolidate_scan(store))
    assert first != second
    assert first["groups"][0]["absorbed_ids"] == ["2"]
    assert second["groups"][0]["absorbed_ids"] == []


def test_a_hostless_member_is_never_absorbed():
    findings = _pair() + [{"id": "3", "type": "idor", "title": "IDOR on order 9",
                           "severity": "high", "url": ""}]
    store = FakeStore(findings)
    asyncio.run(consolidate_scan(store))
    hostless = [r for r in store.rows() if r["id"] == "3"]
    assert hostless == [{"id": "3", "severity": "medium", "false_positive": False}]


def test_one_host_alone_is_not_consolidated():
    findings = [dict(_pair()[0]),
                {"id": "2", "type": "idor", "title": "IDOR on order 2", "severity": "high",
                 "url": "https://a.shop.example/o/2"}]
    store = FakeStore(findings)
    out = asyncio.run(consolidate_scan(store))
    assert all(g["absorbed_ids"] == [] for g in out["groups"])


def test_the_per_host_rollup_and_affected_hosts_disagree_by_construction():
    """Rollups count SURVIVORS, so the absorbed host leaves per_host entirely
    even though the group's affected_hosts still records it."""
    store = FakeStore(_pair())
    out = asyncio.run(consolidate_scan(store))
    assert set(out["groups"][0]["affected_hosts"]) == {"a.shop.example", "b.shop.example"}
    assert set(out["per_host"]) == {"a.shop.example"}
    assert out["deduped"] == {"medium": 1}
    assert out["headline"] == "medium"


def test_it_is_a_no_op_when_governance_is_off(monkeypatch):
    monkeypatch.setenv("AUTOMATOR_GOVERNANCE", "0")
    store = FakeStore(_pair())
    out = asyncio.run(consolidate_scan(store))
    assert out == {"groups": [], "per_host": {}, "deduped": {}, "headline": "info"}
    assert store.governed_calls == []
