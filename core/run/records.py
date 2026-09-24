"""The record vocabulary of a run: what happened, written down once, bound by
digests.

Every record is a frozen dataclass with typed validation, and the identities do
the work. An action's identity is one normalized string -- tool plus canonical
destination -- shared by proposal, selection, execution, recording and
feedback, so every part of the pipeline is talking about the same act. A
capture's identity is a digest of its own content bound to its run, so a
finding that cites it names bytes, not a row number that something else could
overwrite. Digest here means a cryptographic content hash: the same bytes give
the same digest, and any edit gives a different one.
"""

import hashlib
import json
import math
from dataclasses import dataclass, field


SEVERITIES = ("info", "low", "medium", "high", "critical")

REVIEW_DECISIONS = ("accepted", "rejected", "needs_review")


class RecordError(ValueError):
    """A record that does not satisfy the vocabulary."""


def canonical_bytes(value):
    """The one serialization identities are computed over.

    Sorted keys and a fixed layout, same convention as the fixture lab's
    canonical form, so a digest depends on content and not on dict ordering.
    """
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _nonempty_str(value, name):
    if not isinstance(value, str) or not value.strip():
        raise RecordError(f"{name} needs a nonempty string")
    return value


def _plain_json(value, name):
    try:
        canonical_bytes(value)
    except (TypeError, ValueError) as exc:
        raise RecordError(f"{name} needs plain JSON data") from exc
    return value


def action_identity(tool, destination):
    """The one normalized action identity the whole pipeline shares.

    Tool and destination, joined once, after the destination has been
    canonicalized by the policy layer. Every record that talks about an action
    carries this string, so feedback lands on the act that ran and a missing
    destination is a loud error here instead of an empty key downstream.
    """
    _nonempty_str(tool, "tool")
    _nonempty_str(destination, "destination")
    return f"{tool} -> {destination}"


@dataclass(frozen=True)
class Run:
    """One run: its identity and the digest of the policy it ran under."""

    run_id: str
    policy_digest: str

    def __post_init__(self):
        _nonempty_str(self.run_id, "run_id")
        _nonempty_str(self.policy_digest, "policy_digest")


def make_run(policy_snapshot, world_snapshot):
    """Derive a run whose identity is a digest over its actual inputs."""
    policy_digest = digest(_plain_json(policy_snapshot, "policy_snapshot"))
    run_id = digest({"policy": policy_snapshot,
                     "world": _plain_json(world_snapshot, "world_snapshot")})
    return Run(run_id=run_id, policy_digest=policy_digest)


@dataclass(frozen=True)
class Action:
    """One authorized act: a tool aimed at a destination with arguments."""

    action_id: str
    run_id: str
    tool: str
    destination: str
    arguments: dict = field(default_factory=dict)

    def __post_init__(self):
        _nonempty_str(self.run_id, "run_id")
        expected = action_identity(self.tool, self.destination)
        if self.action_id != expected:
            raise RecordError(
                f"action_id {self.action_id!r} is not the normalized identity "
                f"{expected!r}")
        _plain_json(self.arguments, "arguments")


def make_action(run_id, tool, destination, arguments=None):
    return Action(action_id=action_identity(tool, destination), run_id=run_id,
                  tool=tool, destination=destination,
                  arguments=dict(arguments or {}))


@dataclass(frozen=True)
class Capture:
    """One captured response, content-addressed and bound to its run."""

    capture_id: str
    run_id: str
    action_id: str
    status: int
    body: str

    def __post_init__(self):
        _nonempty_str(self.run_id, "run_id")
        _nonempty_str(self.action_id, "action_id")
        if type(self.status) is not int or not 100 <= self.status <= 599:
            raise RecordError("capture status needs an HTTP status integer")
        if not isinstance(self.body, str):
            raise RecordError("capture body needs a string")
        expected = digest({"run_id": self.run_id, "action_id": self.action_id,
                           "status": self.status, "body": self.body})
        if self.capture_id != expected:
            raise RecordError("capture_id is not the digest of this capture's "
                              "own content")


def make_capture(run_id, action_id, status, body):
    capture_id = digest({"run_id": run_id, "action_id": action_id,
                         "status": status, "body": body})
    return Capture(capture_id=capture_id, run_id=run_id, action_id=action_id,
                   status=status, body=body)


@dataclass(frozen=True)
class Finding:
    """One claim about a capture: a kind, a severity, and a verbatim quote.

    The record binds the claim to a specific capture digest and carries the
    quote itself. Whether the quote actually occurs in that capture is the
    write boundary's question, answered when the finding is recorded; whether
    the claim is TRUE is a separate matter for verification, later in the
    course. A verbatim quote is citation integrity, not exploitability.
    """

    finding_id: str
    run_id: str
    capture_id: str
    kind: str
    title: str
    severity: str
    quote: str

    def __post_init__(self):
        for name in ("finding_id", "run_id", "capture_id", "kind", "title"):
            _nonempty_str(getattr(self, name), name)
        if self.severity not in SEVERITIES:
            raise RecordError(f"unknown severity {self.severity!r}")
        _nonempty_str(self.quote, "quote")


@dataclass(frozen=True)
class ReviewDecision:
    """One review outcome for one finding, with the actor named."""

    finding_id: str
    run_id: str
    decision: str
    reason: str
    actor: str

    def __post_init__(self):
        for name in ("finding_id", "run_id", "reason", "actor"):
            _nonempty_str(getattr(self, name), name)
        if self.decision not in REVIEW_DECISIONS:
            raise RecordError(f"unknown review decision {self.decision!r}")


def is_finite_number(value):
    return (type(value) is not bool and isinstance(value, (int, float))
            and math.isfinite(value))
