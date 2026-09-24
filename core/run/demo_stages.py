"""Lesson 3's runnable demo: a clean stage walk and two recorded stage refusals.

Run it from the repository root:

    python3 -m core.run.demo_stages --out /tmp/stages-demo.json

The committed copy is data/course/stages-demo.json. The first machine walks all
seven operational stages with their prerequisites satisfied; the second is
built fresh and shown two transitions the host turns away: a jump straight to
active testing, and detection before any observation exists. A requirement
decision for an action missing its observation closes the demo.
"""

import argparse
import json
from pathlib import Path

from .demo_records import build_policy
from .recorder import Recorder
from .records import make_run
from .stages import (HARNESS_MAPPING, OPERATIONAL_STAGES, StageMachine,
                     observations_from_response, requirements_met, unknown)


FIXTURES = {
    "login": {"status": 200,
              "body": "<html><form action='/login'>...</form></html>"},
    "landing": {"status": 200, "body": "<html><script src='app.js'></script></html>"},
}


def run_demo():
    policy = build_policy()

    # The clean walk: observations, a gate, then every stage in order.
    run = make_run(policy.snapshot(), {"world": "stages-lesson-fixtures"})
    recorder = Recorder(run, policy)
    machine = StageMachine(recorder)
    for name, response in sorted(FIXTURES.items()):
        for row in observations_from_response(name, response):
            recorder.record("observation", {"run_id": run.run_id, **row})
    recorder.record("observation", {"run_id": run.run_id,
                                    **unknown("waf_vendor")})
    recorder.record("gate", {"run_id": run.run_id, "status": "proceed",
                             "mode": "full",
                             "inputs": {"responses": len(FIXTURES),
                                        "error_rate": 0.0}})
    clean_walk = [machine.advance(stage) for stage in OPERATIONAL_STAGES[1:]]

    # The refused transitions, on a fresh machine with an empty recorder.
    run2 = make_run(policy.snapshot(), {"world": "stages-lesson-refusals"})
    recorder2 = Recorder(run2, policy)
    machine2 = StageMachine(recorder2)
    refusals = [
        machine2.advance("active_testing"),
        machine2.advance("detection"),
    ]

    # An action prerequisite decision with the observation missing entirely.
    requirement = requirements_met({"has_form": True},
                                   recorder2.observations)

    return {
        "schema": "stages-demo/v1",
        "operational_stages": list(OPERATIONAL_STAGES),
        "harness_mapping": {k: list(v) for k, v in HARNESS_MAPPING.items()},
        "clean_walk": clean_walk,
        "refusals": refusals,
        "action_requirement_with_missing_observation": requirement,
        "clean_report": recorder.snapshot(),
        "refusal_report": recorder2.snapshot(),
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
