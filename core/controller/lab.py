"""The comparison runner: same worlds, same budgets, same feedback, per policy.

`run_episode` walks one controller through one world under the shared contract:
build the state, offer the same candidates every policy gets, execute the
chosen candidate against the world's reward table, and feed the outcome back
keyed by decision identifier. `compare` runs several controllers over the same
world and seed and reports per-step traces plus the hindsight-regret summary.

Run it from the repository root:

    python3 -m core.controller.lab --world steady-families --out /tmp/compare.json

The committed copies under data/course/ are what the course plots are generated
from, and a sync test re-derives them from this module.
"""

import argparse
import json
from pathlib import Path

from . import make_controller
from .contract import Outcome, State
from .worlds import WORLDS, make_world


def run_episode(controller, world):
    """One controller through one world; returns the per-step trace."""
    trace = []
    total = 0.0
    for step, features, candidates, rewards in world.episode():
        state = State(run_id=f"world:{world.name}:seed{world.seed}",
                      step=step, features=features)
        decision = controller.select(state, candidates)
        if decision.candidate_id not in rewards:
            raise ValueError(
                f"controller {controller.name!r} chose a candidate that was "
                f"not offered: {decision.candidate_id!r}")
        chosen = next(c for c in candidates
                      if c.candidate_id == decision.candidate_id)
        status, reward = world.effective_outcome(
            chosen, rewards[decision.candidate_id])
        outcome = Outcome(decision_id=decision.decision_id,
                          candidate_id=decision.candidate_id,
                          run_id=state.run_id, status=status, feedback=reward)
        learned = controller.observe(outcome)
        total += reward
        trace.append({
            "step": step,
            "chosen_family": decision.family,
            "candidate_id": decision.candidate_id,
            "status": status,
            "reward": reward,
            "cumulative_reward": round(total, 6),
            "learning_applied": learned["applied"],
        })
    return trace


def compare(world_name, *, seed=7, controllers=("priority", "legacy", "linucb"),
            learn=("linucb",)):
    """Every named controller over the same world, seed and feedback."""
    results = {}
    for name in controllers:
        controller = make_controller(name, seed=seed, learn=name in learn)
        world = make_world(world_name, seed=seed)
        trace = run_episode(controller, world)
        statuses = {}
        for row in trace:
            statuses[row["status"]] = statuses.get(row["status"], 0) + 1
        results[name] = {
            "learn": name in learn,
            "total_reward": trace[-1]["cumulative_reward"],
            "statuses": dict(sorted(statuses.items())),
            "trace": trace,
        }
    world = make_world(world_name, seed=seed)
    best_family, best_cumulative = world.best_fixed_family()
    best_fixed = best_cumulative[-1]
    for name, result in results.items():
        result["regret_vs_best_fixed_family"] = round(
            best_fixed - result["total_reward"], 6)
    return {
        "schema": "controller-comparison/v1",
        "world": world_name,
        "seed": seed,
        "steps": world.steps,
        "drift_at": world.drift_at,
        "best_fixed_family": best_family,
        "best_fixed_family_reward": best_fixed,
        "best_fixed_cumulative": best_cumulative,
        "controllers": results,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", choices=sorted(WORLDS), required=True)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    report = compare(args.world, seed=args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(f"{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
