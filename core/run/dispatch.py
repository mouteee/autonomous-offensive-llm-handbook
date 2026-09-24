"""The controlled executor: one action, an ordered plan, or a bounded batch,
all through the same recorder, with the six-status outcome vocabulary.

Whoever chose the action -- a deterministic ranking, a controller, a person --
dispatch re-asks the policy through the write boundary before anything runs,
and re-asks the recorded gate and stage too: a stop gate admits nothing, a
passive gate admits no active tool, and a staged run dispatches only in its
executable stages. A selection is advice; the door is the door. Outcome
statuses stay distinct: an
unavailable tool is not an error, an error is not a clean result, a skip is
neither, and none of them is evidence about the target. Unavailability does not
consume the action budget, and a per-tool counter stops an unavailable tool
from being re-queued forever, so a missing binary costs a bounded number of
ledger rows instead of the whole run.
"""

from ..controller.contract import Outcome
from ..controller.feedback import assemble_signal, scalarize
from .stages import dispatch_admission


EXECUTED_STATUSES = ("clean", "tool_error", "verified_evidence")


class Dispatcher:
    """Runs candidates through the recorder under policy and budget."""

    def __init__(self, recorder, policy, adapters, *, unavailable_limit=2):
        self.recorder = recorder
        self.policy = policy
        self.adapters = dict(adapters)
        self.unavailable_limit = unavailable_limit
        self._executed = 0
        self._unavailable_counts = {}

    def should_requeue(self, tool):
        """Whether an unavailable tool has any re-queue budget left."""
        return self._unavailable_counts.get(tool, 0) < self.unavailable_limit

    def dispatch(self, tool, destination, arguments=None):
        """One action through the door; answers the outcome row it recorded."""
        run_id = self.recorder.run.run_id
        admitted = self.recorder.record("action", {
            "run_id": run_id, "tool": tool, "destination": destination,
            "arguments": dict(arguments or {})})
        if not admitted["recorded"]:
            return {"status": "refused", "reason": admitted["reason"]}
        action_id = admitted["action_id"]
        # An identity whose outcome is already terminal is settled history: the
        # settle-once rule would refuse the second outcome anyway, so the
        # adapter is not run either -- an implicit duplicate never repeats the
        # side effect. An unresolved outcome is refused here too: the side
        # effect may have happened, and only the lifecycle's reconciliation
        # path, after checking the tool's declared idempotency, may repeat it.
        previous = self.recorder.outcome(action_id)
        if previous is not None:
            if previous["status"] == "unresolved":
                reason = ("action identity has an unresolved outcome; ordinary "
                          "dispatch does not repeat a possible side effect -- "
                          "reconciliation owns the unresolved case")
            else:
                reason = ("action identity already has a recorded outcome "
                          f"({previous['status']}); duplicates do not re-run")
            self.recorder.refuse("action", reason,
                                 {"run_id": run_id, "action_id": action_id})
            return {"status": "refused", "action_id": action_id,
                    "reason": reason}
        refused = dispatch_admission(self.recorder, self.policy, tool)
        if refused:
            self.recorder.record("outcome", {
                "run_id": run_id, "action_id": action_id,
                "status": "skipped", "detail": refused})
            return {"status": "skipped", "action_id": action_id,
                    "reason": refused}
        adapter = self.adapters.get(tool)
        if adapter is None:
            self._unavailable_counts[tool] = self._unavailable_counts.get(tool, 0) + 1
            self.recorder.record("outcome", {
                "run_id": run_id, "action_id": action_id,
                "status": "tool_unavailable",
                "detail": f"no adapter registered for {tool!r}"})
            return {"status": "tool_unavailable", "action_id": action_id,
                    "requeue": self.should_requeue(tool)}
        if self._executed >= self.policy.max_actions:
            self.recorder.record("outcome", {
                "run_id": run_id, "action_id": action_id, "status": "skipped",
                "detail": "action budget exhausted"})
            return {"status": "skipped", "action_id": action_id,
                    "reason": "action budget exhausted"}
        self._executed += 1
        try:
            raw = adapter(destination)
            if not isinstance(raw, dict) or set(raw) != {"status", "body"}:
                raise ValueError("adapter result needs exactly status and body")
            captured = self.recorder.record("capture", {
                "run_id": run_id, "action_id": action_id,
                "status": raw["status"], "body": raw["body"]})
            if not captured["recorded"]:
                raise ValueError(captured["reason"])
            self.recorder.record("outcome", {
                "run_id": run_id, "action_id": action_id, "status": "clean",
                "detail": captured["capture_id"]})
            return {"status": "clean", "action_id": action_id,
                    "capture_id": captured["capture_id"]}
        except Exception as exc:
            self.recorder.record("outcome", {
                "run_id": run_id, "action_id": action_id, "status": "tool_error",
                "detail": type(exc).__name__})
            return {"status": "tool_error", "action_id": action_id,
                    "error_type": type(exc).__name__}

    def skip(self, tool, destination, reason):
        """Decline planned work explicitly, leaving the reason in the ledger."""
        run_id = self.recorder.run.run_id
        admitted = self.recorder.record("action", {
            "run_id": run_id, "tool": tool, "destination": destination,
            "arguments": {}})
        if not admitted["recorded"]:
            return {"status": "refused", "reason": admitted["reason"]}
        self.recorder.record("outcome", {
            "run_id": run_id, "action_id": admitted["action_id"],
            "status": "skipped", "detail": reason})
        return {"status": "skipped", "action_id": admitted["action_id"],
                "reason": reason}

    def run_plan(self, rows):
        """An ordered plan, row by row, through the same door."""
        results = []
        for row in rows:
            if row["tool"] in self._unavailable_counts and not self.should_requeue(row["tool"]):
                results.append({"status": "not_requeued", "tool": row["tool"],
                                "destination": row["destination"],
                                "reason": "unavailability budget for this tool "
                                          "is spent"})
                continue
            results.append(self.dispatch(row["tool"], row["destination"],
                                         row.get("arguments")))
        return results

    def run_batch(self, rows, bound):
        """At most `bound` rows of the plan, in order, same door."""
        return self.run_plan(list(rows)[:bound])

    # Controller integration ----------------------------------------------------

    def select_and_run(self, controller, state, candidates):
        """Let a controller choose among eligible candidates, then re-ask policy.

        The controller's choice is advice: dispatch pushes the chosen action
        through the same recorder door as everything else, so a candidate the
        policy would turn away is turned away and recorded even though a controller
        picked it. Feedback goes back only for decisions whose action actually
        executed, under the shared feedback definition.
        """
        decision = controller.select(state, candidates)
        if decision is None:
            return {"status": "no_candidates"}
        chosen = next((c for c in candidates
                       if c.candidate_id == decision.candidate_id), None)
        if chosen is None:
            reason = ("controller decision names a candidate that was not "
                      f"offered: {decision.candidate_id!r}")
            self.recorder.refuse("action", reason,
                                 {"run_id": self.recorder.run.run_id})
            return {"status": "refused", "reason": reason,
                    "learning": {"applied": False, "reason": reason}}
        result = self.dispatch(chosen.features["tool"],
                               chosen.features["destination"])
        status = result["status"]
        executed = status in EXECUTED_STATUSES
        feedback = 0.0
        if executed:
            signal = assemble_signal(status=status, new_observations=1,
                                     novelty=chosen.novelty, cost=chosen.cost)
            feedback = scalarize(signal)
        if status not in ("refused", "not_requeued"):
            outcome = Outcome(decision_id=decision.decision_id,
                              candidate_id=decision.candidate_id,
                              run_id=self.recorder.run.run_id,
                              status=status, feedback=feedback,
                              executed=executed)
            result["learning"] = controller.observe(outcome)
        else:
            result["learning"] = {"applied": False,
                                  "reason": "the action was refused before "
                                            "execution"}
        result["decision_id"] = decision.decision_id
        return result
