#!/usr/bin/env bash
# Publication-only gate for a newly initialized, history-free staging tree.
# Normal development tests do not call this: it deliberately refuses the
# development repository and deliberately requires private operator input.
set -uo pipefail

ROOT="${1:-.}"
EXPECTED_NAME="${PUBLICATION_AUTHOR_NAME:-}"
EXPECTED_EMAIL="${PUBLICATION_AUTHOR_EMAIL:-}"
DENYLIST="$ROOT/scripts/.denylist"

fail() { echo "PUBLICATION FAIL [$1]: $2"; exit 1; }

[ -d "$ROOT/.git" ] || fail repository "staging tree is not a newly initialized Git repository"
[ -n "$EXPECTED_NAME" ] || fail identity "PUBLICATION_AUTHOR_NAME is required"
[ -n "$EXPECTED_EMAIL" ] || fail identity "PUBLICATION_AUTHOR_EMAIL is required"

ACTUAL_NAME=$(git -C "$ROOT" config --local user.name 2>/dev/null || true)
ACTUAL_EMAIL=$(git -C "$ROOT" config --local user.email 2>/dev/null || true)
[ "$ACTUAL_NAME" = "$EXPECTED_NAME" ] || fail identity "local Git author name is not the approved value"
[ "$ACTUAL_EMAIL" = "$EXPECTED_EMAIL" ] || fail identity "local Git author email is not the approved value"

REFS=$(git -C "$ROOT" for-each-ref --format='%(refname)' 2>/dev/null) || fail repository "cannot inspect Git refs"
[ -z "$REFS" ] || fail history "staging repository already has a ref or tag"
GIT_DIR=$(git -C "$ROOT" rev-parse --absolute-git-dir 2>/dev/null) || fail repository "cannot resolve Git metadata"
if find "$GIT_DIR/objects" -type f -print -quit | grep -q .; then
  fail history "staging repository already has Git objects"
fi
if [ -d "$GIT_DIR/logs" ] && find "$GIT_DIR/logs" -type f -print -quit | grep -q .; then
  fail history "staging repository already has reflogs"
fi

[ -r "$DENYLIST" ] || fail denylist "scripts/.denylist is required and must be readable"
PRIVATE_COUNT=$(grep -v '^[[:space:]]*#' "$DENYLIST" | grep -vc '^[[:space:]]*$' || true)
[ "$PRIVATE_COUNT" -gt 0 ] || fail denylist "scripts/.denylist carries no private pattern"

OUTPUT=$(bash "$ROOT/scripts/audit.sh" "$ROOT" 2>&1)
STATUS=$?
printf '%s\n' "$OUTPUT"
[ "$STATUS" -eq 0 ] || fail sanitization "identifier sweep failed"
printf '%s\n' "$OUTPUT" | grep -qx 'sanitization scope: published patterns and the private denylist' \
  || fail denylist "audit did not prove that it merged the private denylist"

echo "publication gate passed: history-free tree, approved author identity, private denylist sweep"
