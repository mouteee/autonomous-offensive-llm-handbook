"""Audit the mechanism claims written in docstrings and comments.

A docstring that says a test catches something is a claim about behaviour, and
nothing else in the gate stack reads it: the citation gate reads ``*.md``, and
false docstrings have shipped past it. This harness makes them countable rather
than checking them itself: it collects every docstring under the Python globs in
`_SWEPT_GLOBS` that asserts a mechanism, and every own-line comment block under
the shell globs in `_SHELL_GLOBS` that does, and fails when one of them has no
recorded verdict in ``docstring_claims_audited.txt``. The globs are named here
rather than restated, because this sentence has already been wrong once about
what they are and a restatement rots every time one is widened. The mutation a
claim describes is applied by hand, to a copy of the tree, and the ledger line
says what happened. A claim whose mutation leaves the suite green is a false
claim, and the ledger is where that gets written down.

The shell half exists because the gates' own prose was the last unread surface
in the repository, and three false claims about what a gate guarantees had
already been found in one header comment. See "The gates' own prose" below.

It also sweeps the same prose for uncited quantities, with verify_claims.sh's
own patterns rather than a second copy of them, because that gate walks ``*.md``
and a number invented in a docstring is exactly as uncited as one invented in a
chapter.
"""
import ast
import hashlib
import pathlib
import re

# Verb set measured against the real tree, not guessed, and widened twice for
# measured reasons rather than taste.
#
# A narrow first draft -- catch, fail, refuse, fire -- was run over the same
# files and matched a minority of the claims this set finds. The gap was
# "never", which several of the ones it missed carry as their only claim verb,
# and in a project whose central invariants are all never-statements ("the
# governor never escalates", "the model never touches the target") a detector
# blind to it would be dormant on exactly the claims that matter most.
#
# EVERY VERB CARRIES ITS PARTICIPLE, and that is not tidiness. A mechanism claim
# is written in the passive at least as often as the active -- "unknown keys are
# dropped", "the request is refused", "escalation is prevented" -- and an active
# only list reads the first of those and misses the rest, because "drop" happens
# to carry "dropped" while "refuse" did not carry "refused". That is the same
# defect as the missing "never", one layer down, in the gate whose whole purpose
# is coverage. "must" is here for the same reason: a requirement stated as an
# obligation is a mechanism claim, and one lives in this suite already.
#
# MATCH was the third widening, and it came from this sweep reaching the gate
# scripts' own prose. Every gate in this stack IS a matcher, so a comment
# describing what one guarantees says "matched", "does not match", "the pattern
# matches X" -- and the paragraph carrying the WORD_RE floor measurement, the
# most quantitative claim in the gate stack, uses no other claim verb, so the
# detector was blind to exactly the sentence a reader is most likely to quote.
# The cost was measured before the verb was added rather than discovered after:
# it pulls in a further handful of comment blocks in the scripts and a further
# handful of docstrings in core/, each one audited in the ledger, and it moved
# no verdict that already existed. The anchored counts are in the ledger entry
# for the census block in tests/test_gates.sh, where they cannot rot into this
# comment.
#
# A dormant gate is worse than no gate, so if a verb here looks like it earns
# nothing, measure before deleting it.
#
# WHAT IS COUNTED is one condition and it is stated rather than illustrated,
# because the shapes that escape it are open-ended and the illustration that
# stood here read as if it were the boundary: a docstring is counted when its
# text carries one of the verbs in this alternation, and it is not counted
# otherwise. A claim built out of any other vocabulary is therefore absent from
# the census, absent from the ledger, and -- this is the part that surprises --
# cannot be put in the ledger by hand, because the orphan arm fails a row whose
# key the census never produced. Widening this alternation is the only route,
# and each widening is a batch of fresh verdicts rather than a regex edit. The
# densest instance in the tree today is core/critic.py::_parse_scores.
CLAIM_RE = re.compile(
    r"(?i)\b(catch(?:es)?|caught|fail(?:s|ing|ed)?|refus(?:e|es|ed)"
    r"|fire(?:s|d)?|guard(?:s|ed)?|pin(?:s|ned)?|prov(?:e|es|en|ed)"
    r"|ensur(?:e|es|ed)|prevent(?:s|ed)?|reject(?:s|ed)?|drop(?:s|ped)?"
    r"|cap(?:s|ped)?|block(?:s|ed)?|cannot|can't|never|only if|must"
    r"|assert(?:s|ed)?|check(?:s|ed)?|enforce[sd]?|resolve[sd]?"
    r"|match(?:es|ed|ing)?|silent(?:ly)?)\b"
)

# Module and class docstrings are in scope, not just functions, because a module
# docstring is where the largest invariant belongs: a never-escalate rule states
# itself once, at the top of the module it constrains, and a walker that read
# only functions would miss exactly the claims that matter most. The
# AsyncFunctionDef arm has no member anywhere in the tree, which is precisely
# why it would be dropped as dead weight -- see the probe that pins it.
_DOC_NODES = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)

# The Python this harness reads. One definition, because the census and the
# quantity sweep have to walk the same files: a file read by one and not the
# other is a hole nobody would see.
#
# All three are walked RECURSIVELY, and tests/ takes every *.py rather than only
# test_*.py. The narrower pair -- core/*.py and tests/test_*.py -- left two blind
# spots that a planted claim walked straight through: core/skills/ is a real
# sub-package already in the tree, and a tests/helpers.py carrying a
# claim-bearing docstring is an ordinary thing for a suite to grow. Neither holds
# a claim today, which is exactly the kind of hole that is found by planting one
# rather than by reading.
#
# scripts/ was added for the same reason and found the same way. A review planted
# a deliberately false claim-bearing docstring in scripts/render.py and got a
# green suite: render.py was this repository's only .py outside these globs, and
# its docstrings are the ones that describe how every byte a reader sees under
# rendered/ is produced. Recursive, so a helper added under scripts/ci/ is swept
# the way core/skills/ is.
#
# tests/ was the last flat one, and it was the same hole a third time: a review
# planted the identical claim-bearing module docstring twice, and the copy in
# tests/defcon/ was invisible while the copy in tests/ was named. The directory
# it used is not hypothetical -- the private repository already has one by that
# name -- so the plant is kept in the probe below rather than left as a note.
#
# walkthrough/ was added for the same reason as scripts/, one phase later:
# a fourth top-level package started shipping claim-bearing docstrings and
# nothing in this file read them until this glob was added. Recursive, for the
# same reason the other three are.
_SWEPT_GLOBS = (("tests", "**/*.py"), ("core", "**/*.py"), ("scripts", "**/*.py"),
                ("walkthrough", "**/*.py"), ("harness", "**/*.py"))


def _repo_root():
    return pathlib.Path(__file__).resolve().parents[1]


def _swept_paths(root=None):
    root = root or _repo_root()
    out = []
    for subdir, pattern in _SWEPT_GLOBS:
        out.extend((root / subdir).glob(pattern))
    return sorted(p for p in out if "__pycache__" not in p.parts)


def _claim_bearing_docstrings(path):
    """Every docstring in `path` that asserts a mechanism, with its name."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, _DOC_NODES):
            doc = ast.get_docstring(node) or ""
            if CLAIM_RE.search(doc):
                name = getattr(node, "name", "<module>")
                out.append((name, getattr(node, "lineno", 1), doc))
    return out


def _all_docstrings(path):
    """Every non-empty docstring in `path`, claim-bearing or not.

    The census proper reads only what `CLAIM_RE` matches. This reads the rest as
    well, and exists so the two failure modes below can be told apart: a ledger
    key with no docstring behind it any more, and a ledger key whose docstring is
    sitting in the tree in words the census has no verb for. Before this, both
    arrived as the same assertion, and its message said the claim no longer
    existed -- which for the second was the opposite of true.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, _DOC_NODES):
            doc = ast.get_docstring(node) or ""
            if doc.strip():
                out.append((getattr(node, "name", "<module>"), doc))
    return out


def _key_for(root, path, name, doc):
    return f"{path.relative_to(root)}::{name}@{_doc_digest(doc)}"


def _docstring_keys(root=None):
    """Every docstring key in the swept tree, split by whether the census sees it.

    Returns (visible, invisible). `visible` is what the census produces on its
    own; `invisible` is the complement -- present in the tree, swept by the
    walker, and carrying none of `CLAIM_RE`'s verbs. The complement is the
    population an `[unswept]` ledger row is allowed to name, and nothing else is.
    """
    root = root or _repo_root()
    visible, invisible = set(), set()
    for path in _swept_paths(root):
        for name, doc in _all_docstrings(path):
            key = _key_for(root, path, name, doc)
            (visible if CLAIM_RE.search(doc) else invisible).add(key)
    return visible, invisible


def _coverage_summary(root=None):
    """Per-directory swept/visible/invisible, for a reader who wants the shape.

    Deliberately not asserted against a stored figure. A count of docstrings
    moves every time anybody writes one, so pinning it here would buy a
    failing test on unrelated work and teach whoever hit it to edit the number
    rather than read it. It is surfaced in the messages below, where it is
    read at the moment it matters.
    """
    root = root or _repo_root()
    rows = {}
    for path in _swept_paths(root):
        top = path.relative_to(root).parts[0]
        swept = rows.setdefault(top, [0, 0])
        for _name, doc in _all_docstrings(path):
            swept[0] += 1
            if CLAIM_RE.search(doc):
                swept[1] += 1
    return "\n".join(
        f"  {k:<13} swept={v[0]:>4}  visible={v[1]:>4}  invisible={v[0] - v[1]:>4}"
        for k, v in sorted(rows.items())
    )


def _doc_digest(doc):
    """The part of a Python row's key that moves when the docstring's words do.

    A key of path::name identifies a docstring by its LOCATION, so an audited
    docstring rewritten to say the opposite keeps its old verdict and the
    census stays green. That was proved by planting a paragraph contradicting
    the shipped code into an already-ledgered docstring and watching the whole
    suite pass. The shell side of this same gate never had that hole, because
    _block_key hashes its block's reflowed text, so the fix is to key the two
    sides the same way, and the audit then re-opens on any edit to the words.
    Reflowing before the hash is what makes a rewrap keep its verdict while a
    reworded claim does not -- the same property, and the same reason,
    _block_key states for the shell side.
    """
    return hashlib.sha1(" ".join(doc.split()).encode("utf-8")).hexdigest()[:8]


def test_the_census_reaches_sub_packages_and_non_test_helpers(tmp_path):
    """Where a claim used to be able to hide from the census.

    core/*.py could not see core/skills/, a sub-package the tree already has;
    tests/test_*.py could not see a tests/helpers.py; and tests/*.py could not
    see a module in a tests/ sub-directory, which is the one that mattered
    because the private repository already has such a directory. Each was found
    by planting a claim rather than by reading the globs, so each stays planted,
    one plant per glob: flattening any single glob in _SWEPT_GLOBS fails this
    test. __pycache__ is excluded here because it is excluded from the walk: a
    stale .pyc is not a docstring anybody wrote.
    """
    for rel in ("core/scoring.py", "core/skills/deep.py", "tests/helpers.py",
                "tests/test_thing.py", "tests/defcon/test_nested.py",
                "scripts/ci/probe.py", "core/__pycache__/stale.py"):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('"""A helper that refuses bad input."""\n', encoding="utf-8")
    found = sorted(str(x.relative_to(tmp_path)) for x in _swept_paths(tmp_path))
    assert found == ["core/scoring.py", "core/skills/deep.py",
                     "scripts/ci/probe.py", "tests/defcon/test_nested.py",
                     "tests/helpers.py", "tests/test_thing.py"], found
    claims = [n for x in _swept_paths(tmp_path) for n, _, _ in _claim_bearing_docstrings(x)]
    assert claims == ["<module>"] * 6, claims


def test_the_walker_reads_module_class_and_async_docstrings(tmp_path):
    """Each arm of _DOC_NODES, including the one the tree cannot exercise.

    The census below catches an arm that stops matching, because a ledger line
    whose claim has vanished fails it -- but only for an arm the tree has a
    member of. There is no async function anywhere in tests/ or core/, so
    dropping AsyncFunctionDef orphans nothing and this test is the only thing
    standing between an async entry point added later and its claims going
    unread. Do not fold it into the planted-claim test above: that one plants a
    single function and asserts the function arm alone.
    """
    planted = tmp_path / "t_shapes.py"
    planted.write_text(
        '"""A module docstring that never lies."""\n'
        "class C:\n"
        '    """A class docstring this walker must catch."""\n'
        "    def m(self):\n"
        '        """A method that refuses bad input."""\n'
        "\n"
        "async def entry():\n"
        '    """An async entry point that drops unknown keys."""\n'
        "\n"
        "def quiet():\n"
        '    """Plain prose about a thing, with no mechanism in it."""\n',
        encoding="utf-8",
    )
    found = [n for n, _, _ in _claim_bearing_docstrings(planted)]
    # ast.walk is breadth-first, so the nested method arrives after the
    # top-level async function. The order is pinned, not just the membership.
    assert found == ["<module>", "C", "entry", "m"], found


def test_the_harness_finds_a_planted_claim(tmp_path):
    planted = tmp_path / "t_planted.py"
    planted.write_text(
        'def test_x():\n    """Loosening the constant makes this assertion fail."""\n    assert 1 == 1\n',
        encoding="utf-8",
    )
    found = _claim_bearing_docstrings(planted)
    assert [n for n, _, _ in found] == ["test_x"]


def _is_tagged(verdict):
    """Whether a ledger verdict carries the unswept marker.

    Read from the verdict, ahead of the first colon, and never from the reason.
    As a free-text substring the check was satisfied by a row that merely
    DISCUSSES the tag -- which the first row written with it does, several times
    over -- so removing the marker did not untag the row, and the recorded
    verification of that arm could not fail. Reading the verdict leaves the marker
    as the only thing carrying meaning and prose about the mechanism as prose.
    """
    return UNSWEPT_TAG in verdict.split(":", 1)[0]


def _ledger_faults(audited, seen, visible, invisible):
    """The three ways a ledger row can be wrong, as sets, doing no I/O.

    Pulled out of the census so the failure directions can be constructed and
    run. Each arm shipped with an assertion and no probe, and neutralising any of
    the three left the suite green: nothing anywhere built a genuine orphan, an
    untagged invisible row, or a tagged visible one. An assertion whose failure
    path nothing exercises is the decorative gate this file exists to catch.
    """
    tagged = {k for k, v in audited.items() if _is_tagged(v)}
    return (
        sorted(k for k in audited if k not in seen and k not in invisible),
        sorted(k for k in audited if k in invisible and k not in tagged),
        sorted(k for k in tagged if k in visible),
    )


def test_the_three_ledger_faults_are_each_reachable():
    """Each arm's failure path, constructed rather than trusted.

    Built as sets rather than as files, because the census reads the real tree
    and a planted row cannot reach these directions without editing the shipped
    ledger. What is asserted is that a clean ledger yields nothing on any arm and
    that each malformed row is caught by its OWN arm and not by another, which is
    what makes a message usable when one of them fires.
    """
    visible, invisible = {"a.py::good@1111"}, {"b.py::unseen@2222"}
    seen = set(visible)
    clean = {"a.py::good@1111": "TRUE: ran it",
             "b.py::unseen@2222": "TRUE " + UNSWEPT_TAG + ": read by hand"}
    assert _ledger_faults(clean, seen, visible, invisible) == ([], [], [])

    gone = dict(clean); gone["c.py::vanished@3333"] = "TRUE: ran it"
    assert _ledger_faults(gone, seen, visible, invisible) == (["c.py::vanished@3333"], [], [])

    bare = dict(clean); bare["b.py::unseen@2222"] = "TRUE: read by hand"
    assert _ledger_faults(bare, seen, visible, invisible) == ([], ["b.py::unseen@2222"], [])

    laundered = dict(clean)
    laundered["a.py::good@1111"] = "TRUE " + UNSWEPT_TAG + ": read by hand"
    assert _ledger_faults(laundered, seen, visible, invisible) == ([], [], ["a.py::good@1111"])

    # The marker counts only in the verdict. A row discussing the tag in its
    # reason is not tagged by doing so, which is the defect that made the
    # recorded check for the unlabelled arm incapable of failing.
    talks = dict(clean)
    talks["b.py::unseen@2222"] = "TRUE: I took the " + UNSWEPT_TAG + " marker off"
    assert _ledger_faults(talks, seen, visible, invisible)[1] == ["b.py::unseen@2222"]


def test_a_docstring_the_census_cannot_see_is_separable_from_one_that_is_gone(tmp_path):
    """The two states the orphan arm used to report identically, on planted input.

    Both halves are planted rather than argued, because the confusion this
    separates is precisely the kind that survives careful reading: one docstring
    the walker reaches and `CLAIM_RE` passes over, and a key naming words that
    are not in the tree at all. `_docstring_keys` has to sort the first into the
    invisible complement and leave the second out of both sets, and if it stops
    doing either, the ledger goes back to calling a present claim retired.
    """
    planted = tmp_path / "planted.py"
    planted.write_text(
        'def visible():\n'
        '    """This one asserts a mechanism and the census catches it."""\n'
        '    return 1\n\n\n'
        'def unseen():\n'
        '    """The default timeout, in seconds, used by the retry helper."""\n'
        '    return 2\n',
        encoding="utf-8",
    )
    by_name = dict(_all_docstrings(planted))
    assert sorted(by_name) == ["unseen", "visible"], "the walker must reach both"

    seen_by_census = [n for n, _, _ in _claim_bearing_docstrings(planted)]
    assert seen_by_census == ["visible"], seen_by_census

    key_unseen = _key_for(tmp_path, planted, "unseen", by_name["unseen"])
    key_gone = _key_for(tmp_path, planted, "unseen", "words that were deleted")
    assert key_unseen != key_gone

    # The distinction the ledger now rests on: one of these keys answers to
    # something in the tree and the other does not, and before the complement
    # existed neither did.
    present = {
        _key_for(tmp_path, planted, name, doc) for name, doc in _all_docstrings(planted)
    }
    assert key_unseen in present
    assert key_gone not in present


# The ledger is the gate. A claim-bearing docstring that nobody has audited
# fails the census below, which is what makes this a check rather than a
# report: the work queue is the failure message.
AUDITED = pathlib.Path(__file__).parent / "docstring_claims_audited.txt"


def _audited_entries():
    entries = {}
    for line in AUDITED.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        key, _, verdict = line.partition("#")
        entries[key.strip()] = verdict.strip()
    return entries


VERDICTS = ("TRUE", "CORRECTED")

# A row for a docstring the census cannot see carries this tag in its reason.
#
# R3's requirement was that an unaudited claim stop being indistinguishable from
# a retired one, and before this tag existed they were the same assertion. The
# orphan arm compared the ledger against what CLAIM_RE had matched, so a row
# hand-written for a docstring built out of other vocabulary failed as "audited
# claims that no longer exist" -- about a docstring sitting in the tree, freshly
# read. Verified by construction rather than reasoned about: a function whose
# docstring said only "The default timeout, in seconds, used by the retry
# helper" passed the census silently with no row, and failed it the moment an
# honest row was written for it. Doing the work was the only way to redden it.
#
# The tag is not a way out of the audit. A tagged row still has to name a
# docstring that is in the tree RIGHT NOW, byte for byte, because the key
# carries `_doc_digest`'s hash of the reflowed text: edit the words and the row
# stops resolving and comes back as a genuine orphan, the same way an untagged
# one does. And it has to name a docstring the census genuinely cannot see, so
# it cannot be used to move a real claim out of the machine's reach. Both
# directions are asserted below.
UNSWEPT_TAG = "[unswept]"


def test_every_mechanism_claim_has_been_audited():
    root = _repo_root()
    seen = []
    where = {}
    for path in _swept_paths(root):
        for name, _lineno, doc in _claim_bearing_docstrings(path):
            seen.append(f"{path.relative_to(root)}::{name}@{_doc_digest(doc)}")
    # The gate scripts' own comments are audited through the same ledger, and
    # their keys carry a locator because a key built from a content hash is not
    # something a reader can find by eye. See _gate_prose_keys.
    for key, locator in _gate_prose_keys(root):
        seen.append(key)
        where[key] = locator
    audited = _audited_entries()

    unaudited = [s + where.get(s, "") for s in seen if s not in audited]
    assert not unaudited, "mechanism claims with no recorded audit:\n" + "\n".join(unaudited)

    # The other direction, and it is the one that keeps this census from going
    # dormant: a ledger line whose claim no longer exists is a verdict about
    # nothing, so a detector narrowed until it stops seeing a claim fails here
    # rather than passing quietly. Without this, deleting a verb from CLAIM_RE
    # or an arm from _DOC_NODES is invisible. It reaches only what the tree has
    # a member of, which is why the async arm carries its own probe.
    seen_set = set(seen)
    visible, invisible = _docstring_keys(root)
    orphaned, unlabelled, mislabelled = _ledger_faults(audited, seen_set, visible, invisible)

    assert not orphaned, "audited claims that no longer exist:\n" + "\n".join(orphaned)

    # An untagged row the census did not produce is the honest-workaround case
    # arriving without its label, and it would otherwise sit in the ledger
    # looking exactly like a census verdict. Name the tag in the message,
    # because the whole point is that a reader doing the right thing should not
    # have to discover the mechanism by reading this file.
    assert not unlabelled, (
        "hand-audited rows for docstrings the census cannot see, missing "
        f"{UNSWEPT_TAG!r} in their reason:\n" + "\n".join(unlabelled)
        + "\n\ncensus coverage:\n" + _coverage_summary(root)
    )

    # And the other direction, which is what stops the tag becoming an exit.
    # A row the census DID produce must not claim to be invisible: tagging a
    # visible claim would park it beyond the reach of the machine that can
    # actually check it, which is the failure this whole file exists to prevent.
    assert not mislabelled, (
        f"rows tagged {UNSWEPT_TAG!r} whose docstring the census does see:\n"
        + "\n".join(mislabelled)
    )

    # And a key with no verdict behind it is a free pass, which is the cheapest
    # way to defeat the whole file: recording the name without doing the work.
    unreasoned = sorted(k for k, v in audited.items() if not v.startswith(VERDICTS))
    assert not unreasoned, (
        "ledger lines with no TRUE/CORRECTED verdict:\n" + "\n".join(unreasoned)
    )


# --- Quantities in docstrings and comments --------------------------------
#
# Check A in scripts/verify_claims.sh walks *.md. Every quantity written into a
# Python docstring or comment is therefore unswept, and the docstrings in this
# repository make exactly the claims Check A exists for: a threshold, a weight,
# a count of something in the code. This is the cheapest correct home for that
# sweep, because the walk above already has the prose.
#
# The patterns are the GATE'S OWN, lifted out of its source rather than
# retyped. verify_claims.sh embeds its Python in a heredoc, so the definitions
# are extracted with ast and executed: a copied regex is a transcription, and
# transcriptions are what this repository keeps getting wrong. Edit a pattern
# there and this sweep changes with it, which is the entire point.
#
# The patterns are NOT run over Python source generally. Code is full of
# numeric literals -- indices, thresholds, weights -- and a check that fires on
# every one of them is noise that gets switched off within a week.
_GATE = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "verify_claims.sh"
_GATE_HEREDOC_RE = re.compile(r"<<'PY'\n(.*?)\nPY\n", re.S)
_GATE_FUNCS = {"_uncode", "strip_exempt_spans", "quantity_phrases",
               "normalize_claim_sentence", "normalize_chapter_blocks"}


def _gate_definitions(source=None):
    """The citation gate's own patterns and helpers, executed from its source.

    Selects the module-level regex assignments and the few helpers this sweep
    needs, compiles just those statements, and returns the namespace. Nothing is
    copied, so the two cannot drift, and a pattern renamed in the gate fails
    loudly rather than leaving this sweep on a stale copy: an assertion here for
    the names this sweep asks for, and a NameError the first time a helper is
    called for the ones only those helpers close over. A rename that keeps the
    ``_RE`` suffix and is applied consistently is the one shape that stays
    silent, and correctly so -- the keep-filter selects on the suffix, so the
    renamed pattern is still extracted and still used.
    """
    source = source or _GATE
    body = _GATE_HEREDOC_RE.search(source.read_text(encoding="utf-8"))
    assert body, "verify_claims.sh no longer embeds its python in a <<'PY' heredoc"
    tree = ast.parse(body.group(1))
    keep = []
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and (node.targets[0].id.endswith("_RE")
                     or node.targets[0].id == "SECTION_MARK")):
            keep.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in _GATE_FUNCS:
            keep.append(node)
    namespace = {"re": re}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(source), "exec"), namespace)
    for name in _GATE_FUNCS | {"NUM_RE", "WORD_RE", "NUM_OK_RE"}:
        assert name in namespace, f"{name} is no longer defined in {source.name}"
    return namespace


# A source locator -- module.py:31, 00-thesis.md:78 -- names a line. It is a
# pointer like the gate's own chapter and layer references, never a measurement,
# and it is the dominant idiom in a file whose job is to cite chapter prose. The
# range form of a chapter reference is here for the same reason: the gate reads
# "chapters 03 and 04" and not "chapters 00 through 05".
_LOCATOR_RE = re.compile(
    r"\b[\w./-]+\.(?:py|md|sh|json|jsonl|txt|ya?ml|js|ts|cfg|ini|toml):\d+(?:-\d+)?\b"
)
# Zero-padded on purpose, and this sweep caught the unpadded draft itself.
# num-ok: 30 and 50 are the illustrative span this comment invents to name the hole, not a measurement of anything
# The unpadded form read "30 to 50 hosts" as a chapter range and silenced it; a
# chapter in this handbook is always written zero-padded, 00 through 05.
_CHAPTER_RANGE_RE = re.compile(
    r"(?i)\b(?:chapters?\s+)?0\d\s*(?:-|--|to|through)\s*0\d\b"
)
# A labelled ordinal is a name. "Claim three", "Stage two", "Round one" are
# positional exactly as a markdown list marker is, and the gate's own note on the
# marker is the reason: "a marker's digit is positional only [...] so exempting
# it cannot hide a real measurement." Aimed at the label, so a bare cardinal
# standing beside one still fires.
#
# version, law and check are deliberately NOT on this list, though they read like
# labels. Each numbers something this repository pins elsewhere and can therefore
# get wrong: the persistence schema's version (whose documented shape was one of
# this audit's own corrections), the five laws, and the citation gate's checks. A
# wrong "version N" is the class of error this sweep exists to catch, so it has
# to stay visible.
_LABEL_RE = re.compile(
    r"(?i)\b(?:claim|stage|step|task|phase|round|mutant|fix)"
    r"\s+\d+\b"
)
# A quoted span reproduced from a chapter carries that chapter's numbers, and
# Check A already swept them where they live. Elisions are split on, because a
# long quote is usually carried with [...] in the middle.
#
# How far the self-tightening goes, measured rather than assumed. Edit the
# chapter and the quotation stops matching, so the span comes back into scope --
# but a quantity inside it only starts firing again if nothing else exempts it,
# and in this repository the usual something else is grounding. Break the
# three-line chapter quotation in test_chapter_claims.py's fifth claim group and
# every cardinal inside it stays silent, because each one is also a numeric
# literal elsewhere in that same file. So: self-tightening for any quantity the
# module's own literals do not already ground, which is every spelled quantity
# and every digit the module never writes. The composition is pinned in the probe
# below rather than left to this comment.
_QUOTED_RE = re.compile(r'"([^"]{8,})"', re.S)
_ELISION_RE = re.compile(r"\[\.\.\.\]")
# A fragment shorter than this is not looked for in the corpus, because the
# elision split leaves short connective scraps ("and", "so that") that match
# something in a corpus of that size by accident and would exempt the whole span
# on nothing. The floor is a false-negative risk in one direction only, so it is
# overridden for any fragment that actually carries a quantity: without that
# override, a quotation ending in an unquoted bare number was silent.
_MIN_QUOTE_FRAGMENT = 12


def _chapter_corpus(root=None):
    """Every chapter paragraph, normalised the way the anchor gate normalises."""
    gate = _gate_definitions()
    root = root or _repo_root()
    blocks = []
    for md in sorted(list((root / "handbook").glob("*.md")) + [root / "README.md"]):
        blocks.extend(gate["normalize_chapter_blocks"](md.read_text(encoding="utf-8")))
    return blocks


def _carries_quantity(fragment, gate):
    """Whether a quotation fragment holds a quantity, however short it is.

    The length floor above exists to stop a connective scrap matching the corpus
    by accident. It must not also wave through the one thing this sweep is for,
    so a fragment carrying a digit, a quantity word or a quantity phrase is
    corpus-checked at any length.
    """
    return bool(
        gate["NUM_RE"].search(fragment)
        or gate["WORD_RE"].search(fragment)
        or gate["quantity_phrases"](fragment)
    )


def _blank_chapter_quotations(text, corpus, gate):
    """Blank the quoted spans this corpus already carries, keep the rest."""
    def replace(match):
        fragments = [
            gate["normalize_claim_sentence"](f)
            for f in _ELISION_RE.split(match.group(1))
        ]
        checked = [
            f for f in fragments
            if len(f) >= _MIN_QUOTE_FRAGMENT or _carries_quantity(f, gate)
        ]
        if checked and all(any(f in block for block in corpus) for f in checked):
            # Blank the characters, keep the newlines. Replacing the whole span
            # with spaces collapsed a multi-line quotation onto a single line, so
            # every later line of that docstring was reported under the wrong
            # number -- in a sweep whose escape hatch is defined as "the line
            # above", which makes an off-by-N the one error it cannot afford.
            return re.sub(r"[^\n]", " ", match.group(0))
        return match.group(0)
    return _QUOTED_RE.sub(replace, text)


def _prose_of(path, corpus=None, gate=None):
    """Docstrings and comments only -- never the code around them.

    Returns (lineno, text) per prose LINE rather than per docstring, because
    the num-ok escape hatch is defined against the line above and a whole
    docstring has no such thing. Quoted spans are resolved over the docstring
    or the run of comment lines as a whole first, so a chapter quotation
    carried across a line break is still recognised as one.

    Line at a time is also what the gate does to markdown, so a quantity phrase
    split by a line break is missed here exactly as it is missed there.
    """
    gate = gate or _gate_definitions()
    corpus = _chapter_corpus() if corpus is None else corpus
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)

    spans = []
    for node in ast.walk(tree):
        if not isinstance(node, _DOC_NODES):
            continue
        body = getattr(node, "body", None)
        if not body or not isinstance(body[0], ast.Expr):
            continue
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            spans.append((value.lineno, value.end_lineno or value.lineno))

    prose = {}
    for start, end in spans:
        blob = "\n".join(lines[start - 1:end]).replace('"""', "   ").replace("'''", "   ")
        blanked = _blank_chapter_quotations(blob, corpus, gate).splitlines()
        for offset, line in enumerate(_drop_literal_blocks(blanked)):
            if line is not None:
                prose[start + offset] = line.strip()

    runs, current = [], []
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#") and number not in prose:
            current.append((number, stripped.lstrip("#").strip()))
            continue
        if current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    for run in runs:
        blob = _blank_chapter_quotations("\n".join(t for _, t in run), corpus, gate)
        for (number, _), line in zip(run, blob.splitlines()):
            prose[number] = line
    return sorted(prose.items())


def _drop_literal_blocks(lines):
    """None out the reST literal blocks in a docstring, keep everything else.

    A block introduced by a line ending in ``::`` and indented past it is a
    listing -- a schema sketch, a usage example, a table of tiers. The citation
    gate exempts a fenced markdown block for exactly that reason, in its own
    words: "that is not a claim about the world, it is a listing." This is the
    same object in reST clothing, and the modules still to be written will carry
    their examples the same way.

    Both directions are probed, and the silent one is the load-bearing one: a
    number inside an example must stay silent, and a number in the prose right
    above it must still fire.
    """
    out = []
    block_indent = None
    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if block_indent is not None:
            if not stripped or indent > block_indent:
                out.append(None)
                continue
            block_indent = None
        out.append(line)
        if stripped.endswith("::"):
            block_indent = indent
    return out


def _module_numbers(path):
    """Every numeric literal in *path*'s code, as floats.

    A digit in a docstring that names a literal in the module it documents is
    cited, in the sense the gate's [[code:...]] citation is: existence, not
    location. The comparison is numeric, so a docstring naming an integer
    threshold is grounded by a source that writes it as a float. Spelled
    quantities get no such grounding -- a word never appears in the source it
    describes, and a spelled count of a code artifact is precisely the shape
    this must not excuse.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            found.add(float(node.value))
    return found


def _as_annotation(text, gate):
    """The reason in a num-ok annotation on this line, or None.

    Two spellings, one pattern: the chapters' ``<!-- num-ok: ... -->`` and the
    bare ``num-ok: ...`` a Python comment or docstring line can carry without
    the HTML ceremony. The bare form is rewritten into the chapters' form and
    read by the gate's own NUM_OK_RE, so the reason requirement cannot drift.
    """
    candidate = text
    if re.match(r"(?i)^num-ok\b", text.strip()):
        candidate = "<!-- " + text.strip() + " -->"
    match = gate["NUM_OK_RE"].match(candidate)
    return match.group(1).strip() if match else None


def _as_float(token):
    """A NUM_RE token as a float, or None when it will not parse as one."""
    try:
        return float(token.replace(",", "").rstrip("%"))
    except ValueError:
        return None


def _quantity_misses(path, corpus=None, gate=None):
    """Uncited quantities in *path*'s docstrings and comments, as messages."""
    gate = gate or _gate_definitions()
    grounded = _module_numbers(path)
    prose = dict(_prose_of(path, corpus=corpus, gate=gate))

    annotations = {}
    for number, text in prose.items():
        reason = _as_annotation(text, gate)
        if reason is not None:
            annotations[number + 1] = reason

    misses = []
    for number, text in sorted(prose.items()):
        own_reason = _as_annotation(text, gate)
        if own_reason is not None:
            # An empty reason is the violation, not a free pass on top of one --
            # the same ruling the gate makes on an empty chapter annotation.
            if not own_reason:
                misses.append(f"{path}:{number}: num-ok annotation has no reason")
            continue
        stripped = _LABEL_RE.sub(
            " ", _CHAPTER_RANGE_RE.sub(" ", _LOCATOR_RE.sub(" ", text))
        )
        cleaned = gate["strip_exempt_spans"](stripped)
        numbers = [t for t in gate["NUM_RE"].findall(cleaned)
                   if _as_float(t) not in grounded]
        words = gate["WORD_RE"].findall(cleaned)
        phrases = gate["quantity_phrases"](cleaned)
        reason = annotations.get(number)
        if reason is not None:
            covered_numbers = {_as_float(t) for t in gate["NUM_RE"].findall(reason)}
            covered_words = {w.lower() for w in gate["WORD_RE"].findall(reason)}
            covered_phrases = set(gate["quantity_phrases"](reason))
            numbers = [t for t in numbers if _as_float(t) not in covered_numbers]
            words = [w for w in words if w.lower() not in covered_words]
            phrases = [p for p in phrases if p not in covered_phrases]
            suffix = "not covered by the num-ok reason"
        else:
            suffix = "in prose"
        for token in numbers:
            misses.append(f"{path}:{number}: uncited number {token!r} {suffix}")
        for token in words:
            misses.append(f"{path}:{number}: uncited quantity word {token!r} {suffix}")
        for token in phrases:
            misses.append(f"{path}:{number}: uncited quantity phrase {token!r} {suffix}")
    return misses


def test_every_quantity_in_a_docstring_is_cited_or_annotated():
    root = _repo_root()
    gate = _gate_definitions()
    corpus = _chapter_corpus(root)
    misses = []
    for path in _swept_paths(root):
        misses.extend(
            m.replace(str(root) + "/", "")
            for m in _quantity_misses(path, corpus=corpus, gate=gate)
        )
    assert not misses, "uncited quantities in docstrings and comments:\n" + "\n".join(misses)


# --- Probes for the sweep's own exemptions --------------------------------
#
# Every exemption below is a hole by construction, so each one is probed in
# both directions: the shape it excuses must stay silent, and a real quantity
# beside that shape must still fire. The silent direction is the one that rots
# unnoticed, which is why it is asserted rather than described.


def _misses(tmp_path, source, corpus=(), name="planted.py"):
    planted = tmp_path / name
    planted.write_text(source, encoding="utf-8")
    return [m.split(": ", 1)[1] for m in _quantity_misses(planted, corpus=list(corpus))]


def test_the_sweep_reads_prose_and_never_the_code_around_it(tmp_path):
    """A quantity in code stays silent; the same quantity in prose does not.

    The planted code carries a SPELLED quantity, not a digit: a digit written
    into code is a literal in that module and would be exempt for the other
    reason, so it could not tell the two mechanisms apart.
    """
    found = _misses(tmp_path, (
        '"""A module that mentions 300 endpoints."""\n'
        "# and 900 of them in a comment\n"
        'LABEL = "fifteen rows of output"\n'
        "def f(x):\n"
        "    return x[47] + 1024\n"
    ))
    assert found == ["uncited number '300' in prose",
                     "uncited number '900' in prose"], found


def test_a_literal_block_in_a_docstring_is_a_listing(tmp_path):
    """The example is silent, the sentence introducing it is not."""
    found = _misses(tmp_path, (
        '"""Sketch.\n'
        "\n"
        "    We saw 300 of them, shaped like this::\n"
        "\n"
        '        {"timeout": 10, "retries": 4}\n'
        "\n"
        "    and 900 after that.\n"
        '    """\n'
    ))
    assert found == ["uncited number '300' in prose",
                     "uncited number '900' in prose"], found


def test_a_grounded_digit_is_cited_and_a_spelled_count_is_not(tmp_path):
    """A literal in the same module cites a digit, and never a quantity word."""
    found = _misses(tmp_path, (
        '"""Documents 15, which is TIER_HIGH, and 16, which is nothing.\n'
        "\n"
        "    The table has two columns.\n"
        '    """\n'
        "TIER_HIGH = 15.0\n"
        "COLUMNS = 2\n"
    ))
    assert found == ["uncited number '16' in prose",
                     "uncited quantity phrase 'two columns' in prose"], found


def test_both_num_ok_spellings_cover_only_what_they_name(tmp_path):
    """Either spelling is read, and neither excuses the rest of its line."""
    found = _misses(tmp_path, (
        "# <!-- num-ok: 0.3 is FATIGUE_FLOOR, a literal -->\n"
        "# The floor is 0.3, and this cut runtime by 42 per cent.\n"
        "# num-ok: 0.4 is CORRELATION_THRESHOLD, a literal\n"
        "# The threshold is 0.4.\n"
        "# num-ok:\n"
        "# An empty reason earns nothing, so 900 still fires.\n"
    ))
    assert found == ["uncited number '42' not covered by the num-ok reason",
                     "num-ok annotation has no reason",
                     "uncited number '900' not covered by the num-ok reason"], found


def test_a_chapter_quotation_is_exempt_only_while_it_is_verbatim(tmp_path):
    """Quote a chapter and the numbers are its; misquote it and they are yours.

    The corpus is injected rather than read from handbook/, so this probe pins
    the mechanism and not the current wording of any chapter.

    The fixture carries module literals on purpose, because the first version did
    not and could therefore not see the interaction it exists to guard: a drifted
    quotation whose number is also a literal in that module stays silent, caught
    by grounding on the way back. A probe simpler than the tree tests the fixture.
    """
    corpus = ["We scanned 300 endpoints across the estate, and 47 of them answered."]
    template = (
        '"""The chapter says:\n'
        "\n"
        '    "We scanned 300 endpoints across the {}, and 47 of them answered."\n'
        '    """\n'
        "GROUNDED = 47\n"
    )
    exact = _misses(tmp_path, template.format("estate"), corpus, name="exact.py")
    assert exact == [], exact
    drifted = _misses(tmp_path, template.format("region"), corpus, name="drifted.py")
    # The drifted quotation's first cardinal comes back, because nothing else
    # covers it. Its second does not: the fixture writes that one as a module
    # literal, so grounding catches it on the way back. That is the limit of the
    # self-tightening, and it is the reason this fixture has literals at all.
    assert drifted == ["uncited number '300' in prose"], drifted

    # And the length floor does not wave a short numeric fragment through. A
    # quotation is exempt as a whole or not at all, so the trailing bare number
    # failing its corpus check brings the whole span back -- which is why all
    # three cardinals are listed here and not just the trailing one.
    short = _misses(
        tmp_path,
        '"""It said "We scanned 300 endpoints across the estate, and 47 of them answered. [...] 4711"."""\n',
        corpus,
        name="short.py",
    )
    assert short == ["uncited number '300' in prose",
                     "uncited number '47' in prose",
                     "uncited number '4711' in prose"], short


def test_a_locator_and_a_labelled_ordinal_are_not_measurements(tmp_path):
    """The pointer is silent and the cardinal standing next to it is not."""
    found = _misses(tmp_path, (
        '"""See core/scheduler.py:677 and handbook/00-thesis.md:78-80.\n'
        "\n"
        "    Claim 3 and Round 2 and chapters 00 through 05, but 300 of them.\n"
        "\n"
        "    A span between two real counts, 30 to 50, is not a chapter range.\n"
        '    """\n'
    ))
    assert found == ["uncited number '300' in prose",
                     "uncited number '30' in prose",
                     "uncited number '50' in prose"], found


def test_the_sweep_moves_when_the_gate_moves(tmp_path):
    """The patterns are the gate's own, so widening one widens this sweep.

    Proof rather than assertion: the gate's source is copied with one cardinal
    added to WORD_RE's alternation, and the definitions loaded from the copy
    read a quantity word the real gate does not. A transcribed pattern would
    leave the two free to drift, and this is what rules that out.
    """
    marker = "    r\"eleven|twelve"
    real = _GATE.read_text(encoding="utf-8")
    assert marker in real, "WORD_RE's alternation is no longer written this way"
    scratch = tmp_path / "verify_claims.sh"
    scratch.write_text(real.replace(marker, "    r\"seven|eleven|twelve", 1), encoding="utf-8")
    assert not _gate_definitions()["WORD_RE"].search("seven hosts refused the probe")
    assert _gate_definitions(scratch)["WORD_RE"].search("seven hosts refused the probe")


# --- The gates' own prose -------------------------------------------------
#
# The gate stack is written in shell, and until this sweep existed no gate
# read a word of it. That is not a hypothetical hole. Three false claims about
# what a gate guarantees were found in a handful of lines of
# scripts/verify_claims.sh's own header -- one of them the replacement written
# for the first -- and the census above could not see any of them, because it
# walks *.py under tests/ and core/ while those sentences live in a .sh file.
#
# Same detector, same ledger, same contract as the docstrings: CLAIM_RE
# decides what counts as a claim, docstring_claims_audited.txt holds the
# verdicts, and a claim nobody has audited is the failure. CLAIM_RE is reused
# rather than restated on purpose -- a second copy of that alternation would
# drift from this one, and a transcription is the error this repository keeps
# making.
#
# NO HEREDOC PARSING IS NEEDED, and that is measured rather than assumed:
# verify_claims.sh embeds its Python in a <<'PY' heredoc, but that Python's
# comments open with # exactly as the shell's do, so an own-line-# sweep
# reaches both. The probe below asserts the heredoc's own claim count is not
# zero and that every claim-bearing block inside it is in the census, so a
# sweep that stopped reaching in there would fail rather than go quiet.
#
# What is out of scope, stated rather than left to be discovered: a comment
# TRAILING code on the same line. Telling that # from a # inside a quoted
# regex or a printf format string needs a shell parser, and all four scripts
# write their claim prose as own-line comments -- the trailing-# population is
# measured in the ledger entry for this block rather than described here.
_SHELL_GLOBS = (("scripts", "**/*.sh"), ("tests", "**/*.sh"))

# Recursive, for the reason core/**/*.py is: a gate script added under
# scripts/ci/ or tests/probes/ would be unswept by a flat glob, and the hole
# would be invisible until someone planted a claim in it.
_COMMENT_RE = re.compile(r"^[ \t]*#(.*)$")


def _shell_paths(root=None):
    root = root or _repo_root()
    out = []
    for subdir, pattern in _SHELL_GLOBS:
        out.extend((root / subdir).glob(pattern))
    return sorted(set(out))


def _comment_blocks(text):
    """Own-line comment runs, split at a bare # the way a paragraph break is.

    A run of consecutive comment lines is one block, and a comment line
    carrying nothing but # ends it, because that is how all four scripts write
    a paragraph break. Without that split a long header making several
    separate claims collapses into a single verdict, and one verdict cannot
    honestly carry the observable for all of them. A line of code ends a
    block too. Line 1's shebang is dropped rather than read as the opening
    line of the header below it.
    """
    blocks, current, start = [], [], None
    for number, line in enumerate(text.splitlines(), 1):
        match = _COMMENT_RE.match(line)
        body = match.group(1) if match else None
        if number == 1 and body is not None and body.startswith("!"):
            body = None
        if body is None or not body.strip():
            if current:
                blocks.append((start, current))
            current, start = [], None
            continue
        if not current:
            start = number
        current.append(body.strip())
    if current:
        blocks.append((start, current))
    return blocks


def _block_key(bodies):
    """A key that moves when the claim's wording moves, and not when it does not.

    A line number rots on the first insertion above it, and an enclosing
    function name collapses every top-level block in a script onto a single
    key, so neither identifies a claim in a shell script. This key is a slug
    of the opening words plus a hash of the block's reflowed text: the slug is
    what a reader greps for, the hash is what re-opens the audit when the
    wording changes. Reflowing to a single line before hashing means a rewrap
    keeps its verdict while an edit to the words does not, which is the
    property this surface needs -- a corrected claim here was once replaced by
    a second false one, and a key blind to that edit would have carried the
    old verdict over.
    """
    reflowed = " ".join(" ".join(bodies).split())
    digest = hashlib.sha1(reflowed.encode("utf-8")).hexdigest()[:8]
    words = re.findall(r"[a-z0-9]+", bodies[0].lower())[:4]
    return f"{'-'.join(words) or 'block'}-{digest}"


def _claim_bearing_comments(path):
    """Every comment block in `path` that asserts a mechanism, keyed and located."""
    out = []
    for start, bodies in _comment_blocks(path.read_text(encoding="utf-8")):
        if any(CLAIM_RE.search(body) for body in bodies):
            out.append((_block_key(bodies), start, bodies[0]))
    return out


def _gate_prose_keys(root=None):
    """(key, locator) for every claim-bearing comment block in the gate scripts."""
    root = root or _repo_root()
    out = []
    for path in _shell_paths(root):
        for key, lineno, first in _claim_bearing_comments(path):
            rel = path.relative_to(root)
            out.append((f"{rel}::{key}", f"  ({rel}:{lineno}: {first[:70]})"))
    return out


# The four gate scripts, named here only so the probes below can copy the real
# thing rather than a fixture that resembles it. The sweep itself reads the
# globs above, so a fifth script is picked up without this list changing; what
# this list pins is that a planted claim is surfaced in each of the scripts
# the README points a reader at.
_GATE_SCRIPTS = ("scripts/verify_claims.sh", "scripts/prose_check.sh",
                 "scripts/audit.sh", "tests/test_gates.sh")

_PLANTED_CLAIM = "# This gate never lets an out-of-scope host through."
_PLANTED_QUIET = "# Written on a Tuesday, in the usual editor, by the usual hands."


def test_the_gate_prose_sweep_reaches_a_nested_and_a_new_script(tmp_path):
    """Where a claim in shell could hide from this census.

    A flat scripts/*.sh could not see scripts/ci/, and neither glob would see
    a script added under tests/probes/. Both are found by planting rather than
    by reading the globs, which is how the same hole was found in the Python
    census, so both stay planted. A .md beside them is not a shell script and
    is not swept.
    """
    for rel in ("scripts/new_gate.sh", "scripts/ci/deep.sh",
                "tests/probes/nested.sh", "scripts/notes.md"):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("#!/usr/bin/env bash\n" + _PLANTED_CLAIM + "\n", encoding="utf-8")
    found = sorted(str(p.relative_to(tmp_path)) for p in _shell_paths(tmp_path))
    assert found == ["scripts/ci/deep.sh", "scripts/new_gate.sh",
                     "tests/probes/nested.sh"], found
    keys = [k for k, _ in _gate_prose_keys(tmp_path)]
    assert len(keys) == 3, keys
    assert all("this-gate-never-lets" in k for k in keys), keys


def test_a_planted_claim_is_surfaced_in_each_of_the_four_gate_scripts(tmp_path):
    """One planted claim per real script, and one planted non-claim beside it.

    The scripts are copied, never edited in place, and the claim is planted in
    the copy: a sweep that cannot see a planted claim in audit.sh -- three
    comment lines, one of them a shebang -- is not covering audit.sh at all,
    and nothing else in this file would say so. The quiet comment is the other
    half: a sweep that surfaces it is not discriminating, it is just listing
    comments.
    """
    root = _repo_root()
    for rel in _GATE_SCRIPTS:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            (root / rel).read_text(encoding="utf-8")
            + f"\n{_PLANTED_CLAIM}\n\n{_PLANTED_QUIET}\n",
            encoding="utf-8",
        )
    keys = [k for k, _ in _gate_prose_keys(tmp_path)]
    for rel in _GATE_SCRIPTS:
        planted = f"{rel}::{_block_key([_PLANTED_CLAIM[2:]])}"
        quiet = f"{rel}::{_block_key([_PLANTED_QUIET[2:]])}"
        assert planted in keys, (rel, planted, keys)
        assert quiet not in keys, (rel, quiet)


def test_the_sweep_reads_the_heredoc_python_comments():
    """The reason this sweep needs no heredoc parsing, asserted on the real file.

    verify_claims.sh runs its Python inside a <<'PY' heredoc. Those comments
    open with # exactly as the shell's do, so the own-line-# sweep reaches
    them, and the claim-bearing blocks in there are the Check A, B, C and D
    headers -- the largest concentration of guarantee-prose in the repository.
    Asserted rather than argued because the alternative reading is expensive
    and wrong: a sweep believed to need a heredoc parser is a sweep somebody
    writes a second time.
    """
    gate = _repo_root() / "scripts" / "verify_claims.sh"
    text = gate.read_text(encoding="utf-8")
    inner = _GATE_HEREDOC_RE.search(text)
    assert inner, "verify_claims.sh no longer embeds its Python in a <<'PY' heredoc"
    first = text[: inner.start(1)].count("\n") + 1
    last = first + inner.group(1).count("\n")
    lines = [
        number
        for number, line in enumerate(text.splitlines(), 1)
        if first <= number <= last and _COMMENT_RE.match(line) and CLAIM_RE.search(line)
    ]
    assert len(lines) > 20, lines
    inside = [
        key
        for key, lineno, _first in _claim_bearing_comments(gate)
        if first <= lineno <= last
    ]
    census = [k.split("::", 1)[1] for k, _ in _gate_prose_keys() if "verify_claims" in k]
    assert inside, "no claim-bearing comment block inside the heredoc"
    assert set(inside) <= set(census), (set(inside) - set(census))


def test_a_comment_paragraph_is_one_verdict_and_a_bare_hash_ends_it(tmp_path):
    """The granularity contract, in both directions.

    A wrapped paragraph making one claim is one verdict -- a key per comment
    line would make the ledger unreadable and the verdicts unwritable. Two
    paragraphs separated by a bare # are two verdicts, because a long header in
    verify_claims.sh makes several independent claims and one verdict cannot
    carry the observable for all of them. A line of code ends a
    block, and the shebang is not part of the header that follows it.
    """
    planted = tmp_path / "scripts" / "g.sh"
    planted.parent.mkdir(parents=True)
    planted.write_text(
        "#!/usr/bin/env bash\n"
        "# One claim, wrapped across\n"
        "# three comment lines, which never\n"
        "# becomes three verdicts.\n"
        "#\n"
        "# A second paragraph, which fails on its own terms.\n"
        "set -uo pipefail\n"
        "# A third, after a line of code, that refuses to merge upward.\n",
        encoding="utf-8",
    )
    blocks = _comment_blocks(planted.read_text(encoding="utf-8"))
    assert [(start, len(bodies)) for start, bodies in blocks] == [
        (2, 3), (6, 1), (8, 1)
    ], blocks
    assert [lineno for _key, lineno, _first in _claim_bearing_comments(planted)] == [
        2, 6, 8
    ]


def test_a_rewrap_keeps_a_verdict_and_a_reworded_claim_asks_for_a_new_one():
    """Why the key carries a hash of the prose and not just a slug.

    A slug alone would carry a verdict across a rewrite of the sentence it
    judged, which is exactly the failure this task was written for: on this
    surface a corrected claim was replaced by a second false one. A hash of
    the reflowed text keeps the verdict through a pure rewrap, where nothing
    was claimed differently, and drops it the moment a word changes -- the
    ledger then reports the old key as an orphan and the new one as unaudited,
    which is the audit re-opening rather than a failure.
    """
    wrapped = ["A claim about what this gate", "never lets through."]
    rewrapped = ["A claim about what this", "gate never lets through."]
    reworded = ["A claim about what this gate", "rarely lets through."]
    assert _block_key(wrapped) == _block_key(rewrapped)
    assert _block_key(wrapped) != _block_key(reworded)
    assert _block_key(wrapped).startswith("a-claim-about-what-")
