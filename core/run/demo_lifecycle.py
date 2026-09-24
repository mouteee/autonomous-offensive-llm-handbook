"""Lesson 9's runnable demo: budgets, an interruption, a resume, a terminal record.

Run it from the repository root:

    python3 -m core.run.demo_lifecycle --out /tmp/lifecycle-demo.json

The committed copy is data/course/lifecycle-demo.json. The run is scripted in
three movements: a flaky tool that pays off on its retry and a dead tool that
exhausts its retry budget; an interruption between execution and recording,
checkpointed, resumed and reconciled -- one action settles because its capture
survived, one stays explicitly unresolved because nothing proves it ran; and a
finish that is first refused while an action is unaccounted for, then completes
with the full accounting. A fake clock makes the wall budget deterministic.
"""

import argparse
import json
from pathlib import Path

from .lifecycle import Budgets, Lifecycle
from .policy import Policy, Tool
from .recorder import Recorder
from .records import make_run


def build_policy():
    return Policy(
        reference="training-authorization-0004",
        origins=["https://lab.example/"],
        tools=[
            Tool(tool_id="steady_probe", activity="passive",
                 family="fam-recon", weight=3.0, cost=1.0),
            Tool(tool_id="flaky_probe", activity="passive",
                 family="fam-recon", weight=2.0, cost=1.0),
            Tool(tool_id="dead_probe", activity="passive",
                 family="fam-recon", weight=1.0, cost=1.0),
        ],
        max_actions=12, max_model_calls=4)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def make_adapters():
    flaky_calls = {"n": 0}

    def steady(url):
        return {"status": 200, "body": f"steady response from {url}"}

    def flaky(url):
        flaky_calls["n"] += 1
        if flaky_calls["n"] == 1:
            raise TimeoutError("first attempt timed out")
        return {"status": 200, "body": f"flaky response from {url}, retried"}

    def dead(url):
        raise ConnectionError("refused every time")

    return {"steady_probe": steady, "flaky_probe": flaky, "dead_probe": dead}


def run_demo():
    policy = build_policy()
    run = make_run(policy.snapshot(), {"world": "lifecycle-lesson"})
    recorder = Recorder(run, policy)
    clock = FakeClock()
    budgets = Budgets(actions=10, model_calls=4, wall_seconds=600, cost=20)
    lifecycle = Lifecycle(recorder, make_adapters(), budgets, clock=clock,
                          retry_limit=1, no_progress_limit=3)

    destination = "https://lab.example/"
    movement_one = {
        "flaky_retry": lifecycle.execute_with_retries("flaky_probe", destination),
        "dead_retries_exhausted": lifecycle.execute_with_retries(
            "dead_probe", destination),
    }

    # The interruption: an action executes and its capture lands, but the
    # process dies before the outcome row is written. Driving the recorder
    # directly is the simulation of that partial write.
    admitted = recorder.record("action", {
        "run_id": run.run_id, "tool": "steady_probe",
        "destination": destination, "arguments": {}})
    recorder.record("capture", {
        "run_id": run.run_id, "action_id": admitted["action_id"],
        "status": 200, "body": "response captured just before the crash"})
    # A second action was authorized but nothing proves it ran at all.
    recorder.refuse("outcome", "simulated crash before this outcome was written",
                    {"action_id": admitted["action_id"], "run_id": run.run_id})
    ghost = recorder.record("action", {
        "run_id": run.run_id, "tool": "flaky_probe",
        "destination": "https://lab.example/ghost", "arguments": {}})

    # Completion is gated: with two authorized actions still unaccounted for,
    # finish answers a refusal, not a report.
    refused_finish = lifecycle.finish()

    checkpoint = lifecycle.checkpoint()

    resumed = Lifecycle.resume(checkpoint, policy, make_adapters(), clock=clock,
                               retry_limit=1, no_progress_limit=3)
    reconciliation = resumed.reconcile()
    finished = resumed.finish()

    return {
        "schema": "lifecycle-demo/v1",
        "movement_one": movement_one,
        "checkpoint_counts": {
            "events": checkpoint["recorder"]["counts"]["events"],
            "budgets_used": checkpoint["budgets"]["used"],
        },
        "finish_refused_while_pending": refused_finish,
        "reconciliation": reconciliation,
        "terminal": finished,
        "ghost_action_id": ghost["action_id"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(run_demo(), indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
