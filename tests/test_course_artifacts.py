"""The committed course artifacts, held byte-identical to a fresh run.

Same discipline as the harness report and the walkthrough artifacts: every
JSON under data/course/ is produced by a documented command, and this test
re-derives each one in memory and compares bytes, so an artifact edited without
a re-run, or a module changed without regenerating its artifact, reddens here
naming the file. What it does not do is judge the numbers; the lesson tests do
that.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from core.controller.demo_linucb import run_demo
from core.controller.lab import compare
from core.controller.demo_mb import run_demo as run_mb_demo
from core.controller.demo_plasticity import run_demo as run_plasticity_demo
from core.controller.demo_graph import run_demo as run_graph_demo
from core.controller.research import PROTOCOL, analyze, freeze, run_all
from core.memory import demo_context, demo_memory
from core.run import (demo_app, demo_dispatch, demo_lifecycle, demo_proposals,
                      demo_records, demo_stages, demo_verify)


ROOT = Path(__file__).resolve().parents[1]
COURSE = ROOT / "data" / "course"


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _bytes(payload):
    return (json.dumps(payload, indent=1, sort_keys=True) + "\n").encode("utf-8")


def test_the_linucb_lesson_trace_matches_its_committed_copy():
    committed = (COURSE / "linucb-trace.json").read_bytes()
    assert committed == _bytes(run_demo()), (
        "data/course/linucb-trace.json is not what core.controller.demo_linucb "
        "produces; regenerate it with the lesson's run command")


@pytest.mark.parametrize("world", ["steady-families", "drifting-signal",
                                   "error-pit-broken", "error-pit-repaired"])
def test_the_comparison_artifacts_match_their_committed_copies(world):
    committed = (COURSE / f"compare-{world}.json").read_bytes()
    assert committed == _bytes(compare(world)), (
        f"data/course/compare-{world}.json is not what core.controller.lab "
        "produces; regenerate it with the lesson's run command")


def test_the_mb_lesson_trace_matches_its_committed_copy():
    committed = (COURSE / "mb-trace.json").read_bytes()
    assert committed == _bytes(run_mb_demo()), (
        "data/course/mb-trace.json is not what core.controller.demo_mb "
        "produces; regenerate it with the lesson's run command")


def test_the_plasticity_ledger_matches_its_committed_copy():
    committed = (COURSE / "plasticity-trace.json").read_bytes()
    assert committed == _bytes(run_plasticity_demo()), (
        "data/course/plasticity-trace.json is not what "
        "core.controller.demo_plasticity produces; regenerate it with the "
        "lesson's run command")


@pytest.mark.parametrize("name, module", [
    ("records-demo.json", demo_records),
    ("stages-demo.json", demo_stages),
    ("proposals-demo.json", demo_proposals),
    ("dispatch-demo.json", demo_dispatch),
    ("app-demo.json", demo_app),
    ("verify-demo.json", demo_verify),
    ("lifecycle-demo.json", demo_lifecycle),
])
def test_the_run_lesson_demos_match_their_committed_copies(name, module):
    committed = (COURSE / name).read_bytes()
    assert committed == _bytes(module.run_demo()), (
        f"data/course/{name} is not what {module.__name__} produces; "
        "regenerate it with the lesson's run command")


def test_the_graph_demo_matches_its_committed_copy():
    committed = (COURSE / "graph-demo.json").read_bytes()
    assert committed == _bytes(run_graph_demo()), (
        "data/course/graph-demo.json is not what core.controller.demo_graph "
        "produces; regenerate it with the lesson's run command")


def test_the_graph_toy_fixture_is_a_valid_authored_input():
    """graph-toy.json is an authored input, not a derived artifact.

    Like the memory corpus, its census entry is justified by a validity
    contract instead of a re-derivation: the schema is the loader's, the
    graph loads, and the fixture names itself fictional.
    """
    from core.controller.graph import ToyGraph
    fixture = json.loads((COURSE / "graph-toy.json").read_text(encoding="utf-8"))
    assert fixture["schema"] == "course-toy-graph/v1"
    assert "fictional" in fixture["note"]
    graph = ToyGraph.load(COURSE / "graph-toy.json")
    assert graph.n == fixture["nodes"]
    assert len(graph.edges) == len(fixture["edges"])


def test_the_research_manifest_matches_a_fresh_freeze():
    committed = (COURSE / "research-manifest.json").read_bytes()
    assert committed == _bytes(freeze(PROTOCOL)), (
        "data/course/research-manifest.json is not a freeze of the committed "
        "PROTOCOL; rerun the lesson's freeze command")


def test_the_research_summary_matches_its_committed_raw():
    manifest = json.loads(
        (COURSE / "research-manifest.json").read_text(encoding="utf-8"))
    committed = (COURSE / "research-summary.json").read_bytes()
    assert committed == _bytes(analyze(manifest, COURSE / "research-raw")), (
        "data/course/research-summary.json is stale against research-raw/; "
        "rerun the lesson's analyze command")


def test_the_research_raw_directory_matches_a_fresh_run(tmp_path):
    """Every committed raw condition file re-derives byte for byte, and the
    committed set is exactly the manifest's condition set."""
    manifest = json.loads(
        (COURSE / "research-manifest.json").read_text(encoding="utf-8"))
    written = run_all(manifest, tmp_path)
    committed = {p.name for p in (COURSE / "research-raw").glob("*.json")}
    assert committed == set(written), sorted(committed ^ set(written))
    for name in written:
        fresh = (tmp_path / name).read_bytes()
        assert (COURSE / "research-raw" / name).read_bytes() == fresh, (
            f"data/course/research-raw/{name} is stale; rerun the lesson's "
            "run command")


def test_the_course_figures_match_their_committed_data():
    """Each docs/assets/course/*.svg is a pure function of a data/course JSON."""
    plots = _script("make_course_plots")
    rendered = plots.render_all()
    committed = {p.name for p in (ROOT / "docs" / "assets" / "course").glob("*.svg")}
    assert committed == set(rendered), sorted(committed ^ set(rendered))
    for name, content in rendered.items():
        on_disk = (ROOT / "docs" / "assets" / "course" / name).read_text(encoding="utf-8")
        assert on_disk == content, (
            f"docs/assets/course/{name} is stale; rerun scripts/make_course_plots.py")


def test_the_course_stats_section_matches_the_artifacts():
    """data/stats.json's course section re-derives from data/course/."""
    stats = json.loads((ROOT / "data" / "stats.json").read_text(encoding="utf-8"))
    derived = _script("update_course_stats").derive_course_section()
    assert stats.get("course") == derived, (
        "data/stats.json course section is stale; rerun "
        "scripts/update_course_stats.py")


@pytest.mark.parametrize("name, module", [
    ("memory-demo.json", demo_memory),
    ("context-demo.json", demo_context),
])
def test_the_memory_lesson_demos_match_their_committed_copies(name, module):
    committed = (COURSE / name).read_bytes()
    assert committed == _bytes(module.run_demo()), (
        f"data/course/{name} is not what {module.__name__} produces; "
        "regenerate it with the lesson's run command")


def test_the_memory_corpus_is_a_valid_demo_input():
    """The corpus is authored input, not derived output; this holds its shape.

    Every other data/course JSON re-derives byte-for-byte from a module. The
    corpus is the one hand-written file, so what a test can hold is its
    contract: the keys the demo reads, fictional identities only (every host
    sits under .example), and ingestability -- demo_memory builds a store from
    it, which the sync test above already exercises end to end.
    """
    corpus = json.loads((COURSE / "memory-corpus.json").read_text("utf-8"))
    assert set(corpus) == {"note", "records", "tactics", "tool_runs", "findings"}
    for finding in corpus["findings"]:
        assert finding["url"].split("/")[2].endswith(".example"), finding
    for tactic in corpus["tactics"]:
        assert tactic["target_domain"].endswith(".example"), tactic


def test_every_committed_course_artifact_is_derived_by_a_test():
    """Each data/course/*.json needs a sync assertion in this file.

    A committed artifact nothing re-derives is the inert-score-file mistake
    test_benchmark_score_files.py records; this keeps the census explicit so
    adding an artifact without a sync test reddens here first.
    """
    derived = {"linucb-trace.json", "compare-steady-families.json",
               "compare-drifting-signal.json", "compare-error-pit-broken.json",
               "compare-error-pit-repaired.json", "records-demo.json",
               "stages-demo.json", "proposals-demo.json",
               "dispatch-demo.json", "mb-trace.json", "plasticity-trace.json",
               "memory-demo.json", "context-demo.json", "memory-corpus.json",
               "verify-demo.json", "lifecycle-demo.json",
               "graph-demo.json", "graph-toy.json", "research-manifest.json",
               "research-summary.json", "app-demo.json"}
    committed = {p.name for p in COURSE.glob("*.json")}
    assert committed == derived, (
        "data/course/ and this file's sync tests disagree; add a sync test "
        f"for the difference: {sorted(committed ^ derived)}")


def test_every_committed_figure_is_well_formed_xml():
    """A truncated or unescaped SVG renders as a broken image on the site
    while every byte-level gate stays green; parsing is the missing check.
    The reader review shipped exactly that failure once."""
    import xml.etree.ElementTree as ET
    figures = sorted((ROOT / "docs" / "assets" / "course").glob("*.svg"))
    assert figures, "no committed figures found"
    for path in figures:
        try:
            ET.fromstring(path.read_text(encoding="utf-8"))
        except ET.ParseError as exc:
            raise AssertionError(f"{path.name} is not well-formed XML: {exc}")
