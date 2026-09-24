"""The comparison protocol, held to lesson 15's completion sentences."""

import json
import pathlib

import pytest

from core.controller.research import (
    PROTOCOL, analyze, freeze, manifest_digest, run_all, run_condition)
from core.controller import make_controller
from core.controller.worlds import make_world


def chapter_claim(chapter, *sentences):
    """Anchor a test to the verbatim lesson sentence(s) it backs.

    Same declaration shape as tests/test_chapter_claims.py: verify_claims.sh's
    Check C parses these decorators and fails when a declared sentence is no
    longer present in its chapter.
    """
    def deco(fn):
        return fn
    return deco


ROOT = pathlib.Path(__file__).resolve().parents[1]
COURSE = ROOT / "data" / "course"


def committed_manifest():
    return json.loads((COURSE / "research-manifest.json").read_text(encoding="utf-8"))


@chapter_claim(
    "handbook/course/15-comparisons-and-interpretation.md",
    "The runner refuses a manifest whose digest does not match its body.",
)
def test_a_drifted_manifest_is_refused(tmp_path):
    manifest = committed_manifest()
    manifest["body"]["seeds"] = [8]
    with pytest.raises(ValueError, match="re-freeze"):
        run_all(manifest, tmp_path)
    with pytest.raises(ValueError, match="re-freeze"):
        analyze(manifest, COURSE / "research-raw")


@chapter_claim(
    "handbook/course/15-comparisons-and-interpretation.md",
    "A raw file produced under a different manifest is refused by name.",
)
def test_a_raw_file_from_another_manifest_is_refused_by_name(tmp_path):
    manifest = committed_manifest()
    for path in (COURSE / "research-raw").glob("*.json"):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    victim = sorted(tmp_path.glob("*.json"))[0]
    raw = json.loads(victim.read_text(encoding="utf-8"))
    raw["manifest_digest"] = "0" * 16
    victim.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match=victim.name):
        analyze(manifest, tmp_path)


@chapter_claim(
    "handbook/course/15-comparisons-and-interpretation.md",
    "A condition the manifest names but the raw directory lacks appears as a "
    "missing row rather than vanishing.",
)
def test_a_missing_condition_is_reported_not_elided(tmp_path):
    manifest = committed_manifest()
    for path in (COURSE / "research-raw").glob("*.json"):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    (tmp_path / "mb--decoy-delay--seed7.json").unlink()
    summary = analyze(manifest, tmp_path)
    rows = {row["condition"]: row for row in summary["rows"]}
    assert rows["mb--decoy-delay--seed7"]["status"] == "missing"
    assert len(summary["rows"]) == len(committed_manifest()["body"]["controllers"]) * \
        len(committed_manifest()["body"]["worlds"]) * \
        len(committed_manifest()["body"]["seeds"])


@chapter_claim(
    "handbook/course/15-comparisons-and-interpretation.md",
    "Rerunning the analysis on the committed raw files reproduces the "
    "committed summary byte for byte.",
)
def test_the_committed_summary_re_derives_from_the_committed_raw():
    manifest = committed_manifest()
    summary = analyze(manifest, COURSE / "research-raw")
    committed = (COURSE / "research-summary.json").read_bytes()
    fresh = (json.dumps(summary, sort_keys=True, indent=1) + "\n").encode("utf-8")
    assert committed == fresh, (
        "data/course/research-summary.json is stale; rerun the lesson's "
        "analyze command")


@chapter_claim(
    "handbook/course/15-comparisons-and-interpretation.md",
    "Every condition sees the same worlds, the same seeds and the same "
    "feedback definition.",
)
def test_every_condition_draws_from_the_manifest_and_nothing_else():
    body = committed_manifest()["body"]
    raw_files = sorted((COURSE / "research-raw").glob("*.json"))
    seen_worlds, seen_seeds = set(), set()
    for path in raw_files:
        raw = json.loads(path.read_text(encoding="utf-8"))
        seen_worlds.add(raw["condition"]["world"])
        seen_seeds.add(raw["condition"]["seed"])
    assert seen_worlds == set(body["worlds"])
    assert seen_seeds == set(body["seeds"])
    assert len(raw_files) == (len(body["controllers"]) * len(body["worlds"])
                              * len(body["seeds"]))
    assert body["feedback_weights"] == "feedback-v1"


@chapter_claim(
    "handbook/course/15-comparisons-and-interpretation.md",
    "These results describe synthetic runs with committed inputs and a "
    "declared reward rule. They do not establish production performance.",
)
def test_the_summary_carries_descriptions_not_verdicts():
    summary = json.loads(
        (COURSE / "research-summary.json").read_text(encoding="utf-8"))
    for row in summary["rows"]:
        assert row["status"] in ("analyzed", "missing")
        assert not any(key in row for key in ("winner", "significant",
                                              "p_value", "better_than"))


@chapter_claim(
    "handbook/course/15-comparisons-and-interpretation.md",
    "delivers each outcome world.delay steps after its decision and flushes "
    "what remains when the episode ends",
)
def test_delayed_delivery_still_credits_the_earning_decision():
    world = make_world("delayed-credit", seed=7)
    assert world.delay > 0
    controller = make_controller("linucb", seed=7, learn=True)
    trace, total = run_condition(controller, world)
    assert len(trace) == world.steps
    # Every decision's feedback landed: no pending entries survive the flush.
    assert controller.snapshot()["pending"] == {}
    assert round(sum(row["reward"] for row in trace), 6) == total


@chapter_claim(
    "handbook/course/15-comparisons-and-interpretation.md",
    "the committed manifest is a fresh freeze of the committed configuration",
)
def test_the_committed_manifest_is_a_fresh_freeze():
    manifest = committed_manifest()
    assert manifest == freeze(PROTOCOL)
    assert manifest["digest"] == manifest_digest(manifest["body"])
