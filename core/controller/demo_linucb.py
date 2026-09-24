"""The LinUCB lesson's scripted trace: eight steps, two families, zero noise.

The scenario is authored, not sampled, so every number in the emitted trace can
be recomputed by hand with the lesson's two equations. Family `fam-a` pays 1.0
while the state's `signal` feature is 0 and nothing after it flips to 1;
family `fam-b` pays the reverse. The interesting moments are the first
selection (all scores equal the exploration bonus), the steps after the flip
(the learned model still predicts from the old context until the bonus lets the
other family back in), and the attribution rows showing exactly which decision
each reward landed on.

Run it from the repository root:

    python3 -m core.controller.demo_linucb --out /tmp/linucb-trace.json

The committed copy is data/course/linucb-trace.json; a sync test re-derives it
from this module, the same discipline the fixture harness report lives under.
"""

import argparse
import json
from pathlib import Path

from .contract import Candidate, Outcome, State
from .linucb import LinUcbController


ALPHA = 0.5
STEPS = 8
FLIP_AT = 4  # the step where the signal feature turns on and rewards swap


def scripted_reward(family, signal):
    if family == "fam-a":
        return 1.0 if signal == 0.0 else 0.0
    return 1.0 if signal == 1.0 else 0.0


def run_demo():
    controller = LinUcbController(alpha=ALPHA, learn=True)
    rows = []
    for step in range(STEPS):
        signal = 0.0 if step < FLIP_AT else 1.0
        state = State(run_id="linucb-lesson", step=step,
                      features={"bias": 1.0, "signal": signal},
                      schema_version="toy-v1")
        candidates = [
            Candidate(candidate_id=f"fam-a:step{step}", family="fam-a", priority=1.0),
            Candidate(candidate_id=f"fam-b:step{step}", family="fam-b", priority=1.0),
        ]
        decision = controller.select(state, candidates)
        reward = scripted_reward(decision.family, signal)
        outcome = Outcome(decision_id=decision.decision_id,
                          candidate_id=decision.candidate_id,
                          run_id="linucb-lesson", status="clean", feedback=reward)
        attribution = controller.observe(outcome)
        rows.append({
            "step": step,
            "x": [1.0, signal],
            "by_family": decision.scores["by_family"],
            "chosen_family": decision.scores["chosen_family"],
            "decision_id": decision.decision_id,
            "candidate_id": decision.candidate_id,
            "reward": reward,
            "attribution": attribution,
        })
    return {
        "schema": "linucb-lesson-trace/v1",
        "alpha": ALPHA,
        "feature_schema": "toy-v1",
        "steps": rows,
        "final_families": controller.snapshot()["families"],
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
