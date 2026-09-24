"""The single write boundary: one door for every state change, refusals
included.

Everything mutable about a run lives behind one `record(kind, payload)` call.
The door validates the payload against the run identity and the policy, and it
answers with a decision record either way: an admitted write appends its event
to the ordered ledger, and a turned-away one appends a refusal event carrying the
reason. A refusal is data, not an exception -- the run's story includes what it
declined to do, and an unexplained refusal would be unfinished work.

The boundary is an application boundary. Adapter code and the host process are
trusted here, exactly as in the fixture lab; process and transport isolation
are a different layer's job and the lessons say so where it matters.
"""

import copy

from ..controller.contract import OUTCOME_STATUSES
from .policy import normalize_destination
from .records import Finding, RecordError, digest, make_action, make_capture


GATE_STATUSES = ("proceed", "limited", "indeterminate")
GATE_MODES = ("full", "passive", "stop")
OBSERVATION_STATES = ("measured", "unknown")
REVIEW_DECISIONS = ("accepted", "rejected", "needs_review")


def _refused(reason):
    return {"recorded": False, "reason": reason}


def _recorded(reason, **extra):
    return {"recorded": True, "reason": reason, **extra}


class Recorder:
    """Owns a run's mutable state; every change comes through `record`."""

    def __init__(self, run, policy):
        self.run = run
        self.policy = policy
        self._events = []
        self._observations = {}
        self._gate = None
        self._stage = None
        self._closed = None
        self._outcomes = {}
        self._captures = {}
        self._authorized = set()
        self._findings = {}
        self._reviews = []

    # The one door -------------------------------------------------------------

    def record(self, kind, payload):
        if self._closed:
            # Terminal closure is enforced here, at the shared boundary, so a
            # finished or aborted run cannot quietly acquire new effects under
            # the identity of a report someone already received. The refusal
            # itself is still appended: the attempt is part of the story.
            return self._refuse(kind,
                                f"the run is closed ({self._closed}); a "
                                "terminal run records no further effects",
                                payload if isinstance(payload, dict) else {})
        handler = getattr(self, f"_record_{kind}", None)
        if handler is None:
            return self._refuse(kind, f"unknown record kind {kind!r}", payload)
        if not isinstance(payload, dict):
            return self._refuse(kind, "payload is not an object", {})
        if payload.get("run_id") != self.run.run_id:
            return self._refuse(kind, "payload run_id does not belong to this run",
                                payload)
        try:
            return handler(payload)
        except (KeyError, TypeError) as exc:
            return self._refuse(kind, f"malformed payload: {exc!r}", payload)

    def refuse(self, kind, reason, payload=None):
        """Record a refusal through the same ledger admitted writes use.

        Host components (the stage machine, the dispatcher) call this when
        they decline work on their own authority; the boundary's internal
        validators route here too. Either way the run's story carries the
        declined operation and its reason in order, beside everything else.
        """
        return self._refuse(kind, reason, payload or {})

    def _refuse(self, kind, reason, payload):
        self._events.append({"event": "refused", "kind": kind, "reason": reason,
                             "payload_keys": sorted(payload) if isinstance(payload, dict) else []})
        return _refused(reason)

    def _append(self, event, **fields):
        self._events.append({"event": event, **fields})

    # Handlers, one per record kind --------------------------------------------

    def _record_observation(self, payload):
        name, state = payload["field"], payload["state"]
        if state not in OBSERVATION_STATES:
            return self._refuse("observation", f"unknown observation state {state!r}", payload)
        if state == "unknown" and payload.get("value") is not None:
            return self._refuse("observation",
                                "an unknown observation carries no value", payload)
        if state == "measured" and not str(payload.get("source", "")).strip():
            return self._refuse("observation",
                                "a measured observation names its source", payload)
        row = {"field": name, "value": payload.get("value"), "state": state,
               "source": payload.get("source", "")}
        self._observations[name] = row
        self._append("observation", **row)
        return _recorded("observation recorded", field=name)

    def _record_gate(self, payload):
        status, mode = payload["status"], payload["mode"]
        if status not in GATE_STATUSES or mode not in GATE_MODES:
            return self._refuse("gate", "unknown gate status or mode", payload)
        self._gate = {"status": status, "mode": mode,
                      "inputs": copy.deepcopy(payload.get("inputs", {}))}
        self._append("gate", **copy.deepcopy(self._gate))
        return _recorded("gate recorded", status=status)

    def _record_stage(self, payload):
        self._stage = payload["stage"]
        self._append("stage", stage=payload["stage"])
        return _recorded("stage recorded", stage=payload["stage"])

    def _record_action(self, payload):
        tool, destination = payload["tool"], payload["destination"]
        for decision in (self.policy.knows_tool(tool),
                         self.policy.allows_destination(destination)):
            if not decision["allowed"]:
                return self._refuse("action", decision["reason"], payload)
        try:
            # One act, one identity: the destination is canonicalized here, at
            # the door, so an alias spelling (case, default port, dot segments)
            # cannot mint a second identity for the same act. The requested
            # spelling stays on the event where a reader can see it.
            canonical = normalize_destination(destination)
            action = make_action(self.run.run_id, tool, canonical,
                                 payload.get("arguments"))
        except ValueError as exc:
            return self._refuse("action", f"malformed action: {exc}", payload)
        self._authorized.add(action.action_id)
        event = {"action_id": action.action_id, "tool": tool,
                 "destination": canonical}
        if destination != canonical:
            event["requested_destination"] = destination
        self._append("action_authorized", **event)
        return _recorded("action authorized", action_id=action.action_id)

    def _record_capture(self, payload):
        if payload["action_id"] not in self._authorized:
            return self._refuse("capture",
                                "capture names an action this run never "
                                "authorized", payload)
        try:
            capture = make_capture(self.run.run_id, payload["action_id"],
                                   payload["status"], payload["body"])
        except ValueError as exc:
            return self._refuse("capture", f"malformed capture: {exc}", payload)
        self._captures[capture.capture_id] = capture
        self._append("capture", capture_id=capture.capture_id,
                     action_id=capture.action_id, status=capture.status)
        return _recorded("capture recorded", capture_id=capture.capture_id)

    def _record_outcome(self, payload):
        action_id, status = payload["action_id"], payload["status"]
        if action_id not in self._authorized:
            return self._refuse("outcome",
                                "outcome names an action this run never "
                                "authorized", payload)
        if status not in OUTCOME_STATUSES:
            return self._refuse("outcome", f"unknown outcome status {status!r}",
                                payload)
        previous = self._outcomes.get(action_id)
        if previous is not None and previous["status"] != "unresolved":
            return self._refuse("outcome",
                                "a terminal outcome for this action is already "
                                "recorded", payload)
        row = {"action_id": action_id, "status": status,
               "detail": payload.get("detail", "")}
        self._outcomes[action_id] = row
        self._append("outcome", **row)
        return _recorded("outcome recorded", action_id=action_id, status=status)

    def _record_finding(self, payload):
        capture = self._captures.get(payload["capture_id"])
        if capture is None:
            return self._refuse("finding",
                                "finding cites a capture this run does not hold",
                                payload)
        quote = payload["quote"]
        if not isinstance(quote, str) or not quote.strip() or quote not in capture.body:
            return self._refuse("finding",
                                "quote does not occur verbatim in the cited "
                                "capture", payload)
        finding_id = digest({"run_id": self.run.run_id,
                             "capture_id": capture.capture_id,
                             "kind": payload["kind"], "quote": quote})
        try:
            finding = Finding(finding_id=finding_id, run_id=self.run.run_id,
                              capture_id=capture.capture_id,
                              kind=payload["kind"], title=payload["title"],
                              severity=payload["severity"], quote=quote)
        except ValueError as exc:
            return self._refuse("finding", f"malformed finding: {exc}", payload)
        self._findings[finding_id] = finding
        self._append("finding", finding_id=finding_id, kind=finding.kind,
                     severity=finding.severity, capture_id=capture.capture_id)
        return _recorded("finding recorded", finding_id=finding_id)

    def _record_review(self, payload):
        if payload["finding_id"] not in self._findings:
            return self._refuse("review",
                                "review names a finding this run does not hold",
                                payload)
        if payload["decision"] not in REVIEW_DECISIONS:
            return self._refuse("review",
                                f"unknown review decision {payload['decision']!r}",
                                payload)
        row = {"finding_id": payload["finding_id"],
               "decision": payload["decision"],
               "reason": payload["reason"], "actor": payload["actor"]}
        self._reviews.append(row)
        self._append("review", **row)
        return _recorded("review recorded", finding_id=payload["finding_id"])

    # Closure --------------------------------------------------------------------

    def close(self, how):
        """Seal the run at the write boundary: finished or aborted, no third word.

        Closure is one-way. There is deliberately no reopen: continuing work
        after a terminal report means starting a new run with its own
        accounting, not appending to a report someone may already have read.
        """
        if how not in ("finished", "aborted"):
            raise RecordError(f"unknown closure {how!r}; a run closes as "
                              "finished or aborted")
        if self._closed is None:
            self._closed = how
        return self._closed

    @property
    def closed(self):
        return self._closed

    # Reads --------------------------------------------------------------------

    @property
    def stage(self):
        """The most recently recorded stage, or None when no stage machine ran."""
        return self._stage

    @property
    def gate(self):
        return copy.deepcopy(self._gate)

    @property
    def observations(self):
        return copy.deepcopy(self._observations)

    def capture(self, capture_id):
        return self._captures.get(capture_id)

    def outcome(self, action_id):
        """The recorded outcome for an action identity, or None."""
        return copy.deepcopy(self._outcomes.get(action_id))

    def snapshot(self):
        events = copy.deepcopy(self._events)
        refusals = [e for e in events if e["event"] == "refused"]
        return {
            "schema": "course-run-report/v1",
            "run_id": self.run.run_id,
            "policy_digest": self.run.policy_digest,
            "closed": self._closed,
            "stage": self._stage,
            "gate": copy.deepcopy(self._gate),
            "observations": copy.deepcopy(self._observations),
            "outcomes": copy.deepcopy(self._outcomes),
            "captures": {cid: {"action_id": c.action_id, "status": c.status,
                               "body": c.body}
                         for cid, c in sorted(self._captures.items())},
            "findings": [vars(f) for _, f in sorted(self._findings.items())],
            "reviews": copy.deepcopy(self._reviews),
            "events": events,
            "counts": {"events": len(events), "refusals": len(refusals)},
        }
