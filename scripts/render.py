#!/usr/bin/env python3
"""Render the handbook chapters so a reader sees the numbers.

The chapters under `handbook/` are the gated source of truth. They carry three
things a GitHub reader cannot use directly:

  * `[[stats:a.b.c]]` macros, which `scripts/verify_claims.sh` proves resolve to
    a key in `data/stats.json` but which show a reader the key path, not the value;
  * `[[code:file.py:symbol]]` macros, which prove a cited symbol exists in `core/`
    but do not link to it;
  * inline `<!-- num-ok: ... -->` annotations, which `verify_claims.sh` reads on
    the line above a number and which are invisible HTML comments to a reader.

The macros stay in the source on purpose: the gate verifies the macro form, so
substituting literals into `handbook/` would delete the gate's subject and turn
every number into an unverifiable transcription. This renderer emits a separate,
generated copy under `rendered/` with the macros resolved and the annotations
collected into a per-chapter footer. The copy is never hand-edited; a sync test
holds it byte-identical to a fresh render, which is what makes a generated second
copy safe rather than a third place a number can rot.

Between reading a chapter and writing its twin, every edit is one of the regex
substitutions in `render_text` plus the footer it appends -- nothing is reflowed,
no heading is changed, no quote is smartened, no prose is rewritten. Two
consequences follow from *how* that is done rather than from what it intends, and
a reader is owed both in the same place as the rule. First, the substitutions run
over the file's whole text and this module has no notion of a fenced code block,
so a macro or an annotation written inside a fence is transformed there like
anywhere else. What the citation gate does with a fence depends on which part of
it is looking. Its macro checks carry no fence handling: they walk every line of
a chapter and reject an unresolvable macro inside a fence as readily as outside
one. The fence skipping lives in the lettered checks, and a num-ok annotation is
read by those alone, so an annotation inside a fence is lifted into the footer
here without any check having read it. Second, the round trip through text is
not byte-preserving: `pathlib.Path.read_text` decodes universal newlines and
`main` writes with an explicit LF newline, so a CRLF or lone-CR source is
rendered with LF endings.

Design note on the stats resolver. The gate's own `resolve` is lifted out of its
`<<'PY'` heredoc and executed here -- the same technique
`tests/test_docstring_claims.py` uses to reuse the gate's regexes -- and it is
the accept/reject authority: a key it refuses is a hard failure here, so the
renderer's notion of a resolvable key cannot drift from the gate's. The value
walk is not the gate's. `resolve` returns a bool, so it can report whether a path
resolves and structurally never what is at it; `_lookup` is a deliberate mirror
of the same traversal, retyped in this module. A mirror that drifts and returns
the wrong value at a key `resolve` accepts raises nothing here -- what catches
that is the byte-identity sync test in `tests/test_rendered_is_in_sync.py`.

Stdlib only.
"""
import ast
import json
import os
import pathlib
import re
import sys


class RenderError(Exception):
    """A macro that cannot be rendered, or a gate script this module cannot read.

    A macro failure names the file and the macro. It is a hard failure and never
    a blanked or passed-through value: hiding it is exactly what the citation
    gate exists to catch. The message also carries the line whenever
    `_validate_stats`'s per-line scan is what found the macro, which is every
    macro whose text lies within a line; a macro broken across a line break is
    caught later, by `_resolve_stat`, and reported with no line number.

    `gate_resolver` raises the same class for something else, and those messages
    name no handbook file and no macro: the gate script's heredoc is missing, or
    defines no `resolve`, or defines more than one.
    """


_STATS_RE = re.compile(r"\[\[stats:([^\]]+)\]\]")
_CODE_WRAPPED_RE = re.compile(r"`\[\[code:([^\]]+)\]\]`")
_CODE_BARE_RE = re.compile(r"\[\[code:([^\]]+)\]\]")
# Retyped from the citation gate's NUM_OK_RE in scripts/verify_claims.sh, with
# every `\s` run replaced by `_H` and re.MULTILINE added. What those changes
# cost and what they buy is in `_extract_numok`, where the census can read it.
_H = r"[^\S\n]"  # whitespace, excluding the newline
_NUMOK_RE = re.compile(
    rf"^{_H}*<!--{_H}*num-ok\b{_H}*:?{_H}*(.*?){_H}*-->{_H}*$", re.M
)
_HEREDOC_RE = re.compile(r"<<'PY'\n(.*?)\nPY\n", re.S)


def repo_root():
    """The repository root, one level above this script's directory."""
    return pathlib.Path(__file__).resolve().parents[1]


def gate_resolver(root):
    """Return `verify_claims.sh`'s own `resolve(doc, path)`, extracted and executed.

    The gate embeds its Python in a `<<'PY' ... PY` heredoc. This scans every
    such heredoc in the script, parses each one, keeps every top-level `def
    resolve` it finds, and requires that there be exactly one before executing
    it in a fresh namespace. `def` is the match condition and not a loose word
    for definition: a top-level `resolve = lambda ...` binds the name without
    being counted, so a lambda shadowing the real `def` later in the same
    heredoc leaves this function reporting no ambiguity while the gate itself
    runs the lambda. Reusing the gate's own definition -- instead of
    retyping its path walk -- is what keeps the renderer's notion of a resolvable
    key identical to the gate's, so a chapter that passes the gate renders and
    one that does not is a hard failure here too.

    The count is enforced rather than assumed. Taking the first match would bind
    whichever definition happens to come first in the file, so a second heredoc
    carrying its own `resolve`, or a second top-level `def resolve` inside one,
    would hand this module a different resolver while every gate stayed green.
    Ambiguity raises `RenderError` instead of resolving it silently.
    """
    gate_src = (root / "scripts" / "verify_claims.sh").read_text(encoding="utf-8")
    heredocs = _HEREDOC_RE.findall(gate_src)
    if not heredocs:
        raise RenderError("could not find the Python heredoc in scripts/verify_claims.sh")
    found = [
        node
        for body in heredocs
        for node in ast.parse(body).body
        if isinstance(node, ast.FunctionDef) and node.name == "resolve"
    ]
    if not found:
        raise RenderError("scripts/verify_claims.sh's heredocs define no resolve()")
    if len(found) > 1:
        raise RenderError(
            f"scripts/verify_claims.sh's heredocs define resolve() {len(found)} times; "
            "the renderer cannot tell which one the gate uses"
        )
    ns = {}
    exec(compile(ast.Module(body=found, type_ignores=[]), "<verify_claims.sh>", "exec"), ns)
    return ns["resolve"]


def _lookup(doc, path):
    """Fetch the value at `path`, walking exactly as the gate's resolve() does.

    Same split on `.`, same integer index into a list, same key into a dict.
    `_resolve_stat` calls this only after the extracted gate function has said
    the path resolves, and the two walks differ in nothing but their error
    handling: the gate's returns False where this one lets `KeyError`,
    `IndexError` or `ValueError` escape. So for any document `json.loads` can
    produce, a path the gate accepts is a path this walk completes -- which is
    why the guard in `_resolve_stat` is unreachable rather than merely
    unexercised.

    What the mirroring does NOT buy is agreement on the value. The gate's
    function answers a bool and never a value, so a retyped walk that completed
    and returned the wrong thing at an accepted path would not be caught here.
    """
    cur = doc
    for part in path.split("."):
        if isinstance(cur, list):
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            cur = cur[part]
        else:
            raise KeyError(part)
    return cur


def _format_value(value):
    """A scalar renders as its own text; a container renders as JSON.

    A string, an int or a float is written with `str()` -- exactly as stored, no
    rounding and no reformatting -- because inventing or reshaping a number is
    the failure mode this whole project guards against. Anything else has no
    prose form and is written with `json.dumps(..., ensure_ascii=False)`: the
    same values as the source, re-serialised compactly rather than copied out of
    the file's own indentation, with non-ASCII characters kept as characters.

    A bool takes the `str()` branch, because `isinstance(True, int)` holds, and
    would therefore render as Python's `True` rather than JSON's `true`.
    `data/stats.json` holds no bool today, so that branch has no reader-visible
    instance to compare against.
    """
    if isinstance(value, (str, int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def _resolve_stat(stats, key, resolve, where):
    """Resolve one stats key to its formatted value, or raise naming `where`.

    The extracted gate function decides whether the key resolves; a key it
    refuses is the hard failure an unresolvable macro must be. The `except` arm
    below is a guard on `_lookup`'s mirrored walk and not a live check: per that
    function's docstring the two walks accept the same paths, so no
    `data/stats.json` this repository can hold reaches it, and deleting the whole
    `try`/`except` leaves the suite green. It is kept so that an edit which
    breaks the mirror raises here rather than substituting silently. It cannot
    catch a mirror that completes the walk and returns the wrong value; the
    byte-identity sync test is what catches that.
    """
    if not resolve(stats, key):
        raise RenderError(f"{where}: unresolvable stats macro [[stats:{key}]]")
    try:
        value = _lookup(stats, key)
    except (KeyError, IndexError, ValueError) as exc:
        raise RenderError(
            f"{where}: renderer value walk diverged from the gate on "
            f"[[stats:{key}]] ({exc!r}); the two path walkers must agree"
        )
    return _format_value(value)


def _validate_stats(source, relpath, stats, resolve):
    """Fail before rendering if a stats macro within a line does not resolve.

    The scan is per line, run against the untouched source, so a reported line
    number is the reader's own and not an offset into half-transformed text. The
    cost of scanning that way is the population it can see: `_STATS_RE` permits a
    newline inside a macro, so a macro whose text is broken across a line break
    matches nothing here and is caught later, by `_resolve_stat` during
    substitution, which names the file and the macro but no line.
    """
    problems = []
    for lineno, line in enumerate(source.splitlines(), 1):
        for key in _STATS_RE.findall(line):
            if not resolve(stats, key):
                problems.append(f"{relpath}:{lineno}: unresolvable stats macro [[stats:{key}]]")
    if problems:
        raise RenderError("\n".join(problems))


def _code_link(payload, up="../"):
    """One `[[code:file.py:symbol]]` payload as a relative markdown link into core/.

    `up` is the climb from the rendered file's own directory back to the
    repository root, and `render_text` derives it from the chapter's path rather
    than assuming a flat tree. `rendered/` and `core/` are siblings at the root,
    so a chapter written directly into `rendered/` needs `../` and a chapter a
    directory deeper needs `../../`; the link therefore resolves on GitHub from
    any depth under `rendered/`. The symbol travels in the link text so the
    reader sees exactly what the chapter cited. This module only builds the link;
    whether the symbol truly lives in that file is the citation gate's job, not
    the renderer's.
    """
    fname = payload.partition(":")[0]
    return f"[`{payload}`]({up}core/{fname})"


def _extract_numok(text):
    r"""Pull each inline num-ok annotation out, leaving a numbered marker in place.

    Returns the body with every num-ok annotation replaced by a `[num-ok N]`
    marker at its own point of use, and the collected annotation texts in
    document order. The texts are captured from the source verbatim and are
    never macro- or prose-processed, because an annotation is commentary about
    a number, not chapter content.

    `_NUMOK_RE` is retyped from the citation gate's `NUM_OK_RE`, not extracted
    the way `gate_resolver` extracts and executes the gate's `resolve`. It
    departs from the gate's pattern in how it is applied and in what its
    whitespace runs match. The gate matches its pattern against each
    `str.splitlines()` line separately; this runs with re.MULTILINE over a
    whole chapter, where `^` and `$` recognise the newline and nothing else.
    And every whitespace run here is `_H`, whitespace other than the newline,
    where the gate writes `\s`, so no run can consume a newline: a `\s` run at
    either anchor reaches across the line break and takes the blank line beside
    an annotation with it, moving bytes this renderer exists to leave alone.

    The departures cancel wherever a chapter's only line boundary is the
    newline. Inside such a line `_H` matches exactly the characters `\s`
    matches, and no match can cross out of one, so the annotations lifted here
    and the annotations the gate honours are the same population. They can
    differ only where the source carries some other character that
    `str.splitlines()` counts as a line boundary: the gate reads it as ending a
    line, re.MULTILINE reads it as ordinary whitespace, and then the gate
    honours an annotation this drops, or this lifts one the gate never
    honoured.
    """
    notes = []

    def repl(match):
        notes.append(match.group(1))
        return f"[num-ok {len(notes)}]"

    body = _NUMOK_RE.sub(repl, text)
    return body, notes


def _footer(notes):
    """Build the per-chapter number-annotations footer from the collected notes."""
    lines = [
        "",
        "---",
        "",
        "## Number annotations",
        "",
        "These notes were written inline in the handbook source beside the numbers "
        "they explain; the renderer collects them here and leaves a `[num-ok N]` "
        "marker at each point of use above.",
        "",
    ]
    for i, note in enumerate(notes, 1):
        lines.append(f"**[num-ok {i}]** {note}")
        lines.append("")
    return "\n".join(lines)


def render_text(source, relpath, stats, resolve):
    """Render one chapter's markdown: resolve macros, collect annotations, footer.

    The transformations run in a fixed order -- annotations are lifted out first
    so their verbatim text is never touched by macro resolution, then code macros
    become links, then stats macros become values, then the footer is appended.

    The code pass runs twice, the backtick-wrapped form and then the bare one.
    The citation gate matches `[[code:...]]` with no regard for surrounding
    backticks, so an unwrapped citation is one the gate accepts, and the second
    pass is what stops such a citation reaching a reader as raw macro text; both
    passes emit the same wrapped link, so which one matched is invisible in the
    output. Every citation in the handbook today is backtick-wrapped, so the bare
    pass currently matches nothing -- it is tolerance for a form the gate allows,
    not a live path.

    Outside these transformations the text is passed through unchanged -- no
    reflowing, no heading changes, no smart quotes, no prose edits -- including
    any HTML comment that is not a num-ok annotation. The module docstring
    records where that sentence needs care: a fenced code block is not exempt
    from the substitutions, and the read/write round trip normalises line
    endings.
    """
    _validate_stats(source, relpath, stats, resolve)

    body, notes = _extract_numok(source)

    up = "../" * (len(pathlib.PurePosixPath(relpath).parts) - 1)
    body = _CODE_WRAPPED_RE.sub(lambda m: _code_link(m.group(1), up), body)
    body = _CODE_BARE_RE.sub(lambda m: _code_link(m.group(1), up), body)

    where = relpath
    body = _STATS_RE.sub(lambda m: _resolve_stat(stats, m.group(1), resolve, where), body)

    if notes:
        body = body + _footer(notes)
    return body


def _index(chapter_names):
    """The rendered tree's own README: what this tree is and how to regenerate it.

    Assembled here rather than rendered, so it is the only file under `rendered/`
    with no `_validate_stats` pass behind it: every other one is a chapter whose
    source was scanned. That is what the macro-shaped text below rests on. It
    documents the macro syntax to a reader rather than asking the renderer to
    resolve it, and nothing would stop it if it were wrong -- routed through
    `render_text` it is a hard failure. Chapter names arrive as paths relative to
    `handbook/`, so a chapter in a subdirectory is linked by a relative path that
    resolves from `rendered/README.md`.
    """
    lines = [
        "# Rendered handbook",
        "",
        "This is a generated, reader-facing copy of the chapters under `handbook/`.",
        "The `[[stats:...]]` macros have been resolved to their values in "
        "`data/stats.json`, the `[[code:...]]` macros have become relative links "
        "into `core/`, and the inline num-ok annotations have been collected into a "
        "footer on each chapter.",
        "",
        "Do not edit these files by hand. They are produced by `scripts/render.py` "
        "and held byte-identical to a fresh render by "
        "`tests/test_rendered_is_in_sync.py`. To regenerate them after a change to a "
        "chapter or to `data/stats.json`, run:",
        "",
        "```",
        "python3 scripts/render.py",
        "```",
        "",
        "The source of truth is `handbook/`, which keeps the macros and stays under "
        "the citation gates. Read the source there if you want to see what a number "
        "is cited as; read here if you want to see the number.",
        "",
        "`scripts/prose_check.sh` is run against `handbook/` and not against this "
        "tree, and that is deliberate rather than an omission. Its rules are rules "
        "about authoring, and this tree is generated: the punctuation it forbids "
        "reaches these files from a `data/stats.json` string reproduced verbatim, "
        "not from a sentence anybody wrote here, so gating this copy would make the "
        "rule enforceable only by editing the data it is quoting.",
        "",
        "## Chapters",
        "",
    ]
    for name in chapter_names:
        lines.append(f"- [{name}]({name})")
    lines.append("")
    return "\n".join(lines)


def render_all(root=None):
    """Render every chapter plus the index, returned as `{rel_path: content}`.

    Reads `handbook/`, `data/stats.json` and the gate script, and returns the
    full mapping the renderer would write. It never writes; `main` does that.

    The chapter walk is `handbook/`'s own `rglob("*.md")`, which is the walk
    `scripts/verify_claims.sh` sweeps a directory target with, so the renderer's
    notion of a chapter is the gate's: a chapter in a subdirectory gets a twin at
    the matching path under `rendered/` instead of being gated as a chapter and
    rendered nowhere. Keys are repo-relative (`rendered/...`) so a caller can
    compare them against the committed tree directly.
    """
    root = pathlib.Path(root) if root is not None else repo_root()
    stats = json.loads((root / "data" / "stats.json").read_text(encoding="utf-8"))
    resolve = gate_resolver(root)

    out = {}
    chapter_names = []
    source_dir = root / "handbook"
    for src in sorted(source_dir.rglob("*.md")):
        name = src.relative_to(source_dir).as_posix()
        relpath = f"handbook/{name}"
        rendered = render_text(src.read_text(encoding="utf-8"), relpath, stats, resolve)
        out[f"rendered/{name}"] = rendered
        chapter_names.append(name)

    out["rendered/README.md"] = _index(chapter_names)
    return out


def main(argv=None):
    root = repo_root()
    if argv:
        root = pathlib.Path(argv[0]).resolve()
    tree = render_all(root)
    out_dir = root / "rendered"
    out_dir.mkdir(parents=True, exist_ok=True)
    for rel, content in sorted(tree.items()):
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8", newline="\n")
    print(f"rendered {len(tree)} file(s) into {os.path.relpath(out_dir, os.getcwd())}/")


if __name__ == "__main__":
    main(sys.argv[1:])
