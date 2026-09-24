#!/usr/bin/env python3
"""Fold the course artifacts' citable numbers into data/stats.json.

The course chapters cite their numbers through the same [[stats:...]] macros as
every other chapter, so the citation gate can hold them. This script derives the
`course` section of data/stats.json from the committed artifacts under
data/course/ and writes nothing else; a sync test re-derives the section, so a
stats value that drifts from its artifact reddens instead of shipping.
"""

import json
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
STATS = ROOT / "data" / "stats.json"
COURSE = ROOT / "data" / "course"


def derive_course_section():
    trace = json.loads((COURSE / "linucb-trace.json").read_text(encoding="utf-8"))
    steps = trace["steps"]

    def fam_a(step):
        return steps[step]["by_family"]["fam-a"]

    section = {
        "note": ("Derived from the committed artifacts under data/course/ by "
                 "scripts/update_course_stats.py; tests/test_course_artifacts.py "
                 "re-derives this section, so these values cannot drift from "
                 "the artifacts they cite."),
        "linucb_toy": {
            "alpha": trace["alpha"],
            "feature_schema": trace["feature_schema"],
            "steps": len(steps),
            "initial_score": round(fam_a(0)["score"], 6),
            "score_after_one_reward": round(fam_a(1)["score"], 6),
            "predicted_after_one_reward": round(fam_a(1)["predicted"], 6),
            "bonus_after_one_reward": round(fam_a(1)["bonus"], 6),
            "first_fam_b_step": next(r["step"] for r in steps
                                     if r["chosen_family"] == "fam-b"),
        },
        "compare": {},
    }

    mb = json.loads((COURSE / "mb-trace.json").read_text(encoding="utf-8"))
    mb_rows = mb["steps"]
    first_switch = next(r["step"] for r in mb_rows if r["winner"] == "fam-recon")
    exploration_steps = [r["step"] for r in mb_rows if r["exploration"]]
    peak_penalty = max(r["by_family"]["fam-inject"]["habituation"] for r in mb_rows)
    section["mb"] = {
        "seed": mb["seed"],
        "steps": len(mb_rows),
        "n_kc": 512,
        "k_active": 10,
        "claws": 3,
        "originating_n_kc": 8192,
        "originating_k_active": 164,
        "originating_claws": 6,
        "first_switch_step": first_switch,
        "exploration_steps": exploration_steps,
        "peak_inject_penalty": peak_penalty,
        "final_inject_penalty": mb_rows[-1]["by_family"]["fam-inject"]["habituation"],
        "final_inject_activation": mb_rows[-1]["by_family"]["fam-inject"]["activation"],
        "final_recon_activation": mb_rows[-1]["by_family"]["fam-recon"]["activation"],
    }

    plastic = json.loads(
        (COURSE / "plasticity-trace.json").read_text(encoding="utf-8"))
    ledger = plastic["ledger"]
    rewards = [r for r in ledger if r["phase"] == "reward"]
    stale_final = [r for r in ledger if r["phase"] == "stale"][-1]
    saturate = [r for r in ledger if r["phase"] == "saturate"]
    section["plasticity"] = {
        "seed": plastic["seed"],
        "first_reward_delta": rewards[0]["total_abs_delta"],
        "first_reward_w_dot": rewards[0]["learned_w_dot"]["fam-a"],
        "stale_fam_a_w_dot_before": [r for r in ledger
                                     if r["phase"] == "delayed"][-1]
                                    ["learned_w_dot"]["fam-a"],
        "stale_fam_a_w_dot_after": stale_final["learned_w_dot"]["fam-a"],
        "stale_fam_b_w_dot_after": stale_final["learned_w_dot"]["fam-b"],
        "first_clipped_count": next(r["clipped"] for r in saturate
                                    if r["clipped"]),
        "saturated_delta": saturate[-1]["total_abs_delta"],
        "final_total_change": plastic["final_total_change"],
    }
    graph = json.loads((COURSE / "graph-demo.json").read_text(encoding="utf-8"))
    toy_fixture = json.loads(
        (COURSE / "graph-toy.json").read_text(encoding="utf-8"))
    arms = graph["arms"]

    def _picks(arm, family):
        return arm["chosen_families"].get(family, 0)

    section["graph"] = {
        "seed": graph["seed"],
        "world": graph["world"],
        "nodes": toy_fixture["nodes"],
        "edges": len(toy_fixture["edges"]),
        "k_active": max(1, round(toy_fixture["nodes"] * 0.15)),
        "toy_total": arms["toy"]["total_reward"],
        "toy_frozen_total": arms["toy-frozen"]["total_reward"],
        "toy_decoy_picks": _picks(arms["toy"], "fam-decoy"),
        "toy_side_picks": _picks(arms["toy"], "fam-side"),
        "toy_pay_picks": _picks(arms["toy"], "fam-pay"),
        "frozen_decoy_picks": _picks(arms["toy-frozen"], "fam-decoy"),
        "frozen_side_picks": _picks(arms["toy-frozen"], "fam-side"),
        "toy_learned_edges": arms["toy"]["parity"]["learned_edges_n"],
        "toy_median_abs_learned": arms["toy"]["parity"]["median_abs_learned"],
        "random_learned_edges": arms["random"]["parity"]["learned_edges_n"],
        "random_clipped_fraction": arms["random"]["parity"]["clipped_fraction"],
        "shuffled_total": arms["shuffled"]["total_reward"],
        "random_total": arms["random"]["total_reward"],
        "no_hop_total": arms["no-hop"]["total_reward"],
    }

    manifest = json.loads(
        (COURSE / "research-manifest.json").read_text(encoding="utf-8"))
    summary = json.loads(
        (COURSE / "research-summary.json").read_text(encoding="utf-8"))
    by_condition = {r["condition"]: r for r in summary["rows"]}

    def _row(name):
        return by_condition[name]

    section["research"] = {
        "conditions": len(summary["rows"]),
        "worlds": len(manifest["body"]["worlds"]),
        "controllers": len(manifest["body"]["controllers"]),
        "seeds": len(manifest["body"]["seeds"]),
        "payout_threshold": manifest["body"]["payout_threshold"],
        "manifest_digest": summary["manifest_digest"],
        "linucb_decoy_total": _row("linucb--decoy-delay--seed7")["total_reward"],
        "linucb_decoy_regret": _row("linucb--decoy-delay--seed7")["regret_vs_best_fixed_family"],
        "linucb_decoy_repeat_ratio": _row("linucb--decoy-delay--seed7")["repeat_ratio"],
        "linucb_decoy_first_payout": _row("linucb--decoy-delay--seed7")["steps_to_first_payout"],
        "linucb_frozen_decoy_total": _row("linucb-frozen--decoy-delay--seed7")["total_reward"],
        "priority_decoy_total": _row("priority--decoy-delay--seed7")["total_reward"],
        "priority_decoy_repeat_ratio": _row("priority--decoy-delay--seed7")["repeat_ratio"],
        "priority_delayed_regret": _row("priority--delayed-credit--seed7")["regret_vs_best_fixed_family"],
        "mb_decoy_total": _row("mb--decoy-delay--seed7")["total_reward"],
        "mb_plastic_decoy_total": _row("mb-plastic--decoy-delay--seed7")["total_reward"],
    }
    for world in ("steady-families", "drifting-signal",
                  "error-pit-broken", "error-pit-repaired"):
        data = json.loads(
            (COURSE / f"compare-{world}.json").read_text(encoding="utf-8"))
        entry = {
            "steps": data["steps"],
            "seed": data["seed"],
            "best_fixed_family": data["best_fixed_family"],
            "best_fixed_reward": data["best_fixed_family_reward"],
        }
        for name, result in data["controllers"].items():
            entry[name] = {
                "total_reward": result["total_reward"],
                "regret": result["regret_vs_best_fixed_family"],
                "statuses": result["statuses"],
            }
        entry["linucb_minus_priority"] = round(
            entry["linucb"]["total_reward"] - entry["priority"]["total_reward"], 6)
        section["compare"][world] = entry

    memory = json.loads((COURSE / "memory-demo.json").read_text(encoding="utf-8"))
    context = json.loads((COURSE / "context-demo.json").read_text(encoding="utf-8"))
    section["memory"] = {
        "wilson_one_of_one": memory["wilson_example"]["one_of_one"],
        "wilson_twelve_of_twenty_three":
            memory["wilson_example"]["twelve_of_twenty_three"],
        "vector_weight": memory["hybrid"]["trace"]["weights"]["vector"],
        "keyword_weight": memory["hybrid"]["trace"]["weights"]["keyword"],
        "priors_top_tool": memory["lanes"]["profile_priors"][0]["tool"],
        "priors_top_confidence":
            memory["lanes"]["profile_priors"][0]["confidence"],
        "dry_tool_tries": next(p["n"] for p in memory["lanes"]["profile_priors"]
                               if p["dry"]),
        "context_large_budget": context["large_budget"]["total_budget"],
        "context_small_budget": context["small_budget"]["total_budget"],
        "context_large_included": len(context["large_budget"]["included"]),
        "context_small_included": len(context["small_budget"]["included"]),
        "context_small_omitted": len(context["small_budget"]["omissions"]),
    }
    return section


def main():
    # The file's own conventions are preserved exactly: insertion order, one
    # space of indent, ASCII escapes, no trailing newline. A byte-for-byte
    # round trip of the untouched sections is what keeps this script's diff
    # limited to the course section it owns.
    stats = json.loads(STATS.read_text(encoding="utf-8"))
    stats["course"] = derive_course_section()
    STATS.write_text(json.dumps(stats, indent=1), encoding="utf-8")
    print("data/stats.json: course section updated")


if __name__ == "__main__":
    main()
