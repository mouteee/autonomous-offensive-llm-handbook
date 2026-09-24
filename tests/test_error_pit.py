"""The error-pit exercise, held to the sentence it exists for.

The originating campaigns' corrected record attributes early adaptive-advantage
readings to broken tools absorbing a static policy's budget. The lesson 15
exercise reproduces that confound on a world pair; these tests hold the pair's
arithmetic so the exercise cannot drift into telling a different story.
"""

import json
from pathlib import Path

from core.controller.lab import compare
from core.controller.worlds import make_world


ROOT = Path(__file__).resolve().parents[1]


def chapter_claim(chapter, *sentences):
    """Anchor a test to the verbatim lesson sentence(s) it backs.

    Same declaration shape as tests/test_chapter_claims.py: verify_claims.sh's
    Check C parses these decorators and goes red when a declared sentence is
    no longer present in its chapter.
    """
    def deco(fn):
        return fn
    return deco


@chapter_claim(
    "handbook/course/15-comparisons-and-interpretation.md",
    "The error-pit pair separates tool health from controller quality: the "
    "broken world's lead collapses when the tool is repaired.",
    "almost the entire broken-world difference came from tool health, not "
    "controller quality",
)
def test_the_broken_world_lead_collapses_on_repair():
    broken = compare("error-pit-broken")["controllers"]
    repaired = compare("error-pit-repaired")["controllers"]
    lead_broken = (broken["linucb"]["total_reward"]
                   - broken["priority"]["total_reward"])
    lead_repaired = (repaired["linucb"]["total_reward"]
                     - repaired["priority"]["total_reward"])
    # The static baseline spends its whole budget in the pit; the bandit
    # learns its way out after a bounded number of touches.
    assert broken["priority"]["statuses"] == {"tool_error": 120}
    assert broken["linucb"]["statuses"].get("tool_error", 0) <= 3
    assert lead_broken > 100
    assert abs(lead_repaired) < 5
    # The sentence the exercise exists for, as arithmetic: repairing the tool
    # removes almost the entire difference.
    assert abs(lead_repaired) / lead_broken < 0.05


@chapter_claim(
    "handbook/course/15-comparisons-and-interpretation.md",
    "Hindsight in a broken world is computed over effective rewards, so an "
    "unreachable table value cannot set the regret bar.",
)
def test_hindsight_uses_effective_rewards_in_the_broken_world():
    broken = make_world("error-pit-broken")
    repaired = make_world("error-pit-repaired")
    assert broken.best_fixed_family()[0] != "fam-inject"
    assert repaired.best_fixed_family()[0] == "fam-inject"


def _dedup_scores(runs, pair, arm):
    """Union-rule deduplicated recall per run, from the committed study file."""
    # The pair contributes a single condition when either of its entries is
    # matched; every other entry contributes itself; the denominator is the
    # deduplicated condition count the statistics file declares.
    values = []
    for row in runs:
        if row["arm"] != arm:
            continue
        matched = set(row["P5_gt_matched"])
        distinct = len(matched - pair) + bool(matched & pair)
        values.append(distinct / 19)
    return values


def _exact_two_sided_p(pooled, n_first):
    """Exact tie-aware two-sided Mann-Whitney permutation over every
    assignment of the first arm's labels; answers (U, p)."""
    import itertools
    import math
    ranks = [2 * sum(y < x for y in pooled) + sum(y == x for y in pooled) + 1
             for x in pooled]
    observed = sum(ranks[:n_first]) - n_first * (n_first + 1)
    center = n_first * (len(pooled) - n_first)
    extreme = sum(
        abs(sum(ranks[i] for i in indexes) - n_first * (n_first + 1) - center)
        >= abs(observed - center)
        for indexes in itertools.combinations(range(len(pooled)), n_first))
    return observed / 2, extreme / math.comb(len(pooled), n_first)


@chapter_claim(
    "handbook/course/15-comparisons-and-interpretation.md",
    "A double-counted ground-truth condition moves both arms by the same "
    "rule, and the declared scoring unit travels with the number.",
    "The published deduplicated block derives from the committed per-run "
    "matches, not from a summary someone once wrote down.",
)
def test_the_dedup_block_derives_from_the_committed_matches():
    import statistics
    stats = json.loads((ROOT / "data" / "stats.json").read_text(encoding="utf-8"))
    study = stats["benchmark"]["verifier_ablation"]
    dedup = study["recall_dedup"]
    pair = frozenset(dedup["duplicate_pair"]["ids"])
    assert pair == {"juice-auth-001", "juice-sqli-002"}
    runs = json.loads(
        (ROOT / "data" / "benchmark" / "verifier-study" /
         "study-results.json").read_text(encoding="utf-8"))["runs"]

    # The metric's own claim, checked against the artifact readers receive:
    # both entries of the duplicated pair are matched in every run.
    assert all(pair <= set(row["P5_gt_matched"]) for row in runs)

    full = _dedup_scores(runs, pair, "FULL")
    noverify = _dedup_scores(runs, pair, "NOVERIFY")
    assert len(full) == len(noverify) == 10
    assert round(statistics.median(full), 3) == dedup["FULL_median"]
    assert round(statistics.median(noverify), 3) == dedup["NOVERIFY_median"]

    u, p = _exact_two_sided_p(full + noverify, len(full))
    assert u == dedup["u"]
    assert f"{p:.3f}" == dedup["p_two_sided"]
    # Both entries present in every run makes deduplication rank-preserving,
    # so the deduplicated p equals the raw recall p by construction.
    assert dedup["p_two_sided"] == study["recall"]["p_two_sided"]

    # The published direction claims, still derived rather than asserted.
    for arm_scores, arm in ((full, "FULL_median"), (noverify, "NOVERIFY_median")):
        assert statistics.median(arm_scores) < study["recall"][arm]
    assert statistics.median(full) > statistics.median(noverify)


@chapter_claim(
    "handbook/course/15-comparisons-and-interpretation.md",
    "The published deduplicated block derives from the committed per-run "
    "matches, not from a summary someone once wrote down.",
)
def test_the_union_rule_counts_a_lone_duplicate_label_once():
    # The derivation cannot assume both labels always appear: a record
    # matching a lone pair entry keeps that condition counted, and a record
    # matching neither leaves it uncounted.
    pair = frozenset({"juice-auth-001", "juice-sqli-002"})
    both = {"arm": "X", "P5_gt_matched": ["juice-auth-001", "juice-sqli-002",
                                          "juice-idor-001"]}
    auth_only = {"arm": "X", "P5_gt_matched": ["juice-auth-001",
                                               "juice-idor-001"]}
    neither = {"arm": "X", "P5_gt_matched": ["juice-idor-001"]}
    scores = _dedup_scores([both, auth_only, neither], pair, "X")
    assert scores == [2 / 19, 2 / 19, 1 / 19]


@chapter_claim(
    "handbook/course/15-comparisons-and-interpretation.md",
    "identify merged labels by id rather than by description",
)
def test_the_alternate_pairing_the_recheck_used_reproduces_its_p_value():
    # The correction note's numbers are themselves derivable: pairing
    # juice-auth-001 with the distinct product-search entry juice-sqli-001 --
    # the reading the independent recheck reasonably took from the
    # then-ambiguous package -- leaves three runs holding a lone pair entry
    # and yields the alternate statistic the note records.
    stats = json.loads((ROOT / "data" / "stats.json").read_text(encoding="utf-8"))
    correction = stats["benchmark"]["verifier_ablation"]["recall_dedup"]["correction"]
    runs = json.loads(
        (ROOT / "data" / "benchmark" / "verifier-study" /
         "study-results.json").read_text(encoding="utf-8"))["runs"]
    wrong_pair = frozenset({"juice-auth-001", "juice-sqli-001"})
    incomplete = {(row["arm"], row["run"]) for row in runs
                  if not wrong_pair <= set(row["P5_gt_matched"])}
    assert incomplete == {("FULL", 7), ("NOVERIFY", 2), ("NOVERIFY", 5)}
    full = _dedup_scores(runs, wrong_pair, "FULL")
    noverify = _dedup_scores(runs, wrong_pair, "NOVERIFY")
    u, p = _exact_two_sided_p(full + noverify, len(full))
    assert u == 66.0
    assert str(p) in correction["reason"]


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "A fast failure and a timeout are charged as what the clock observed: the "
    "first spends attempts and no wall time, the second spends wall time and "
    "stops the plan with its owner named.",
)
def test_fast_failures_and_timeouts_charge_different_budgets():
    from core.run.lifecycle import Budgets, Lifecycle
    from core.run.policy import Policy, Tool
    from core.run.recorder import Recorder
    from core.run.records import make_run

    class Clock:
        def __init__(self):
            self.now = 0.0

        def __call__(self):
            return self.now

    def build(adapters, clock):
        policy = Policy(reference="duration-exercise",
                        origins=["https://lab.example/"],
                        tools=[Tool(tool_id="probe", activity="active")],
                        max_actions=10, max_model_calls=1)
        run = make_run(policy.snapshot(), {"world": "duration-exercise"})
        budgets = Budgets(actions=10, model_calls=1, wall_seconds=30, cost=50)
        return Lifecycle(Recorder(run, policy), adapters, budgets,
                         clock=clock, retry_limit=1)

    fast = build({"probe": lambda url: (_ for _ in ()).throw(RuntimeError())},
                 Clock())
    result = fast.execute_with_retries("probe", "https://lab.example/a")
    assert result["status"] == "tool_error" and result["attempts"] == 2
    assert fast.budgets.used["wall_seconds"] == 0.0
    assert fast._blocked() is None

    slow_clock = Clock()

    def slow_probe(url):
        slow_clock.now += 20.0
        return {"status": 200, "body": "slow"}

    slow = build({"probe": slow_probe}, slow_clock)
    ledger = slow.run_plan([
        {"tool": "probe", "destination": "https://lab.example/a"},
        {"tool": "probe", "destination": "https://lab.example/b"},
        {"tool": "probe", "destination": "https://lab.example/c"},
    ])
    assert [row["status"] for row in ledger] == ["clean", "clean", "skipped"]
    assert slow.budgets.used["wall_seconds"] >= 30
    assert "operator.wall_clock" in slow.stop_reason
