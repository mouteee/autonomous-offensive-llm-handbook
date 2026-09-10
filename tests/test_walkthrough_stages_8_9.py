import asyncio
import json
import pathlib
import subprocess
import sys

import pytest

from core.fingerprint import TargetProfile
from walkthrough import run as runner
from walkthrough.fixture_schema import load_fixture

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "walkthrough" / "fixtures"

# The status at or above which a response is errored, held here as a second copy -- one that
# catches less than a second copy sounds like it would, and the gap is measured rather than
# argued. No committed response carries a status of 400 or more, so every committed response
# is a non-error either side of any floor above 200, and moving the driver's own
# `_ERROR_STATUS_FLOOR` anywhere inside that range reddens nothing here and moves no committed
# byte. What this file does hold, measured by editing that constant alone: at 200 or under,
# test_every_gate_input_is_recounted_from_the_fixtures_it_is_counted_from and
# test_the_error_rate_fed_in_is_the_one_the_gate_will_record both redden; above 500 the second
# reddens alone. So the floor is pinned to the interval above 200 up to and including 500 and
# not to the value below it. Only the lower bound belongs to this copy, which is why moving
# BOTH copies together inside the interval leaves the file green: the upper bound is held by
# the 0.33 written into test_the_error_rate_fed_in_is_the_one_the_gate_will_record, whose three
# synthetic responses are the only ones in the tree that an error floor can classify either
# way, and that number has no second copy anywhere.
_ERROR_STATUS = 400

_SEVEN_INPUTS = {"error_rate", "forms_found", "pages_crawled", "parameters_found",
                 "scripts_found", "total_responses", "waf_detected"}

# The order the consolidator reads when it picks a headline, held here as a second copy so a
# reordering in either place is visible rather than agreed.
_SEVERITY_ORDER = ("critical", "high", "medium", "low", "info")

# The one non-ASCII character the artifact set contains, and therefore the only thing in the
# tree that exercises `ensure_ascii=False`.
_MULTIPLICATION_SIGN = "×"


def test_the_two_stages_emit_their_artifacts_and_record_that_they_ran():
    """A dropped `await` is what this compares against, and `!= {}` would not see it.

    `consolidate_scan` is a coroutine function, so a driver that dropped the `await` would
    put a coroutine object under this key -- truthy, unequal to `{}`, and refused only much
    later when `json.dumps` reached it. The key set is compared instead, because `set()` over
    a coroutine raises rather than passing.
    """
    out = asyncio.run(runner.run_all(ROOT))
    assert "09-consolidation.json" in out and "10-gate.json" in out
    assert {"consolidate", "gate"} <= set(out["_stages"])
    assert set(out["09-consolidation.json"]) == {"groups", "per_host", "deduped", "headline"}


def test_the_consolidation_rollup_describes_this_run_s_own_surviving_findings():
    """An empty or borrowed record would satisfy the key-set check above.

    So the rollup is compared against the findings the write stage stored: the survivor count
    against `deduped`, and the headline against the highest severity among them, re-derived
    here from `_SEVERITY_ORDER` rather than read out of the record being checked.
    """
    out = asyncio.run(runner.run_all(ROOT))
    record = out["09-consolidation.json"]
    survivors = [f for f in out["07-findings.json"]["findings"]
                 if not f.get("false_positive")]
    assert survivors, "nothing survived the write stage: the rollup would count nothing"
    assert sum(record["deduped"].values()) == len(survivors)
    highest = next(s for s in _SEVERITY_ORDER
                   if any(f["severity"] == s for f in survivors))
    assert record["headline"] == highest


def test_a_consolidation_that_grouped_nothing_is_refused(monkeypatch):
    """`HARNESS_GOVERNANCE=0` turns the whole pass into a no-op that returns empty rollups.

    Nothing raises on that path -- `consolidate_scan` returns its zero record and writes
    nothing -- so the run would publish empty groups, an empty per-host map and an `info`
    headline as though they were this scan's answer. The accepting direction is asserted
    beside the refusal, because a guard widened to refuse everything satisfies the refusal
    alone.
    """
    monkeypatch.setenv("HARNESS_GOVERNANCE", "0")
    with pytest.raises(RuntimeError, match="grouped nothing"):
        asyncio.run(runner.run_all(ROOT))

    monkeypatch.delenv("HARNESS_GOVERNANCE")
    assert asyncio.run(runner.run_all(ROOT))["09-consolidation.json"]["groups"]


def test_the_gate_reads_the_seven_keys_it_documents():
    out = asyncio.run(runner.run_all(ROOT))
    assert set(out["10-gate.json"]["inputs"]) == _SEVEN_INPUTS


def test_the_gate_inputs_are_echoed_back_by_the_call_that_read_them():
    """The set above is a hand-written copy; this one is the module's own answer.

    `decide_gate_status` echoes the inputs it read under `evidence`, so a key renamed in
    `core/gate_check.py` leaves the hand-written set stale and green while the gate silently
    defaults the key nobody fed it. Comparing against the echo is what catches that.
    """
    out = asyncio.run(runner.run_all(ROOT))
    gate = out["10-gate.json"]
    assert set(gate["inputs"]) == set(gate["decision"]["evidence"])


def test_no_gate_input_is_taken_from_the_store_s_coverage():
    out = asyncio.run(runner.run_all(ROOT))
    gate = out["10-gate.json"]
    shared = sorted(set(gate["store_coverage"]) & set(gate["inputs"]))
    assert shared == []
    # The artifact states this on its own face, and the statement is checked here rather
    # than trusted: a reader who never opens the driver sees the empty list beside the two
    # blocks, so it has to be the intersection and not a constant.
    assert gate["inputs_also_named_by_store_coverage"] == shared


def test_the_gate_refuses_inputs_it_would_not_have_read_and_inputs_worth_nothing():
    """Both refusals, and the accepting middle that keeps them from refusing everything.

    A key the tree does not read is refused because the gate would default the one it wanted
    and answer over a value nobody supplied; an input dict equal to the defaults is refused
    because the status it produces is the status an empty dict produces, so the artifact
    would demonstrate nothing about the fixtures.
    """
    baseline = runner.decide_gate_status({})
    full = dict(baseline["evidence"], total_responses=7)

    decision, no_inputs = runner._gate_decision(full)
    assert decision["evidence"]["total_responses"] == 7
    # Compared whole and not by status: both statuses resolve to the answer over an empty
    # dict, so a second element that was really the decision over `full` would compare equal
    # on `status` alone and this line would assert nothing.
    assert no_inputs == baseline

    with pytest.raises(RuntimeError, match="never read"):
        runner._gate_decision(dict(full, pages_crawled_typo=1))
    with pytest.raises(RuntimeError, match="defaults"):
        runner._gate_decision(dict(baseline["evidence"]))


def test_main_writes_every_artifact_and_the_same_bytes_from_a_second_directory(tmp_path):
    """Two script-mode runs, each with its own output directory and its own working directory.

    Task 7 compares the committed bytes against a fresh run, so a value drawn from a clock, a
    random source, an absolute path or a filesystem-dependent iteration order fails there
    rather than here. Varying the working directory as well as the run is what makes the
    path-dependent clause above reachable at all: `run_all` resolves every path from its
    `root` argument, and a helper that reached for the working directory instead would come
    out identical across two runs made from the same directory.
    """
    first_dir, second_dir = tmp_path / "first", tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    for out_dir in (first_dir, second_dir):
        subprocess.run([sys.executable, str(ROOT / "walkthrough" / "run.py"),
                        "--out", str(out_dir)], check=True, cwd=str(out_dir))

    first = {p.name: p.read_bytes() for p in sorted(first_dir.iterdir())}
    second = {p.name: p.read_bytes() for p in sorted(second_dir.iterdir())}
    assert len(first) == 10, sorted(first)
    assert first == second, "a second run produced different bytes"


def test_the_writer_and_the_public_serialiser_are_one_implementation(tmp_path):
    """`_write` must not dump its own JSON, because the byte comparison re-does the same work.

    Whatever compares the committed files against a fresh run re-serialises these objects,
    so two hand-written `json.dumps` calls over one object drift on a flag or a separator and
    the comparison then fails on a correct tree -- the fastest way to get a check switched
    off. Dropping `ensure_ascii=False` from the writer alone is that drift, and it moves the
    bytes of exactly one artifact.
    """
    assert runner.main(["--out", str(tmp_path)]) == 0
    out = asyncio.run(runner.run_all(ROOT))
    for name, obj in out.items():
        if name.startswith("_"):
            continue
        assert (tmp_path / name).read_text(encoding="utf-8") == runner.serialize(obj), name


def test_the_one_non_ascii_character_is_written_raw_and_never_escaped(tmp_path):
    """`ensure_ascii=False` pinned on the written bytes, not on the call that wrote them.

    The test above compares the file against `serialize`, so an edit to `serialize` moves
    both sides of it and stays green; this reads the property off the file alone. The
    multiplication sign reaches the plan through the scheduler's own reason suffixes and is
    the only character above ASCII anywhere in the set, so it is also the only thing
    exercising the flag -- were it to leave those reasons, this fails and the flag goes back
    to being untested loudly rather than quietly.
    """
    assert runner.main(["--out", str(tmp_path)]) == 0
    plan = (tmp_path / "04-test-plan.json").read_text(encoding="utf-8")
    assert _MULTIPLICATION_SIGN in plan
    assert "\\u00d7" not in plan

    above_ascii = {ch for path in sorted(tmp_path.iterdir())
                   for ch in path.read_text(encoding="utf-8") if ord(ch) > 127}
    assert above_ascii == {_MULTIPLICATION_SIGN}, above_ascii


def _query_parameter_names(url):
    """Parameter names in `url`'s query, split by hand rather than through `parse_qs`.

    A second copy of `parse_qs` would agree with the driver about its own defaults --
    `keep_blank_values=False` drops `?id=` and contributes no name -- so the recount below
    would confirm a number it never checked. Splitting on `&` and taking the text before the
    first `=` keeps a valueless parameter, which is what makes the two implementations able
    to disagree.
    """
    query = url.partition("?")[2].partition("#")[0]
    return {pair.partition("=")[0] for pair in query.split("&") if pair.partition("=")[0]}


def _exchange_fixtures():
    """Every committed exchange fixture as (filename, object), read off disk."""
    out = []
    for path in sorted(FIXTURES.glob("*.json")):
        obj = load_fixture(path)
        if obj.get("kind") == "exchange":
            out.append((path.name, obj))
    return out


def test_every_gate_input_is_recounted_from_the_fixtures_it_is_counted_from():
    """Seven numbers reach committed data, and byte-freezing them is not checking them.

    The byte gate freezes these artifacts against a fresh run, so a count taken off the
    request URLs instead of the response URLs, or a body counted twice, is byte-stable and
    invisible to it: the wrong number is committed beside the code that produced it and the
    two agree forever. Every one is therefore recounted here off the fixture files, never
    through `_gate_inputs`, and `waf_detected` is compared against what the fingerprint
    artifact published rather than against the profile object the gate stage was handed.

    `error_rate` is compared against the rate the module itself would record for the recounted
    ratio, so this assertion carries no copy of the gate's rounding precision and holds on any
    fixture set.
    """
    out = asyncio.run(runner.run_all(ROOT))
    inputs = out["10-gate.json"]["inputs"]
    fixtures = _exchange_fixtures()
    assert fixtures, "no exchange fixtures: every assertion below would be vacuous"
    bodies = [obj["response"].get("body", "") for _name, obj in fixtures]

    assert inputs["total_responses"] == len(fixtures)
    assert inputs["pages_crawled"] == len(
        {obj["response"].get("url", "") for _name, obj in fixtures})
    assert inputs["forms_found"] == sum(body.lower().count("<form") for body in bodies)
    assert inputs["scripts_found"] == sum(body.lower().count("<script") for body in bodies)

    names = set()
    for _name, obj in fixtures:
        names |= _query_parameter_names(obj["request"]["url"])
    assert inputs["parameters_found"] == len(names)

    errored = [obj for _name, obj in fixtures
               if obj["response"]["status"] >= _ERROR_STATUS]
    ratio = len(errored) / len(fixtures)
    assert inputs["error_rate"] == runner.decide_gate_status(
        {"error_rate": ratio})["evidence"]["error_rate"]

    waf = out["01-fingerprint.json"]["profile_components"]["waf_status"]
    assert inputs["waf_detected"] is (waf != "nowaf")


def test_the_error_rate_fed_in_is_the_one_the_gate_will_record():
    """A rate the gate rounds must not be fed to it with more precision than it records.

    `decide_gate_status` writes `round(error_rate, 2)` into the `evidence` block a reader is
    invited to re-derive the branch from, so a caller feeding more precision publishes one
    number under `inputs.error_rate` and a different one under `decision.evidence.error_rate`,
    and the record no longer settles which side of the `error_rate > 0.8` test the call fell
    on. Every committed fixture answers 200 and gives 0.0 under either treatment, so the
    discrimination is built here on three synthetic responses, one of them a 500: the ratio
    does not terminate in decimal, and what the gate records is 0.33.
    """
    fixtures = [
        (f"9{index}-synthetic-not-committed.json",
         {"request": {"method": "GET", "url": f"https://shop.example.com/{index}"},
          "response": {"status": status, "url": f"https://shop.example.com/{index}",
                       "body": ""}})
        for index, status in enumerate((200, 200, 500))
    ]
    inputs = runner._gate_inputs(TargetProfile(), fixtures)
    assert inputs["error_rate"] == 0.33
    assert runner.decide_gate_status(inputs)["evidence"]["error_rate"] == inputs["error_rate"]


def test_a_query_parameter_with_no_value_is_still_counted():
    """`keep_blank_values=True` is not `parse_qs`'s default and no committed fixture reaches it.

    `parse_qs` drops `?id=` entirely, so without the flag a parameter discovered with no value
    goes uncounted while the driver's docstring names only the unread request bodies as the
    gap. Every committed URL carries a value, so the flag has no effect on the published number
    and could be removed with the whole suite green; this is what stops that.
    """
    fixtures = [("90-synthetic-not-committed.json", {
        "request": {"method": "GET", "url": "https://shop.example.com/q?id=&sort=asc"},
        "response": {"status": 200, "url": "https://shop.example.com/q", "body": ""}})]
    assert runner._gate_inputs(TargetProfile(), fixtures)["parameters_found"] == 2


def _unsorted_key_sites(obj, path="<root>"):
    """Every mapping inside `obj` whose keys are not in sorted order, as JSON-ish paths."""
    sites = []
    if isinstance(obj, dict):
        if list(obj) != sorted(obj):
            sites.append(path)
        for key, value in obj.items():
            sites.extend(_unsorted_key_sites(value, f"{path}.{key}"))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            sites.extend(_unsorted_key_sites(value, f"{path}[{index}]"))
    return sites


def test_every_mapping_in_every_written_file_has_its_keys_in_sorted_order(tmp_path):
    """`sort_keys=True` pinned on the written bytes, the way the sibling flag already is.

    The serialiser-identity test regenerates both sides of its comparison, so dropping
    `sort_keys=True` leaves it green; nothing that re-serialises these objects can catch the
    flag. Read off the file alone it is catchable, and cheaply: `json.loads` preserves the
    order the file carries, so a recursive walk sees construction order wherever the flag is
    not doing its work. Nested mappings are walked and not only the top level, because the
    ten artifacts carry mappings inside lists inside mappings and the deepest of those are
    where the driver's construction order is least likely to be alphabetical by accident.
    """
    assert runner.main(["--out", str(tmp_path)]) == 0
    written = sorted(tmp_path.iterdir())
    assert len(written) == 10, written
    unsorted = {}
    for path in written:
        sites = _unsorted_key_sites(json.loads(path.read_text(encoding="utf-8")))
        if sites:
            unsorted[path.name] = sites
    assert not unsorted, f"keys not in sorted order: {unsorted}"
