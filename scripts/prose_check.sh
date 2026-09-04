#!/usr/bin/env bash
# AI-tell gate. Exits 0 only when none of the tells below is present in a
# *.md file under TARGET, and that scope is the whole of the guarantee: a
# tell in any other kind of file, or outside TARGET, is never read, and a
# TARGET that does not exist reports clean. Catches what a grep can catch;
# voiceless rhythm and absent opinion are the humanizer pass's job, not this
# script's.
set -uo pipefail

# Pin a UTF-8 locale before any grep runs. Under a plain POSIX/C locale, the
# literal-Unicode bracket expressions below (curly-quote, emoji) degrade into
# raw byte-set matching, so ordinary multi-byte UTF-8 text -- accented
# letters, an ellipsis, a bullet -- can misfire a check even though it
# contains no curly quote and no emoji. This overrides whatever locale the
# caller's shell had: the gate's correctness must not depend on the caller's
# environment. The four candidates are tried in order and the first one
# `locale -a` confirms is the one exported: C.UTF-8 leads because it is the
# portable spelling where it exists, and the en_US pair is there for boxes
# that carry only a regional locale. Which of the four a given box has is
# not assumed anywhere -- nothing is exported before `locale -a` confirms it,
# which is the branch below.
#
# UTF8_LOCALE, if the caller's environment already set it, is tried as-is
# instead of being probed for -- the hook tests/test_gates.sh's locale probes
# use to drive the failure branch below without touching the box's real
# locale list. If none of the four candidates is confirmed present in
# `locale -a` -- the caller's override included -- the script does not fall
# back to exporting a guess: it exits non-zero and names all four, because an
# unconfirmed locale is exactly the silent byte-matching failure this comment
# opens with, just deferred to whichever grep runs first.
#
# `locale -a` is captured ONCE into _LOCALES rather than piped to grep fresh
# per candidate: under the `set -o pipefail` this script enables above,
# `locale -a | grep -qix ...` intermittently reports failure even when grep
# finds the match, because grep -q can close its end of the pipe before
# locale -a finishes writing, and the SIGPIPE that follows makes locale -a's
# own non-zero exit status -- not grep's -- the value pipefail reports for
# the whole pipeline. Testing a herestring against an already-captured
# variable has no live producer left to receive that signal.
#
# This paragraph used to cite that setting by line number, and the citation
# rotted the first time the header above it grew: an insertion two paragraphs
# up moved the line and nothing matched the number any more. A line number in
# prose about its own file is a restated figure -- it goes stale on an edit
# that has nothing to do with what it claims -- so name the thing, never its
# coordinates. Third time this project has reached that conclusion.
_LOCALES=$(locale -a 2>/dev/null)
if [ -z "${UTF8_LOCALE:-}" ]; then
  UTF8_LOCALE=""
  for _candidate in C.UTF-8 C.utf8 en_US.UTF-8 en_US.utf8; do
    if grep -qix "$_candidate" <<< "$_LOCALES"; then
      UTF8_LOCALE="$_candidate"
      break
    fi
  done
fi
if [ -z "$UTF8_LOCALE" ] || ! grep -qix "$UTF8_LOCALE" <<< "$_LOCALES"; then
  echo "PROSE FAIL [locale]: no confirmed UTF-8 locale (tried C.UTF-8, C.utf8, en_US.UTF-8, en_US.utf8) -- refusing to guess, since an unavailable locale silently degrades Unicode matching to byte matching" >&2
  exit 1
fi
export LC_ALL="$UTF8_LOCALE"
unset _candidate UTF8_LOCALE _LOCALES

TARGET="${1:-handbook}"
FAIL=0

report() { # name, pattern, extra grep flags
  local name="$1" pat="$2"; shift 2
  local hits
  hits=$(grep -rEnI "$pat" "$TARGET" "$@" --include='*.md' 2>/dev/null || true)
  if [ -n "$hits" ]; then
    echo "PROSE FAIL [$name]:"; echo "$hits"; FAIL=1
  fi
}

report "em-dash"            '—'
report "curly-quote"        '[“”‘’]'
report "emoji"              '[🚀💡✅🔥📊✨🎯⚡🧠🔍]'
report "ai-vocabulary"      '\b(delve|tapestry|testament|pivotal|underscore[sd]?|showcas(e|es|ing)|intricate|interplay|multifaceted|realm|landscape of|vibrant|seamless(ly)?|robust solution|leverage[sd]? the|garner(ed|s)?|foster(ing|s)?|holistic)\b' -i
report "significance-puff"  '\b(stands as|serves as|marks a (pivotal|key|significant)|is a testament|plays a (vital|crucial|key|pivotal) role|underscores the importance|reflects broader|setting the stage)\b' -i
report "negative-parallel"  "\b(not (just|only|merely) [^.]{1,60}(but|it'?s))\b" -i
report "superficial-ing"    '\b(highlighting|underscoring|emphasizing|symbolizing|showcasing|exemplifying) (the|its|a|how)\b' -i
report "filler"             '\b(in order to|due to the fact that|at this point in time|it is important to note|has the ability to|in the event that)\b' -i
report "hedge-stack"        '\b(could potentially|might possibly|may perhaps|it could be argued that)\b' -i
report "chatbot-artifact"   '\b(I hope this helps|Let me know if|Great question|Certainly!|Of course!|feel free to)\b' -i
report "generic-uplift"     '\b(the future looks bright|exciting times|step in the right direction|continues to thrive|journey toward)\b' -i
report "title-case-heading" '^#{1,6} +([A-Z][a-z]+ ){2,}[A-Z][a-z]+ *$'
report "inline-header-list" '^[-*] +\*\*[^*]+:\*\*'

if [ "$FAIL" -ne 0 ]; then exit 1; fi
echo "prose clean: $TARGET"
