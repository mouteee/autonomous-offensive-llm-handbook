"""The grounding gate: does the claim quote its evidence, and is quoting the
right test for that kind of claim?

Chapter 02 calls this the deep-thinker critic, after the filename it carries in
the system this re-expresses (`deep_thinker_critic.py`). Here it is
`core/critic.py`, and the other name appears nowhere else in this repository.

TWO KINDS OF CLAIM. An insight about something observed — this endpoint
answered this way — can be checked against the transcript the model was shown,
so an unquoted one is dropped. An insight proposing a future action cannot be:
nothing in a transcript confirms a request nobody has sent, and execution
settles a proposal where citation settles an observation. `GROUNDED_PHASES`
holds the phases whose insights meet the hard gate, and what it holds is
`surface`. Every phase is scored; only a phase in that set has anything
dropped. The membership of that frozenset is the whole of the split — widen it
to the proposal phases and unquoted proposals begin to be dropped, empty it and
no unquoted observation is ever dropped.

CONTAINMENT, the ladder. `evidence.ref` and `evidence.snippet` are each looked
for in the lowercased context. Both offered and both found scores `0.85`;
either one found scores `0.6`; something offered and neither found scores
`0.35`; nothing offered at all scores `0.15`. Four rungs, and the middle rung
is reached by either field alone, so a snippet that grounds without a ref
scores what a ref that grounds without a snippet scores.

A snippet is looked for by its first `60` characters rather than in full, so a
snippet longer than that grounds on its opening however its tail reads. That is
a loosening in the check, and it is written down here because nothing else
writes it down.

THE CALLER ADVISES. An insight may arrive carrying a `confidence` of its own.
The reported confidence is `min(containment, self_score)`, so the caller's
number is read only where it is the lower of the two, and the keep-or-drop
comparison reads containment rather than the reported number. Both directions
follow from those two conditions rather than from a list of cases:

num-ok: `0.99` and `0.0` here are illustrative self-scores a caller might send, not constants of this module -- they are the values tests/test_critic.py sends, and they appear in no source literal here because nothing in the module names them
  - an invented insight self-scored `0.99` is reported and judged at its
    containment;
  - a grounded insight self-scored `0.0` is reported at `0.0` and kept.

On the path this re-expresses, the caller is the model whose claims this gate
exists to check, which is why its opinion of its own work is advisory here.

A bool is not a score. `isinstance(True, int)` is true in Python, so a bool
`confidence` would otherwise arrive as a number; the type check rejects it
before any arithmetic and the reported confidence stays at containment.

THE RECORD. `critic_containment_score` and `critic_notes` are written on every
returned insight from the gate's own measurement, whatever the caller sent under
them: `critic_containment_score` is containment, written under that key
regardless of what arrived there, and `critic_notes` is the containment record
plus what became of any self-score. `critic_self_score` and `critic_notes_caller`
are written only when there is something to write — the first when the caller's
`confidence` was a usable number, the second holding a caller's own
`critic_notes` moved aside, cut to `200` characters, so it sits beside the gate's
record rather than in place of it.

The insight is copied before any of that, so the caller's other keys ride through
untouched, and one edge of that is worth naming rather than leaving to be found.
The gate clears none of its own record keys it did not write on a given pass: a
caller that plants `critic_self_score` while sending no `confidence`, or
`critic_notes_caller` while sending no `critic_notes`, or `critic_forced_keep` on
an item the floor never rescues, gets that key back unchanged, because the
conditional writes above do not fire and nothing else touches it. Only
`critic_containment_score` and `critic_notes` are proof against such a plant —
written every pass, from the gate's own measurement — which is the exact extent
to which the audit record can be trusted over what a caller supplied. This is
faithful to the module this re-expresses.

THE FLOOR, and the channel it leaves open. When the gate is dropping and the
batch would come back empty, the strongest of the dropped pile is returned
tagged `critic_forced_keep`. So a lone insight below the threshold is always
kept, and a one-item result cannot show a drop.

That floor is a caller channel the containment rule does not close, and it is
named here rather than left to be found. The floor orders the dropped pile by
the reported `confidence` — the number a caller can pull down — and its
condition is that every insight in the batch was dropped. Whenever that
condition holds, lowering one insight's reported confidence moves it down that
ordering and a different insight is the one returned. So through the per-insight
`confidence`, a caller cannot flip a verdict or enlarge the kept set — the
keep-or-drop test reads containment, and the floor keeps exactly one — but it can
still choose which insight survives a batch that was going to be emptied.

Call-level configuration is a separate thing, and not a smuggle. `threshold`,
`phase` and `intel_context` are the gate's own settings: the party that supplies
them sets what the gate is for rather than defeating it, and on the path this
re-expresses they arrive in the same request body as the insights. So
`threshold=0.0` drops nothing, a `phase` outside `GROUNDED_PHASES` drops nothing,
and an `intel_context` grounds whatever it quotes — a caller that writes the
context an insight is checked against can ground that insight at the top rung.
That is configuration deciding the terms of the check, a different act from a
self-score trying to move a number past containment, and a reader wiring
`score_grounded` behind a request the model controls is owed the difference named
rather than a universal negative that the same request disproves.

WITHHELD. `Critic.score_batch` and `Critic._raw_call` make a model call and
raise `NotImplementedError` here. `score_grounded` needs no model and ships
whole: it is the deterministic side, and the argument rests on it.
"""
from __future__ import annotations

import json
import math
import os
import re
from typing import Any

# The phases whose insights QUOTE observed data, and so the only phases where an
# unquoted insight is dropped rather than merely scored. See the module
# docstring: this frozenset is where the surface/proposal split is written down.
GROUNDED_PHASES = frozenset({"surface"})

_ENV_ENABLED = "HARNESS_DT_CRITIC"
_ENV_THRESHOLD = "HARNESS_DT_CRITIC_THRESHOLD"
_DEFAULT_THRESHOLD = 0.55

# The containment ladder, in the order the checks are made. Named rather than
# inlined so the ladder is one thing a reader can find.
_BOTH_FOUND = 0.85
_EITHER_FOUND = 0.6
_OFFERED_NOT_FOUND = 0.35
_NOTHING_OFFERED = 0.15

# A snippet is matched on this many leading characters, not in full.
_SNIPPET_MATCH_CHARS = 60

# A caller's own notes are kept at this length when moved aside.
_CALLER_NOTES_CHARS = 200


class Critic:
    """The model-graded critic: one call per phase batch, not one per insight.

    The deterministic gate in `score_grounded` needs no model at all, so this
    class is the paid path, and both of its model-touching methods are withheld
    here. What remains is the shape a caller integrates against, plus
    `_parse_scores`, which reads whatever the model sent back.
    """

    def __init__(self, llm: Any, threshold: float = _DEFAULT_THRESHOLD,
                 context_char_limit: int = 60000):
        self._llm = llm
        self._threshold = threshold
        self._context_limit = context_char_limit

    @property
    def threshold(self) -> float:
        """The drop threshold this critic was constructed with, read-only."""
        return self._threshold

    async def score_batch(self, insights: list[dict], intel_context: str,
                          phase: str) -> list[dict]:
        """Grade one phase batch with a single model call, returning survivors.

        Withheld: this makes a live model call. `phase` carries no default, so
        the arity alone prevents a caller reaching the model without saying
        which kind of claim it is grading.

        The coroutine matters to anyone testing this. An un-awaited call
        returns a coroutine object and raises nothing at all, because the body
        never runs — so a test expecting `NotImplementedError` has to await it,
        and making this method synchronous to spare it that would change the
        shape a caller integrates against.
        """
        raise NotImplementedError("withheld in public handbook")

    async def _raw_call(self, prompt: str) -> str:
        """Send one prompt to the model and hand back its raw text.

        Withheld: this is the request itself. With it withheld nothing in this
        module reaches outside the process — what is left is arithmetic and
        string containment over values the caller passed in, plus two
        environment reads.
        """
        raise NotImplementedError("withheld in public handbook")

    @staticmethod
    def _parse_scores(content: str, expected_n: int) -> dict[int, dict]:
        """Read a model's JSON verdict into `{index: entry}`, dropping the rest.

        This ships real and has no caller in this module, because its only
        caller is `score_batch` and that is withheld. It is here because it is
        the schema-validation side of the model boundary — the decision about
        what to believe from a model — and withholding it would take that
        decision out while keeping nothing dangerous.

        Forgiving in one direction and strict in the other, deliberately.
        Forgiving: the span from the first `{` to the last `}` is what gets
        parsed, so an answer wrapped in prose is still read; the payload may
        name its list `scores` or `items`; and empty, brace-less or
        unparseable content yields an empty dict, as does a well-formed
        payload that names no such list. An entry is left out by one of two
        separate steps. `int(entry.get("i"))` sits inside the one try/except,
        so an `i` that is missing or non-numeric is excluded there — `int(None)`
        raises `TypeError`, `int("x")` raises `ValueError`, and the `except`
        absorbs both. An `i` that is a number but out of bounds raises nothing
        at that step; it is excluded afterwards by the separate
        `0 <= index < expected_n` comparison, which alone decides whether the
        entry is stored. So the missing-or-non-numeric case and the out-of-range
        case are excluded by different lines. Two
        operations after the parse are not softened, though: the list value is
        iterated, so a payload answering with a truthy non-iterable there — a
        bare number for `scores` — raises `TypeError`, and each entry is asked
        for its `i`, so an entry that is not a mapping raises `AttributeError`.
        A model answering with the agreed schema reaches neither; a model
        answering with something else surfaces as one of those two exceptions
        rather than as missing indices.
        """
        if not content:
            return {}
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            return {}
        try:
            payload = json.loads(match.group())
        except json.JSONDecodeError:
            return {}
        entries = payload.get("scores") or payload.get("items") or []
        out: dict[int, dict] = {}
        for entry in entries:
            try:
                index = int(entry.get("i"))
            except (TypeError, ValueError):
                continue
            if 0 <= index < expected_n:
                out[index] = entry
        return out


# Both accessors below are read by nothing in this repository. `score_grounded`
# does not consult either, and their only callers in the tree are in
# tests/test_critic.py -- so the grounding gate ships with its switches present
# and unwired, which is the arm an ablation of this layer would reach for first
# and the reason chapter 05 says that arm is not available here.
#
# That is a publication decision and not an oversight. Wiring either into the
# scoring function would install an off switch inside a core scoring path, in a
# handbook that argues at chapter 03 and again at chapter 04 that a control with
# a documented off switch is a control and not a guarantee. An external integration
# may make that call for itself, at its own call
# sites, which are not published here. tests/test_environment_switches.py holds
# the accessors unconsulted, so wiring one reddens instead of passing quietly.
def critic_enabled() -> bool:
    """Whether the critic pass runs, read from `HARNESS_DT_CRITIC`.

    The condition is an equality: True when the variable is absent or reads
    exactly `1`, and False for every other value. It is not an inequality
    against `0`, so `true` and `yes` turn this pass off as surely as `0` does.
    """
    return os.getenv(_ENV_ENABLED, "1") == "1"


def critic_threshold() -> float:
    """The drop threshold, read from `HARNESS_DT_CRITIC_THRESHOLD`.

    A value that will not parse as a float falls back to the default rather
    than raising, so a malformed environment cannot stop a scan. The cost of
    that choice is that a typo and an unset variable are indistinguishable at
    the call site.
    """
    try:
        return float(os.getenv(_ENV_THRESHOLD, str(_DEFAULT_THRESHOLD)))
    except ValueError:
        return _DEFAULT_THRESHOLD


def _containment(ref_found: bool, snippet_found: bool,
                 anything_offered: bool) -> float:
    """The ladder as a function of what was offered and what was found.

    Four rungs and the middle one is reached by either field alone, which is
    the rung a three-step reading of this ladder loses. The values are the
    module constants; the module docstring carries them in prose.
    """
    if ref_found and snippet_found:
        return _BOTH_FOUND
    if ref_found or snippet_found:
        return _EITHER_FOUND
    return _OFFERED_NOT_FOUND if anything_offered else _NOTHING_OFFERED


def _self_score(prior: Any) -> tuple[float | None, str]:
    """Read a caller-supplied `confidence` into a usable number and a note.

    Returns `(None, note)` for anything that is not a finite real number,
    bools included: `isinstance(True, int)` is true in Python, so a bool is
    rejected on its own type before the numeric test can accept it. A usable
    number is clamped into `0.0`-`1.0`. The note that comes back records what
    became of the caller's value, and is empty when the caller sent none.
    """
    if prior is None:
        return None, ""
    if (isinstance(prior, bool) or not isinstance(prior, (int, float))
            or not math.isfinite(float(prior))):
        return None, f",self_score={prior!r}(ignored:not-a-score)"
    return min(max(float(prior), 0.0), 1.0), ""


def score_grounded(insights: list[dict], intel_context: str,
                   threshold: float = _DEFAULT_THRESHOLD,
                   phase: str = "surface") -> dict:
    """Score a batch of insights for grounding and split it into kept and dropped.

    Returns `{"kept": [...], "dropped": [...], "scores": {...}}`. `scores` maps
    each insight's position in the input list — an `int` key, never a string —
    to the confidence it was scored at: the lowered number where a caller
    supplied one and the containment score otherwise. `scores` carries that
    number unrounded, while the copy of the insight rounds its own `confidence`,
    so the two read the same only down to that rounding.

    Insights are copied rather than annotated in place, so a caller's own dicts
    come back untouched and the same list can be scored twice under different
    phases without the first pass leaking into the second.

    `threshold` is compared against containment and never against the reported
    confidence. `phase` decides whether that comparison drops anything at all:
    a phase outside `GROUNDED_PHASES` is scored and nothing is dropped. The
    ladder, the self-score rule, the record written on every insight and the
    forced-keep floor are all described at the top of this module.
    """
    if not insights:
        return {"kept": [], "dropped": [], "scores": {}}
    grounded_gate = phase in GROUNDED_PHASES
    haystack = (intel_context or "").lower()
    kept: list[dict] = []
    dropped: list[dict] = []
    scores: dict[int, float] = {}

    for index, original in enumerate(insights):
        evidence = original.get("evidence") or {}
        ref = (evidence.get("ref") or "").strip()
        snippet = (evidence.get("snippet") or "").strip()
        ref_found = bool(ref and ref.lower() in haystack)
        snippet_found = bool(
            snippet and snippet.lower()[:_SNIPPET_MATCH_CHARS] in haystack)
        containment = _containment(ref_found, snippet_found,
                                   bool(ref or snippet))

        self_score, note = _self_score(original.get("confidence"))
        if self_score is not None:
            note = (f",self_score={self_score:g}(applied:lowered-priority)"
                    if self_score < containment
                    else f",self_score={self_score:g}(ignored:cannot-raise)")
        confidence = containment if self_score is None else min(containment,
                                                                self_score)

        insight = dict(original)
        caller_notes = insight.get("critic_notes")
        insight["confidence"] = round(confidence, 3)
        insight["critic_containment_score"] = containment
        insight["critic_notes"] = (
            f"grounded:ref={ref_found},snippet={snippet_found}{note}")
        if self_score is not None:
            insight["critic_self_score"] = round(self_score, 3)
        if caller_notes is not None and str(caller_notes).strip():
            insight["critic_notes_caller"] = str(caller_notes)[:_CALLER_NOTES_CHARS]

        scores[index] = confidence
        if grounded_gate and containment < threshold:
            dropped.append(insight)
        else:
            kept.append(insight)

    if grounded_gate and not kept and dropped:
        dropped.sort(key=lambda i: i.get("confidence", 0), reverse=True)
        forced = dict(dropped[0])
        forced["critic_forced_keep"] = True
        kept.append(forced)
        dropped = dropped[1:]
    return {"kept": kept, "dropped": dropped, "scores": scores}
