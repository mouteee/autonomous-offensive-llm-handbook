import asyncio

import pytest

from walkthrough.store import WalkthroughStore

def _cors_finding():
    """A wildcard-CORS finding with STRONG evidence, so a rule fires rather than the ceiling.

    Two things here are load-bearing and both were measured. The type is `wildcard`, because
    that is what the `cors-wildcard` rule matches -- a `cors_misconfiguration` type matches no
    public rule at all. And the evidence is strong (request, response, poc_curl, poc_output),
    because a thin-evidence finding caps to medium via `evidence-ceiling` instead, which looks
    identical in the final severity and would prove nothing about the rule.
    """
    return {"type": "wildcard", "severity": "critical",
            "url": "https://shop.example.com/api/orders", "title": "CORS wildcard",
            "raw_data": {"evidence": "Access-Control-Allow-Origin: *",
                         "request": {"method": "GET", "url": "https://shop.example.com/api/orders"},
                         "response": {"status": 200,
                                      "headers": {"Access-Control-Allow-Origin": "*"},
                                      "body": "{}"},
                         "poc_curl": "curl -i https://shop.example.com/api/orders",
                         "poc_output": "Access-Control-Allow-Origin: *"}}

def test_the_write_path_governs_before_persisting():
    """add_finding governs; a store that skips it persists whatever it was handed.

    Measured on the shipped governor: this finding enters as critical and the
    `cors-wildcard` rule caps it at medium, so a stored severity of critical proves the
    write path did not govern.
    """
    store = WalkthroughStore()
    asyncio.run(store.add_finding(_cors_finding()))
    assert store.findings[0]["severity"] == "medium"
    assert store.findings[0]["rules_fired"] == ["cors-wildcard"]
    rec = store.governance_records[0]
    assert rec["original_severity"] == "critical" and rec["final_severity"] == "medium"


def test_an_empty_ruleset_is_refused_at_construction():
    """load_rules returns [] for a missing file, which would silently disable governance."""
    import core.severity_governor as sg
    import walkthrough.store as ws
    orig = ws.load_rules
    ws.load_rules = lambda *a, **k: []
    try:
        with pytest.raises(RuntimeError, match="loaded empty"):
            WalkthroughStore()
    finally:
        ws.load_rules = orig

def test_the_protocol_async_asymmetry_is_matched():
    """Seven members are awaitable and update_finding_governed never is."""
    import inspect
    s = WalkthroughStore()
    for name in ("add_finding", "get_findings", "add_tool_result", "add_tool_execution",
                 "get_coverage", "rollup_scan_stats", "update_status"):
        assert inspect.iscoroutinefunction(getattr(s, name)), f"{name} must be async"
    assert not inspect.iscoroutinefunction(s.update_finding_governed)

def test_rollup_returns_a_dict_even_when_empty():
    """A None here would poison every caller's `.get()` call, which this test blocks."""
    assert isinstance(asyncio.run(WalkthroughStore().rollup_scan_stats()), dict)

def test_get_findings_is_awaitable_and_returns_a_list():
    store = WalkthroughStore()
    asyncio.run(store.add_finding(_cors_finding()))
    assert asyncio.run(store.get_findings()) != []


def test_a_governed_write_to_an_unknown_id_is_refused():
    """A governed write that matches no stored finding raises instead of returning quietly.

    The callers under `core/` discard this member's return value, so a lost write has no
    other signal: the exception is the whole of it. The store already holds a governed
    finding when the mismatched write is made, and that finding is asserted untouched
    afterwards, so a refusal that first wrote the grade onto whatever row it did have fails
    here rather than reading as a clean refusal. It says nothing about a partial write to a
    row that DID match: this call never enters the matching branch.
    """
    store = WalkthroughStore()
    fid = asyncio.run(store.add_finding(_cors_finding()))
    with pytest.raises(KeyError, match="would be lost"):
        store.update_finding_governed("not-a-stored-id", "low", {})
    assert store.findings[0]["id"] == fid
    assert store.findings[0]["severity"] == "medium"
