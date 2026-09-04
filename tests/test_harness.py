import copy
import json
from pathlib import Path

import pytest

from harness.demo import inputs, run_demo
from harness.runtime import GATE_KEYS, SEVERITIES, Harness, PolicyError, canonical_bytes, origin, strict_gate


SIGNALS = {"waf_detected": False, "total_responses": 2, "error_rate": 0.0,
           "parameters_found": 0, "forms_found": 0, "pages_crawled": 1, "scripts_found": 0}


def make(manifest=None, adapter=None):
    default, fixtures = inputs()
    manifest = manifest or default
    calls = []
    def callback(url, fixture):
        calls.append(url)
        return adapter(url) if adapter else copy.deepcopy(fixtures[fixture])
    adapters = {t["id"]: (lambda url, fixture=t["fixture"]: callback(url, fixture)) for t in manifest["tools"]}
    return Harness(manifest, adapters, fixtures), calls


def execute_all(run, url="https://lab.example/", signals=None):
    run.observe(SIGNALS if signals is None else signals)
    run.advance("plan")
    plan = run.plan(url)
    run.advance("execute")
    outcomes = [run.execute(item["tool"], item["url"]) for item in plan]
    run.advance("review")
    return outcomes


@pytest.mark.parametrize("url", ["https://other.lab.example/", "https://example/", "https://lab.example.evil.invalid/", "http://lab.example/", "https://lab.example:444/"])
def test_scope_blocks_callback_for_unauthorized_origins(url):
    run, calls = make()
    outcomes = execute_all(run, url)
    assert calls == []
    assert all(row["status"] == "skipped" for row in outcomes)
    assert all("authorized origins" in row["reason"] for row in outcomes)


@pytest.mark.parametrize("url", ["/relative", "https:///nohost", "file:///etc/passwd", "https://user@lab.example/", "https://lab.example/#x", "https://lab.example\\evil/", "https://lab.example:bad/", "https://lab.example /", "https://%6cab.example/"])
def test_malformed_urls_are_not_scope_facts(url):
    with pytest.raises(PolicyError):
        origin(url)


@pytest.mark.parametrize("key", GATE_KEYS)
def test_missing_each_gate_key_stops_callbacks(key):
    signals = dict(SIGNALS)
    del signals[key]
    run, calls = make()
    outcomes = execute_all(run, signals=signals)
    assert calls == []
    assert all(row["reason"] == "gate indeterminate" for row in outcomes)
    assert run.snapshot()["gate"]["missing"] == [key]


@pytest.mark.parametrize("key,value", [("waf_detected", "false"), ("pages_crawled", True), ("forms_found", -1), ("error_rate", float("nan")), ("error_rate", float("inf")), ("error_rate", 1.1), ("error_rate", None)])
def test_invalid_gate_values_are_rejected(key, value):
    signals = dict(SIGNALS, **{key: value})
    with pytest.raises(PolicyError):
        strict_gate(signals)


@pytest.mark.parametrize("rate", [.8, .804, .994, 1])
def test_gate_replays_exact_consulted_values(rate):
    result = strict_gate(dict(SIGNALS, error_rate=rate))
    assert result["inputs"]["error_rate"] == rate
    assert strict_gate(result["inputs"]) == result


def test_missing_gate_and_plan_prevent_stage_advance():
    run, calls = make()
    with pytest.raises(PolicyError):
        run.advance("plan")
    run.observe(SIGNALS)
    run.advance("plan")
    with pytest.raises(PolicyError):
        run.advance("execute")
    assert not calls


def test_out_of_stage_and_unplanned_tools_never_call_adapter():
    run, calls = make()
    with pytest.raises(PolicyError):
        run.execute("inspect_headers", "https://lab.example/")
    with pytest.raises(PolicyError):
        run.advance("execute")
    run.observe(SIGNALS)
    run.advance("plan")
    run.plan("https://lab.example/")
    run.advance("execute")
    with pytest.raises(PolicyError):
        run.execute("inspect_graphql", "https://lab.example/")
    assert calls == []


def test_unknown_profile_field_fails_manifest():
    manifest, _ = inputs()
    manifest["tools"][0]["requires"] = {"invented": True}
    with pytest.raises(PolicyError):
        make(manifest)


def test_unknown_is_not_false_and_catalogue_scoring_is_explicit():
    run, _ = make()
    run.observe(SIGNALS)
    run.advance("plan")
    plan = run.plan("https://lab.example/")
    assert [(r["tool"], r["score"]) for r in plan] == [("inspect_headers", 4), ("check_lab_marker", 2)]
    with pytest.raises(PolicyError):
        run.plan("https://lab.example/")


def test_budget_and_passive_gate_are_applied_before_callback():
    manifest, _ = inputs()
    manifest["max_actions"] = 1
    run, calls = make(manifest)
    outcomes = execute_all(run)
    assert len(calls) == 1
    assert outcomes[1]["reason"] == "action budget exhausted"
    run, calls = make()
    outcomes = execute_all(run, signals=dict(SIGNALS, error_rate=.804))
    assert len(calls) == 1
    assert outcomes[1]["reason"] == "gate permits passive work only"


def test_adapter_errors_are_charged_and_recorded():
    def broken(url):
        raise RuntimeError("synthetic failure")
    run, calls = make(adapter=broken)
    outcomes = execute_all(run)
    assert len(calls) == 2
    assert all(row["status"] == "error" for row in outcomes)
    assert run.snapshot()["coverage"]["error"] == 2


def review_run():
    run, _ = make()
    rows = execute_all(run)
    evidence_id = rows[1]["evidence_id"]
    finding = run.propose_finding(finding_id="f", title="Lab", kind="lab_marker", severity="critical", evidence_id=evidence_id, quote="LAB_CONFIRMED")
    return run, rows, finding


@pytest.mark.parametrize("quote", [None, "", " ", "paraphrased marker", "Access-Control-Allow-Origin: *"])
def test_bad_quotes_do_not_raise_or_mutate(quote):
    run, rows, _ = review_run()
    before = run.snapshot()
    with pytest.raises(PolicyError):
        run.verify_raise(finding_id="f", evidence_id=rows[1]["evidence_id"], quote=quote, severity="high", rule_id="synthetic-lab-proof")
    assert run.snapshot() == before


def test_cross_finding_evidence_and_forged_digest_are_rejected():
    run, rows, _ = review_run()
    for evidence_id in (rows[0]["evidence_id"], "fabricated"):
        with pytest.raises(PolicyError):
            run.verify_raise(finding_id="f", evidence_id=evidence_id, quote="LAB_CONFIRMED", severity="high", rule_id="synthetic-lab-proof")


def test_real_quote_without_independent_predicate_is_insufficient():
    run, _ = make()
    rows = execute_all(run)
    eid = rows[0]["evidence_id"]
    run.propose_finding(finding_id="f", title="Header", kind="header", severity="critical", evidence_id=eid, quote="Access-Control-Allow-Origin: *")
    with pytest.raises(PolicyError):
        run.verify_raise(finding_id="f", evidence_id=eid, quote="Access-Control-Allow-Origin: *", severity="high", rule_id="synthetic-lab-proof")
    assert run.snapshot()["findings"][0]["severity"] == "medium"


@pytest.mark.parametrize("capture", [
    {"status": 201, "body": "CAPTURED_CONTEXT LAB_CONFIRMED"},
    {"status": 200, "body": "CAPTURED_CONTEXT without the required marker"},
], ids=["wrong-status", "missing-marker"])
def test_matching_kind_tool_cannot_raise_without_capture_predicate(capture):
    # Keep the registered positive fixture intact. Only the adapter's fresh
    # capture differs, so kind/tool/quote/ceiling validation all pass and each
    # case isolates one runtime predicate, not constructor validation.
    run, _ = make(adapter=lambda url: copy.deepcopy(capture))
    rows = execute_all(run)
    evidence_id = rows[1]["evidence_id"]
    finding = run.propose_finding(
        finding_id="f", title="Synthetic marker candidate", kind="lab_marker",
        severity="critical", evidence_id=evidence_id, quote="CAPTURED_CONTEXT")
    assert finding["severity"] == "low"
    before = run.snapshot()
    with pytest.raises(PolicyError, match="independent policy predicate"):
        run.verify_raise(
            finding_id="f", evidence_id=evidence_id, quote="CAPTURED_CONTEXT",
            severity="high", rule_id="synthetic-lab-proof")
    assert run.snapshot() == before


@pytest.mark.parametrize("severity", SEVERITIES)
def test_governor_never_raises_across_severity_domain(severity):
    run, _ = make()
    rows = execute_all(run)
    result = run.propose_finding(finding_id="f", title="Header", kind="header", severity=severity, evidence_id=rows[0]["evidence_id"], quote="Access-Control-Allow-Origin: *")
    assert SEVERITIES.index(result["severity"]) <= SEVERITIES.index(severity)


def test_policy_validated_raise_keeps_human_acceptance_and_copies():
    run, rows, finding = review_run()
    finding["severity"] = "critical"
    assert run.snapshot()["findings"][0]["severity"] == "low"
    result = run.verify_raise(finding_id="f", evidence_id=rows[1]["evidence_id"], quote="LAB_CONFIRMED", severity="high", rule_id="synthetic-lab-proof")
    assert result["severity"] == "high"
    assert result["acceptance"] == "human_review_required"
    result["severity"] = "critical"
    snapshot = run.snapshot()
    snapshot["evidence"].clear()
    assert run.snapshot()["findings"][0]["severity"] == "high"
    assert len(run.snapshot()["evidence"]) == 2


def test_coverage_is_independently_recountable_and_stage_order_is_exact():
    report = run_demo()
    assert [e["stage"] for e in report["events"] if e["event"] == "stage"] == ["observe", "plan", "execute", "review", "report"]
    actions = [e for e in report["events"] if e["event"] == "action"]
    assert report["coverage"]["planned"] == len(report["plan"])
    for status in ("executed", "error", "skipped"):
        assert report["coverage"][status] == sum(e["status"] == status for e in actions)
    assert report["coverage"]["pending"] == 0
    assert report["finished"] is True


def test_pending_actions_prevent_normal_completion_and_abort_accounts_for_them():
    run, _ = make()
    run.observe(SIGNALS)
    run.advance("plan")
    run.plan("https://lab.example/")
    run.advance("execute")
    with pytest.raises(PolicyError):
        run.advance("review")
    report = run.abort("operator stopped tutorial")
    assert report["finished"]
    assert report["coverage"]["skipped"] == 2
    assert report["coverage"]["pending"] == 0
    with pytest.raises(PolicyError):
        run.execute("inspect_headers", "https://lab.example/")


def test_committed_demo_matches_fresh_run_and_is_repeatable():
    first = canonical_bytes(run_demo())
    assert first == canonical_bytes(run_demo())
    expected = Path(__file__).parents[1] / "harness" / "report.json"
    assert first == expected.read_bytes()


def test_explicit_zero_port_is_rejected():
    with pytest.raises(PolicyError):
        origin("https://lab.example:0/")


@pytest.mark.parametrize("url", ["https://lab.example/safe", "https://lab.example/?scope=narrow"])
def test_origin_declaration_does_not_silently_discard_path_restrictions(url):
    manifest, _ = inputs()
    manifest["authorization"]["origins"] = [url]
    with pytest.raises(PolicyError):
        make(manifest)


@pytest.mark.parametrize("operation", ["execute", "skip"])
def test_reverse_plan_order_cannot_choose_budget_winner(operation):
    manifest, _ = inputs()
    manifest["max_actions"] = 1
    run, calls = make(manifest)
    run.observe(SIGNALS)
    run.advance("plan")
    plan = run.plan("https://lab.example/")
    run.advance("execute")
    args = [plan[1]["tool"], plan[1]["url"]]
    if operation == "skip":
        args.append("model skipped the better tool")
    with pytest.raises(PolicyError):
        getattr(run, operation)(*args)
    assert calls == []


def test_proof_rule_cannot_raise_an_unrelated_finding_kind():
    run, _ = make()
    rows = execute_all(run)
    eid = rows[1]["evidence_id"]
    with pytest.raises(PolicyError):
        run.propose_finding(finding_id="f", title="Wrong kind", kind="header", severity="critical", evidence_id=eid, quote="synthetic")
    assert run.snapshot()["findings"] == []


def test_finite_operands_cannot_produce_nonfinite_score():
    manifest, _ = inputs()
    manifest["tools"][0].update(weight=1e308, cost=1e-308)
    with pytest.raises(PolicyError):
        make(manifest)


@pytest.mark.parametrize("change", [{"status": 999}, {"marker": "NOT_IN_FIXTURE"}])
def test_proof_rule_needs_valid_status_and_positive_fixture(change):
    manifest, _ = inputs()
    manifest["proof_rules"][0].update(change)
    with pytest.raises(PolicyError):
        make(manifest)


def test_measured_source_is_text_and_boolean_requirement_is_typed():
    manifest, _ = inputs()
    manifest["profile"]["has_http"]["source"] = True
    with pytest.raises(PolicyError):
        make(manifest)
    manifest["profile"]["has_http"].update(source="fixture", value=1)
    run, calls = make(manifest)
    execute_all(run)
    assert calls == []
    assert run.snapshot()["coverage"]["planned"] == 0


def test_curriculum_decisions_are_complete_and_name_real_adversarial_tests():
    import ast
    root = Path(__file__).parents[1]
    curriculum = json.loads((root / "harness/curriculum.json").read_text())
    assert [d["id"] for d in curriculum["decisions"]] == list(range(11))
    assert [s for phase in curriculum["phases"] for s in phase["steps"]] == list(range(11))
    assert curriculum["laws"][-1] == "Report what you didn't do."
    tests = {n.name for n in ast.walk(ast.parse(Path(__file__).read_text())) if isinstance(n, ast.FunctionDef)}
    assert all(d["test"] in tests for d in curriculum["decisions"])


def test_historical_store_coverage_is_recounted_from_store_records(monkeypatch):
    import asyncio
    from walkthrough import run as historical
    captured = []
    original = historical.WalkthroughStore
    class ObservedStore(original):
        def __init__(self):
            super().__init__()
            captured.append(self)
    monkeypatch.setattr(historical, "WalkthroughStore", ObservedStore)
    artifacts = asyncio.run(historical.run_all(Path(__file__).parents[1]))
    store = captured[0]
    assert artifacts["10-gate.json"]["store_coverage"] == {
        "findings": len(store.findings), "tools_run": len(store.tool_executions)}


def test_unknown_finding_kind_cannot_bypass_governance():
    run, _ = make()
    rows = execute_all(run)
    with pytest.raises(PolicyError):
        run.propose_finding(finding_id="f", title="Invented kind", kind="invented", severity="critical", evidence_id=rows[0]["evidence_id"], quote="Access-Control-Allow-Origin: *")
    assert run.snapshot()["findings"] == []


def test_observation_values_follow_fixture_changes():
    from harness.demo import observations
    _, fixtures = inputs()
    _, baseline = observations(fixtures)
    fixtures["headers"] = {"status": 503, "body": '<form><input name="q"><script> WAF_BLOCKED'}
    profile, changed = observations(fixtures)
    assert changed["total_responses"] == 2
    assert changed["error_rate"] == .5
    assert changed["pages_crawled"] == 1
    assert changed["forms_found"] == changed["scripts_found"] == changed["parameters_found"] == 1
    assert changed["waf_detected"] is True
    assert changed != baseline
    assert profile["source"] == "fixtures:headers,marker"
