"""Byte-identity between the committed rendered tree and a fresh render.

`scripts/render.py` turns `handbook/` plus `data/stats.json` into the
reader-facing copy under `rendered/`. That copy is generated and not
hand-edited, so it is trustworthy only while it equals what the renderer
produces from today's source and today's data. These tests read the committed
copy and a from-scratch in-memory render and compare them. The numbers'
anchor is the source; this file is the test side of that anchor-versus-test
split, so it goes red the moment source or `data/stats.json` moves without a
re-render, and it stays quiet under edits that leave the rendered bytes alone.

Both sides are walked recursively and keyed on the path relative to their own
root, so the two sides compare like with like: a chapter in a subdirectory of
`handbook/` and a file hand-dropped into a subdirectory of `rendered/` are both
visible here rather than falling outside a flat glob.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import render  # noqa: E402  (ModuleNotFoundError here until scripts/render.py exists)


def _on_disk_paths():
    """Every file under `rendered/`, keyed repo-relative, at any depth.

    Recursive and extension-agnostic on purpose: a flat `rendered/*.md` glob
    cannot see a hand-dropped `rendered/notes/scratch.txt`, so the
    never-hand-edited guarantee would have a seam that only the sanitization
    gate covered. Paths are collected without being read, so an unexpected file
    is named by the set comparison rather than decoded first.
    """
    rendered = ROOT / "rendered"
    return {
        p.relative_to(ROOT).as_posix(): p
        for p in sorted(rendered.rglob("*"))
        if p.is_file()
    }


def test_rendered_tree_is_byte_identical_to_a_fresh_render():
    """The committed `rendered/` bytes equal a fresh render, and diverge loudly.

    A fresh render over the current `handbook/` and `data/stats.json` is compared
    file-by-file against what is committed under `rendered/`. Any difference --
    a stats value that moved, a macro added to a chapter, a hand-edit -- fails
    this and names the file, so the generated copy cannot silently drift from
    the source the gates actually verify. The file set is compared before any
    content is read, so a file present in one side and not the other is named
    rather than opened.

    Neither failure can say which SIDE is wrong, so the set message names no
    remedy at all -- the shape `tests/test_walkthrough_is_in_sync.py` already
    settled for the same comparison. An earlier draft told the reader to delete
    anything listed as only on disk. Run against a renderer that stops emitting
    one chapter, that message appears as
    `only on disk=['rendered/05-honest-reporting.md']`, which is a correct,
    committed chapter and the renderer is the thing that is wrong. The per-file
    message does still suggest re-running the renderer: a byte difference is
    usually a stale commit, and re-rendering cannot destroy a correct file when
    it is the wrong guess, so that one is a convenience rather than a verdict on
    which side moved.
    """
    generated = render.render_all(ROOT)
    on_disk = _on_disk_paths()

    only_disk = sorted(set(on_disk) - set(generated))
    only_gen = sorted(set(generated) - set(on_disk))
    assert not only_disk and not only_gen, (
        f"rendered file set differs from a fresh render: "
        f"only on disk={only_disk}, only generated={only_gen} "
        f"-- the committed tree and the renderer disagree about which files exist, "
        f"and which of the two is wrong is not something this check can tell you"
    )
    for key in sorted(generated):
        assert on_disk[key].read_text(encoding="utf-8") == generated[key], (
            f"{key} on disk differs from a fresh render -- re-run scripts/render.py"
        )


def test_the_sync_check_covers_every_chapter_and_is_not_vacuous():
    """One rendered chapter per source chapter plus the index, counted from source.

    The expected shape is derived from `handbook/`'s own recursive walk, never
    written as a constant, so a renderer that returned an empty mapping fails
    here rather than passing over nothing: the chapter twins are a non-empty set
    that must be a subset of the render, and the only permitted extra output is
    the generated index. The walk is `rglob`, which is what the citation gate
    sweeps a directory target with, so a chapter in a subdirectory of `handbook/`
    is a chapter here too and its twin is expected at the matching path.

    What this does NOT catch is a chapter added without a re-render. The twins
    are derived from the same walk `render_all` does, so a new chapter is in
    `generated` as soon as it is in `handbook/` and the subset assertion holds by
    construction. That case reddens
    `test_rendered_tree_is_byte_identical_to_a_fresh_render` instead, which is
    the test that reads the bytes on disk.
    """
    generated = render.render_all(ROOT)
    source_dir = ROOT / "handbook"
    source_chapters = sorted(source_dir.rglob("*.md"))
    assert source_chapters, "no source chapters found under handbook/"

    chapter_twins = {
        f"rendered/{s.relative_to(source_dir).as_posix()}" for s in source_chapters
    }
    assert chapter_twins <= set(generated), (
        f"source chapters with no rendered twin: {sorted(chapter_twins - set(generated))}"
    )
    extra = set(generated) - chapter_twins
    assert extra == {"rendered/README.md"}, (
        f"the only non-chapter output must be the index; got extras {sorted(extra)}"
    )
