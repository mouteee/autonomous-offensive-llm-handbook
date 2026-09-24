"""The plasticity lesson's update ledger, in four scripted phases.

Phase "reward": one family is selected and paid repeatedly; its traced weights
climb and the learned readout term becomes visible in the family's `w_dot`.
Phase "delayed": two decisions are made back to back and their outcomes arrive
in reverse order; the decision-keyed contract lands each credit, and the ledger
shows that a delayed modulation brushes every trace still alive at observe
time, including the newer decision's. Phase "stale": several further
selects decay a family's traces before its reward lands, so the same modulation
moves that family visibly less than an immediate reward did, and most of the
credit leaks onto the other family's fresher traces instead -- the
credit-interference effect the originating project's research record measured. Phase "saturate": oversized rewards drive traced
weights into the clipping bound, after which further reward changes nothing.

Run it from the repository root:

    python3 -m core.controller.demo_plasticity --out /tmp/plasticity-trace.json

The committed copy is data/course/plasticity-trace.json; a sync test
re-derives it.
"""

import argparse
import json
from pathlib import Path

from .contract import Candidate, Outcome, State
from .plasticity import PlasticMbController


SEED = 0
PROBE_FAMILIES = ("fam-a", "fam-b")


def _candidate(family, step):
    return Candidate(candidate_id=f"{family}:probe", family=family, priority=1.0,
                     features={"url": f"https://lab.example/{family}"})


def _state(step):
    return State(run_id="plasticity-lesson", step=step, features={
        "bias": 1.0, "stage_progress": 0.5, "surface_known": 1.0,
        "recent_error_rate": 0.0, "budget_remaining": 0.5})


def run_demo():
    controller = PlasticMbController(seed=SEED, learn=True)
    step = 0
    ledger = []

    def probe_w_dots():
        z = controller._last_z
        return {family: round(controller._weights.w_dot(z, family), 6)
                for family in PROBE_FAMILIES}

    def select(family):
        nonlocal step
        decision = controller.select(_state(step), [_candidate(family, step)])
        step += 1
        return decision

    def feed(decision, feedback, phase, note):
        outcome = Outcome(decision_id=decision.decision_id,
                          candidate_id=decision.candidate_id,
                          run_id="plasticity-lesson",
                          status="verified_evidence", feedback=feedback)
        report = controller.observe(outcome)
        ledger.append({
            "phase": phase,
            "note": note,
            "decision_family": decision.family,
            "modulation": feedback,
            "updated": report.get("updated", 0),
            "clipped": report.get("clipped", 0),
            "total_abs_delta": report.get("total_abs_delta", 0.0),
            "traces_alive": len(controller._elig.traces()),
            "learned_w_dot": probe_w_dots(),
        })

    # Phase 1: reward. Same family, immediate outcomes.
    for _ in range(3):
        feed(select("fam-a"), 1.0, "reward",
             "immediate credit; fam-a's traced weights climb")

    # Phase 2: delayed, interleaved. Outcomes arrive in reverse order.
    first = select("fam-a")
    second = select("fam-b")
    feed(second, 1.0, "delayed",
         "the newer decision's outcome lands first")
    feed(first, 1.0, "delayed",
         "the older decision's outcome lands second and also brushes "
         "fam-b's still-alive traces: credit crosstalk")

    # Phase 3: stale. fam-a's traces decay through four fam-b selects
    # before fam-a's reward arrives.
    stale = select("fam-a")
    for _ in range(4):
        feed(select("fam-b"), 0.0, "stale",
             "unrewarded fam-b selects; every select decays all traces")
    feed(stale, 1.0, "stale",
         "fam-a's decayed traces buy about half the earlier update while "
         "fam-b's fresher traces capture most of the credit")

    # Phase 4: saturation. Oversized rewards pin weights at the bound.
    for _ in range(6):
        feed(select("fam-b"), 5.0, "saturate",
             "oversized reward; weights clip at the bound")

    return {
        "schema": "plasticity-lesson-trace/v1",
        "seed": SEED,
        "ledger": ledger,
        "final_total_change": round(controller._weights.total_change(), 6),
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
