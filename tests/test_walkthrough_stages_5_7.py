import asyncio
import pathlib

import pytest

from core.http_evidence import capture_request, capture_response
from core.severity_governor import evidence_grade
from walkthrough import run as runner
from walkthrough.fixture_schema import load_fixture

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "walkthrough" / "fixtures"

_STAGES = ("evidence", "critic", "write")
_ARTIFACTS = ("05-evidence.json", "06-critic.json", "07-findings.json",
              "08-governance.json")

# The only `expected` entry no observable answers. The evidence-ceiling fixture's `note` is
# guidance addressed to whoever writes the driver rather than an outcome of running it, while
# the no-public-rule fixture's `note` IS an outcome and is asserted in full by
# test_at_least_one_finding_is_downgraded_by_the_write_path.
_UNVERIFIABLE = frozenset({"note"})


def _exchange_fixtures():
    """Every committed exchange fixture as (filename, object), read off disk."""
    out = []
    for path in sorted(FIXTURES.glob("*.json")):
        obj = load_fixture(path)
        if obj.get("kind") == "exchange":
            out.append((path.name, obj))
    return out


def _fixture_for_rule(rule_id):
    """The one committed fixture whose `provenance.rule_id` is `rule_id`, as (name, object)."""
    found = [(name, obj) for name, obj in _exchange_fixtures()
             if obj.get("provenance", {}).get("rule_id") == rule_id]
    assert len(found) == 1, f"expected exactly one {rule_id} fixture, found {found}"
    return found[0]


def _by_source(entries):
    return {entry["source"]: entry for entry in entries}


def _observed(finding, entry):
    """What the run produced for one fixture, keyed the way that fixture's contract is keyed.

    `original_severity` is read off the governance entry with no fallback, and the fallback
    that used to sit here is why: it substituted the stored finding's own severity where the
    governor wrote no record, and the one fixture that reaches that branch is the one whose
    stored grade equals its entered grade, so the substituted value and the published one were
    the same string and the fallback could not tell a driver that published the entering
    severity from one that published nothing. Every key here is read off the record or off the
    stored finding, never off the contract being compared against.
    """
    raw = finding.get("raw_data") or {}
    return {
        "attach_exchange_evidence": "evidence" in raw,
        "evidence_grade": evidence_grade(finding),
        "final_severity": entry.get("final_severity"),
        "original_severity": entry["original_severity"],
        "rules_fired": finding.get("rules_fired") or [],
        "false_positive": bool(finding.get("false_positive")),
        "environment": entry.get("environment"),
        "governance_record": finding.get("governance_record"),
    }


def test_the_three_stages_emit_their_artifacts_and_record_that_they_ran():
    out = asyncio.run(runner.run_all(ROOT))
    for name in _ARTIFACTS:
        assert name in out, f"{name} missing"
    for stage in _STAGES:
        assert out.stage_ran(stage), f"{stage} did not record itself"


def test_evidence_is_captured_through_the_real_capture_functions():
    """Every exchange is captured, and a response snippet is never published as `body`.

    Each captured dict is compared against `capture_request` and `capture_response` called
    directly on the same fixture, so a driver that hand-built an exchange, or reshaped what
    came back, fails here instead of publishing a capture the module never produced.
    `capture_response` returns `body_snippet` beside `body_length` and no `body` key at all,
    so an artifact carrying the snippet under `body` would tell a reader the whole response is
    there; that key is asserted absent.
    """
    out = asyncio.run(runner.run_all(ROOT))
    exchanges = out["05-evidence.json"]["exchanges"]
    assert exchanges and all("request" in e and "response" in e for e in exchanges)
    fixtures = dict(_exchange_fixtures())
    assert [e["source"] for e in exchanges] == sorted(fixtures)
    for entry in exchanges:
        request = fixtures[entry["source"]]["request"]
        response = fixtures[entry["source"]]["response"]
        assert entry["request"] == capture_request(
            method=request["method"], url=request["url"],
            headers=request.get("headers"), body=request.get("body")), entry["source"]
        assert entry["response"] == capture_response(
            status=response["status"], headers=response.get("headers"),
            body=response.get("body", ""), url=response.get("url")), entry["source"]
        assert "body" not in entry["response"], entry["response"]


def test_the_critic_drops_something_so_containment_is_visible():
    """A critic stage where nothing drops proves nothing.

    The insights fixture carries three or more entries precisely so the forced-keep floor
    does not mask containment; measured on the shipped module, three insights keep one and
    drop two.
    """
    out = asyncio.run(runner.run_all(ROOT))
    critic = out["06-critic.json"]
    assert critic["dropped_count"] >= 1, "no insight dropped: containment is not demonstrated"
    assert critic["kept_count"] >= 1
    assert critic["kept_count"] == len(critic["kept"])
    assert critic["dropped_count"] == len(critic["dropped"])


def test_critic_scores_are_serialised_with_string_keys_and_say_so():
    """`score_grounded` keys `scores` by `int`, and the artifact stringifies those keys itself.

    JSON has no integer key, so leaving the conversion to the writer keeps the written bytes
    right while the in-memory artifact disagrees with them -- the same artifact carrying one
    type in memory and another on disk, with nothing to catch it. `scores_key_type_in_python`
    is derived from the keys the module
    returned rather than spelled out here, so a reader comparing the artifact against a live
    Python call must not read those string keys back as the module's own.
    """
    out = asyncio.run(runner.run_all(ROOT))
    critic = out["06-critic.json"]
    assert critic["scores_key_type_in_python"] == "int"
    assert critic["scores"] and all(isinstance(k, str) for k in critic["scores"])


def test_the_critic_gate_the_driver_ran_is_not_read_out_of_the_fixture():
    """Two independent copies of the grounding gate, so a drift between them is visible here.

    The driver holds the threshold and the phase it runs the critic under; the insights
    fixture declares the same pair in its own `expected` block. Reading either out of the
    other would make an edit to one a coordinated edit that nothing checks, which is why the
    artifact records what the driver ran and this compares it against the fixture on disk.
    """
    out = asyncio.run(runner.run_all(ROOT))
    critic = out["06-critic.json"]
    expected = load_fixture(FIXTURES / "08-critic-containment.json")["expected"]
    assert critic["threshold"] == expected["threshold"]
    assert critic["phase"] == expected["phase"]
    assert critic["kept_count"] == expected["kept_count"]
    assert critic["dropped_count"] == expected["dropped_count"]


def test_at_least_one_finding_is_downgraded_by_the_write_path():
    """The governance artifact must show a grade actually moving.

    The governor's record uses `original_severity` and `final_severity` (measured), and it is
    ABSENT entirely when nothing acted -- a strong-evidence `sqli` finding matches no public
    rule -- so a finding with no record is a legitimate outcome and is recorded as such rather
    than dropped. The note on those entries is compared against the fixture's own `expected`
    note in full, not by substring, so the two spellings cannot drift apart.
    """
    out = asyncio.run(runner.run_all(ROOT))
    records = out["08-governance.json"]["records"]
    moved = [r for r in records
             if r.get("original_severity") != r.get("final_severity")
             and r.get("final_severity") is not None]
    assert moved, "no finding changed grade: the write path is not governing"
    ungoverned = [r for r in records if r.get("final_severity") is None]
    assert all("no rule matched" in r.get("note", "") for r in ungoverned)

    name, fixture = _fixture_for_rule("no-public-rule-matches")
    assert [r["source"] for r in ungoverned] == [name]
    assert ungoverned[0]["note"] == fixture["expected"]["note"]


def test_the_governance_artifact_accounts_for_every_stored_finding():
    out = asyncio.run(runner.run_all(ROOT))
    findings = out["07-findings.json"]["findings"]
    records = out["08-governance.json"]["records"]
    assert len(findings) == len(_exchange_fixtures())
    assert [r["source"] for r in records] == [f["raw_data"]["source_fixture"] for f in findings]
    assert [r["finding_id"] for r in records] == [f["id"] for f in findings]


def test_the_evidence_ceiling_fired_on_the_fixture_that_cannot_prevent_a_strong_grade():
    """The thin-evidence fixture is the one that can be silenced without failing anything.

    The governor reads any non-empty dict as content, so a driver that attaches this fixture's
    two-key envelope wholesale grades it `strong`, the ceiling never fires, the severity stays
    `critical`, and the fixture demonstrates the opposite of its purpose on a green run.
    Asserting that its finding exists, or that the run is green, catches none of that. So the
    grade, the rule id, the ceiling flag and the severity that came out are each asserted, and
    the fixture is located by its `provenance.rule_id` rather than by filename so a rename
    cannot quietly point this at nothing.
    """
    name, _fixture = _fixture_for_rule("evidence-ceiling")
    out = asyncio.run(runner.run_all(ROOT))
    entry = _by_source(out["08-governance.json"]["records"])[name]
    assert entry["evidence_grade"] == "thin", entry
    assert "evidence-ceiling" in entry["rules_fired"], entry
    assert entry["ceiling_enforced"] is True, entry
    assert entry["original_severity"] == "critical", entry
    assert entry["final_severity"] == "medium", entry
    stored = [f for f in out["07-findings.json"]["findings"] if f["id"] == entry["finding_id"]]
    assert [f["severity"] for f in stored] == ["medium"], stored
    assert [evidence_grade(f) for f in stored] == ["thin"], stored


def test_every_fixture_reproduces_the_contract_in_its_own_expected_block():
    """Each fixture's whole `expected` block against the run, in one comparison per fixture.

    An `expected` key no observable answers fails rather than being skipped, so a contract a
    later fixture widens cannot go unchecked here. The severity the governor RECORDS as having
    entered is what `original_severity` is compared against: a driver that hardcoded the
    entering severity satisfied every other key in this block, which is measured rather than
    supposed -- it is how that hole was found.
    """
    out = asyncio.run(runner.run_all(ROOT))
    findings = {f["id"]: f for f in out["07-findings.json"]["findings"]}
    entries = _by_source(out["08-governance.json"]["records"])
    fixtures = _exchange_fixtures()
    assert len(fixtures) >= 6, fixtures

    for name, fixture in fixtures:
        entry = entries[name]
        observed = _observed(findings[entry["finding_id"]], entry)
        contract = {key: value for key, value in fixture["expected"].items()
                    if key not in _UNVERIFIABLE}
        assert contract, name
        missing = sorted(set(contract) - set(observed))
        assert not missing, f"{name}: no observable for expected.{missing}"
        assert {key: observed[key] for key in contract} == contract, name


def test_a_fixture_that_does_not_declare_the_attach_flag_is_refused():
    """A flag read with a default silently caps, or silently fails to cap, a whole finding.

    Defaulted to false the finding grades `thin` and the evidence ceiling fires in place of
    the rule the fixture exists to exercise; defaulted to true the ceiling never fires. Both
    halves look correct in isolation. A string is refused for the same reason a missing key
    is: `"false"` is truthy, so the two spellings of the mistake fail in opposite directions.
    The accepting direction is asserted beside them, because a guard that refused everything
    would satisfy the refusals alone.
    """
    assert runner._attach_flag("99-synthetic-not-committed.json",
                               {"expected": {"attach_exchange_evidence": True}}) is True
    assert runner._attach_flag("99-synthetic-not-committed.json",
                               {"expected": {"attach_exchange_evidence": False}}) is False
    for broken in ({}, {"attach_exchange_evidence": "false"},
                   {"attach_exchange_evidence": None}):
        with pytest.raises(RuntimeError, match="attach_exchange_evidence"):
            runner._attach_flag("99-synthetic-not-committed.json", {"expected": broken})


def test_a_count_of_insights_fixtures_other_than_one_is_refused(tmp_path):
    """Zero and two are refused, and the accepting middle is asserted so the refusal is narrow.

    Without the one-fixture direction this pair is satisfied by a helper that raises on
    everything, which would take the critic stage out of every run.
    """
    fixtures = tmp_path / "walkthrough" / "fixtures"
    fixtures.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="exactly one insights fixture"):
        runner._insights_fixture(tmp_path)

    source = (FIXTURES / "08-critic-containment.json").read_text(encoding="utf-8")
    (fixtures / "08-critic-containment.json").write_text(source, encoding="utf-8")
    name, obj = runner._insights_fixture(tmp_path)
    assert name == "08-critic-containment.json" and obj["kind"] == "insights"

    (fixtures / "09-second-insights.json").write_text(source, encoding="utf-8")
    with pytest.raises(RuntimeError, match="exactly one insights fixture"):
        runner._insights_fixture(tmp_path)
