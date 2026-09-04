#!/usr/bin/env bash
# Sanitization gate. Prints "sanitization clean: <target>" and exits 0 only if
# a case-insensitive, line-oriented grep over TARGET both COMPLETED and found
# no DENY pattern. The "only if" is load-bearing in both directions and the
# detector that audits this prose reads it: the paragraphs below say what a
# completed sweep still cannot see.
#
# A TARGET that does not exist, that cannot be read, or that grep cannot
# finish walking is a HARD FAILURE naming the path, never a clean report. It
# used to be the second: a mistyped path printed "sanitization clean" and
# exited 0, which is the neutered-denylist defect from the other side -- a
# gate reporting success for work it never did. Both directions are probed in
# tests/test_gates.sh.
#
# WHAT IS DETECTED is one condition, stated rather than enumerated, because a
# list of escapes goes stale on the next --exclude and the list that stood
# here was already short of the walk's real behaviour: a DENY pattern is
# reported only where it matches, case-insensitively, entirely within one line
# of a file this grep invocation both reaches and reads as text. Whatever that
# condition does not cover is reported clean, so "sanitization clean" asserts
# the condition and never that the tree carries no identifier. The --exclude
# arguments are part of the condition: no sweep reaches a file named audit.sh
# or .denylist at any depth, so an identifier planted in either is reported
# clean.
#
# WHAT IS PUBLISHED is a separate failure direction from what is detected, and
# separating them is what the split below is for. It used to be one direction:
# DENY named employer, client and host identifiers outright, so the file the
# sweep is excluded from reading was also the file leaking, and the gate could
# report the tree clean while being the only thing in it that was not. DENY
# below names no employer, no client and no engagement host, and the condition
# that keeps it that way is about the pattern as published, not about what the
# pattern matches: a pattern belongs in DENY only if the regex written there
# names no employer, no client, no engagement host and no internal scheme of
# one. /Users/[a-z]+/projects/ passes that condition and still matches paths
# that name a person or a company, which is why the condition reads that way;
# a public vendor's own name passes it too, and an internal application-ID
# scheme does not. Keeping the LLM-vendor token published is deliberate rather
# than tolerated, because tests/test_gates.sh assembles its own planted
# identifier from that token at runtime and that probe must still fire in a
# public clone. Every pattern the condition rules out lives in
# scripts/.denylist, which is gitignored and is merged into DENY when it is
# readable and has a pattern in it: a public clone enforces the published half,
# the operator's checkout enforces both, and that difference is stated here
# rather than discovered. Add an employer, client, host or internal-scheme
# identifier to .denylist, never to DENY.
set -uo pipefail
TARGET="${1:-.}"; shift || true
if [ ! -e "$TARGET" ]; then echo "SANITIZATION FAIL [target]: no such path: $TARGET"; exit 1; fi
if [ ! -r "$TARGET" ]; then echo "SANITIZATION FAIL [target]: unreadable path: $TARGET"; exit 1; fi
DENY='sk-or-v1|openrouter|OPENROUTER_API_KEY|/Users/[a-z]+/projects/'
PRIVATE_DENY_FILE="$(dirname "$0")/.denylist"
# The merge is a soft test, and a soft test that says nothing is a gate that
# reports work it did not do. Three states, and the sweep announces which one
# it ran under, because the two narrow ones are indistinguishable from the wide
# one in the exit code and in the success line. The absent case is not a
# failure: on a genuinely published clone there is nothing for the private half
# to catch, and failing there would train an operator to ignore a red gate.
# The empty case is separate from the absent one on purpose -- a denylist
# present but carrying no pattern is the neutered-denylist defect the header
# above describes, and it reaches this branch looking exactly like a clone.
# The first line says NO READABLE rather than absent, because `-r` is false
# for a file that is missing and for one that exists and cannot be read, and
# announcing the second as the first would misdescribe a permissions problem
# on the operator's own checkout as a clean public clone.
SCOPE="published patterns only -- no readable private denylist beside this script, so employer, client, host and internal-scheme identifiers were NOT swept"
if [ -r "$PRIVATE_DENY_FILE" ]; then
  EXTRA=$(grep -v '^[[:space:]]*#' "$PRIVATE_DENY_FILE" | grep -v '^[[:space:]]*$' | paste -sd'|' -)
  if [ -n "$EXTRA" ]; then
    DENY="$DENY|$EXTRA"
    SCOPE="published patterns and the private denylist"
  else
    SCOPE="published patterns only -- the private denylist is readable but carries no pattern, so employer, client, host and internal-scheme identifiers were NOT swept"
  fi
fi
echo "sanitization scope: $SCOPE"
ERRS=$(mktemp); trap 'rm -f "$ERRS"' EXIT
HITS=$(grep -rEinI "$DENY" "$TARGET" "$@" --exclude-dir=.git --exclude='audit.sh' --exclude='.denylist' 2>"$ERRS")
STATUS=$?
# grep exits 0 with matches and 1 with none; anything above that is an error,
# and an error means the sweep did not cover what it was asked to cover.
if [ "$STATUS" -gt 1 ]; then
  echo "SANITIZATION FAIL [incomplete]: grep did not finish over $TARGET"; cat "$ERRS"; exit 1
fi
if [ -n "$HITS" ]; then echo "SANITIZATION FAIL:"; echo "$HITS"; exit 1; fi
echo "sanitization clean: $TARGET"
