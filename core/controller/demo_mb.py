"""The mushroom-body lesson's scripted trace: habituation moves the winner.

Two families with fixed candidates. The injection family starts with the higher
host priority but every execution against its surface errors; the recon family
produces verified evidence every time, and a hit leaves habituation untouched. So the
erroring family is suppressed after its first error, an exploration draw
re-touches it a few steps later and it errors again, and from there its penalty
decays select by select, walking it visibly back toward contention while the
hit family's habituation stays at zero: family competition, habituation and
seeded exploration in one trace. Every number in
the emitted trace is recomputable from the constants in core/controller/mb.py.

Run it from the repository root:

    python3 -m core.controller.demo_mb --out /tmp/mb-trace.json

The committed copy is data/course/mb-trace.json; a sync test re-derives it.
"""

import argparse
import json
from pathlib import Path

from .contract import Candidate, Outcome, State
from .mb import MushroomBodyController


STEPS = 18
SEED = 0


def scripted_candidates():
    return [
        Candidate(candidate_id="sqli-probe:api-users", family="fam-inject",
                  priority=6.0, cost=3.0,
                  features={"url": "https://lab.example/api/users"}),
        Candidate(candidate_id="dir-walk:docs", family="fam-recon",
                  priority=4.0, cost=1.0,
                  features={"url": "https://lab.example/docs"}),
    ]


def scripted_status(family):
    return "tool_error" if family == "fam-inject" else "verified_evidence"


def run_demo():
    controller = MushroomBodyController(seed=SEED)
    rows = []
    for step in range(STEPS):
        state = State(run_id="mb-lesson", step=step, features={
            "bias": 1.0, "stage_progress": 0.5, "surface_known": 1.0,
            "recent_error_rate": 0.0, "budget_remaining": 0.5})
        decision = controller.select(state, scripted_candidates())
        status = scripted_status(decision.family)
        outcome = Outcome(decision_id=decision.decision_id,
                          candidate_id=decision.candidate_id,
                          run_id="mb-lesson", status=status, feedback=0.0)
        report = controller.observe(outcome)
        rows.append({
            "step": step,
            "kc_active": decision.scores["kc_active"],
            "winner": decision.scores["winner"],
            "runner_up": decision.scores["runner_up"],
            "margin": decision.scores["margin"],
            "exploration": decision.scores["exploration"],
            "by_family": decision.scores["by_family"],
            "outcome_status": status,
            "habituation_after": report["habituation"],
        })
    return {
        "schema": "mb-lesson-trace/v1",
        "seed": SEED,
        "steps": rows,
        "final_snapshot_habituation": controller.snapshot()["habituation"],
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
