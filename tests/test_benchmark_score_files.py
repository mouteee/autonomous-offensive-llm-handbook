"""The four committed benchmark score files, held against the figures published from them.

`data/benchmark/` carries the scorer's output for the scanner runs and the ZAP
baseline, and `grep -rn "data/benchmark\\|score.json" tests/ scripts/ core/
walkthrough/` returned nothing before this file existed: every committed score
file was inert. Nothing read them, so nothing compared them to `data/stats.json`, and
`data/stats.json` is where chapter 05 gets the counts it calls the runs' real
metrics. A cited number in this repository is protected by
`scripts/verify_claims.sh`, which resolves it to a key. The excluded runs' counts are cited by no chapter, so the gate never reached
them, and neither did anything else: the excluded counts replaced with a sentinel
in the statistics file, and a false-positive count changed in a score file, each
left the whole suite and all five gates green. The ledger row for this docstring
carries both runs.

The relationship pinned here is agreement between the evidence and the
publication, in both directions -- every committed file has a published home and
every published run has a committed file -- plus each file's own arithmetic,
which is what makes a single edited count fail rather than merely disagree.
"""

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCORE_DIR = ROOT / "data" / "benchmark"
STATS = ROOT / "data" / "stats.json"

# Score file -> the path in data/stats.json its numbers are published at, written
# out by hand on purpose. The alternative -- searching the statistics file for the
# entry whose counts match the score file's -- is a check that cannot fail: it
# would locate whichever entry a mutated file had come to agree with and report
# agreement. This map is also the population, so it has to be kept in step with
# the directory, and the first test below is what makes that true rather than
# hoped for.
PUBLISHED_AT = {
    "automator_juiceshop_run1.score.json": ("juice_shop", "excluded", 0),
    "automator_juiceshop_run2.score.json": ("juice_shop", "excluded", 1),
    "automator_juiceshop_run3.score.json": ("juice_shop", "included", 0),
    "zap_juiceshop_baseline_result.score.json": ("zap_baseline",),
}

COUNTS = ("true_positives", "false_positives", "false_negatives",
          "ground_truth_count", "findings_count")
METRICS = ("precision", "recall", "f1")

# What an `included` entry is allowed to carry. The block's own note in
# data/stats.json states this as an allowlist -- "no label, no path, no
# timestamp" -- and a path or a timestamp is exactly the shape of thing
# scripts/audit.sh exists to keep out of a published tree, so the claim is worth
# holding rather than trusting. The score files themselves each carry a label;
# the published copy drops it.
INCLUDED_FIELDS = frozenset(COUNTS + METRICS)
EXCLUDED_FIELDS = frozenset(COUNTS + METRICS + ("label", "reason"))
SCORE_FIELDS = frozenset(COUNTS + METRICS + ("label",))
JUICE_FIELDS = frozenset({"_unmeasured_reason", "excluded", "f1", "included",
                          "n", "note", "precision", "recall"})
METRIC_FIELDS = frozenset({"mean", "stdev", "values"})
ZAP_FIELDS = frozenset(COUNTS + METRICS + ("label", "note"))


def _stats():
    return json.loads(STATS.read_text(encoding="utf-8"))["benchmark"]


def _resolve(bench, where):
    node = bench
    for step in where:
        node = node[step]
    return node


def _scores():
    return {p.name: json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(SCORE_DIR.glob("*.score.json"))}


def test_every_committed_score_file_is_published_and_every_published_run_has_one():
    """The population is asserted in both directions, because one direction is
    the drift that actually happens: a fourth scanner run scored and committed
    without the statistics file being rebuilt, or an entry appended to the
    statistics with no score file behind it. A count on one side alone would
    pass in whichever direction it was not written for.
    """
    on_disk = set(_scores())
    assert on_disk == set(PUBLISHED_AT), sorted(on_disk ^ set(PUBLISHED_AT))

    bench = _stats()
    for name, where in PUBLISHED_AT.items():
        _resolve(bench, where)  # KeyError or IndexError names the missing home

    published = len(bench["juice_shop"]["excluded"]) + len(bench["juice_shop"]["included"]) + 1
    assert published == len(PUBLISHED_AT), (
        f"{published} published runs against {len(PUBLISHED_AT)} committed score files"
    )


def test_each_score_file_matches_the_figures_published_from_it():
    """Exact equality on every shared field, floats included and not rounded.

    Float equality is the point rather than a hazard here: a rounded F1 and the
    committed one are different published figures, and `==` is the operator that
    tells them apart. `scripts/render.py`'s `_format_value` refuses to round for
    the same reason, and its own audited row names the committed value.
    """
    bench = _stats()
    for name, where in sorted(PUBLISHED_AT.items()):
        score = json.loads((SCORE_DIR / name).read_text(encoding="utf-8"))
        entry = _resolve(bench, where)
        shared = [f for f in COUNTS + METRICS if f in score and f in entry]
        assert shared, f"{name} shares no field with {'.'.join(map(str, where))}"
        for field in shared:
            assert score[field] == entry[field], (
                f"{name}:{field} is {score[field]!r} and "
                f"benchmark.{'.'.join(map(str, where))}.{field} is {entry[field]!r}"
            )


def test_each_score_file_is_internally_consistent():
    """Every metric in a score file recomputes from that file's own three counts.

    This is what makes a single edited count a failure rather than a
    disagreement someone can dismiss as a stale snapshot: change
    `false_positives` and the file stops agreeing with itself as well as with
    the statistics. The zero conventions are the scorer's and are asserted, not
    assumed away -- runs 1 and 2 and the ZAP baseline all have no true positive
    at all, so precision, recall and F1 are the branch where the denominator
    vanishes.

    The F1 expression is the harmonic mean of the two rates and not the
    algebraically equivalent form over the counts, because on the included run
    the two are not the same float. The harmonic form reproduces the committed
    value; the counts form comes out on a shorter exact decimal. So the trailing
    digits the handbook publishes are that operation order and not measured
    precision, and the assertion has to use the form the value was produced by.
    """
    for name, score in sorted(_scores().items()):
        tp = score["true_positives"]
        fp = score["false_positives"]
        fn = score["false_negatives"]
        assert score["findings_count"] == tp + fp, name
        assert score["ground_truth_count"] == tp + fn, name

        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        assert score["precision"] == p, f"{name}: {score['precision']!r} vs {p!r}"
        assert score["recall"] == r, f"{name}: {score['recall']!r} vs {r!r}"
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        assert score["f1"] == f1, f"{name}: {score['f1']!r} vs {f1!r}"


def test_the_aggregate_is_the_included_runs_and_nothing_else():
    """n, the values arrays and the means all come from `included` and from
    nothing else, and the absent spread is tied to n rather than left as a
    standing null.

    `stdev` is `null` today with an `_unmeasured_reason` beside it, which is the
    honest form of n=1. The assertion is the biconditional: a second run folded
    in without a spread being computed fails here, and so does a spread reported
    over one run.
    """
    juice = _stats()["juice_shop"]
    included = juice["included"]
    assert juice["n"] == len(included), (juice["n"], len(included))

    for metric in METRICS:
        block = juice[metric]
        want = [e[metric] for e in included]
        assert block["values"] == want, f"{metric}: {block['values']!r} vs {want!r}"
        assert block["mean"] == sum(want) / len(want), f"{metric}: {block['mean']!r}"
        if len(want) < 2:
            assert block["stdev"] is None, f"{metric}: a spread over one run"
        else:
            assert block["stdev"] is not None, f"{metric}: {len(want)} runs and no spread"

    if any(juice[m]["stdev"] is None for m in METRICS):
        assert juice["_unmeasured_reason"], "no spread and no reason given for it"


def test_a_published_included_run_carries_no_label_no_path_and_no_timestamp():
    """The `included` block's own note states its fields as an allowlist. A path
    or a timestamp reaching a published statistics file is the shape
    `scripts/audit.sh` exists to catch, and the score files each carry a label
    the published copy is supposed to drop, so the claim is held here instead of
    trusted.
    """
    for entry in _stats()["juice_shop"]["included"]:
        extra = set(entry) - INCLUDED_FIELDS
        assert not extra, f"included run carries {sorted(extra)}"


def test_every_published_benchmark_aggregate_has_an_explicit_schema():
    """The evidence-limit claim is structural, not a disclaimer-word grep.

    Adding a target ID, run ID, raw finding, matcher record or ground-truth row
    anywhere under the published aggregate must fail this allowlist even when
    every existing arithmetic relation still holds.
    """
    bench = _stats()
    assert set(bench) == {"juice_shop", "zap_baseline"}
    juice = bench["juice_shop"]
    assert set(juice) == JUICE_FIELDS
    for metric in METRICS:
        assert set(juice[metric]) == METRIC_FIELDS, metric
    for entry in juice["included"]:
        assert set(entry) == INCLUDED_FIELDS
    for entry in juice["excluded"]:
        assert set(entry) == EXCLUDED_FIELDS
    assert set(bench["zap_baseline"]) == ZAP_FIELDS


def test_every_committed_score_file_has_an_explicit_schema():
    for name, score in _scores().items():
        assert set(score) == SCORE_FIELDS, f"{name}: {sorted(set(score) ^ SCORE_FIELDS)}"
