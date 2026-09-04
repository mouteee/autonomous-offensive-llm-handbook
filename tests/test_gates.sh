#!/usr/bin/env bash
# Every gate this file plants against -- audit.sh, prose_check.sh, and each of
# verify_claims.sh's four checks -- must FAIL on a planted violation and PASS
# on clean input, and the sanitization gate must also come back clean over the
# repository itself. The pytest gates wired in at the end are RUN and not
# probed: nothing here plants a violation for them, so what this sweep
# guarantees about them is only that a failure in one of them fails the sweep.
# That sentence used to open on a count of those gates, and the count was
# false: it said three, written when there were three, and a fourth was wired
# in four days later without it being touched. A total is the wrong thing to
# put in a comment beside the list it counts, because the next task to append
# to that list invalidates it silently, so the count is gone rather than
# corrected.
set -uo pipefail
cd "$(dirname "$0")/.."
export HANDBOOK_ROOT=.
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/probe"

# LAYER 1 (sanitization): scripts/audit.sh is the gate that keeps client,
# employer and host identifiers out of a public repository, and it was the only
# layer in the stack with no probe in either direction and no caller here. Two
# consequences were both reproduced before this block existed: a DENY
# expression neutered to match nothing still printed "sanitization clean", and
# a live employer name planted mid-chapter left "gates verified" unchanged,
# because nothing in this sweep ran audit.sh at all.
#
# So: run it over the repository, and probe it in both directions.
#
# The planted token is assembled from two fragments at runtime, and that is
# load-bearing rather than decorative. A literal denylist match written into
# this file would be found by audit.sh itself on the very next sweep of the
# tree, so the self-test would fail the gate it exists to verify. Nothing under
# $TMP is inside the repository, so the assembled value is never published. It
# is also deliberately NOT read out of audit.sh's own DENY expression: an
# expectation derived from the denylist would still be met by a denylist that
# had been gutted, which is the first of the two failures above.
OUT=$(bash scripts/audit.sh . 2>&1) || { echo "FAIL: sanitization gate reports the repository unclean"; echo "$OUT"; exit 1; }

# That sweep ran the gate over the repository and threw everything but the exit
# status away, which is the defect this block closes. audit.sh announces which
# denylist state it ran under and exits 0 under every one of them, so on the
# operator's own checkout the private half could be missing, empty or
# unreadable and the whole pre-publication run would still print "gates
# verified" -- the neutered-denylist failure from the top of this file, one
# level out, with the announcement that would have shown it going unread. Two
# assertions, and the split between them is what makes them capable.
#
# First, unconditionally: the sweep has to announce a scope at all. Deleting
# the announcement from audit.sh fails here and, measured, nowhere else.
echo "$OUT" | grep -q '^sanitization scope: ' || { echo "FAIL: sanitization gate swept the repository without announcing what it swept"; echo "$OUT"; exit 1; }

# Second, gated on the private denylist EXISTING rather than on what is inside
# it. A public clone has no private half and nothing to assert, which is why
# this is not unconditional and why its absence is not a failure. Where the
# file is there, the only one of the announcements that describes a sweep of
# both halves is the merged one, so anything else means the employer, client
# and host patterns were not applied to the tree about to be published.
# Existence rather than content is the load-bearing choice: an expectation
# derived from the file's patterns would be satisfied by a file whose patterns
# had been removed, which is the same mistake the DENY fragments above are
# assembled by hand to avoid. Empty scripts/.denylist, or chmod 000 it, and
# this fails.
if [ -e scripts/.denylist ]; then
  echo "$OUT" | grep -q '^sanitization scope: published patterns and the private denylist$' || { echo "FAIL: scripts/.denylist is present but the sweep of the repository did not merge it"; echo "$OUT"; exit 1; }
fi

mkdir -p "$TMP/sanitize"
printf 'A paragraph naming no client, no employer and no host.\n' > "$TMP/sanitize/clean.md"
OUT=$(bash scripts/audit.sh "$TMP/sanitize" 2>&1) || { echo "FAIL: sanitization gate rejected clean input"; exit 1; }
echo "$OUT" | grep -q 'sanitization clean' || { echo "FAIL: sanitization gate passed clean input without saying so"; exit 1; }

DENY_FRAGMENT_A='open'; DENY_FRAGMENT_B='router'
printf 'The key was read out of the %s%s dashboard.\n' "$DENY_FRAGMENT_A" "$DENY_FRAGMENT_B" > "$TMP/sanitize/planted.md"
OUT=$(bash scripts/audit.sh "$TMP/sanitize" 2>&1)
STATUS=$?
if [ "$STATUS" -eq 0 ]; then echo "FAIL: sanitization gate passed a planted denylist identifier"; exit 1; fi
echo "$OUT" | grep -q 'SANITIZATION FAIL' || { echo "FAIL: sanitization gate failed without reporting why"; exit 1; }
echo "$OUT" | grep -q 'planted.md' || { echo "FAIL: sanitization gate did not name the file it found the identifier in"; exit 1; }
rm "$TMP/sanitize/planted.md"
bash scripts/audit.sh "$TMP/sanitize" >/dev/null || { echo "FAIL: sanitization gate stayed red after the planted identifier was removed"; exit 1; }
unset DENY_FRAGMENT_A DENY_FRAGMENT_B OUT

# A target this gate cannot read is a HARD FAILURE, not a clean report, and
# that is the same defect as the neutered denylist above seen from the other
# side: until this was fixed, a mistyped path printed "sanitization clean" and
# exited 0, so the gate reported success for a tree it never opened. Three
# directions, because the three are separate code paths: a path that does not
# exist, a target directory that cannot be opened, and a target that opens but
# holds a file grep cannot read -- a partial sweep is not a clean one. The
# fourth direction is the one that keeps the other three honest: the same
# directory, readable, must still pass.
OUT=$(bash scripts/audit.sh "$TMP/sanitize/no-such-dir" 2>&1)
if [ $? -eq 0 ]; then echo "FAIL: sanitization gate reported a nonexistent target clean"; exit 1; fi
echo "$OUT" | grep -q 'no such path' || { echo "FAIL: sanitization gate failed on a missing target without saying so: $OUT"; exit 1; }
echo "$OUT" | grep -q 'no-such-dir' || { echo "FAIL: sanitization gate did not name the missing path: $OUT"; exit 1; }

# chmod cannot create an unreadable file for a uid that ignores file modes, so
# these two are skipped there rather than asserted into a false pass.
if [ "$(id -u)" -ne 0 ]; then
    mkdir -p "$TMP/sanitize/shut"; chmod 000 "$TMP/sanitize/shut"
    OUT=$(bash scripts/audit.sh "$TMP/sanitize/shut" 2>&1)
    if [ $? -eq 0 ]; then echo "FAIL: sanitization gate reported an unopenable directory clean"; exit 1; fi
    echo "$OUT" | grep -q 'unreadable path' || { echo "FAIL: sanitization gate failed on an unopenable directory without saying so: $OUT"; exit 1; }
    chmod 755 "$TMP/sanitize/shut"; rmdir "$TMP/sanitize/shut"

    printf 'nothing to see\n' > "$TMP/sanitize/locked.md"; chmod 000 "$TMP/sanitize/locked.md"
    OUT=$(bash scripts/audit.sh "$TMP/sanitize" 2>&1)
    if [ $? -eq 0 ]; then echo "FAIL: sanitization gate reported clean over a file it could not read"; exit 1; fi
    echo "$OUT" | grep -q 'did not finish' || { echo "FAIL: sanitization gate swallowed an incomplete sweep: $OUT"; exit 1; }
    chmod 644 "$TMP/sanitize/locked.md"; rm -f "$TMP/sanitize/locked.md"
fi

bash scripts/audit.sh "$TMP/sanitize" >/dev/null || { echo "FAIL: sanitization gate rejected a target that exists and is readable"; exit 1; }
unset OUT

printf '# a clean heading\n\nPlain text with a citation [[stats:corpus.scans.total]].\n' > "$TMP/probe/ok.md"
./scripts/prose_check.sh "$TMP/probe" >/dev/null || { echo "FAIL: prose gate rejected clean input"; exit 1; }
./scripts/verify_claims.sh "$TMP/probe" >/dev/null || { echo "FAIL: claim gate rejected a real key"; exit 1; }

printf '# bad\n\nThis serves as a testament — delving into the landscape of things.\n' > "$TMP/probe/bad.md"
if ./scripts/prose_check.sh "$TMP/probe" >/dev/null 2>&1; then echo "FAIL: prose gate passed AI tells"; exit 1; fi
rm "$TMP/probe/bad.md"

printf 'Cites [[stats:no.such.key]] and [[code:nope.py:missing]].\n' > "$TMP/probe/miss.md"
if ./scripts/verify_claims.sh "$TMP/probe" >/dev/null 2>&1; then echo "FAIL: claim gate passed a bogus citation"; exit 1; fi

# FIX 1 (locale): the prose gate must not depend on the caller's locale. Under
# a plain POSIX/C locale the Unicode bracket expressions degrade into raw
# byte-set matching; the gate must pin its own locale before grep runs so
# this text -- which has no curly quote and no emoji -- stays clean, while
# genuine instances of either still fire.
mkdir -p "$TMP/locale"
printf 'Caf\xc3\xa9 na\xc3\xafve r\xc3\xa9sum\xc3\xa9\xe2\x80\xa6 \xe2\x80\xa2 a normal bullet\n' > "$TMP/locale/clean.md"
if ! LC_ALL=POSIX ./scripts/prose_check.sh "$TMP/locale" >/dev/null 2>&1; then echo "FAIL: prose gate misfired on plain UTF-8 text under a POSIX locale"; exit 1; fi
rm "$TMP/locale/clean.md"

printf 'She said \xe2\x80\x9chello\xe2\x80\x9d to the room.\n' > "$TMP/locale/quote.md"
if LC_ALL=POSIX ./scripts/prose_check.sh "$TMP/locale" >/dev/null 2>&1; then echo "FAIL: prose gate missed a genuine curly quote under a POSIX locale"; exit 1; fi
rm "$TMP/locale/quote.md"

printf 'Shipping fast \xf0\x9f\x9a\x80 today.\n' > "$TMP/locale/emoji.md"
if LC_ALL=POSIX ./scripts/prose_check.sh "$TMP/locale" >/dev/null 2>&1; then echo "FAIL: prose gate missed a genuine emoji under a POSIX locale"; exit 1; fi
rm "$TMP/locale/emoji.md"

# FIX 2 (empty symbol): a code citation naming no symbol must not pass on
# file existence alone.
mkdir -p "$TMP/symbol"
printf 'Cites [[code:fingerprint.py]].\n' > "$TMP/symbol/a.md"
if ./scripts/verify_claims.sh "$TMP/symbol" >/dev/null 2>&1; then echo "FAIL: claim gate passed a symbol-less citation"; exit 1; fi

printf 'Cites [[code:fingerprint.py:]].\n' > "$TMP/symbol/a.md"
if ./scripts/verify_claims.sh "$TMP/symbol" >/dev/null 2>&1; then echo "FAIL: claim gate passed a trailing-colon empty-symbol citation"; exit 1; fi

printf 'Cites [[code:fingerprint.py:TargetProfile]].\n' > "$TMP/symbol/a.md"
./scripts/verify_claims.sh "$TMP/symbol" >/dev/null || { echo "FAIL: claim gate rejected a real symbol citation"; exit 1; }

# CHECK A (uncited numbers): a numeral or spelled-out quantity in chapter
# prose must be cited, annotated, or fall into a named exemption. Each probe
# below runs in its own fresh directory, since $TMP/probe carries a
# permanently-failing file (miss.md, above) from this point on.
mkdir -p "$TMP/numbers"

printf 'We scanned 300 endpoints across the estate.\n' > "$TMP/numbers/a.md"
if ./scripts/verify_claims.sh "$TMP/numbers" >/dev/null 2>&1; then echo "FAIL: uncited-number gate passed a bare digit in prose"; exit 1; fi
rm "$TMP/numbers/a.md"

printf 'Forty endpoints answered before the scan gave up.\n' > "$TMP/numbers/a.md"
if ./scripts/verify_claims.sh "$TMP/numbers" >/dev/null 2>&1; then echo "FAIL: uncited-number gate passed a spelled-out quantity word"; exit 1; fi
rm "$TMP/numbers/a.md"

# BOUNDARY, deliberate and pinned here: a spelled cardinal at ten or below is
# not matched by WORD_RE, so the chapter-00 "the four layers" / "three gates"
# case stays silent. The note above WORD_RE in verify_claims.sh records the
# measurement behind that exemption; ARTIFACT_COUNT_RE, probed further down,
# is what reads the small cardinals that do carry a claim. This probe exists
# so that widening the alternation turns a test red and forces the decision,
# instead of the boundary living only in a comment nothing checks.
printf 'The four layers rank decisions by how derivable each one is, across three gates.\n' > "$TMP/numbers/a.md"
./scripts/verify_claims.sh "$TMP/numbers" >/dev/null || { echo "FAIL: a spelled cardinal at ten or below is no longer exempt -- widen deliberately, then update this probe and the note above WORD_RE"; exit 1; }
rm "$TMP/numbers/a.md"

# A stats citation is exempt even when its own key path contains a digit
# (a list index, e.g. "excluded.0.false_positives" -- a real shape in
# data/stats.json), proving the whole [[stats:...]] span is skipped rather
# than the check getting lucky on digit-free key names.
printf 'Total volume: [[stats:corpus.scans.total]]. First excluded run: [[stats:benchmark.juice_shop.excluded.0.false_positives]].\n' > "$TMP/numbers/a.md"
./scripts/verify_claims.sh "$TMP/numbers" >/dev/null || { echo "FAIL: uncited-number gate flagged a digit inside a stats citation path"; exit 1; }
rm "$TMP/numbers/a.md"

# Numbers inside a fenced code block stay silent -- that is not a claim
# about the world, it is a listing.
printf '# fenced numbers stay quiet\n\n```\nBase = 300\n```\n' > "$TMP/numbers/a.md"
./scripts/verify_claims.sh "$TMP/numbers" >/dev/null || { echo "FAIL: uncited-number gate flagged a digit inside a code fence"; exit 1; }
rm "$TMP/numbers/a.md"

# A backtick span that is nothing but a bare numeral is a measurement in a
# code costume, not code -- it must fire like any other uncited number.
printf 'We ran `847` scans across `219` hosts.\n' > "$TMP/numbers/a.md"
if ./scripts/verify_claims.sh "$TMP/numbers" >/dev/null 2>&1; then echo "FAIL: uncited-number gate passed a bare backticked numeral"; exit 1; fi
rm "$TMP/numbers/a.md"

# A backticked code expression or formula -- an operator or a name beyond
# the digits -- is still genuinely code and stays exempt.
printf 'Fatigue decays at `0.8 ** consecutive_failures` and the score is `Score = (Base x Relevance x Impact) / Cost`.\n' > "$TMP/numbers/a.md"
./scripts/verify_claims.sh "$TMP/numbers" >/dev/null || { echo "FAIL: uncited-number gate flagged a backticked code expression or formula"; exit 1; }
rm "$TMP/numbers/a.md"

# A bare year and a chapter/section/layer reference are not measurements.
printf 'Written in 2026, this refers to chapter 03 and Layer 0 only.\n' > "$TMP/numbers/a.md"
./scripts/verify_claims.sh "$TMP/numbers" >/dev/null || { echo "FAIL: uncited-number gate flagged a bare year or a chapter/layer reference"; exit 1; }
rm "$TMP/numbers/a.md"

# A leading ordered-list marker ("1.", "2.", ...) is list syntax, not a
# claimed quantity -- this is the handbook's own five-numbered-laws shape.
printf '1. **First law.** No number claimed here.\n\n2. **Second law.** Still none.\n' > "$TMP/numbers/a.md"
./scripts/verify_claims.sh "$TMP/numbers" >/dev/null || { echo "FAIL: uncited-number gate flagged an ordered-list marker"; exit 1; }
rm "$TMP/numbers/a.md"

# Escape hatch: a reasoned num-ok annotation excuses the number on the very
# next line.
printf '<!-- num-ok: CVSS 9.0 is a fixed threshold from the CVSS v3.1 specification, not a measurement -->\nA CVSS score of 9.0 is categorized as critical.\n' > "$TMP/numbers/a.md"
./scripts/verify_claims.sh "$TMP/numbers" >/dev/null || { echo "FAIL: uncited-number gate flagged a number covered by a reasoned num-ok annotation"; exit 1; }
rm "$TMP/numbers/a.md"

# A reasoned num-ok annotation excuses only the token(s) it actually
# names -- any other uncited number on the same line still has to earn
# its own citation or annotation, so the escape hatch cannot be used to
# smuggle unrelated invented figures in next to a covered one.
printf '<!-- num-ok: 0.3 is FATIGUE_FLOOR, a literal in core/scheduler.py, not a measurement -->\nThe floor is 0.3, and this cut mean runtime by 42 per cent across 900 runs.\n' > "$TMP/numbers/a.md"
OUT=$(./scripts/verify_claims.sh "$TMP/numbers" 2>&1)
STATUS=$?
if [ "$STATUS" -eq 0 ]; then echo "FAIL: uncited-number gate let a num-ok reason exempt numbers it never named"; exit 1; fi
echo "$OUT" | grep -q "uncited number '42' not covered by the num-ok reason" || { echo "FAIL: uncited-number gate did not flag the uncovered 42"; exit 1; }
echo "$OUT" | grep -q "uncited number '900' not covered by the num-ok reason" || { echo "FAIL: uncited-number gate did not flag the uncovered 900"; exit 1; }
if echo "$OUT" | grep -q "uncited number '0.3'"; then echo "FAIL: uncited-number gate flagged the number the annotation actually covered"; exit 1; fi
rm "$TMP/numbers/a.md"

# An annotation with no reason is itself a violation, and -- because it
# never earned the escape -- the number on the following line still fires
# too.
printf '<!-- num-ok: -->\nA CVSS score of 9.0 is categorized as critical.\n' > "$TMP/numbers/a.md"
OUT=$(./scripts/verify_claims.sh "$TMP/numbers" 2>&1)
STATUS=$?
if [ "$STATUS" -eq 0 ]; then echo "FAIL: uncited-number gate passed an empty num-ok annotation"; exit 1; fi
echo "$OUT" | grep -q "num-ok annotation has no reason" || { echo "FAIL: uncited-number gate did not report the empty annotation itself"; exit 1; }
echo "$OUT" | grep -q "uncited number '9.0'" || { echo "FAIL: uncited-number gate let an empty annotation excuse the next line anyway"; exit 1; }
rm "$TMP/numbers/a.md"

# CHECK A, spelled quantities past the tens: a teen cardinal, a vague
# quantifier, a fraction in partitive position, and a ratio idiom are all
# quantity claims, and none of them contains a digit for the numeral check to
# find. While WORD_RE started at twenty none of these shapes was read by
# anything mechanical: a count written as a teen cardinal ("fifteen lines"
# for a 29-line function), a proportion written as a fraction ("better than
# a third"), and a ratio idiom all cleared a check that read digits and
# cardinals from twenty up. The ratio idioms need their own pattern rather
# than a longer alternation, because each half of "three in ten" is
# separately innocuous. Each planted line below must FAIL.
#
# KEEP "nineteen hosts refused the probe". It is the only line here that
# still discriminates WORD_RE's teen extension on its own: ARTIFACT_COUNT_RE
# reads "fifteen lines" as an artifact count, so that phrase survives a
# WORD_RE revert and stopped pinning the extension by itself. "hosts" is not
# on the artifact noun list, which is what leaves the nineteen-hosts line
# depending on WORD_RE alone. Deleting it as redundant drops the teen
# extension's only probe.
mkdir -p "$TMP/words"
for phrase in "fifteen lines of SQL" \
              "nineteen hosts refused the probe" \
              "a couple of hours" \
              "a fifth of the corpus" \
              "better than a third of them" \
              "three in ten scans" \
              "three times the all-attempt mean"; do
  printf '# t\n\nThe run showed %s.\n' "$phrase" > "$TMP/words/a.md"
  if ./scripts/verify_claims.sh "$TMP/words" >/dev/null 2>&1; then
    echo "FAIL: uncited spelled quantity not caught: $phrase"; exit 1
  fi
done

# The clean twins must stay silent. A reasoned num-ok annotation covers the
# quantity it names, exactly as it does for a digit -- and it has to sit on
# its own line, because NUM_OK_RE anchors on the whole line: a comment
# trailing the prose is stripped as a comment, never read as an annotation.
printf '# t\n\n<!-- num-ok: fifteen rows is the count this probe plants, not a measurement -->\nThe fixture table has fifteen rows.\n' > "$TMP/words/a.md"
./scripts/verify_claims.sh "$TMP/words" >/dev/null || { echo "FAIL: annotated quantity word rejected"; exit 1; }

# A ratio idiom is a phrase, so the reason has to name the phrase, not just
# happen to contain its words -- and when it does, the phrase is covered.
printf '# t\n\n<!-- num-ok: three in ten is the ratio this probe fixture encodes, not a measurement -->\nThe fixture encodes three in ten scans.\n' > "$TMP/words/a.md"
./scripts/verify_claims.sh "$TMP/words" >/dev/null || { echo "FAIL: annotated ratio idiom rejected"; exit 1; }

# Word-boundary anchoring: a quantity word inside a longer word or a proper
# noun is not a quantity ("Fifteenth", "halfway"), and a fraction word in
# ORDINAL position names an item rather than a proportion of one ("the third
# law", "the third party") -- which is why the fraction pattern requires a
# partitive "of"/"the" after the word instead of matching it bare.
printf '# t\n\nThe Fifteenth Street office is halfway done, and the third law binds the third party.\n' > "$TMP/words/a.md"
./scripts/verify_claims.sh "$TMP/words" >/dev/null || { echo "FAIL: quantity word inside a longer word, or a fraction word in ordinal position, was flagged"; exit 1; }
rm -rf "$TMP/words"

# CHECK A, a cardinal counting a code artifact. This is the shape the
# below-twenty exemption cannot read, reconstructed here as the shape that
# produces it: a three-column table described as having two.
# The pattern is aimed at the noun, not at the cardinal, which is the only
# reason the exemption can survive beside it -- so both directions matter,
# and the silent direction is the load-bearing one.
mkdir -p "$TMP/artifact"
for phrase in "the table has two columns" \
              "the fix is one call site" \
              "nine instances of the same misconfiguration" \
              "two tests assert on it" \
              "the hash is built in one method"; do
  printf '# t\n\nI checked, and %s.\n' "$phrase" > "$TMP/artifact/a.md"
  if ./scripts/verify_claims.sh "$TMP/artifact" >/dev/null 2>&1; then
    echo "FAIL: uncited count of a code artifact not caught: $phrase"; exit 1
  fi
done

# The structural vocabulary the exemption protects must stay silent, all of
# it on one line: if any of these starts firing, the noun list has grown into
# the document's own vocabulary and the exemption above has stopped meaning
# anything.
printf '# t\n\nTwo orchestrators, four layers and five laws, and the eight stage names that carry them.\n' > "$TMP/artifact/a.md"
./scripts/verify_claims.sh "$TMP/artifact" >/dev/null || { echo "FAIL: a structural cardinal was read as a count of a code artifact"; exit 1; }

# And an artifact count is annotatable like any other quantity: the reason
# has to name the phrase, since this pattern matches a phrase and not a token.
printf '# t\n\n<!-- num-ok: two columns is the count this probe plants, not a measurement -->\nThe table has two columns.\n' > "$TMP/artifact/a.md"
./scripts/verify_claims.sh "$TMP/artifact" >/dev/null || { echo "FAIL: annotated count of a code artifact rejected"; exit 1; }
rm -rf "$TMP/artifact"

# CHECK B (cross-references): a relative handbook-to-handbook markdown link
# must point at a file that exists; anchors are not validated.
mkdir -p "$TMP/xrefs"

printf 'See [the next chapter](01-does-not-exist.md) for detail.\n' > "$TMP/xrefs/a.md"
if ./scripts/verify_claims.sh "$TMP/xrefs" >/dev/null 2>&1; then echo "FAIL: cross-reference gate passed a link to a missing file"; exit 1; fi
rm "$TMP/xrefs/a.md"

printf '# sibling\n' > "$TMP/xrefs/01-sibling.md"
printf 'See [the next chapter](01-sibling.md#some-heading) for detail.\n' > "$TMP/xrefs/a.md"
./scripts/verify_claims.sh "$TMP/xrefs" >/dev/null || { echo "FAIL: cross-reference gate flagged a link to a file that exists"; exit 1; }
rm "$TMP/xrefs/a.md" "$TMP/xrefs/01-sibling.md"

# External URLs and same-page anchors are not handbook cross-references.
printf 'External [docs](https://example.com/guide) and a [same-page jump](#some-heading) are not handbook cross-references.\n' > "$TMP/xrefs/a.md"
./scripts/verify_claims.sh "$TMP/xrefs" >/dev/null || { echo "FAIL: cross-reference gate flagged an external URL or a same-page anchor as broken"; exit 1; }
rm "$TMP/xrefs/a.md"

# README: the repo's front door carries the five laws, chapter cross-references
# and the same attribution line, so it must clear the same gates the chapters
# do. Both gate scripts default to the handbook/ directory and take a target
# argument, so the README has to be named explicitly -- without these two lines
# its citations, its numbers and its links to the chapters are checked by
# nobody, and a law copied wrong or a chapter renamed would ship silently.
./scripts/prose_check.sh README.md >/dev/null || { echo "FAIL: prose gate rejected README.md"; exit 1; }
./scripts/verify_claims.sh README.md >/dev/null || { echo "FAIL: claim gate rejected README.md"; exit 1; }

# Check C's boundary, reconstructed. Check C compares a chapter_claim
# decorator's sentence against the chapter it names, and that decorator is the
# only copy of the sentence it has -- so one edit that changes the chapter
# sentence AND the anchor is compared with itself, matches, and is passed. That
# is structural: exact matching, bounded matching and hashing all read the
# anchor, so tightening the matcher does not reach it. Do not "fix" the second
# direction below by making Check C stricter; what catches a coordinated edit is
# a content assertion holding its own copy of the wording
# (tests/test_chapter_claims.py, ADMISSION_CLAUSE), which the pytest run further
# down exercises.
#
# Check C reads $HANDBOOK_ROOT/tests/**/*.py, so a scratch tree carrying its own
# tests/ isolates the mechanism from this repository's real anchors: the fixture
# is failed only by what it planted itself.
mkdir -p "$TMP/anchor/handbook" "$TMP/anchor/tests" "$TMP/anchor/data"
cp data/stats.json "$TMP/anchor/data/stats.json"
printf '# t\n\nEvery chapter after the first two ends by admitting what its control still gets wrong.\n' \
  > "$TMP/anchor/handbook/00-thesis.md"
write_probe_anchor() {  # $1 = the sentence the planted decorator declares
    cat > "$TMP/anchor/tests/test_probe_claims.py" <<PROBEPY
def chapter_claim(chapter, *sentences):
    def deco(fn):
        return fn
    return deco


@chapter_claim('handbook/00-thesis.md', '$1')
def test_probe():
    assert True
PROBEPY
}

# The firing direction first, on purpose: it is what proves Check C reads this
# fixture at all. Without it, the silent direction below would pass just as
# happily on a tree the gate never opened, which is how a probe stops
# discriminating without anyone noticing. Here the chapter carries the narrowed
# sentence while the anchor still quotes the original.
# The reason is asserted, not just the exit code: the planted chapter could one
# day trip Check A, B or D instead, and a probe that accepts any non-zero exit
# would stay green while no longer exercising Check C at all.
write_probe_anchor 'Every chapter after the first ends by admitting what its control still gets wrong.'
OUT=$(HANDBOOK_ROOT="$TMP/anchor" ./scripts/verify_claims.sh "$TMP/anchor/handbook" 2>&1)
if [ $? -eq 0 ]; then
    echo "FAIL: chapter-claim gate passed an anchor whose sentence its chapter does not carry"; exit 1
fi
echo "$OUT" | grep -q 'CHAPTER CLAIM FAIL' || { echo "FAIL: the anchor probe now fails for some reason other than Check C: $OUT"; exit 1; }

# The silent direction, and the silence is correct rather than a defect: the
# same narrowing, made in the chapter and in the anchor together. Read this as a
# boundary being recorded, not as a gate being verified.
write_probe_anchor 'Every chapter after the first two ends by admitting what its control still gets wrong.'
HANDBOOK_ROOT="$TMP/anchor" ./scripts/verify_claims.sh "$TMP/anchor/handbook" >/dev/null \
  || { echo "FAIL: the coordinated-edit fixture no longer clears Check C, so this probe no longer isolates the boundary it documents"; exit 1; }
rm -rf "$TMP/anchor"

# Chapter-claim gate: tests/test_chapter_claims.py holds executable
# assertions about core/'s actual behaviour, backing specific sentences in
# chapter 00 that a citation check cannot verify -- verify_claims.sh can
# prove a symbol exists, not that a claim about its behaviour is true. A
# claim test nothing runs is a document, not a gate, so its failure has to
# fail this sweep too. Labelled distinctly from the shell-gate failures
# above: this is pytest catching a stale or wrong chapter claim against
# core/, not a planted prose/citation/link violation.
if ! PYTEST_OUT=$(python3 -m pytest tests/test_chapter_claims.py -q -p no:cacheprovider 2>&1); then
    echo "CHAPTER-CLAIM TEST FAIL (pytest, not a shell gate):"
    echo "$PYTEST_OUT"
    exit 1
fi

# Import-consistency gate: tests/test_import_consistency.py's ast-based check
# asserts every core/**/*.py import resolves against the standard library
# only -- a constraint neither verify_claims.sh nor the chapter-claim test
# above can see, since neither one reads an import statement. Wired in beside
# the chapter-claim gate so a stdlib violation fails this sweep instead of
# passing as nobody's business, which is what it did before this line
# existed.
python3 -m pytest tests/test_import_consistency.py -q -p no:cacheprovider >/dev/null \
  || { echo "FAIL: core import consistency"; exit 1; }

# Docstring-claim gate: nothing above reads a docstring for truth. A docstring
# saying a test catches something is the same kind of statement as a chapter
# sentence saying so, and the citation gate walks *.md only, so both a false
# mechanism claim and an invented number in a docstring clear every check
# above. tests/test_docstring_claims.py closes that: it fails when a
# claim-bearing docstring has no recorded audit verdict, when a recorded
# verdict is about a claim that no longer exists, and when a quantity in a
# docstring or comment is neither grounded in the module's own literals nor
# annotated. Labelled distinctly for the same reason the chapter-claim block
# above is: this is pytest reading prose, not a planted violation.
#
# The same census now reads THIS FILE and the three scripts above it. Every
# own-line comment block in scripts/**/*.sh and tests/**/*.sh that asserts a
# mechanism needs a verdict in the same ledger, because until that sweep
# existed no gate in the stack had ever read the gates' own prose -- and three
# false claims about what a gate guarantees had already been found by accident
# in verify_claims.sh's Check C header, one of them the replacement written for
# the first. A comment in THIS file describing a probe is a claim about what
# that probe catches, which is the same kind of sentence.
if ! PYTEST_OUT=$(python3 -m pytest tests/test_docstring_claims.py -q -p no:cacheprovider 2>&1); then
    echo "DOCSTRING-CLAIM AUDIT FAIL (pytest, not a shell gate):"
    echo "$PYTEST_OUT"
    exit 1
fi

# Rendered-tree sync gate: tests/test_rendered_is_in_sync.py keeps the generated
# rendered/ copy of the chapters in step with scripts/render.py over the current
# handbook source and data/stats.json. It sits here at the end with the other
# pytest gates, RUN and not probed, because the rendered tree lives outside
# handbook/ where none of the sweeps above reach it.
python3 -m pytest tests/test_rendered_is_in_sync.py -q -p no:cacheprovider >/dev/null \
  || { echo "FAIL: rendered tree out of sync with its source"; exit 1; }

# Walkthrough sync gate: tests/test_walkthrough_is_in_sync.py compares the
# committed files under walkthrough/artifacts/ against what walkthrough/run.py
# produces from today's fixtures, byte for byte, and fails naming the file that
# moved. It sits here at the end with the other pytest gates, RUN and not
# probed. What earns it a line of its own is scope: nothing above it opens a
# generated .json. prose_check.sh greps --include='*.md'; verify_claims.sh
# rglobs *.md for Checks A, B and D and tests/**/*.py for Check C's chapter
# anchors, so it does read Python, just never an artifact. audit.sh DOES reach
# the artifact tree, and asks only whether it carries an identifier -- never
# whether its bytes are still the ones the source produces.
#
# What this gate catches is drift between the committed bytes and the current
# source: a fixture edited without a re-run, a stage whose output changed, a
# hand-edit to a committed file. What it does NOT catch is a wrong artifact. A
# figure the driver computes incorrectly is written out by that same driver, so
# both sides carry it and this gate stays green. The gate-input figures are
# recounted from the fixtures by tests/test_walkthrough_stages_8_9.py, which is
# where a wrong one is caught, and it is a separate file because this gate
# cannot see one.
python3 -m pytest tests/test_walkthrough_is_in_sync.py -q -p no:cacheprovider >/dev/null \
  || { echo "FAIL: walkthrough artifacts out of sync with their source"; exit 1; }

echo "gates verified"
