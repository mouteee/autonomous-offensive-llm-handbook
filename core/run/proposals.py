"""Model proposals: a provider behind a wrapper, a hypothesis contract in
front of it, and the host deciding admission either way.

A proposal is more than an action request: it names the hypothesis kind, the
observed surface it is about, and the observation records it treats as
evidence. The wrapper parses strictly -- the same byte limit, duplicate-key and
constant-handling discipline as the fixture bridge in examples/model_bridge.py,
restated here because core/ imports only core/ -- and repair is bounded: a
malformed reply earns the provider another attempt carrying the validation
error, while a well-formed proposal the policy turns away is terminal, because
rephrasing a forbidden action does not make it permitted.

Timeouts here are cooperative: the elapsed time is read after the provider
call returns, so a hung provider is surfaced but not interrupted. Real
cancellation needs process or transport machinery outside this teaching
module, and the lesson says so.
"""

import json
import time

from .records import RecordError
from .policy import normalize_destination
from .records import action_identity


MAX_REPLY_BYTES = 4096
PROPOSAL_KEYS = frozenset({"kind", "surface", "evidence", "action"})
ACTION_KEYS = frozenset({"tool", "destination", "arguments"})


class ProposalError(RecordError):
    """A provider reply that does not satisfy the proposal contract."""


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ProposalError("duplicate JSON key")
        obj[key] = value
    return obj


def _invalid_constant(value):
    raise ProposalError("nonstandard JSON constant")


def parse_strict(raw):
    """One JSON object from provider text, within the byte limit, nothing else."""
    if not isinstance(raw, str):
        raise ProposalError("provider output is not JSON text")
    if len(raw.encode("utf-8")) > MAX_REPLY_BYTES:
        raise ProposalError("proposal exceeds the byte limit")
    try:
        proposal = json.loads(raw, object_pairs_hook=_unique_object,
                              parse_constant=_invalid_constant)
    except ProposalError:
        raise
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ProposalError("invalid JSON proposal") from exc
    if not isinstance(proposal, dict):
        raise ProposalError("proposal is not an object")
    return proposal


def validate_shape(proposal, observations):
    """Schema and evidence binding; raises ProposalError naming the defect."""
    if set(proposal) != PROPOSAL_KEYS:
        raise ProposalError(
            f"proposal keys are exactly {sorted(PROPOSAL_KEYS)}; "
            f"got {sorted(proposal)}")
    for name in ("kind", "surface"):
        if not isinstance(proposal[name], str) or not proposal[name].strip():
            raise ProposalError(f"{name} needs a nonempty string")
    evidence = proposal["evidence"]
    if not isinstance(evidence, list) or not evidence:
        raise ProposalError("evidence needs a nonempty list of observation "
                            "fields")
    if not all(isinstance(ref, str) for ref in evidence):
        raise ProposalError("evidence needs a list of observation field names")
    unknown_refs = [ref for ref in evidence if ref not in observations]
    if unknown_refs:
        raise ProposalError(f"evidence names unrecorded observations: "
                            f"{unknown_refs}")
    if proposal["surface"] not in observations:
        raise ProposalError("surface names an unrecorded observation")
    action = proposal["action"]
    if not isinstance(action, dict) or set(action) != ACTION_KEYS:
        raise ProposalError(
            f"action keys are exactly {sorted(ACTION_KEYS)}; "
            f"got {sorted(action) if isinstance(action, dict) else type(action).__name__}")
    if not isinstance(action["arguments"], dict):
        raise ProposalError("action arguments need an object")
    return proposal


class FakeProvider:
    """A provider that replays authored replies, for tests and demos."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.contexts = []

    def __call__(self, context):
        self.contexts.append(context)
        if not self._replies:
            raise RuntimeError("fake provider ran out of authored replies")
        return self._replies.pop(0)


class ProviderSession:
    """Bounded proposal attempts against one provider, with usage accounting.

    `admission`, when the host supplies one, is a callable consulted
    immediately before every provider invocation -- the first call and every
    repair alike -- answering a refusal reason or None. It is how the run's
    own stops (closure, cancellation, the wall clock) reach into a session
    already in progress: a synchronous call that has started may finish after
    its deadline, but finishing late never authorizes starting another one.
    """

    def __init__(self, provider, *, max_attempts=2, max_model_calls=8,
                 timeout_seconds=None, cancelled=None, admission=None,
                 clock=time.monotonic):
        if type(max_attempts) is not int or not 1 <= max_attempts <= 4:
            raise ProposalError("max_attempts needs an integer from 1 to 4")
        self.provider = provider
        self.max_attempts = max_attempts
        self.max_model_calls = max_model_calls
        self.timeout_seconds = timeout_seconds
        self.cancelled = cancelled
        self.admission = admission
        self.clock = clock
        self.usage = {"calls": 0, "request_bytes": 0, "reply_bytes": 0}

    def _call(self, context):
        self.usage["calls"] += 1
        self.usage["request_bytes"] += len(
            json.dumps(context, sort_keys=True).encode("utf-8"))
        started = self.clock()
        raw = self.provider(context)
        elapsed = self.clock() - started
        if isinstance(raw, str):
            try:
                self.usage["reply_bytes"] += len(raw.encode("utf-8"))
            except UnicodeError as exc:
                # The provider did answer; the reply's bytes are the problem.
                raise ProposalError(f"reply is not encodable text: {exc}") from exc
        return raw, elapsed

    def propose(self, context, *, observations, policy):
        """One admitted proposal, or a terminal report saying why not.

        Repair applies to malformed output only. A well-formed proposal the
        policy declines is terminal: authorization lives in the policy, and
        no amount of rephrasing moves it.
        """
        attempts = []
        validation_error = None
        for attempt in range(1, self.max_attempts + 1):
            if self.admission is not None:
                reason = self.admission()
                if reason:
                    return {"admitted": False, "status": "admission_refused",
                            "reason": reason, "attempts": attempts,
                            "usage": dict(self.usage)}
            if self.cancelled is not None and self.cancelled():
                return {"admitted": False, "status": "cancelled",
                        "attempts": attempts, "usage": dict(self.usage)}
            if self.usage["calls"] >= self.max_model_calls:
                return {"admitted": False, "status": "model_call_budget_exhausted",
                        "attempts": attempts, "usage": dict(self.usage)}
            call_context = {**context, "validation_error": validation_error}
            try:
                raw, elapsed = self._call(call_context)
            except ProposalError as exc:
                # The provider did answer; its reply's bytes are the problem,
                # which is a malformed attempt with a repair round, not an
                # outside-process failure.
                validation_error = str(exc)
                attempts.append({"attempt": attempt, "status": "malformed",
                                 "reason": validation_error})
                continue
            except Exception as exc:  # a provider is an outside process
                attempts.append({"attempt": attempt, "status": "provider_error",
                                 "error_type": type(exc).__name__})
                return {"admitted": False, "status": "provider_error",
                        "attempts": attempts, "usage": dict(self.usage)}
            if self.timeout_seconds is not None and elapsed > self.timeout_seconds:
                attempts.append({"attempt": attempt, "status": "timeout"})
                return {"admitted": False, "status": "timeout",
                        "attempts": attempts, "usage": dict(self.usage)}
            try:
                proposal = validate_shape(parse_strict(raw), observations)
            except ProposalError as exc:
                validation_error = str(exc)
                attempts.append({"attempt": attempt, "status": "malformed",
                                 "reason": validation_error})
                continue
            action = proposal["action"]
            decision = policy.allows_action(action["tool"],
                                            action["destination"],
                                            action["arguments"])
            if not decision["allowed"]:
                attempts.append({"attempt": attempt, "status": "refused_by_policy",
                                 "reason": decision["reason"]})
                return {"admitted": False, "status": "refused_by_policy",
                        "reason": decision["reason"], "proposal": proposal,
                        "attempts": attempts, "usage": dict(self.usage)}
            action_id = action_identity(
                action["tool"], normalize_destination(action["destination"]))
            attempts.append({"attempt": attempt, "status": "admitted"})
            return {"admitted": True, "proposal": proposal,
                    "action_id": action_id, "attempts": attempts,
                    "usage": dict(self.usage)}
        return {"admitted": False, "status": "repair_exhausted",
                "attempts": attempts, "usage": dict(self.usage)}
