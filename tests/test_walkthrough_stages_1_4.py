import asyncio
import json
import pathlib
import subprocess
import sys

import pytest

from core.scope_guard import ScopeGuard
from walkthrough import run as runner
from walkthrough.fixture_schema import load_fixture
from walkthrough.store import WalkthroughStore

ROOT = pathlib.Path(__file__).resolve().parents[1]

_STAGES = ("fingerprint", "scope", "recommend", "schedule")
_ARTIFACTS = ("01-fingerprint.json", "02-scope.json", "03-recommendations.json",
              "04-test-plan.json")


def test_the_four_stages_emit_their_artifacts_and_record_that_they_ran():
    out = asyncio.run(runner.run_all(ROOT))
    for name in _ARTIFACTS:
        assert name in out, f"{name} missing"
    assert set(_STAGES) <= set(out["_stages"])
    for stage in _STAGES:
        assert out.stage_ran(stage), f"{stage} did not record itself"


def test_the_stage_ledger_is_the_store_s_own_list():
    """One store, one ledger, so a second record of what ran can never disagree with it.

    `_stages` must be the same list object as `WalkthroughStore.stages_run` -- not a copy and
    not a parallel list -- and this catches a driver that keeps its own. The store is
    subclassed rather than replaced, so the real construction still runs, empty-ruleset
    refusal included.
    """
    seen = []
    original = runner.WalkthroughStore

    class Recording(original):
        def __init__(self):
            super().__init__()
            seen.append(self)

    runner.WalkthroughStore = Recording
    try:
        out = asyncio.run(runner.run_all(ROOT))
    finally:
        runner.WalkthroughStore = original
    assert len(seen) == 1, f"run_all constructed {len(seen)} stores, not one"
    assert out["_stages"] is seen[0].stages_run


def test_the_profile_records_which_fields_a_withheld_probe_would_have_set():
    """The artifact names the fields nothing reachable measured, per field and not in a lump.

    `has_graphql` and `has_websocket` are declared on `TargetProfile` and read by the
    recommender, and `core/` never assigns either one: their only writer would be
    `probe_graphql` / `probe_websocket`, which raise here. `accepts_xml` and
    `error_verbosity` are different -- `Fingerprinter._analyze_attack_surface` can raise
    them from a response body -- so for those the withheld probe is what would settle the
    question, and the default they keep is an absence of signal rather than a measurement.
    Both readings are wrong to publish as a probe result, and the per-field block keeps
    them apart instead of flattening them into one sentence.
    """
    out = asyncio.run(runner.run_all(ROOT))
    fingerprint = out["01-fingerprint.json"]
    unreachable = fingerprint["unreachable_without_live_probes"]
    assert set(unreachable) == {"has_graphql", "has_websocket", "accepts_xml",
                                "error_verbosity"}
    per_field = fingerprint["withheld_probe_fields"]
    assert set(per_field) == set(unreachable)
    assert per_field["has_graphql"]["passive_writers"] == []
    assert per_field["has_websocket"]["passive_writers"] == []
    assert per_field["accepts_xml"]["passive_writers"] == ["_analyze_attack_surface"]
    assert per_field["error_verbosity"]["passive_writers"] == ["_analyze_attack_surface"]
    # A default published as a measurement is the defect; the value is recorded so a reader
    # can see it is the dataclass default rather than an answer.
    assert per_field["error_verbosity"]["published_value"] == "low"
    assert "error_verbosity" not in fingerprint["populated_fields"]


def test_no_withheld_probe_is_ever_called():
    """A withheld probe raises, so a driver that called one would fail the run.

    The firing direction runs first and on purpose: a recording harness that cannot catch a
    probe call proves nothing about a run that makes none, and a test asserting an empty
    list is the cheapest thing in this repository to get wrong. Only the stubs are ever
    called -- the shipped methods stay uncalled in both halves.
    """
    import core.fingerprint as fp
    names = ("probe_graphql", "probe_websocket", "probe_xml_support", "probe_error_verbosity")
    originals = {name: getattr(fp.Fingerprinter, name) for name in names}

    fired = []
    try:
        for name in names:
            setattr(fp.Fingerprinter, name,
                    lambda self, *a, _n=name, **k: fired.append(_n))
        prober = fp.Fingerprinter()
        for name in names:
            getattr(prober, name)("https://example.com/")
        assert fired == list(names), fired
    finally:
        for name, original in originals.items():
            setattr(fp.Fingerprinter, name, original)

    called = []
    try:
        for name in names:
            setattr(fp.Fingerprinter, name,
                    lambda self, *a, _n=name, **k: called.append(_n))
        asyncio.run(runner.run_all(ROOT))
        assert called == []
    finally:
        for name, original in originals.items():
            setattr(fp.Fingerprinter, name, original)


def test_scope_stage_records_both_a_rejection_and_the_published_parent_admission():
    """The guard admits a parent domain, and the artifact says so rather than hiding it.

    Measured on the committed fixtures: the target is the first fixture's request URL, whose
    registrable base is `example.com`, so `https://example.com/` answers in-scope. That is
    the registrable-domain defect this handbook publishes deliberately, so the artifact
    records it beside a real rejection and derives it from the guard's own answer instead of
    asserting it as a constant.
    """
    out = asyncio.run(runner.run_all(ROOT))
    scope = out["02-scope.json"]
    assert any(d["in_scope"] is False for d in scope["decisions"])
    assert scope["known_parent_domain_admission"] is True
    parent = [d for d in scope["decisions"] if d["role"] == "registrable_parent"]
    assert [d["url"] for d in parent] == [f"https://{scope['registrable_base']}/"]
    assert scope["guard_enabled"] is True and scope["guard_seeded"] is True
    # Against the fixture on disk and against the measured base, not against the artifact:
    # deriving the expectation from the artifact under test would only prove it agrees with
    # itself.
    first = load_fixture(ROOT / "walkthrough" / "fixtures" / "01-cors-wildcard.json")
    assert scope["target"] == first["request"]["url"]
    assert scope["registrable_base"] == "example.com"


def test_an_unseeded_guard_is_refused():
    """A guard with no base admits every URL, and `_require_live_guard` refuses it by name.

    This is the unseeded condition only, and it is a unit call rather than a run: the
    environment variable cannot produce an unseeded guard, so the other fail-open condition
    needs its own test and gets one below. Nothing here checks WHEN the refusal happens
    relative to the first decision -- that ordering leaves no observable trace, so it is not
    claimed. What is checked is that the message says `unseeded` and not merely that
    something was refused, because the two conditions have different fixes.
    """
    with pytest.raises(RuntimeError, match="unseeded"):
        runner._require_live_guard(ScopeGuard(target=""))


def test_the_scope_stage_refuses_a_disabled_guard(monkeypatch):
    """AUTOMATOR_SCOPE_TRACKING=0 fails the whole run rather than flipping the artifact."""
    monkeypatch.setenv("AUTOMATOR_SCOPE_TRACKING", "0")
    with pytest.raises(RuntimeError, match="disabled"):
        asyncio.run(runner.run_all(ROOT))


def test_main_writes_one_json_file_per_artifact_and_no_stage_ledger(tmp_path):
    """`main` writes the artifacts and never writes `_stages`, which is not an artifact name."""
    assert runner.main(["--out", str(tmp_path)]) == 0
    written = sorted(p.name for p in tmp_path.iterdir())
    # A subset, because later stages add artifacts to the same run and this file is about the
    # first four. The no-stage-ledger half is what stays asserted whole: `_write` skips a name
    # by its leading underscore, so no written name may open with one.
    assert set(_ARTIFACTS) <= set(written), written
    assert [name for name in written if name.startswith("_")] == [], written
    for name in _ARTIFACTS:
        assert json.loads((tmp_path / name).read_text(encoding="utf-8"))


def test_the_file_runs_as_a_script_from_a_foreign_working_directory(tmp_path):
    """Script mode is a separate execution path, and only a subprocess reaches it.

    Imported, `sys.path` already holds the repository root and `import core` resolves. Run as
    a script it does not: `sys.path[0]` is the file's own directory and the working directory
    is never added, so without the bootstrap at the top of `walkthrough/run.py` this dies
    with ModuleNotFoundError -- from the repository root as surely as from anywhere else. Every
    other test in this file passes against that mutant, so this is the only thing here that
    catches it, and Task 6 shells out to this file with the same argv from a directory that
    is not the repository root.
    """
    result = subprocess.run(
        [sys.executable, str(ROOT / "walkthrough" / "run.py"), "--out", str(tmp_path)],
        cwd="/", capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    written = sorted(p.name for p in tmp_path.iterdir())
    assert set(_ARTIFACTS) <= set(written), written
    assert [name for name in written if name.startswith("_")] == [], written


def test_a_passively_measured_field_is_never_also_published_as_unreachable():
    """The mirror of the defect the fingerprint artifact exists to expose.

    `accepts_xml` and `error_verbosity` are named unreachable without a live probe AND have a
    passive writer, so a response body that reaches that writer would put the same field in
    `populated_fields` and in `unreachable_without_live_probes` at once -- a measurement
    published as a non-measurement, with both halves individually correct and nothing to
    catch the contradiction. No committed fixture body trips it today, which is why the
    collision is constructed here instead of waited for.
    """
    xml_exchange = ("99-synthetic-not-committed.json", {
        "kind": "exchange",
        "request": {"method": "POST", "url": "https://shop.example.com/api/quotes"},
        "response": {"status": 200, "url": "https://shop.example.com/api/quotes",
                     "headers": {}, "cookies": {},
                     "body": "the endpoint answers application/xml on request"},
    })
    with pytest.raises(RuntimeError, match="unreachable"):
        runner._stage_fingerprint(WalkthroughStore(), [xml_exchange])
