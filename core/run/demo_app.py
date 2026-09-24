"""Lesson 16's runnable demo: one configured agent, setup to terminal report.

Run it from the repository root:

    python3 -m core.run.demo_app --out /tmp/app-demo.json

The committed copy is data/course/app-demo.json. Four segments: a complete
configured run (stages, gate, candidates, an observation-phase proposal the
policy refuses, controller-advised execution, an evidence-phase proposal
admitted from the new captures, findings with verdicts including a rejection
kept visible, cross-host consolidation and the gated finish); an interrupted
run resumed from its checkpoint and reconciled; a controller swap showing
identical eligibility under a different order; and three runs sharing one
memory store, where the first run's surviving findings become tactics the
second run retrieves, and a refutation keeps them out of the third.
"""

import argparse
import json
from pathlib import Path

from .app import Application
from .demo_lifecycle import FakeClock
from .proposals import FakeProvider


LAB = "https://lab.example"
BETA = "https://beta.lab.example"

# The fixture world: three surfaces on two hosts. The shared banner marker
# appears on both hosts, which is what gives consolidation a cross-host group.
WORLD = {
    "name": "assembly-lesson-fixtures",
    "surfaces": [
        {"surface_id": "landing", "url": f"{LAB}/",
         "response": {"status": 200,
                      "body": "<html>lab landing\nServer: lab\n"
                              "LAB_SHARED_BANNER</html>"}},
        {"surface_id": "login", "url": f"{LAB}/login",
         "response": {"status": 200,
                      "body": "<html><form action=/login>user</form></html>"}},
        {"surface_id": "beta", "url": f"{BETA}/",
         "response": {"status": 200,
                      "body": "<html>beta landing\nServer: lab\n"
                              "LAB_SHARED_BANNER</html>"}},
    ],
}


def adapters():
    from urllib.parse import urlsplit

    def echo(url):
        parts = urlsplit(url)
        if parts.path == "/health":
            return {"status": 200, "body": "healthy\n"}
        for surface in WORLD["surfaces"]:
            fixture = urlsplit(surface["url"])
            if fixture.hostname == parts.hostname and \
                    (fixture.path or "/") == (parts.path or "/"):
                return dict(surface["response"])
        raise LookupError(f"no fixture surface for {url}")

    return {"inspect_headers": echo, "form_probe": echo}


# The provider replies are authored: the first asks for a tool the policy
# knows against a host it does not authorize (terminal refusal, recorded);
# the second is admitted and adds a distinct health-path action to the plan.
PROPOSAL_REFUSED = json.dumps({
    "kind": "exfil-hypothesis", "surface": "landing_status",
    "evidence": ["landing_status"],
    "action": {"tool": "inspect_headers",
               "destination": "https://outside.example/",
               "arguments": {}}})
PROPOSAL_ADMITTED = json.dumps({
    "kind": "health-endpoint-disclosure", "surface": "landing_status",
    "evidence": ["landing_status", "landing_has_form"],
    "action": {"tool": "inspect_headers",
               "destination": f"{LAB}/health",
               "arguments": {}}})


def demo_verifier(packet):
    """A scripted verifier: rejects the form finding, accepts the banners.

    The rejection is deliberately WRONG -- the form is really in the capture --
    so the artifact carries a false rejection kept visible for a human to
    overrule, the failure mode lesson 8 gives equal billing.
    """
    if packet["finding"]["kind"] == "form-exposure":
        return json.dumps({"verdict": "reject",
                           "reason": "verifier judged the form a template "
                                     "artifact; a human should check this"})
    return json.dumps({"verdict": "accept",
                       "reason": "banner marker verified in the capture"})


def build_config(controller_name="priority", provider=None, verifier=None):
    return {
        "authorization": {"reference": "training-authorization-0016",
                          "origins": [f"{LAB}/", f"{BETA}/"]},
        "tools": [
            {"tool_id": "inspect_headers", "activity": "passive",
             "family": "fam-recon", "weight": 3.0, "cost": 1.0},
            {"tool_id": "form_probe", "activity": "active",
             "requires": {"has_form": True}, "family": "fam-inject",
             "weight": 4.0, "cost": 2.0},
        ],
        "adapters": adapters(),
        "budgets": {"actions": 12, "model_calls": 6,
                    "wall_seconds": 300, "cost": 60},
        "coverage": [["inspect_headers", f"{LAB}/"]],
        "controller": {"name": controller_name, "seed": 0, "learn": False},
        "provider": provider,
        "verifier": verifier,
        "finding_rules": [
            {"kind": "shared-banner", "title": "Shared lab banner disclosed",
             "severity": "medium", "marker": "LAB_SHARED_BANNER"},
            {"kind": "form-exposure", "title": "Login form reachable",
             "severity": "low", "marker": "<form"},
        ],
    }


def run_demo():
    # A fake clock everywhere: the committed artifact's wall accounting is
    # deterministic, and the real default (time.monotonic) stays the
    # application's ordinary behavior.
    # Segment one: the complete configured run.
    provider = FakeProvider([PROPOSAL_REFUSED, PROPOSAL_ADMITTED])
    app = Application(build_config(provider=provider, verifier=demo_verifier),
                      clock=FakeClock())
    report = app.run(WORLD)

    # Segment two: interrupt between dispatch and outcome, resume, reconcile.
    broken = Application(build_config(), clock=FakeClock())
    broken._start(WORLD)
    broken._observe(WORLD)
    _, ranked = broken._plan(WORLD)
    # The interruption happens mid-execution, so the run is advanced into its
    # executable stages first -- the dispatch door refuses anything earlier.
    broken.machine.advance("scanning")
    broken.machine.advance("active_testing")
    run_id = broken.recorder.run.run_id
    first = ranked[0]
    executed = broken.lifecycle.execute_with_retries(
        first.features["tool"], first.features["destination"])
    # The interruption: an action authorized and captured, its outcome never
    # recorded; and a second action authorized with no capture at all.
    lost_capture = broken.recorder.record("action", {
        "run_id": run_id, "tool": "inspect_headers",
        "destination": f"{LAB}/login"})
    broken.recorder.record("capture", {
        "run_id": run_id, "action_id": lost_capture["action_id"],
        "status": 200, "body": "<html><form action=/login>user</form></html>"})
    lost_entirely = broken.recorder.record("action", {
        "run_id": run_id, "tool": "form_probe",
        "destination": f"{LAB}/login"})
    checkpoint = broken.checkpoint()
    resumed, reconciliation = Application.resume(checkpoint, build_config(),
                                                 clock=FakeClock())
    finish = resumed.lifecycle.finish()
    interrupted = {
        "executed_before_interrupt": executed["status"],
        "interrupted_action_ids": [lost_capture["action_id"],
                                   lost_entirely["action_id"]],
        "reconciliation": reconciliation,
        "finish": finish["completed"],
        "coverage": finish["report"]["coverage"],
    }

    # Segment three: the controller swap. Same configuration otherwise; the
    # eligibility table must be identical and only the order may move.
    swap = {}
    for name in ("priority", "legacy"):
        run = Application(build_config(controller_name=name),
                          clock=FakeClock()).run(WORLD)
        swap[name] = {
            "eligible": run["candidate_table"]["eligible"],
            "execution_order": [d["candidate_id"] for d in run["decisions"]],
            "feedback_weights": sorted({d["feedback"]["weights"]
                                        for d in run["decisions"]}),
        }

    # Segment four: a completed run teaches the next one. Three runs share one
    # store: the first writes its surviving findings back as tactics, the
    # second retrieves them into its provider context, and after the operator
    # refutes them the third run's context excludes them while the write-back
    # declines to rehabilitate.
    from ..memory.store import MemoryStore

    store = MemoryStore(":memory:")

    def memory_config():
        config = build_config(
            provider=FakeProvider([PROPOSAL_REFUSED, PROPOSAL_ADMITTED]),
            verifier=demo_verifier)
        config["retrieval"] = {"enabled": True, "store": store, "records": [],
                               "query": "shared lab banner", "budget": 400,
                               "scope": {
                                   "engagement": "assembly-lesson-fixtures",
                                   "profile_hash":
                                       "fixture:assembly-lesson-fixtures"}}
        return config

    first = Application(memory_config(), clock=FakeClock(),
                        wall_clock=FakeClock()).run(WORLD)
    second = Application(memory_config(), clock=FakeClock(),
                         wall_clock=FakeClock()).run(WORLD)
    for row in store.fetch(record_type="tactic"):
        meta = json.loads(row["metadata"])
        store.record_refuted(profile_hash=row["profile_hash"],
                             tool=row["tool_name"], endpoint=row["url_pattern"],
                             param=meta.get("param_name"),
                             technique=meta.get("bypass_technique"))
    third = Application(memory_config(), clock=FakeClock(),
                        wall_clock=FakeClock()).run(WORLD)
    memory_across_runs = {
        "first_run_wrote": first["memory_written"],
        "second_run_context_included": second["retrieval"]["observation"]["included"],
        "after_refutation_included": third["retrieval"]["observation"]["included"],
        "after_refutation_write_back": third["memory_written"],
    }

    return {
        "schema": "app-lesson-demo/v1",
        "complete_run": report,
        "interrupted_and_resumed": interrupted,
        "controller_swap": swap,
        "memory_across_runs": memory_across_runs,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(run_demo(), indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
