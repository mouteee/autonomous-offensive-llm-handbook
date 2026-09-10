"""The walkthrough driver: the shipped decision modules, run over committed fixtures.

Every stage calls a real `core/` module and records what came back. Nothing here makes a
request or asks a model, and the withheld `Fingerprinter.probe_*` methods are never called:
they raise in this repository, so a driver that reached one would fail the run rather than
quietly publish a default. The fields those probes would have settled are named in the
fingerprint artifact instead, per field, because all four of them exist on `TargetProfile`
with defaults that read like measurements. Two of those fields also have a passive writer,
so the fingerprint stage refuses to publish a name in both places at once: a field the
passive analysis measured is never also published as unreachable without a probe.

A stage appends its own name to `store.stages_run` as its last action, and `run_all` returns
that same list under the `_stages` key. There is one store and therefore one stage ledger: a
driver keeping a second list would give the run two records that can disagree, and "the
artifact came out non-empty" is not evidence that a stage ran, because an empty result can
be the correct answer.

The scope stage refuses to decide anything against a fail-open guard. `core/scope_guard.py`
names two such conditions -- `HARNESS_SCOPE_TRACKING=0`, and a guard with no base -- and
on either one every URL answers in-scope while the out-of-scope list cannot take that back.
Both are read before any URL is, so a run under either would publish an artifact in which
the URL chosen to be rejected is admitted. That is the same shape as `load_rules()`
answering with an empty list for a missing file, and it is answered the same way: raise,
naming which condition tripped.

Paths are resolved from the `root` handed to `run_all`, never from the working directory,
because the committed artifacts must come out identical from any directory a reader runs in.
"""
import argparse
import ast
import asyncio
import copy
import dataclasses
import json
import pathlib
import sys
from urllib.parse import parse_qs, urlsplit

# Run as a script rather than imported, `sys.path[0]` is this file's OWN directory --
# walkthrough/ -- and the working directory is never added to the path, so `import core`
# dies with ModuleNotFoundError even when the working directory IS the repository root.
# Measured all three ways: script from a foreign directory fails, script from the repository
# root fails identically, imported as a module is fine -- which is why a pytest-only proof
# would not catch it. On import `__package__` is "walkthrough", so this branch is skipped and
# the import-consistency sweep sees an unmodified path.
if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from core import fingerprint as fingerprint_module
from core.consolidator import consolidate_scan
from core.critic import score_grounded
from core.gate_check import decide_gate_status
from core.http_evidence import capture_request, capture_response
from core.scheduler import SmartScheduler
from core.scope_guard import ScopeGuard
from core.severity_governor import evidence_grade
from core.tool_recommender import ToolRecommender
from walkthrough.fixture_schema import load_fixture
from walkthrough.store import WalkthroughStore

_FIXTURES_DIRNAME = "fixtures"
_ARTIFACTS_DIRNAME = "artifacts"

# A URL under a reserved TLD that no fixture is served from, so the scope artifact carries a
# real rejection beside the parent-domain admission. Nothing is ever sent to it.
_OUT_OF_SCOPE_PROBE = "https://evil.invalid/"

# Each field, against the withheld probe that would have settled it. Checked by name against
# the shipped class before anything is published -- never called -- so a renamed probe fails
# the run instead of leaving a stale mapping inside a committed artifact.
_WITHHELD_PROBES = {
    "has_graphql": "probe_graphql",
    "has_websocket": "probe_websocket",
    "accepts_xml": "probe_xml_support",
    "error_verbosity": "probe_error_verbosity",
}

# The grounding gate the critic stage runs under. Held here rather than read out of the
# insights fixture's own `expected` block, so the fixture and the driver are two independent
# copies of the same pair and tests/test_walkthrough_stages_5_7.py can compare them.
_CRITIC_THRESHOLD = 0.55
_CRITIC_PHASE = "surface"

# What the governance artifact says about a finding the governor left alone. Kept as a single
# literal, and tests/test_walkthrough_stages_5_7.py compares it in full against the no-rule
# fixture's own `expected.note`, so this spelling and the fixture's cannot drift apart.
_NO_GOVERNANCE_NOTE = "no rule matched and no ceiling applied"

# The response status at or above which the gate stage counts a response as errored. Held
# here because core/gate_check.py defines no such threshold: the tree reads an `error_rate`
# its caller already computed, so the line behind that rate is the caller's to state, and
# this is where this caller states it.
_ERROR_STATUS_FLOOR = 400

# What a response carrying no `status` key is read as, defined here and nowhere else. This
# driver reads the same fixture shape twice -- once into the dicts `analyze_many` consumes,
# once into the gate's counted inputs -- and until this constant existed the two normalised a
# missing status differently, 200 on one path and 0 on the other, so one number the run
# publishes would have called the absence a success and the other a status no server sends.
# 200 and not 0 because `core/fingerprint.py`'s own `analyze_many` normalises a missing
# `status` to 200 itself: that function is the reader `_responses_of` feeds, so 200 is already
# the tree's answer for an absent status and a driver default of 0 would be a second answer
# that only the driver held. The pick is inert in the published `error_rate` -- both candidates
# sit below `_ERROR_STATUS_FLOOR`, so neither is counted as errored -- and no committed fixture
# reaches it, because `walkthrough/fixture_schema.py` makes `response.status` a required key
# and every committed exchange carries one. What changes is that there is one rule to read.
_MISSING_STATUS = 200


class Artifacts(dict):
    """Artifact name to object, plus the run's stage ledger under `_stages`."""

    def stage_ran(self, name):
        """Whether `name` appears in this run's stage ledger."""
        return name in self.get("_stages", ())


def _fixtures_dir(root):
    """The committed fixture directory under `root`."""
    return pathlib.Path(root) / "walkthrough" / _FIXTURES_DIRNAME


def _exchange_fixtures(root):
    """Every committed `exchange` fixture as (filename, object), in filename order.

    The `insights` fixture is a later stage's input and is left alone here. Filename order
    and never directory order, because the first fixture is load-bearing: it sets the
    profile's `target_url` and the scope stage's target, so the committed bytes move when
    this order does.
    """
    out = []
    for path in sorted(_fixtures_dir(root).glob("*.json")):
        obj = load_fixture(path)
        if obj.get("kind") == "exchange":
            out.append((path.name, obj))
    return out


def _responses_of(fixtures):
    """The response dicts for `analyze_many`, keyed the way it reads them."""
    return [
        {
            "body": obj["response"].get("body", ""),
            "cookies": obj["response"].get("cookies", {}),
            "headers": obj["response"].get("headers", {}),
            "status": obj["response"].get("status", _MISSING_STATUS),
            "url": obj["response"].get("url", ""),
        }
        for _name, obj in fixtures
    ]


def _insights_fixture(root):
    """The committed `insights` fixture as (filename, object). Any count but one is refused.

    With two committed, `found[0]` takes whichever one filename order put first and the run
    stays green over a different artifact, so the choice would never surface. With none it
    raises `IndexError` out of a helper naming neither the fixture kind nor the directory.
    The refusal covers both directions and names the count it found.
    """
    found = []
    for path in sorted(_fixtures_dir(root).glob("*.json")):
        obj = load_fixture(path)
        if obj.get("kind") == "insights":
            found.append((path.name, obj))
    if len(found) != 1:
        raise RuntimeError(
            f"the critic stage needs exactly one insights fixture under "
            f"{_fixtures_dir(root)}; found {[name for name, _obj in found]}"
        )
    return found[0]


def _attach_flag(name, fixture):
    """Whether this fixture's captured exchange is attached to the finding built from it.

    Declared per fixture as `expected.attach_exchange_evidence`, and read rather than
    defaulted, because this flag settles the evidence grade and the grade settles the
    ceiling: `evidence_grade` grades `strong` on a request and a response together, so an
    attached exchange caps nothing while a withheld one caps the finding at `medium`. A
    fixture that declared nothing would silently take whichever branch a default named, and
    the run would then publish a governance artifact its own `expected` block contradicts --
    which is why an absent or non-boolean declaration is refused here instead.
    """
    flag = (fixture.get("expected") or {}).get("attach_exchange_evidence")
    if not isinstance(flag, bool):
        raise RuntimeError(
            f"{name} does not declare expected.attach_exchange_evidence as a boolean "
            f"(found {flag!r}); that flag decides the evidence grade, so there is no safe "
            f"default for it"
        )
    return flag


def _passive_writers(field_names, source=None):
    """Which `Fingerprinter` methods assign each of `field_names`, from the module's source.

    A hand-written list of passive writers goes stale the first time `core/fingerprint.py`
    grows one, and the artifact would then publish a fact that nothing checks. This parses
    the shipped module instead and reports the enclosing function of every
    `<something>.<field> = ...` assignment, so a writer added, removed or renamed moves the
    artifact. An empty list means the field's only writer would be the withheld probe, which
    is what makes the fingerprint artifact's per-field distinction a measurement rather than
    a restatement of this docstring.
    """
    path = pathlib.Path(source or fingerprint_module.__file__)
    writers = {name: set() for name in field_names}
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Assign):
                continue
            for target in inner.targets:
                if isinstance(target, ast.Attribute) and target.attr in writers:
                    writers[target.attr].add(node.name)
    return {name: sorted(found) for name, found in writers.items()}


def _require_live_guard(guard):
    """Refuse a fail-open guard: a disabled or an unseeded one admits every URL.

    Both conditions are read inside `is_in_scope` before the URL is, so neither can be
    undone by the out-of-scope list, and a run under either would publish an artifact in
    which the URL chosen to be rejected is admitted. The message names which condition
    tripped, because the two fixes are different ones: unset `HARNESS_SCOPE_TRACKING`, or
    seed the guard with a target.
    """
    if not guard.enabled:
        raise RuntimeError(
            "the scope guard is disabled (HARNESS_SCOPE_TRACKING=0), so every URL answers "
            "in-scope and the out-of-scope list cannot take that back"
        )
    if not guard.base:
        raise RuntimeError(
            "the scope guard is unseeded (it has no base), so every URL answers in-scope "
            "and the out-of-scope list cannot take that back"
        )


def _stage_fingerprint(store, fixtures):
    """Stage `fingerprint`: the passive profile, plus the per-field withheld-probe record."""
    profile = fingerprint_module.Fingerprinter().analyze_many(_responses_of(fixtures))
    default = dataclasses.asdict(fingerprint_module.TargetProfile())
    measured = dataclasses.asdict(profile)
    writers = _passive_writers(list(_WITHHELD_PROBES))

    withheld = {}
    for field, probe in _WITHHELD_PROBES.items():
        if not hasattr(fingerprint_module.Fingerprinter, probe):
            raise RuntimeError(
                f"{probe} is not a member of Fingerprinter any more, so the field it would "
                f"have settled ({field}) cannot be named against it"
            )
        if field not in measured:
            raise RuntimeError(f"{field} is not a member of TargetProfile any more")
        withheld[field] = {
            "probe": probe,
            "published_value": measured[field],
            "passive_writers": writers[field],
        }

    populated = {k: v for k, v in sorted(measured.items()) if v != default[k]}
    # The mirror of the defect this artifact exists to expose. The block above names a field
    # as unreachable without a live probe; two of those fields also have a passive writer, so
    # a fixture body that reaches one would put the same name in both places at once and
    # publish a measurement as a non-measurement. Nothing else would notice, because both
    # halves would be individually correct.
    collided = sorted(set(withheld) & set(populated))
    if collided:
        raise RuntimeError(
            f"the passive analysis measured {', '.join(collided)}, so naming it unreachable "
            f"without a live probe is false; a fixture body now reaches the passive writer "
            f"and this stage has to publish the measurement instead"
        )

    artifact = {
        "fixtures_fingerprinted": [name for name, _obj in fixtures],
        "profile_hash": profile.profile_hash(),
        "profile_components": profile.profile_components(),
        "populated_fields": populated,
        # The keys of the block below, never a second list of the same names, so the
        # summary and the per-field detail cannot disagree.
        "unreachable_without_live_probes": list(withheld),
        "withheld_probe_fields": withheld,
    }
    store.stages_run.append("fingerprint")
    return profile, artifact


def _stage_scope(store, fixtures):
    """Stage `scope`: a decision per fixture URL, the registrable parent, and the probe."""
    target = fixtures[0][1]["request"]["url"]
    guard = ScopeGuard(target=target)
    _require_live_guard(guard)

    parent = f"https://{guard.base}/"
    decisions = [
        {"role": "fixture", "source": name, "url": obj["request"]["url"],
         "in_scope": guard.is_in_scope(obj["request"]["url"])}
        for name, obj in fixtures
    ]
    decisions.append({"role": "registrable_parent", "source": "guard.base", "url": parent,
                      "in_scope": guard.is_in_scope(parent)})
    decisions.append({"role": "deliberate_out_of_scope", "source": "_OUT_OF_SCOPE_PROBE",
                      "url": _OUT_OF_SCOPE_PROBE,
                      "in_scope": guard.is_in_scope(_OUT_OF_SCOPE_PROBE)})

    admitted = [d["in_scope"] for d in decisions if d["role"] == "registrable_parent"]
    artifact = {
        "target": target,
        "registrable_base": guard.base,
        "guard_enabled": guard.enabled,
        "guard_seeded": bool(guard.base),
        "decisions": decisions,
        # The guard's own answer, not a constant: change the guard and this moves.
        "known_parent_domain_admission": admitted == [True],
    }
    store.stages_run.append("scope")
    return artifact


def _stage_recommend(store, profile):
    """Stage `recommend`: the recommender's triples, each with the tier its score lands in."""
    recommender = ToolRecommender()
    recommendations = recommender.recommend(profile)
    artifact = {
        "profile_hash": profile.profile_hash(),
        "recommendations": [
            {"tool": tool, "score": score, "reason": reason, "tier": recommender.tier(score)}
            for tool, score, reason in recommendations
        ],
    }
    store.stages_run.append("recommend")
    return recommendations, artifact


def _stage_schedule(store, profile, recommendations):
    """Stage `schedule`: the recommended order after the scheduler's contextual adjustment."""
    scheduler = SmartScheduler(stats_file=None)
    scheduler.set_profile(profile.profile_hash())
    adjusted = scheduler.adjust(recommendations)
    artifact = {
        "profile_hash": profile.profile_hash(),
        # Read off the scheduler rather than out of the environment a second time. Measured,
        # and stated no wider than it was measured: with HARNESS_SCHEDULER_ENABLED=0 every
        # score below changes and every reason loses its adjustment suffix, while the ranking
        # is unchanged -- so this flag moves the numbers in this artifact, and an ambient
        # override would otherwise be invisible in them. HARNESS_AGGRESSION_LEVEL is NOT
        # recorded beside it: with stats_file=None and no record() call it changes nothing
        # here -- the adjusted list comes out identical, tool for tool, score for score,
        # reason for reason -- so a setting with no effect on these bytes has no place in
        # them. There is no public accessor, which is the only reason this is a private read.
        "scheduler_enabled": scheduler._scheduler_enabled,
        "adjusted_order": [
            {"tool": tool, "score": score, "reason": reason}
            for tool, score, reason in adjusted
        ],
    }
    store.stages_run.append("schedule")
    return artifact


def _stage_evidence(store, fixtures):
    """Stage `evidence`: `capture_request` and `capture_response` over each exchange fixture."""
    exchanges = []
    for name, obj in fixtures:
        request, response = obj["request"], obj["response"]
        exchanges.append({
            "source": name,
            # Read once, here, and consumed by the write stage from this same record, so the
            # capture and the finding built from it cannot disagree about the flag.
            "attached_to_finding": _attach_flag(name, obj),
            "request": capture_request(
                method=request["method"], url=request["url"],
                headers=request.get("headers"), body=request.get("body")),
            "response": capture_response(
                status=response["status"], headers=response.get("headers"),
                body=response.get("body", ""), url=response.get("url")),
        })
    store.stages_run.append("evidence")
    return exchanges, {"exchanges": exchanges}


def _stage_critic(store, insights_fixture):
    """Stage `critic`: the grounding split, and the key type the artifact had to convert.

    `score_grounded` keys `scores` by the insight's position as an `int`, and JSON has no
    integer key, so writing the artifact would silently restate those keys as strings. They
    are converted here and the type they were converted from is published beside them,
    measured off the returned mapping rather than asserted, so a reader comparing the artifact
    against a live call is not misled into reading string keys back into Python.

    Two conditions are refused, and only the first of them is reachable from the shipped
    module. An EMPTY mapping means the critic scored nothing -- `score_grounded` returns empty
    lists and an empty `scores` for an empty insights list -- which is the vacuous critic stage
    this whole artifact exists to rule out, and it is refused under its own name rather than as
    a missing type. A mapping whose keys are not all one type is refused separately, because
    then no single type name describes it; `core/critic.py` keys `scores` off `enumerate`, so
    nothing short of a monkeypatch reaches that one, and it is kept because the published type
    name is derived from those keys and a mixed mapping would make it a false one.
    """
    name, fixture = insights_fixture
    result = score_grounded(fixture["insights"], fixture["intel_context"],
                            threshold=_CRITIC_THRESHOLD, phase=_CRITIC_PHASE)
    scores = result["scores"]
    if not scores:
        raise RuntimeError(
            f"score_grounded scored no insights from {name}, so the critic stage would publish "
            f"a kept-and-dropped split of nothing at all"
        )
    key_types = sorted({type(key).__name__ for key in scores})
    if len(key_types) != 1:
        raise RuntimeError(
            f"score_grounded returned scores keyed by {key_types}, so the artifact cannot "
            f"name the type it converted from"
        )
    artifact = {
        "source": name,
        "threshold": _CRITIC_THRESHOLD,
        "phase": _CRITIC_PHASE,
        "kept_count": len(result["kept"]),
        "dropped_count": len(result["dropped"]),
        "kept": result["kept"],
        "dropped": result["dropped"],
        "scores": {str(key): scores[key] for key in sorted(scores)},
        "scores_key_type_in_python": key_types[0],
    }
    store.stages_run.append("critic")
    return artifact


def _finding_from(name, fixture, exchange):
    """One finding built from a fixture's declared finding, its provenance and its capture."""
    declared = fixture["finding"]
    raw_data = {
        "source_fixture": name,
        "rule_id": fixture["provenance"]["rule_id"],
    }
    if exchange["attached_to_finding"]:
        # Deep-copied, and the reason is narrower than it looks: `raw_data` and this evidence
        # dict are both built fresh per finding, so the only objects a plain reference would
        # share are `capture_request`/`capture_response`'s own outputs -- which 05-evidence.json
        # publishes. Measured: without the copy, every attached request and response dict is
        # shared between the two artifacts, and both come out byte-identical anyway, because
        # the one write the governor
        # makes into an evidence dict sits on the branch where neither side is present and
        # cannot be reached with both attached. So this prevents a future writer from editing an
        # already-published artifact; it is not fixing a write that happens today.
        raw_data["evidence"] = {
            "request": copy.deepcopy(exchange["request"]),
            "response": copy.deepcopy(exchange["response"]),
        }
    return {
        "type": declared["type"],
        "title": declared["title"],
        "url": declared["url"],
        "severity": declared["severity"],
        "evidence": declared["evidence"],
        "raw_data": raw_data,
    }


async def _stage_write(store, fixtures, exchanges):
    """Stage `write`: one governed finding per exchange fixture, and one record per finding.

    The severity that enters is the fixture's own `finding.severity` and is never chosen here,
    so the artifact shows the governor moving a grade its fixture declared rather than one the
    driver picked to be movable. Where the governor acted, its `governance_record` is copied
    through as it stands. Where nothing moved there is no record at all, and that finding
    still gets an entry -- the severity that entered under `original_severity`, `final_severity`
    null, and the evidence grade that says why no ceiling applied -- rather than being dropped,
    because an artifact holding only the findings something happened to counts how many were
    governed while reading as a count of how many there are.

    The entering severity is PUBLISHED on that entry rather than left to the reader, and the
    reason is a discrimination and not tidiness: a governance entry that states only its
    outcome makes a reader recover the input from the stored finding, and on this branch the
    stored grade equals the entered one, so any comparison built that way agrees with itself
    whatever the driver did. The key is written from the finding the store holds, so the two
    published artifacts state the same grade twice and can disagree.
    """
    by_source = {exchange["source"]: exchange for exchange in exchanges}
    for name, fixture in fixtures:
        await store.add_finding(_finding_from(name, fixture, by_source[name]))

    records = []
    for finding in store.findings:
        entry = {"source": finding["raw_data"]["source_fixture"], "finding_id": finding["id"]}
        record = finding.get("governance_record")
        if record:
            entry.update(record)
        else:
            entry["original_severity"] = finding["severity"]
            entry["final_severity"] = None
            entry["evidence_grade"] = evidence_grade(finding)
            entry["note"] = _NO_GOVERNANCE_NOTE
        records.append(entry)
    store.stages_run.append("write")
    return {"findings": store.findings}, {"records": records}


async def _stage_consolidate(store):
    """Stage `consolidate`: the cross-host grouping pass, and a refusal when it grouped nothing.

    `HARNESS_GOVERNANCE=0` turns `consolidate_scan` into a no-op that returns empty groups,
    an empty per-host map and an `info` headline, and writes nothing to the store -- without
    raising. Publishing that record would state this scan's own rollups as empty, which is
    the same fail-open shape the scope stage refuses, so an empty grouping is refused here
    rather than emitted. The refusal reads the record and not the switch: a store holding no
    non-false-positive finding produces the identical empty record for a different reason,
    and both are a consolidation artifact that describes nothing.
    """
    record = await consolidate_scan(store)
    if not record.get("groups"):
        raise RuntimeError(
            "consolidate_scan grouped nothing, so this artifact would publish empty rollups "
            "as though they were this scan's answer; HARNESS_GOVERNANCE=0 returns exactly "
            "that record without raising, and so does a scan with no surviving finding"
        )
    store.stages_run.append("consolidate")
    return record


def _gate_inputs(profile, fixtures):
    """The seven inputs `decide_gate_status` reads, each measured off this run.

    `waf_detected` comes off the fingerprint profile the first stage published -- one of the
    three inputs the reference caller in `core/gate_check.py`'s own account also takes from an
    earlier stage's artifact rather than counting live. The other six are counted over the
    committed exchanges: responses at or above `_ERROR_STATUS_FLOOR` for the rate, distinct
    response URLs for the pages, distinct query parameter NAMES across the request URLs for
    the parameters, and `<form` / `<script` occurrences across the response bodies for the
    other two.

    The parameter count is narrower than its name suggests, and saying so matters because
    `decide_gate_status` never distinguishes a parameter nobody looked for from one that is
    not there: request bodies are not read here, so a field posted rather than queried is
    uncounted, and a zero in `parameters_found` and `forms_found` together is what its
    `no_surface` test matches. `keep_blank_values=True` is passed for the same reason and is
    not a default: `parse_qs` drops `?id=` entirely, so a parameter discovered with no value
    would go uncounted while the sentence above named only the bodies as the gap.

    The rate is rounded before it is fed rather than after, because `decide_gate_status`
    records `round(error_rate, 2)` and its record is meant to settle which branch fired. A
    caller feeding more precision publishes one number as its input and another in the
    record, and `error_rate > 0.8` can fall on either side of the two. The precision is read
    back out of the module rather than copied here, so a change there moves this.
    """
    responses = [obj["response"] for _name, obj in fixtures]
    bodies = [response.get("body", "").lower() for response in responses]
    errored = [response for response in responses
               if response.get("status", _MISSING_STATUS) >= _ERROR_STATUS_FLOOR]
    parameters = set()
    for _name, obj in fixtures:
        parameters.update(
            parse_qs(urlsplit(obj["request"]["url"]).query, keep_blank_values=True))
    inputs = {
        "error_rate": len(errored) / len(responses),
        "forms_found": sum(body.count("<form") for body in bodies),
        "pages_crawled": len({response.get("url", "") for response in responses}),
        "parameters_found": len(parameters),
        "scripts_found": sum(body.count("<script") for body in bodies),
        "total_responses": len(responses),
        "waf_detected": profile.waf_detected,
    }
    inputs["error_rate"] = decide_gate_status(inputs)["evidence"]["error_rate"]
    return inputs


def _gate_decision(inputs):
    """`decide_gate_status` over `inputs` and over nothing, refusing two vacuous calls.

    Returns both, because the second is what says whether the first carries any information:
    the tree is fail-open, so an empty dict already resolves to the most permissive outcome,
    and a status equal to that one was not earned by these inputs.

    The two refusals. An input dict equal to the defaults would produce exactly the answer an
    empty dict produces, so a derivation that came out at zero across the board -- reading a
    renamed attribute, counting an empty list -- would publish a permissive status and look
    like a gate that ran. And a key `decide_gate_status` does not read is refused by
    comparing against the `evidence` block it echoes rather than against a name written down
    here: a key renamed in `core/gate_check.py` leaves any hand-written list of the seven
    stale and green while the gate quietly defaults the input nobody fed it.
    """
    no_inputs = decide_gate_status({})
    if inputs == no_inputs["evidence"]:
        raise RuntimeError(
            "every gate input came out at the value decide_gate_status defaults it to, so "
            "the status would be the one an empty dict reaches and the artifact would say "
            "nothing about the fixtures"
        )
    decision = decide_gate_status(inputs)
    unread = sorted(set(inputs) - set(decision["evidence"]))
    unfed = sorted(set(decision["evidence"]) - set(inputs))
    if unread or unfed:
        raise RuntimeError(
            f"decide_gate_status never read {unread} and defaults {unfed} that this stage "
            f"did not feed it; the inputs fed in and the evidence echoed back have to carry "
            f"the same names or the decision is partly over values nobody supplied"
        )
    return decision, no_inputs


async def _stage_gate(store, profile, fixtures):
    """Stage `gate`: the inputs this run measured, the status they decide, and what decided it.

    The store's own coverage is published beside them and supplies none of them: it counts
    tools run and findings stored, neither of which is one of the seven, and
    tests/test_walkthrough_stages_8_9.py asserts the coverage keys and the input keys stay
    disjoint, so a store that grows a matching counter is not shadowed by the fixture-derived
    number.

    That disjointness is published too, as the intersection itself rather than as a sentence
    in this docstring. Adjacency in a JSON object reads as provenance, so a reader who never
    opens this file would be as entitled to take `store_coverage` for the inputs' source as
    not; an empty `inputs_also_named_by_store_coverage` says otherwise on the artifact's own
    face, and being the intersection rather than a constant it fills in if that ever changes.
    """
    inputs = _gate_inputs(profile, fixtures)
    decision, no_inputs = _gate_decision(inputs)
    coverage = await store.get_coverage()
    artifact = {
        "inputs": inputs,
        "decision": decision,
        "store_coverage": coverage,
        "inputs_also_named_by_store_coverage": sorted(set(coverage) & set(inputs)),
        # The gate's own answer over an empty dict, not a constant: it says whether these
        # inputs moved the status at all, and it moves when the fixtures do.
        "status_unchanged_by_these_inputs": decision["status"] == no_inputs["status"],
    }
    store.stages_run.append("gate")
    return artifact


async def run_all(root):
    """Run every stage over the committed fixtures under `root` and return the artifacts.

    One store is constructed here and its `stages_run` list is what comes back under
    `_stages`, so the record of what ran cannot disagree with itself. `root` fixes every path
    read, so the result never depends on the working directory.
    """
    root = pathlib.Path(root)
    store = WalkthroughStore()
    fixtures = _exchange_fixtures(root)
    if not fixtures:
        raise RuntimeError(f"no exchange fixtures under {_fixtures_dir(root)}")

    profile, fingerprint_artifact = _stage_fingerprint(store, fixtures)
    scope_artifact = _stage_scope(store, fixtures)
    recommendations, recommend_artifact = _stage_recommend(store, profile)
    schedule_artifact = _stage_schedule(store, profile, recommendations)
    exchanges, evidence_artifact = _stage_evidence(store, fixtures)
    critic_artifact = _stage_critic(store, _insights_fixture(root))
    findings_artifact, governance_artifact = await _stage_write(store, fixtures, exchanges)
    consolidation_artifact = await _stage_consolidate(store)
    gate_artifact = await _stage_gate(store, profile, fixtures)

    return Artifacts({
        "01-fingerprint.json": fingerprint_artifact,
        "02-scope.json": scope_artifact,
        "03-recommendations.json": recommend_artifact,
        "04-test-plan.json": schedule_artifact,
        "05-evidence.json": evidence_artifact,
        "06-critic.json": critic_artifact,
        "07-findings.json": findings_artifact,
        "08-governance.json": governance_artifact,
        "09-consolidation.json": consolidation_artifact,
        "10-gate.json": gate_artifact,
        "_stages": store.stages_run,
    })


def serialize(obj):
    """The artifact format, as one implementation: sorted keys, fixed indent, unescaped, newline.

    Anything that re-serialises these objects to compare them against the committed files
    calls this, rather than writing the expression out a second time. Two hand-written
    `json.dumps` calls over one object drift on a flag or a separator, and a comparison
    between them then fails on a correct tree -- which is the fastest way to get a check
    switched off.

    `ensure_ascii=False` is load-bearing and not cosmetic. The scheduler's reason suffixes
    carry a multiplication sign, so the plan artifact built from them comes out with
    different bytes under the default than under the flag, and no other artifact does. Sorted
    keys and a fixed indent are what make comparing any of these bytes possible at all:
    without them the comparison fails on dictionary ordering.
    """
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _write(out_dir, artifacts):
    """Write each artifact to its own file through `serialize`; return the paths written.

    Keys opening with an underscore are the run's own bookkeeping rather than artifacts, so
    `_stages` is never written as a file. The format is `serialize`'s and is deliberately not
    restated here, because a second copy of it is exactly what the byte gate cannot survive.
    """
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, obj in artifacts.items():
        if name.startswith("_"):
            continue
        path = out_dir / name
        path.write_text(serialize(obj), encoding="utf-8")
        written.append(path)
    return written


def main(argv=None):
    """Write the artifacts to `walkthrough/artifacts/`, or to the `--out` directory."""
    root = pathlib.Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Run the walkthrough and write its artifacts.")
    parser.add_argument(
        "--out", default=None,
        help="directory to write the artifacts into (default: walkthrough/artifacts)",
    )
    args = parser.parse_args(argv)
    out_dir = pathlib.Path(args.out) if args.out else root / "walkthrough" / _ARTIFACTS_DIRNAME
    for path in _write(out_dir, asyncio.run(run_all(root))):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
