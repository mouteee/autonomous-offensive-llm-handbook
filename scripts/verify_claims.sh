#!/usr/bin/env bash
# Citation gate. Every `[[stats:KEY.PATH]]` must resolve in data/stats.json,
# every `[[code:file.py:symbol]]` must resolve in core/ -- as a substring of
# that file, which proves existence and never location -- every digit in
# chapter prose outside the exemptions Check A names, and every spelled
# quantity Check A's four patterns read, must be cited or annotated by name
# (Check A), every relative handbook-to-handbook markdown link must point at
# a file that exists (Check B), every chapter sentence a claim test anywhere
# under tests/ declares itself to back must still be present in its chapter
# after normalisation (Check C), and an identifier named alongside a bare
# core/*.py path in the same sentence must be found in one of the files that
# sentence names, unless the sentence carries a negation cue (Check D). Each
# check's own header records what it does not reach; none of them is as broad
# as its one-line summary here. Exits 1 listing misses.
set -uo pipefail
TARGET="${1:-handbook}"
python3 - "$TARGET" <<'PY'
import ast, json, os, pathlib, re, sys

target = pathlib.Path(sys.argv[1])
root = pathlib.Path(os.environ.get("HANDBOOK_ROOT", "."))
stats = json.loads((root / "data" / "stats.json").read_text())

def resolve(doc, path):
    cur = doc
    for part in path.split("."):
        if isinstance(cur, list):
            try: cur = cur[int(part)]
            except (ValueError, IndexError): return False
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return False
    return True

files = sorted(target.rglob("*.md")) if target.is_dir() else [target]
misses = []
for f in files:
    text = f.read_text(encoding="utf-8")
    for n, line in enumerate(text.splitlines(), 1):
        for key in re.findall(r"\[\[stats:([^\]]+)\]\]", line):
            if not resolve(stats, key):
                misses.append(f"{f}:{n}: unresolved stats key {key!r}")
        for ref in re.findall(r"\[\[code:([^\]]+)\]\]", line):
            fname, _, symbol = ref.partition(":")
            src = root / "core" / fname
            if not src.exists():
                misses.append(f"{f}:{n}: no such file core/{fname}")
            elif not symbol:
                misses.append(f"{f}:{n}: no symbol named in citation core/{fname}")
            elif symbol not in src.read_text(encoding="utf-8"):
                misses.append(f"{f}:{n}: {symbol!r} not found in core/{fname}")

# --- Check A: uncited numbers in chapter prose ----------------------------
# A quantity typed as ordinary prose ("we scanned 300 endpoints") is
# invisible to the stats-key check above unless it is written as a
# [[stats:...]] citation. Nothing mechanical caught that shape of mistake
# before this check existed: three invented figures in chapter 00 were
# caught only because the author happened to notice them while writing.
#
# Spelled quantities are read in four shapes, because a spelled quantity
# claim does not always contain a cardinal and never contains a digit:
# WORD_RE for the cardinals and the vague quantifiers (dozen, couple),
# FRACTION_RE for a fraction in partitive position, RATIO_RE for the ratio
# idioms, and ARTIFACT_COUNT_RE for a cardinal counting a code artifact.
# RATIO_RE needs its own pattern rather than a longer alternation because
# each half of "three in ten" is separately innocuous.
# All four report through the same list and take the same num-ok escape
# hatch as the digit check. Two known false positives, both from RATIO_RE
# taking any word as its leading half: "at times the", where that word is
# not a quantifier at all, and "in ten <unit>" -- "finished in ten minutes"
# -- where the ten is a duration and not a denominator. Either shape has to
# be annotated like any other match.
#
# Where the cardinal line is drawn, and why it stays there: WORD_RE starts
# at eleven, so a spelled cardinal at ten or below is not matched. That
# exemption is the original decision, kept -- and it now carries the
# measurement it was made without. As of commit 0e84607, removing the floor
# -- adding one..ten to the alternation -- makes THIS GATE report 507
# further matches on 260 of the 688 non-blank lines in the six chapters and
# the README, 274 of the 507 being the single token "one", which this prose
# also uses as a pronoun and as a determiner -- "the other one", "one of
# which", "one for governance" -- where it quantifies nothing and so has
# nothing to cite.
#
# The sha is load-bearing, not decoration. This is a measurement this
# repository takes over its own chapters, so every commit that edits a
# chapter moves it, and the figures above went stale four times while this
# note was being written for exactly that reason. Anchored to the tree they
# were taken on, they are a fact about that tree and cannot rot; published
# as bare numbers they would be wrong again by the next chapter edit. They
# are also counts this gate prints rather than counts of the raw text, which
# is why the reproduction is the gate and not a grep. One line re-derives
# them on any tree, from the repository root:
#
#   sed 's/r"eleven|twelve/r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve/' \
#     scripts/verify_claims.sh > /tmp/wide.sh && chmod +x /tmp/wide.sh &&
#     HANDBOOK_ROOT=. /tmp/wide.sh handbook; HANDBOOK_ROOT=. /tmp/wide.sh README.md
#
# Clearing that set means a citation, an annotation or a deletion on each
# of those 260 lines, every annotation a newly written claim of its own, to
# reach the matches that are real measurements. The boundary is pinned by a
# probe in tests/test_gates.sh rather than left to this comment, so widening
# the alternation turns a test red instead of passing unnoticed.
#
# ARTIFACT_COUNT_RE covers the gap that exemption leaves, without reopening
# it. The shape the floor cannot read is not the small cardinal in general,
# it is the small cardinal counting a code artifact -- "two columns" for a
# three-column table, "fifteen lines" for a 29-line function -- so the
# pattern pairs a spelled cardinal below twenty with an artifact noun and
# reads that shape only. The structural vocabulary the exemption exists to
# protect is untouched: "two orchestrators", "four layers" and "five laws"
# stay silent, and both directions are pinned in tests/test_gates.sh.
#
# Bare digits get no such exemption: a digit is exactly as cheap to cite as
# it is to type, small or large -- "Layer 0" is forgiven only because it
# names a section of the document (LAYER_REF_RE), not because 0 is a small
# number -- so only the named categories below (citation, a fenced code
# block, an inline backtick span that is more than a bare numeral, an inline
# HTML comment, a link/filename, a chapter-, section-, or layer-reference, a
# bare year, a leading markdown ordered-list marker, or an explicit num-ok
# annotation naming that literal) ever exempt a digit. Those same
# categories are stripped before the spelled-quantity patterns run too,
# since strip_exempt_spans() is shared. The HTML-comment category is a hole
# and not only ceremony: any inline comment is blanked whether or not it is
# a num-ok annotation, so a quantity written inside one on a prose line is
# exempt and unread. Recorded here rather than closed, because blanking
# fewer spans is a decision about the gate and not a correction to this
# sentence. It is also one half of a pair, recorded together so neither gets
# fixed into a half-true property: the OTHER half is the annotation line, whose
# own text is never swept at all -- a figure invented inside a num-ok reason
# ("measured across 900 scans") is read by nothing, because a matching
# annotation line is consumed and skipped. Both are this check trusting comment
# content it should be reading, and they close together or not at all.
#
# The list marker is its own
# category rather than a chapter-00 special case: "1." opening a numbered
# item is rendering syntax in any chapter that uses an ordered list, on
# par with a bullet character, and never itself the quantity being claimed
# -- unlike a table cell, whose content is prose the table is merely
# arranging, a marker's digit is positional only, always 1, 2, 3.. in
# order, so exempting it cannot hide a real measurement.
#
# An inline backtick span is exempt only when its entire content is code
# or a formula -- `0.8 ** consecutive_failures` and `Score = (Base x
# Relevance x Impact) / Cost` stay exempt because there is an operator or
# a name in there beyond the digits. A span that is nothing but a bare
# numeral, `0.91`, is a disclosed measurement wearing a code costume, not
# code, so it is unwrapped back into prose and scanned like any other
# number. And a num-ok annotation exempts only the literal token(s) its
# own reason text names, not the rest of the line it sits above: a reason
# that explains 0.3 does not also license an unrelated 42 on the same
# line to go uncited, which would turn the escape hatch into exactly the
# invention channel it exists to close.
#
# KNOWN AND NOT FIXED, and stated as the condition rather than as a list
# of what slips past it: a token on the excused line is covered when the
# reason's own text carries the same token, which compares the token and
# not what it refers to. So an annotation reasoning about one 8 exempts
# every other 8 on the line it excuses, whatever those other ones count,
# while a 42 the reason never names still fires. This belongs with the
# pair recorded above and is deferred on the same terms: covering it means
# positional matching, whose false-positive cost is a design question,
# and covering the inline-comment hole means a distinction between an
# own-line and an inline comment that Check D reads too. Each is this
# check trusting comment content it should be reading, and a fix to one
# alone leaves the property only partly true, so they close together or
# not at all.
NUM_RE = re.compile(r"\b\d+(?:[.,]\d+)*\b%?")
WORD_RE = re.compile(
    r"(?i)\b("
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen"
    r"|nineteen"
    r"|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
    r"|hundred|thousand|million|billion"
    r"|dozen|couple"
    r")s?\b"
)
# A fraction word is a quantity only in partitive position -- "a third OF
# them", "half THE corpus". The same word in ordinal position names an item
# ("the third law") or is not a quantity at all ("the third party"), which
# is why the following "of"/"the" is required rather than the word matched
# bare.
FRACTION_RE = re.compile(
    r"(?i)\b(?:half|halves|third|thirds|quarter|quarters|fifth|fifths)"
    r"\s+(?:of|the)\b"
)
# The ratio idioms. The leading word is deliberately any word, not a
# cardinal list: "many times the mean" and "nine out of ten" are the same
# claim shape, and restricting the leading half to cardinals would read the
# second and miss the first.
RATIO_RE = re.compile(
    r"(?i)\b[a-z]+\s+(?:in|out\s+of)\s+(?:ten|twenty|hundred|thousand)\b"
    r"|\b[a-z]+\s+times\s+(?:the|as)\b"
)
# A cardinal counting a code artifact. Aimed at the observed error class --
# a count of columns, lines, call sites, tests -- rather than at small
# cardinals in general, so the noun list is what makes it discriminating:
# "two columns" is read and "two orchestrators" is not, which is how the
# below-twenty exemption above survives beside it. Same narrowing move as
# Check D, and the same trade: a count of something not on this list is
# missed rather than guessed at.
#
# THE THREE EDGES, written down rather than left to be found. This pattern
# is narrow on purpose, and a reader is owed its limits in the same place
# as its behaviour.
#
# 1. The noun list is itself a floor. A real count of something not on it
#    goes unread, and the corpus has one: "six components" in chapter 01,
#    "because six components is a decision about what the system is allowed
#    to learn from" -- a count of the components the profile hash projects
#    the profile down to, which is exactly the kind of claim this pattern
#    exists for, and "components" is not a noun it lists.
#
# 2. Adjacency is required. The noun has to follow the cardinal, through at
#    most an "of", so one intervening word defeats the match. Also already
#    in the corpus, all three silent today while their adjacent forms fire:
#    "two middle rows" (chapter 00), "four more fields" (chapter 05) and
#    "three decimal places" (chapter 01), against "two rows", "four fields"
#    and "three places", which are read.
#
# 3. Any addition to the noun list re-runs the must-stay-silent probe in
#    tests/test_gates.sh. The reach of an addition is not intuitive: adding
#    layers, laws and orchestrators to this list -- three words that read as
#    harmless -- makes the pattern fire on the handbook's own structural
#    vocabulary, which is the one thing the exemption above exists to keep
#    out. Widen the list and that probe is the check that the exemption
#    still means something.
ARTIFACT_COUNT_RE = re.compile(
    r"(?i)\b(?:one|two|three|four|five|six|seven|eight|nine|ten"
    r"|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen"
    r"|nineteen)"
    r"\s+(?:of\s+)?"
    r"(?:columns?|lines?|entries|entry|call\s+sites?|callers?|files?|sites?"
    r"|places?|instances?|rows?|fields?|methods?|functions?|arguments?"
    r"|parameters?|commits?|tests?|assertions?|branch(?:es)?|modules?|keys?)"
    r"\b"
)
FENCE_RE = re.compile(r"^\s*```")
LIST_MARKER_RE = re.compile(r"^\s{0,3}\d{1,3}\.\s+")
CITATION_RE = re.compile(r"\[\[(?:stats|code):[^\]]*\]\]")
INLINE_CODE_RE = re.compile(r"`([^`]+)`")
BARE_NUMERAL_SPAN_RE = re.compile(r"^\s*\d+(?:[.,]\d+)*%?\s*$")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->")
MD_LINK_TARGET_RE = re.compile(r"\]\([^)]*\)")
AUTOLINK_RE = re.compile(r"<https?://[^>]*>")
BARE_URL_RE = re.compile(r"https?://\S+")
FILENAME_RE = re.compile(
    r"\b[\w./-]+\.(?:py|md|sh|json|jsonl|txt|ya?ml|js|ts|cfg|ini|toml)\b"
)
CHAPTER_REF_RE = re.compile(
    r"(?i)\bchapters?\s+\d{1,3}(?:\s*(?:,|and|&)\s*\d{1,3})*\b"
)
SECTION_MARK = chr(0xA7)  # section sign, spelled this way so the script's
                          # own source bytes stay plain ASCII regardless of
                          # the caller's locale -- see prose_check.sh's
                          # locale comment for why that independence matters
SECTION_REF_RE = re.compile(SECTION_MARK + r"\s?\d+(?:\.\d+)?")
LAYER_REF_RE = re.compile(r"(?i)\blayer\s+\d+\b")
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
NUM_OK_RE = re.compile(r"^\s*<!--\s*num-ok\b\s*:?\s*(.*?)\s*-->\s*$")

def quantity_phrases(text):
    """Multi-word quantity matches, whitespace-collapsed and lowered.

    FRACTION_RE, RATIO_RE and ARTIFACT_COUNT_RE each match a phrase rather
    than a single token, so coverage by a num-ok reason is compared on the
    phrase itself: a reason has to name "three in ten", not merely happen
    to contain the words three and ten somewhere in it.
    """
    return [
        re.sub(r"\s+", " ", m.group(0)).strip().lower()
        for pat in (FRACTION_RE, RATIO_RE, ARTIFACT_COUNT_RE)
        for m in pat.finditer(text)
    ]


def _uncode(m):
    # Keep a backticked span's own text when it is nothing but a bare
    # numeral (a measurement in a code costume); blank everything else
    # (real code, a formula, an identifier) so it stays exempt.
    inner = m.group(1)
    return inner if BARE_NUMERAL_SPAN_RE.match(inner) else " "

def strip_exempt_spans(line):
    line = LIST_MARKER_RE.sub("", line, count=1)
    line = CITATION_RE.sub(" ", line)
    line = INLINE_CODE_RE.sub(_uncode, line)
    line = HTML_COMMENT_RE.sub(" ", line)
    line = MD_LINK_TARGET_RE.sub("]", line)
    line = AUTOLINK_RE.sub(" ", line)
    line = BARE_URL_RE.sub(" ", line)
    line = FILENAME_RE.sub(" ", line)
    line = CHAPTER_REF_RE.sub(" ", line)
    line = SECTION_REF_RE.sub(" ", line)
    line = LAYER_REF_RE.sub(" ", line)
    line = YEAR_RE.sub(" ", line)
    return line

uncited = []
for f in files:
    text = f.read_text(encoding="utf-8")
    in_fence = False
    pending_reason = None
    for n, line in enumerate(text.splitlines(), 1):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        ann = NUM_OK_RE.match(line)
        if ann:
            reason = ann.group(1).strip()
            if not reason:
                uncited.append(f"{f}:{n}: num-ok annotation has no reason")
            # Only a *reasoned* annotation earns the next line an escape --
            # an empty one is the violation, not a free pass on top of it.
            pending_reason = reason or None
            continue
        cleaned = strip_exempt_spans(line)
        found_numbers = NUM_RE.findall(cleaned)
        found_words = WORD_RE.findall(cleaned)
        found_phrases = quantity_phrases(cleaned)
        if pending_reason is not None:
            # The annotation excuses only the literal token(s) it names,
            # not the whole line: anything else numeric on this line still
            # has to earn its own citation or annotation.
            reason_numbers = set(NUM_RE.findall(pending_reason))
            reason_words = {w.lower() for w in WORD_RE.findall(pending_reason)}
            reason_phrases = set(quantity_phrases(pending_reason))
            for tok in found_numbers:
                if tok not in reason_numbers:
                    uncited.append(
                        f"{f}:{n}: uncited number {tok!r} "
                        "not covered by the num-ok reason"
                    )
            for tok in found_words:
                if tok.lower() not in reason_words:
                    uncited.append(
                        f"{f}:{n}: uncited quantity word {tok!r} "
                        "not covered by the num-ok reason"
                    )
            for tok in found_phrases:
                if tok not in reason_phrases:
                    uncited.append(
                        f"{f}:{n}: uncited quantity phrase {tok!r} "
                        "not covered by the num-ok reason"
                    )
            pending_reason = None
            continue
        for tok in found_numbers:
            uncited.append(f"{f}:{n}: uncited number {tok!r} in prose")
        for tok in found_words:
            uncited.append(f"{f}:{n}: uncited quantity word {tok!r} in prose")
        for tok in found_phrases:
            uncited.append(f"{f}:{n}: uncited quantity phrase {tok!r} in prose")

# --- Check B: handbook-to-handbook cross-references -----------------------
# File existence only. Anchors (the part after '#') are not validated.
LINK_RE = re.compile(r"\]\(([^)]+)\)")
SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")

badlinks = []
for f in files:
    text = f.read_text(encoding="utf-8")
    in_fence = False
    for n, line in enumerate(text.splitlines(), 1):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for target_str in LINK_RE.findall(line):
            path_part, _, _anchor = target_str.partition("#")
            if not path_part or SCHEME_RE.match(path_part):
                continue  # same-page anchor, or an external/mailto scheme
            if not path_part.lower().endswith(".md"):
                continue  # only handbook-chapter targets are in scope
            candidate = (
                root / path_part.lstrip("/")
                if path_part.startswith("/")
                else f.parent / path_part
            )
            if not candidate.exists():
                badlinks.append(
                    f"{f}:{n}: broken cross-reference to {path_part!r}"
                )

# --- Check C: chapter sentences a claim test declares itself to back ------
# tests/test_chapter_claims.py pins CODE behaviour; until this check existed,
# nothing ever read the CHAPTER sentence a given test was supposedly backing.
# A test could keep asserting true things about core/ forever while the
# prose it was written to support drifted, or was simply wrong from the
# start, and the suite stayed green throughout -- exactly the shape of two
# real errors chapter 01's review found. Each claim test now declares, via
# a `chapter_claim(chapter, *sentences)` decorator, the chapter file and the
# verbatim sentence(s) it backs. This check parses that declaration with the
# stdlib `ast` module -- no import of the test module, no pytest collection,
# so a collection error in the test file (a broken import, a syntax slip)
# cannot silently take this check down with it -- and fails when a declared
# sentence is no longer present in its chapter, or when a chapter test has
# no declaration at all.
#
# Normalisation, applied identically to the chapter side and the declared
# sentence, and deliberately narrow -- the task's own instruction was to be
# conservative, because normalising harder makes it easier for a changed
# fact to still match:
#   - a fenced code block is dropped before anything else runs, so a
#     sentence can never be satisfied by a code listing;
#   - the chapter is then split into blocks on blank lines, markdown's own
#     paragraph boundary, and each block's internal newlines (i.e. ordinary
#     line-wrap inside one paragraph) collapse to single spaces -- but nothing
#     ever merges two different blocks, so two separate paragraphs can never
#     fuse into an accidental match;
#   - a [[stats:...]] / [[code:...]] citation is removed -- it is citation
#     ceremony a reader quoting the sentence by hand would not type;
#   - an HTML comment is removed for the same reason: a num-ok annotation
#     typically sits immediately above its paragraph with no blank line
#     between them, so without this it would fuse into the block it precedes;
#   - a backtick is removed but its contents kept, since `requires` reads as
#     requires to a reader quoting the sentence.
# Nothing else changes: no case-folding, no punctuation-stripping, no
# whitespace-insensitive fuzzy matching beyond the paragraph-internal
# line-wrap named above. A changed fact still has to fail -- unless the anchor
# quoting it was changed in the same edit, and that limit is worth stating here
# rather than leaving a reader to infer it from the driver. The decorator is the
# only copy of the sentence this check has, so a sentence and its anchor edited
# together are compared with each other and match. Tightening the comparison
# does not reach it: exact matching, bounded matching and hashing all read the
# anchor, so all of them pass a coordinated edit too. Containment also accepts a
# fragment, so an anchor trimmed to part of a sentence stops pinning the rest.
# What guards a coordinated edit is a content assertion holding its own
# expectation -- tests/test_chapter_claims.py, ADMISSION_CLAUSE -- and a human
# reading the diff. The law-line comparison beside it does a different job and
# does not guard this case: it compares two documents, so it fires when the
# README's copy of a law diverges from chapter 00's and stays silent when both
# are edited together (run: one law reworded in both files leaves every gate
# green and the suite passing). tests/test_gates.sh probes both directions of
# this boundary and says which one is silent on purpose.
#
# Chapter existence (below, "declares a chapter that does not exist") and
# anchor coverage ("has no chapter_claim() anchor") are checked against every
# claim test unconditionally, because both are properties of tests/ and
# never differ by invocation. Sentence-presence is checked only for a
# chapter that falls within this invocation's TARGET (i.e. is a member of
# `files`, computed above): a synthetic probe run against a throwaway
# directory must never be failed by the real handbook's real, current
# anchor status, only by what it planted itself.
CHAPTER_CLAIM_DECORATOR = "chapter_claim"


def normalize_chapter_blocks(text):
    lines = []
    in_fence = False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        lines.append(line)
    blocks, current = [], []
    for line in lines:
        if line.strip() == "":
            if current:
                blocks.append("\n".join(current))
                current = []
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return [normalize_claim_sentence(b) for b in blocks]


def normalize_claim_sentence(s):
    s = HTML_COMMENT_RE.sub(" ", s)
    s = CITATION_RE.sub(" ", s)
    s = s.replace("`", "")
    return re.sub(r"\s+", " ", s).strip()


def extract_chapter_claims(py_path):
    """Return (anchors, unanchored, malformed) via ast -- no import, no exec.

    anchors: (py_path, lineno, test_name, chapter, sentence) per declared
    sentence. unanchored: (py_path, lineno, test_name) for a test_* function
    with no chapter_claim decorator, in a file that uses the decorator at
    least once. malformed: (py_path, lineno, test_name) for a decorator
    call this parser cannot make sense of (not a plain string-literal call).
    """
    tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
    anchors, seen_functions, file_uses_decorator = [], [], False
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_"):
            continue
        has_anchor = False
        for dec in node.decorator_list:
            if not (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Name)
                and dec.func.id == CHAPTER_CLAIM_DECORATOR
            ):
                continue
            file_uses_decorator = True
            has_anchor = True
            try:
                args = [ast.literal_eval(a) for a in dec.args]
            except ValueError:
                args = []
            if len(args) < 2 or not all(isinstance(a, str) for a in args):
                anchors.append((py_path, node.lineno, node.name, None, None))
                continue
            chapter, *sentences = args
            for sentence in sentences:
                anchors.append((py_path, node.lineno, node.name, chapter, sentence))
        seen_functions.append((node.lineno, node.name, has_anchor))
    unanchored = (
        [(py_path, lineno, name) for lineno, name, has in seen_functions if not has]
        if file_uses_decorator
        else []
    )
    return anchors, unanchored


claim_misses = []
resolved_files = {f.resolve() for f in files}
chapter_block_cache = {}
tests_dir = root / "tests"
for py_path in sorted(tests_dir.rglob("*.py")) if tests_dir.is_dir() else []:
    anchors, unanchored = extract_chapter_claims(py_path)
    for py_file, lineno, test_name, chapter, sentence in anchors:
        if chapter is None:
            claim_misses.append(
                f"{py_file}:{lineno}: {test_name} has a chapter_claim() this "
                "gate cannot parse (expected string-literal arguments)"
            )
            continue
        chapter_path = (root / chapter).resolve()
        if not chapter_path.exists():
            claim_misses.append(
                f"{py_file}:{lineno}: {test_name} declares chapter {chapter!r}, "
                "which does not exist"
            )
            continue
        if chapter_path not in resolved_files:
            continue  # chapter out of scope for this invocation's TARGET
        if chapter_path not in chapter_block_cache:
            chapter_block_cache[chapter_path] = normalize_chapter_blocks(
                chapter_path.read_text(encoding="utf-8")
            )
        needle = normalize_claim_sentence(sentence)
        if not any(needle in block for block in chapter_block_cache[chapter_path]):
            claim_misses.append(
                f"{py_file}:{lineno}: {test_name} claims a sentence not found "
                f"in {chapter}: {sentence!r}"
            )
    for py_file, lineno, test_name in unanchored:
        claim_misses.append(
            f"{py_file}:{lineno}: {test_name} has no chapter_claim() anchor"
        )

# --- Check D: a symbol named alongside a file must live in that file ------
# Three shipped errors, none caught by any check above, all the same shape:
# a sentence (twice inside a num-ok reason, which nothing before this check
# ever read) named a file and named a symbol together, and the symbol was
# not in that file. [[code:file.py:symbol]] already proves a cited symbol
# exists -- but only for prose that uses that citation syntax. Free-form
# prose that instead says "X lives in core/whatever.py" was never checked
# at all, in either direction.
#
# SCOPE, DELIBERATELY NARROW -- read this before assuming more coverage
# than exists:
#   - This catches misattribution to the WRONG FILE ONLY. It cannot tell a
#     module-level constant from a class attribute (the second of the three
#     real errors), and it cannot check a count claim ("five tools", "21
#     conditions") against anything (the third). Both stay on human review;
#     this check does not attempt either.
#   - An identifier counts if it is backtick-wrapped AND the entire
#     backtick span is nothing but an identifier shape: `[A-Za-z_]\w*`,
#     optionally with a trailing `()`. A formula, a condition string, a
#     quoted comment, or a bare value (`0.65`) is not a symbol to resolve,
#     by construction of that same pattern -- no separate value/formula
#     denylist is needed.
#   - BACKTICKING AN IDENTIFIER IS THE PREFERRED CONVENTION, and the rule
#     above is how this check reads it. The branch below is a safety net
#     for when an author does not, not a second style to write in: all
#     three real errors this check exists for wrote their identifier and
#     file bare, inside a num-ok reason, so without this branch the check
#     would not have caught any of them as actually written. A BARE
#     (unbackticked) token also counts, but only if its shape is one no
#     ordinary English word has by accident: it contains an underscore
#     (`hash_similarity`, `from_dict`), or it is internally capitalised --
#     an upper-case letter, a run of lower-case, then another upper-case
#     (`SmartScheduler`, `TargetProfile`) -- which a plain capitalised word
#     or an all-caps acronym (`SPA`, `WAF`) does not have, or it is
#     followed by `()` (`record()`), which plain English never is even
#     though the bare word alone (`record`, `adjust`) constantly is. A
#     bare lower-case word with none of those three shapes is never
#     treated as a symbol, on purpose: matching every bare word would
#     drown this check in false positives on ordinary prose.
#   - A file-name mention (anything ending .py, .md, and the other
#     extensions Check A already recognises) is stripped before bare-token
#     scanning, so a phrase like "pinned in tests/test_chapter_claims.py"
#     cannot be misread as a claim that a symbol named test_chapter_claims
#     exists -- that word is a filename component, not an identifier, and
#     the underscore rule alone cannot tell those apart without this.
#   - A sentence naming a file with no qualifying identifier beside it
#     is not a violation; there is nothing to check.
#   - A sentence naming more than one core/*.py file passes an identifier
#     found in ANY of them. Which file a multi-file sentence means for a
#     given identifier is not inferred; forcing a guess here would risk
#     failing a true, correctly-hedged sentence, which is the one failure
#     mode explicitly ruled out below.
#
# NEGATION. "`_tools_tried` is not restored by `from_dict`" is a true and
# useful claim of absence, and this check must not fail it just because
# the named symbol is, correctly, not in the file. Handled by skipping a
# whole sentence when it contains a negation cue, rather than trying to
# scope the negation to one identifier: precise enough for the shape of
# sentence this handbook actually writes, and erring toward a missed
# error over a false failure on a true one, which is the direction every
# check in this gate has erred when the two trade off against each other.
#
# SENTENCE, for this check, is: a num-ok comment's own text (its own unit,
# since it usually sits on the line directly above its paragraph with no
# blank line to separate them), or a blank-line-delimited paragraph
# elsewhere, split on ordinary sentence punctuation after fenced code is
# dropped and internal line-wrap collapses to single spaces -- the same
# block-then-split shape Check C already uses, so a sentence can span a
# wrapped line but two paragraphs can never fuse into one accidental match.
FILE_MENTION_RE = re.compile(r"\bcore/[\w./-]*\.py\b")
IDENTIFIER_SHAPE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\(\))?$")
BACKTICK_SPAN_RE = re.compile(r"`([^`]*)`")
BARE_TOKEN_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)(\(\))?")
CAMEL_INTERNAL_CAP_RE = re.compile(r"[A-Z][a-z0-9]+[A-Z]")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
NEGATION_RE = re.compile(
    r"(?i)\b(?:not|never|cannot|isn't|doesn't|don't|n't|absent from|"
    r"missing from|nowhere in|no longer)\b"
)
COMMENT_LINE_RE = re.compile(r"^\s*<!--(.*)-->\s*$")


def bare_token_qualifies(name, has_parens):
    return bool(has_parens or "_" in name or CAMEL_INTERNAL_CAP_RE.search(name))


def extract_identifiers(sentence):
    found = []
    for inner in BACKTICK_SPAN_RE.findall(sentence):
        if IDENTIFIER_SHAPE_RE.match(inner):
            found.append(inner[:-2] if inner.endswith("()") else inner)
    # Bare tokens are scanned only OUTSIDE backticks, citations, and
    # filenames, so a formula, a [[code:...]] citation, or a path like
    # tests/test_chapter_claims.py is never mined for a qualifying
    # sub-word it was never making a claim about.
    remainder = CITATION_RE.sub(" ", sentence)
    remainder = BACKTICK_SPAN_RE.sub(" ", remainder)
    remainder = FILENAME_RE.sub(" ", remainder)
    for m in BARE_TOKEN_RE.finditer(remainder):
        name, parens = m.group(1), m.group(2)
        if bare_token_qualifies(name, bool(parens)):
            found.append(name)
    return found


def sentence_units(text):
    lines = text.splitlines()
    kept = []
    in_fence = False
    for i, line in enumerate(lines, 1):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        kept.append((i, line))

    blocks = []
    current, current_start = [], None
    for lineno, line in kept:
        m = COMMENT_LINE_RE.match(line)
        if m:
            if current:
                blocks.append((current_start, "\n".join(current)))
                current, current_start = [], None
            blocks.append((lineno, m.group(1)))
            continue
        if line.strip() == "":
            if current:
                blocks.append((current_start, "\n".join(current)))
                current, current_start = [], None
        else:
            if not current:
                current_start = lineno
            current.append(line)
    if current:
        blocks.append((current_start, "\n".join(current)))

    for start_lineno, block in blocks:
        joined = re.sub(r"\s+", " ", block).strip()
        for sentence in SENTENCE_SPLIT_RE.split(joined):
            sentence = sentence.strip()
            if sentence:
                yield start_lineno, sentence


attribution_misses = []
for f in files:
    text = f.read_text(encoding="utf-8")
    source_cache = {}
    for lineno, sentence in sentence_units(text):
        files_named = sorted(set(FILE_MENTION_RE.findall(sentence)))
        if not files_named:
            continue
        identifiers = extract_identifiers(sentence)
        if not identifiers:
            continue  # naming a file with no qualifying identifier is fine
        if NEGATION_RE.search(sentence):
            continue  # a true claim of absence must not fail here
        sources = []
        for fname in files_named:
            if fname not in source_cache:
                fp = root / fname
                source_cache[fname] = (
                    fp.read_text(encoding="utf-8") if fp.exists() else None
                )
            sources.append(source_cache[fname])
        for name in set(identifiers):
            if not any(src is not None and name in src for src in sources):
                attribution_misses.append(
                    f"{f}:{lineno}: sentence claims {name!r} lives in "
                    f"{' or '.join(files_named)}, but it is not there: "
                    f"{sentence!r}"
                )

if misses or uncited or badlinks or claim_misses or attribution_misses:
    if misses:
        print("CLAIM VERIFICATION FAIL:")
        print("\n".join(misses))
    if uncited:
        print("UNCITED NUMBER FAIL:")
        print("\n".join(uncited))
    if badlinks:
        print("CROSS-REFERENCE FAIL:")
        print("\n".join(badlinks))
    if claim_misses:
        print("CHAPTER CLAIM FAIL:")
        print("\n".join(claim_misses))
    if attribution_misses:
        print("FILE ATTRIBUTION FAIL:")
        print("\n".join(attribution_misses))
    sys.exit(1)
print(f"claims verified: {len(files)} file(s)")
PY
