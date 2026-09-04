"""Byte-identity between the committed walkthrough artifacts and a fresh run.

`walkthrough/run.py` turns the committed fixtures into the artifact files under
`walkthrough/artifacts/`. Those files are generated and never hand-edited, so they are
worth reading only while they equal what today's driver produces from today's fixtures.
These tests run the driver in memory and compare its output, file by file, against the
committed bytes.

What that catches is drift between the two: a fixture edited without a re-run, a stage
whose output changed shape, a hand-edit to a committed file, an artifact deleted or one
added. What it does NOT catch is a wrong artifact. A value the driver computes
incorrectly is committed by that same driver, both sides carry it, and this file is
green. So a pass here says the committed bytes match what the current source produces,
and says nothing about whether either of them is right. The gate-input figures are
recounted from the fixtures by `tests/test_walkthrough_stages_8_9.py`, which is where a
wrong number is caught, and it is a separate test file because this one cannot see one.

The comparison serialises through `runner.serialize`, the same function the driver writes
the files with. A second hand-written `json.dumps` here would be a second definition of
the artifact format, the two would drift on a flag or a separator, and this gate would
then redden on a correct tree -- which is the fastest way to get a check switched off.
"""
import asyncio
import pathlib

from walkthrough import run as runner

ROOT = pathlib.Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "walkthrough" / "artifacts"


def _on_disk_paths():
    """Every committed artifact file, keyed by its path under the artifact directory.

    Recursive, and keyed on the path relative to `walkthrough/artifacts` -- the shape
    `tests/test_rendered_is_in_sync.py` keys its own side with. For the flat directory the
    writer emits, every path built as `out_dir / name`, that relative path IS the artifact
    name, so the two sides are keyed alike; and a stray file in a subdirectory keeps the
    subdirectory in its key, so it can never take a real artifact's key and is always
    caught by the set comparison instead.

    Keying on `p.name` was tried first and must not come back. A stray named after a real
    artifact collides with it under that key, and `sorted(rglob)` alone decides which of
    the two survives: a stray in a directory sorting AFTER the real file blames the real
    file for a difference it did not cause, and one sorting BEFORE it is dropped
    silently, so the check passes. Both directions were run, before and after.

    Paths are collected here and never read, so a file that does not decode as `UTF-8` is
    named by the set comparison rather than raising while this function builds its result.
    """
    return {p.relative_to(ARTIFACTS).as_posix(): p
            for p in sorted(ARTIFACTS.rglob("*")) if p.is_file()}


def _fresh():
    """The driver's artifacts, serialised the way the driver writes them.

    Keys opening with an underscore are the run's own bookkeeping rather than artifacts,
    and are dropped here for the same reason `_write` skips them: `_stages` is a ledger,
    not a file. Serialisation is `runner.serialize`, not a copy of it.
    """
    tree = asyncio.run(runner.run_all(ROOT))
    return {name: runner.serialize(obj)
            for name, obj in tree.items() if not name.startswith("_")}


def test_the_committed_artifacts_equal_a_fresh_run():
    """The committed bytes equal a fresh run's, and any drift fails here naming the artifact.

    The file set is compared before any content is read: `_on_disk_paths` collects paths and
    nothing opens one until it has a counterpart to compare it against, so a file on one side
    only is named without being decoded. Then the bytes, one artifact at a time, so a failure
    says which file moved rather than that something did.

    Neither failure can say which SIDE is wrong. A name on one side only is a stray file or
    a stage that stopped emitting; a byte difference is a stale commit or a bad source
    change. So the set message names no remedy at all: an earlier draft told the reader to
    delete anything listed as only on disk, and on the stopped-emitting mutation that
    message appears naming a CORRECT artifact. The per-file message does suggest re-running
    the writer, which is the common case and is not destructive if it is the wrong one --
    the suggestion is a convenience, not a verdict on which side moved.

    This is byte identity and not validation: a figure the driver computes wrongly is
    written out by that same driver, so both sides carry it and this cannot catch it.
    """
    fresh, disk = _fresh(), _on_disk_paths()
    only_disk = sorted(set(disk) - set(fresh))
    only_fresh = sorted(set(fresh) - set(disk))
    assert not only_disk and not only_fresh, (
        f"artifact set differs: only on disk={only_disk}, only generated={only_fresh} "
        f"-- the committed directory and the driver disagree about which artifacts exist, "
        f"and which of the two is wrong is not something this check can tell you")
    for name in sorted(fresh):
        assert disk[name].read_text(encoding="utf-8") == fresh[name], (
            f"{name} differs -- re-run python3 walkthrough/run.py")


def test_the_check_covers_every_stage_and_is_not_vacuous():
    """Ten artifacts come back from the run, so an empty run fails instead of passing.

    The set the test above compares is the run's own output, and that is what makes an
    empty run dangerous: with nothing generated the byte loop iterates zero times and
    only the set difference against the committed directory is left to catch it. That
    difference does catch it today, but it stops being a check at all the moment the
    committed directory is empty too. So the count is asserted against the driver's
    output directly, and a driver returning nothing fails here.

    The count is stage coverage as well, because every stage's output is one of the names
    counted: `write` contributes the findings and governance artifacts and each of the
    other stages one apiece, so a stage dropped from what `run_all` returns takes the
    count down with it. What is not re-checked here is that each stage RECORDED itself in
    the `_stages` ledger -- `tests/test_walkthrough_stages_1_4.py`, `_5_7` and `_8_9` read
    that ledger, and this file never looks at it.
    """
    fresh = _fresh()
    assert len(fresh) == 10, f"expected ten artifacts, got {sorted(fresh)}"
    assert all(n.endswith(".json") for n in fresh), (
        f"every artifact name must be a .json filename; got {sorted(fresh)}")
