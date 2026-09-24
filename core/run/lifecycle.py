"""Stop, recover and finish: budgets, retries, checkpoints and the terminal record.

Two rules carry this module. First, an outcome is a terminal fact: a retry is
part of the attempt, not an edit to the record, so the retrying executor runs
its attempts before writing the one outcome the action gets. Second, missing
evidence is missing: an action interrupted between execution and recording
resumes as `unresolved`, and reconciliation either finds its capture and
settles it, or leaves it explicitly unresolved -- it is not re-dispatched
unless its tool is declared idempotent, because repeating an uncertain side
effect is how one write becomes two.

Admission happens at the attempt, not around it: before every attempt --
first try and every retry alike -- the executor re-asks the recorded gate and
stage, cancellation, elapsed wall time and the remaining action and cost
budgets, so a caller that skips the plan runner cannot skip the controls.

Completion here is gated: `finish` answers with a refusal while any planned
action lacks a terminal or explicitly unresolved state. The originating
implementation's completion step was unconditional accounting, with sequencing
living in an operator script; lesson 9 labels the gate as a teaching
correction. A completed finish -- or an abort -- closes the run at the write
boundary, the same terminal closure the fixture harness keeps, and a closed
run refuses every later effect. A completed run is still not an accepted
report -- acceptance is a human review decision, recorded separately.
"""

import time

from .records import digest, make_run
from .recorder import Recorder
from .stages import dispatch_admission


BUDGET_OWNERS = {
    "actions": "policy.max_actions",
    "model_calls": "policy.max_model_calls",
    "wall_seconds": "operator.wall_clock",
    "cost": "operator.cost_ceiling",
}


class Budgets:
    """Named budgets with named owners; exhaustion is an event, not an exception."""

    def __init__(self, *, actions, model_calls, wall_seconds, cost):
        self.limits = {"actions": actions, "model_calls": model_calls,
                       "wall_seconds": wall_seconds, "cost": cost}
        self.used = {name: 0.0 for name in self.limits}
        self.exhausted_events = []

    def charge(self, name, amount):
        self.used[name] += amount

    def remaining(self, name):
        return self.limits[name] - self.used[name]

    def exhausted(self, name):
        if self.used[name] >= self.limits[name]:
            event = {"budget": name, "owner": BUDGET_OWNERS[name],
                     "limit": self.limits[name], "used": self.used[name]}
            if event not in self.exhausted_events:
                self.exhausted_events.append(event)
            return event
        return None

    def snapshot(self):
        return {"limits": dict(self.limits), "used": dict(self.used),
                "exhausted": [dict(e) for e in self.exhausted_events]}

    def restore(self, snapshot):
        self.limits = dict(snapshot["limits"])
        self.used = dict(snapshot["used"])
        self.exhausted_events = [dict(e) for e in snapshot["exhausted"]]


class Lifecycle:
    """The accountable loop around dispatch: run, interrupt, resume, finish."""

    def __init__(self, recorder, adapters, budgets, *, clock=time.monotonic,
                 retry_limit=1, no_progress_limit=3, idempotent_tools=()):
        self.recorder = recorder
        self.adapters = dict(adapters)
        self.budgets = budgets
        self.clock = clock
        self.retry_limit = retry_limit
        self.no_progress_limit = no_progress_limit
        # Which tools may be re-dispatched after an unresolved attempt. This
        # belongs beside the tool catalogue in the policy; it lives here so the
        # lesson can teach the rule without changing the policy record shape.
        self.idempotent_tools = frozenset(idempotent_tools)
        self.attempts = []
        self.stop_reason = None
        self._cancelled = False
        self._no_progress_streak = 0
        self._started = clock()
        # Wall time already spent before this construction (nonzero on resume),
        # so a checkpoint/resume cycle cannot hand the wall budget back.
        self._wall_base = float(budgets.used.get("wall_seconds", 0.0))

    # Running --------------------------------------------------------------------

    def cancel(self, reason="cancelled by operator"):
        self._cancelled = True
        self.stop_reason = reason

    @property
    def cancelled(self):
        return self._cancelled

    @property
    def closed(self):
        """The run's terminal closure, owned by the recorder: None until finish or abort."""
        return self.recorder.closed

    def _account_wall(self):
        elapsed = self.clock() - self._started
        self.budgets.used["wall_seconds"] = self._wall_base + elapsed

    def run_halted(self):
        """Closure, cancellation or wall exhaustion: the stops that end the whole run.

        These are distinct from the action budgets below because they stop
        everything -- model calls included -- while a spent action or cost
        budget stops actions and nothing else. Closure is first: a finished or
        aborted run spends nothing further, model calls included, even through
        a caller that skips the write boundary.
        """
        if self.closed:
            return f"the run is closed ({self.closed})"
        if self._cancelled:
            return self.stop_reason
        self._account_wall()
        event = self.budgets.exhausted("wall_seconds")
        if event:
            return f"budget exhausted: {event['budget']} ({event['owner']})"
        return None

    def _blocked(self):
        """The first reason no further action may run, or None.

        Model calls are deliberately not in this list: a run that has spent
        its model budget can still execute already-planned actions, and the
        model budget is enforced where model calls happen.
        """
        halted = self.run_halted()
        if halted:
            return halted
        for name in ("actions", "cost"):
            event = self.budgets.exhausted(name)
            if event:
                return f"budget exhausted: {event['budget']} ({event['owner']})"
        if self._no_progress_streak >= self.no_progress_limit:
            return "no progress: consecutive attempts produced no new evidence"
        return None

    def _unaffordable(self, tool):
        """Why the tool's declared cost refuses the next attempt, or None.

        The cost of an attempt is known before it runs -- it is the tool's
        declared cost -- so fitting it is a preflight comparison, not a
        prediction: an attempt whose declared cost exceeds the remaining
        allowance is refused without invoking its adapter. This is deliberately
        different from wall time, whose spend is only known afterwards.
        """
        cost = self.recorder.policy.tools[tool].cost
        remaining = self.budgets.remaining("cost")
        if cost > remaining:
            return (f"declared cost {cost} exceeds the remaining cost "
                    f"allowance {remaining} ({BUDGET_OWNERS['cost']})")
        return None

    def execute_with_retries(self, tool, destination, arguments=None):
        """Attempts up to the retry bound, then the one terminal outcome.

        The recorder's settle-once rule makes an outcome a terminal fact, so
        retrying after recording would be rewriting history; the retries happen
        inside the attempt, and the single recorded outcome carries the attempt
        count in its detail. Admission runs before anything else: a closed run
        refuses at the write boundary, a settled or unresolved identity is
        refused here, and the gate, stage, budget and cancellation checks run
        before every attempt inside `_attempt`.
        """
        run_id = self.recorder.run.run_id
        admitted = self.recorder.record("action", {
            "run_id": run_id, "tool": tool, "destination": destination,
            "arguments": dict(arguments or {})})
        if not admitted["recorded"]:
            return {"status": "refused", "reason": admitted["reason"]}
        action_id = admitted["action_id"]
        # The duplicate guard, same as the dispatcher's door: a settled
        # identity never re-runs, and an unresolved one is refused here too,
        # because the side effect may have happened -- reconcile() is the one
        # path that may repeat it, after checking the tool's declared
        # idempotency.
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
        return self._attempt(action_id, tool, destination)

    def _attempt(self, action_id, tool, destination, *, keep_unresolved=False):
        """Admission, then the bounded attempt loop, then one terminal outcome.

        Every attempt -- the first and every retry -- is admitted against the
        recorded gate and stage, cancellation, closure, elapsed wall time and
        the remaining action and cost budgets before the adapter runs. A retry
        allowance never outspends a budget: the loop re-asks between attempts
        and stops with the reason in the outcome detail. With
        `keep_unresolved`, reconciliation's flag, a refused admission leaves
        the existing unresolved outcome standing instead of relabeling the
        uncertainty as a skip.
        """
        run_id = self.recorder.run.run_id
        refused = dispatch_admission(self.recorder, self.recorder.policy, tool)
        if not refused:
            blocked = self._blocked()
            if blocked:
                self.stop_reason = self.stop_reason or blocked
                refused = blocked
        if not refused:
            # The declared-cost preflight does not set a stop reason: an
            # unaffordable action is refused on its own, and cheaper work may
            # still fit the same allowance.
            refused = self._unaffordable(tool)
        if refused:
            if keep_unresolved:
                self.recorder.refuse(
                    "reconcile",
                    f"{action_id} stays unresolved: re-dispatch not admitted "
                    f"({refused})",
                    {"run_id": run_id, "action_id": action_id})
                return {"status": "refused", "action_id": action_id,
                        "reason": refused}
            self.recorder.record("outcome", {
                "run_id": run_id, "action_id": action_id,
                "status": "skipped", "detail": refused})
            return {"status": "skipped", "action_id": action_id,
                    "reason": refused}
        adapter = self.adapters.get(tool)
        if adapter is None:
            self.recorder.record("outcome", {
                "run_id": run_id, "action_id": action_id,
                "status": "tool_unavailable", "detail": "no adapter"})
            return {"status": "tool_unavailable", "action_id": action_id}

        last_error = None
        stopped = None
        attempts_run = 0
        for attempt in range(1, self.retry_limit + 2):
            if attempt > 1:
                stopped = self._blocked()
                if stopped:
                    self.stop_reason = self.stop_reason or stopped
                else:
                    stopped = dispatch_admission(self.recorder,
                                                 self.recorder.policy, tool) \
                        or self._unaffordable(tool)
                if stopped:
                    break
            self.budgets.charge("actions", 1)
            self.budgets.charge("cost", self.recorder.policy.tools[tool].cost)
            attempts_run = attempt
            row = {"action_id": action_id, "attempt": attempt}
            try:
                raw = adapter(destination)
                if not isinstance(raw, dict) or set(raw) != {"status", "body"}:
                    raise ValueError("adapter result needs exactly status and body")
                captured = self.recorder.record("capture", {
                    "run_id": run_id, "action_id": action_id,
                    "status": raw["status"], "body": raw["body"]})
                if not captured["recorded"]:
                    raise ValueError(captured["reason"])
                row.update(result="clean", capture_id=captured["capture_id"])
                self.attempts.append(row)
                self._no_progress_streak = 0
                self.recorder.record("outcome", {
                    "run_id": run_id, "action_id": action_id, "status": "clean",
                    "detail": f"attempt {attempt} of at most "
                              f"{self.retry_limit + 1}"})
                return {"status": "clean", "action_id": action_id,
                        "attempts": attempt,
                        "capture_id": captured["capture_id"]}
            except Exception as exc:
                last_error = type(exc).__name__
                row.update(result="error", error_type=last_error)
                self.attempts.append(row)
                self._no_progress_streak += 1
        detail = f"{last_error} after {attempts_run} attempts"
        if stopped:
            detail += f"; retries stopped: {stopped}"
        else:
            detail = f"{last_error} after {self.retry_limit + 1} attempts"
        self.recorder.record("outcome", {
            "run_id": run_id, "action_id": action_id, "status": "tool_error",
            "detail": detail})
        return {"status": "tool_error", "action_id": action_id,
                "attempts": attempts_run, "error_type": last_error}

    def run_plan(self, rows):
        """The plan in order; a stop turns the remainder into recorded skips."""
        results = []
        remaining = list(rows)
        while remaining:
            reason = self._blocked()
            if reason:
                self.stop_reason = self.stop_reason or reason
                for row in remaining:
                    skipped = self._skip(row, reason)
                    results.append(skipped)
                break
            row = remaining.pop(0)
            results.append(self.execute_with_retries(
                row["tool"], row["destination"], row.get("arguments")))
        return results

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

    def _skip(self, row, reason):
        return self.skip(row["tool"], row["destination"], reason)

    # Checkpoint and resume --------------------------------------------------------

    def checkpoint(self):
        # The wall budget is brought up to date first, so the elapsed time a
        # checkpoint carries is what the clock actually observed rather than
        # whatever the last admission check happened to leave behind.
        self._account_wall()
        body = {
            "schema": "course-checkpoint/v1",
            "recorder": self.recorder.snapshot(),
            "budgets": self.budgets.snapshot(),
            "attempts": [dict(a) for a in self.attempts],
            "stop_reason": self.stop_reason,
        }
        # Tamper evidence, not tamper proofing: the digest makes silent edits
        # loud at resume. An operator who edits the file can recompute it, and
        # the lesson says so.
        return {**body, "digest": digest(body)}

    @classmethod
    def resume(cls, checkpoint, policy, adapters, *, clock=time.monotonic,
               **kwargs):
        """Rebuild a run from its checkpoint, through the same write boundary.

        The recorder is reconstructed by replaying the checkpoint's own tables
        through the one door -- state is the ledger folded, not a pickle. An
        action whose outcome was missing at the interruption comes back as
        `unresolved`; reconcile() settles it or leaves it explicitly so.
        Arguments of authorized actions are not carried by the snapshot, a
        stated simplification of this teaching checkpoint.
        """
        body = {k: v for k, v in checkpoint.items() if k != "digest"}
        if checkpoint.get("digest") != digest(body):
            raise ValueError("checkpoint digest does not match its body; "
                             "refusing to resume tampered or corrupted state")
        saved = checkpoint["recorder"]
        if policy.digest() != saved["policy_digest"]:
            raise ValueError("the supplied policy is not the one this run was "
                             "authorized under; resuming would misattribute "
                             "authorization")
        # The run identity is restored verbatim: this is the same run resuming,
        # not a new one, so the digest is not recomputed from a changed world.
        from .records import Run
        recorder = Recorder(Run(run_id=saved["run_id"],
                                policy_digest=saved["policy_digest"]), policy)
        for name, row in sorted(saved["observations"].items()):
            recorder.record("observation", {"run_id": saved["run_id"], **row})
        if saved["gate"]:
            recorder.record("gate", {"run_id": saved["run_id"], **saved["gate"]})
        # The current stage is state the dispatch door reads, so it folds back
        # too: a run checkpointed outside its executable stages must not
        # resume into a door with no stage opinion. (`get`: checkpoints
        # written before the field existed replay stageless.)
        if saved.get("stage"):
            recorder.record("stage", {"run_id": saved["run_id"],
                                      "stage": saved["stage"]})
        for capture_id, capture in sorted(saved["captures"].items()):
            tool, _, destination = capture["action_id"].partition(" -> ")
            recorder.record("action", {"run_id": saved["run_id"], "tool": tool,
                                       "destination": destination})
            recorder.record("capture", {"run_id": saved["run_id"],
                                        "action_id": capture["action_id"],
                                        "status": capture["status"],
                                        "body": capture["body"]})
        replayed = {c["action_id"] for c in saved["captures"].values()}
        authorized = {e["action_id"] for e in saved["events"]
                      if e["event"] == "action_authorized"}
        for action_id in sorted(authorized - replayed):
            tool, _, destination = action_id.partition(" -> ")
            recorder.record("action", {"run_id": saved["run_id"], "tool": tool,
                                       "destination": destination})
        captured_ids = {c["action_id"] for c in saved["captures"].values()}
        for action_id, outcome in sorted(saved["outcomes"].items()):
            if (outcome["status"] in ("clean", "verified_evidence")
                    and action_id not in captured_ids):
                # An evidence-bearing status with no evidence in the same
                # checkpoint is exactly the fabrication the fold must not
                # believe: it resumes unresolved, with the reason recorded.
                recorder.refuse("outcome",
                                f"checkpoint carried a {outcome['status']!r} "
                                f"outcome for {action_id} with no capture; "
                                "replayed as unresolved")
                recorder.record("outcome", {
                    "run_id": saved["run_id"], "action_id": action_id,
                    "status": "unresolved",
                    "detail": "evidence-bearing checkpoint outcome had no "
                              "capture"})
                continue
            recorder.record("outcome", {"run_id": saved["run_id"], **outcome})
        for action_id in sorted(authorized - set(saved["outcomes"])):
            recorder.record("outcome", {
                "run_id": saved["run_id"], "action_id": action_id,
                "status": "unresolved",
                "detail": "interrupted before its outcome was recorded"})
        for finding in saved["findings"]:
            recorder.record("finding", {"run_id": saved["run_id"], **{
                k: finding[k] for k in ("capture_id", "kind", "title",
                                        "severity", "quote")}})
        for review in saved["reviews"]:
            recorder.record("review", {"run_id": saved["run_id"], **review})
        budgets = Budgets(actions=1, model_calls=1, wall_seconds=1, cost=1)
        budgets.restore(checkpoint["budgets"])
        lifecycle = cls(recorder, adapters, budgets, clock=clock, **kwargs)
        lifecycle.attempts = [dict(a) for a in checkpoint["attempts"]]
        lifecycle.stop_reason = checkpoint["stop_reason"]
        # Terminal closure survives the fold: a run that finished or aborted
        # before the checkpoint resumes closed, and stays closed. (`get`, not
        # a key access: checkpoints written before closure existed replay open.)
        if saved.get("closed"):
            recorder.close(saved["closed"])
        return lifecycle

    def reconcile(self):
        """Settle what the evidence supports; leave the rest explicitly unresolved.

        An unresolved action whose capture exists settles to `clean` through
        the settle-once rule -- the evidence was already on disk, only the
        outcome row was lost. An unresolved action with no capture stays
        unresolved: nothing here invents a success, and this is the one path
        that may re-dispatch one -- through `_redispatch`, which re-verifies
        the tool's declared idempotency, because the side effect may have
        happened. A closed run reconciles nothing: its terminal report is
        already out.
        """
        if self.closed:
            self.recorder.refuse(
                "reconcile",
                f"reconcile refused: the run is closed ({self.closed})")
            return []
        snapshot = self.recorder.snapshot()
        report = []
        for action_id, outcome in sorted(snapshot["outcomes"].items()):
            if outcome["status"] != "unresolved":
                continue
            capture_id = next((cid for cid, c in snapshot["captures"].items()
                               if c["action_id"] == action_id), None)
            if capture_id is not None:
                self.recorder.record("outcome", {
                    "run_id": snapshot["run_id"], "action_id": action_id,
                    "status": "clean",
                    "detail": f"settled on reconciliation: capture "
                              f"{capture_id[:12]} already existed"})
                report.append({"action_id": action_id, "settled": "clean",
                               "capture_id": capture_id})
                continue
            tool = action_id.split(" -> ", 1)[0]
            if tool in self.idempotent_tools and tool in self.adapters:
                retried = self._redispatch(action_id, tool,
                                           action_id.split(" -> ", 1)[1])
                if retried["status"] == "refused":
                    # The gate, stage or budgets refused the repeat: the
                    # action keeps its unresolved outcome -- the uncertainty
                    # is a fact, and a refusal is not evidence about it.
                    report.append({"action_id": action_id,
                                   "settled": "unresolved",
                                   "reason": retried["reason"]})
                    continue
                report.append({"action_id": action_id,
                               "settled": "re-dispatched (declared idempotent)",
                               "result": retried["status"]})
                continue
            self.recorder.refuse(
                "reconcile",
                f"{action_id} stays unresolved: no capture found, and the tool "
                "is not declared idempotent, so the side effect may have "
                "happened and is not repeated")
            report.append({"action_id": action_id, "settled": "unresolved"})
        return report

    def _redispatch(self, action_id, tool, destination):
        """The controlled re-execution path for one unresolved action.

        Ordinary dispatch refuses unresolved identities outright; this method
        is reconciliation's alone. It re-verifies the declaration it exists to
        enforce -- the tool must be in `idempotent_tools` -- and then runs the
        same admitted attempt loop as any other dispatch, so gate, stage,
        budget and cancellation checks still apply to the repeat.
        """
        if tool not in self.idempotent_tools:
            reason = (f"re-dispatch refused: {tool!r} is not declared "
                      "idempotent, and repeating an uncertain side effect "
                      "needs that declaration")
            self.recorder.refuse("reconcile", reason,
                                 {"run_id": self.recorder.run.run_id,
                                  "action_id": action_id})
            return {"status": "refused", "action_id": action_id,
                    "reason": reason}
        return self._attempt(action_id, tool, destination,
                             keep_unresolved=True)

    # Finishing --------------------------------------------------------------------

    def _pending_actions(self):
        snapshot = self.recorder.snapshot()
        authorized = {e["action_id"] for e in snapshot["events"]
                      if e["event"] == "action_authorized"}
        return sorted(authorized - set(snapshot["outcomes"]))

    def finish(self):
        """The gated terminal record: every planned action accounted for.

        The originating implementation completed unconditionally and left
        sequencing to an operator script; this gate is the teaching
        correction. Completion is still not acceptance: the report's findings
        keep their review state, whatever it is. A completed finish closes the
        run at the write boundary -- the same closure the fixture harness
        keeps -- so the report handed back is the last word this run gets to
        write. Calling finish again answers the same closed report.
        """
        if self.closed:
            return {"completed": True,
                    "report": self._report(aborted=self.closed == "aborted")}
        pending = self._pending_actions()
        if pending:
            self.recorder.refuse("complete",
                                 f"completion refused: {len(pending)} action(s) "
                                 "have no terminal or unresolved outcome")
            return {"completed": False, "pending": pending,
                    "reason": "every planned action needs a terminal or "
                              "explicitly unresolved state first"}
        self._account_wall()
        self.recorder.close("finished")
        return {"completed": True, "report": self._report(aborted=False)}

    def abort(self, reason):
        """The same accounting, under an abort reason, with pending work skipped.

        Abort closes the run exactly as finish does; an already-closed run
        refuses a second closure rather than rewriting its stop reason.
        """
        if self.closed:
            refusal = f"abort refused: the run is already closed ({self.closed})"
            self.recorder.refuse("complete", refusal)
            return {"completed": False, "reason": refusal}
        for action_id in self._pending_actions():
            self.recorder.record("outcome", {
                "run_id": self.recorder.run.run_id, "action_id": action_id,
                "status": "skipped", "detail": f"run aborted: {reason}"})
        self.stop_reason = f"aborted: {reason}"
        self._account_wall()
        self.recorder.close("aborted")
        return {"completed": True, "report": self._report(aborted=True)}

    def _report(self, *, aborted):
        snapshot = self.recorder.snapshot()
        outcomes = snapshot["outcomes"].values()
        by_status = {}
        for outcome in outcomes:
            by_status[outcome["status"]] = by_status.get(outcome["status"], 0) + 1
        omitted = [{"action_id": aid, "reason": o["detail"]}
                   for aid, o in sorted(snapshot["outcomes"].items())
                   if o["status"] == "skipped"]
        unresolved = [aid for aid, o in sorted(snapshot["outcomes"].items())
                      if o["status"] == "unresolved"]
        return {
            "schema": "course-terminal-report/v1",
            "run_id": snapshot["run_id"],
            "aborted": aborted,
            "stop_reason": self.stop_reason,
            "outcomes_by_status": by_status,
            "coverage": {"planned": len(snapshot["outcomes"]),
                         "terminal": len(snapshot["outcomes"]) - len(unresolved),
                         "unresolved": unresolved},
            "evidence_count": len(snapshot["captures"]),
            "omitted": omitted,
            "attempts": [dict(a) for a in self.attempts],
            "resource_use": self.budgets.snapshot(),
            "acceptance": "report acceptance is a separate human decision",
            "run_report": snapshot,
        }
