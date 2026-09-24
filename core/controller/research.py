"""The reproducible comparison protocol: freeze, run, then analyze.

Three steps, in an order the tooling makes hard to skip. `freeze` writes the
manifest -- worlds, seeds, steps, controllers with their learn flags, the
feedback weights version -- and stamps it with a digest over its own frozen
body. `run` refuses a manifest whose digest does not match its body, executes
every condition, and writes one raw trace file per condition carrying the
manifest digest. `analyze` computes the summary strictly from the saved raw
files, never from a live rerun, so the summary is a pure function of artifacts
a reader can hold in their hands.

The committed protocol run here is deliberately tiny: one seed, short episodes.
It demonstrates the protocol, not statistical power, and no significance
arithmetic is computed over it on purpose.
"""

import argparse
import hashlib
import json
import pathlib

from . import make_controller
from .contract import Outcome, State
from .feedback import WEIGHTS_VERSION
from .worlds import make_world


# The committed protocol configuration the lesson runs. A reader changing any
# value re-freezes, which is the point of the exercise.
PROTOCOL = {
    "schema": "controller-research-manifest/v1",
    "worlds": ["steady-families", "drifting-signal", "delayed-credit",
               "decoy-delay"],
    "seeds": [7],
    "controllers": [
        {"name": "priority", "learn": False},
        {"name": "legacy", "learn": False},
        {"name": "linucb", "learn": True},
        {"name": "linucb", "learn": False, "label": "linucb-frozen"},
        {"name": "mb", "learn": False},
        {"name": "mb-plastic", "learn": True},
    ],
    "feedback_weights": WEIGHTS_VERSION,
    "payout_threshold": 0.5,
    "code_revision": "committed-with-this-tree",
}


def canonical_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=1) + "\n").encode("utf-8")


def manifest_digest(body):
    return hashlib.sha256(canonical_bytes(body)).hexdigest()[:16]


def freeze(config=PROTOCOL):
    """The manifest: the frozen body plus a digest over exactly that body."""
    body = json.loads(json.dumps(config, sort_keys=True))
    return {"body": body, "digest": manifest_digest(body)}


def verify_manifest(manifest):
    expected = manifest_digest(manifest["body"])
    if manifest.get("digest") != expected:
        raise ValueError(
            "manifest digest does not match its body; re-freeze before running")
    return manifest["body"]


def condition_label(controller_config, world_name, seed):
    name = controller_config.get("label", controller_config["name"])
    return f"{name}--{world_name}--seed{seed}"


def run_condition(controller, world):
    """One controller through one world, honoring the world's feedback delay.

    Rewards are computed at choice time from the world's table; delivery waits
    `world.delay` steps, and outcomes still pending when the episode ends are
    delivered afterwards in order. The decision-keyed contract is what lets a
    late outcome land on the decision that earned it rather than on whatever
    ran when it arrived.
    """
    pending = []
    trace = []
    total = 0.0
    for step, features, candidates, rewards in world.episode():
        while pending and pending[0][0] <= step:
            _, outcome = pending.pop(0)
            controller.observe(outcome)
        state = State(run_id=f"world:{world.name}:seed{world.seed}",
                      step=step, features=features)
        decision = controller.select(state, candidates)
        reward = rewards[decision.candidate_id]
        total += reward
        outcome = Outcome(decision_id=decision.decision_id,
                          candidate_id=decision.candidate_id,
                          run_id=state.run_id, status="clean", feedback=reward)
        pending.append((step + world.delay, outcome))
        trace.append({"step": step, "family": decision.family,
                      "reward": reward, "cum": round(total, 6)})
    for _, outcome in pending:
        controller.observe(outcome)
    return trace, round(total, 6)


def run_all(manifest, out_dir):
    """Every manifest condition, one raw file each, digest-stamped."""
    body = verify_manifest(manifest)
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for controller_config in body["controllers"]:
        for world_name in body["worlds"]:
            for seed in body["seeds"]:
                controller = make_controller(controller_config["name"],
                                             seed=seed,
                                             learn=controller_config["learn"])
                world = make_world(world_name, seed=seed)
                trace, total = run_condition(controller, world)
                label = condition_label(controller_config, world_name, seed)
                raw = {
                    "schema": "controller-research-raw/v1",
                    "manifest_digest": manifest["digest"],
                    "condition": {**controller_config, "world": world_name,
                                  "seed": seed},
                    "total_reward": total,
                    "trace": trace,
                }
                # The raw file carries a digest over its own body, so a later
                # edit to a saved result is a refusal at analysis, not a quiet
                # summary entry.
                raw["body_digest"] = manifest_digest(raw)
                path = out / f"{label}.json"
                path.write_bytes(canonical_bytes(raw))
                written.append(path.name)
    return written


def _summarize(raw, body):
    trace = raw["trace"]
    world = make_world(raw["condition"]["world"], seed=raw["condition"]["seed"])
    best_family, best_cumulative = world.best_fixed_family()
    repeats = sum(1 for prev, row in zip(trace, trace[1:])
                  if row["family"] == prev["family"])
    threshold = body["payout_threshold"]
    first_payout = next((row["step"] for row in trace
                         if row["reward"] >= threshold), None)
    return {
        "total_reward": raw["total_reward"],
        "regret_vs_best_fixed_family": round(
            best_cumulative[-1] - raw["total_reward"], 6),
        "best_fixed_family": best_family,
        "repeat_ratio": round(repeats / max(len(trace) - 1, 1), 6),
        "steps_to_first_payout": first_payout,
    }


def analyze(manifest, raw_dir):
    """The summary, computed strictly from the saved raw files.

    A condition the manifest names but the raw directory lacks appears as a
    row with status "missing" -- an absent run is reported, not elided -- and
    a raw file whose manifest digest differs is refused by name.
    """
    body = verify_manifest(manifest)
    raw_dir = pathlib.Path(raw_dir)
    rows = []
    for controller_config in body["controllers"]:
        for world_name in body["worlds"]:
            for seed in body["seeds"]:
                label = condition_label(controller_config, world_name, seed)
                path = raw_dir / f"{label}.json"
                if not path.exists():
                    rows.append({"condition": label, "status": "missing"})
                    continue
                raw = json.loads(path.read_text(encoding="utf-8"))
                if raw.get("manifest_digest") != manifest["digest"]:
                    raise ValueError(
                        f"{path.name} was produced under a different manifest")
                raw_body = {k: v for k, v in raw.items() if k != "body_digest"}
                if raw.get("body_digest") != manifest_digest(raw_body):
                    raise ValueError(
                        f"{path.name} does not match its own body digest; "
                        "a saved result was edited after the run")
                rows.append({"condition": label, "status": "analyzed",
                             **_summarize(raw, body)})
    return {
        "schema": "controller-research-summary/v1",
        "manifest_digest": manifest["digest"],
        "rows": rows,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_freeze = sub.add_parser("freeze")
    p_freeze.add_argument("--out", type=pathlib.Path, required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("--manifest", type=pathlib.Path, required=True)
    p_run.add_argument("--raw-dir", type=pathlib.Path, required=True)
    p_analyze = sub.add_parser("analyze")
    p_analyze.add_argument("--manifest", type=pathlib.Path, required=True)
    p_analyze.add_argument("--raw-dir", type=pathlib.Path, required=True)
    p_analyze.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "freeze":
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(canonical_bytes(freeze()))
        print(args.out)
    elif args.command == "run":
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        written = run_all(manifest, args.raw_dir)
        print(f"{len(written)} raw condition files in {args.raw_dir}")
    else:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        summary = analyze(manifest, args.raw_dir)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(canonical_bytes(summary))
        print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
