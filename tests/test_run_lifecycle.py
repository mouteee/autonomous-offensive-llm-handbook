"""The lifecycle, held at its stops: budgets, retries, resume, completion."""

from core.run.demo_lifecycle import FakeClock, build_policy, make_adapters
from core.run.lifecycle import Budgets, Lifecycle
from core.run.recorder import Recorder
from core.run.records import make_run


def chapter_claim(chapter, *sentences):
    """Anchor a test to the verbatim lesson sentence(s) it backs.

    Same declaration shape as tests/test_chapter_claims.py: verify_claims.sh's
    Check C parses these decorators and goes red when a declared sentence is
    no longer present in its chapter.
    """
    def deco(fn):
        return fn
    return deco


DEST = "https://lab.example/"


def fresh(*, adapters=None, retry_limit=1, no_progress_limit=3,
          idempotent_tools=(), **budget_overrides):
    policy = build_policy()
    run = make_run(policy.snapshot(), {"world": "lifecycle-tests"})
    recorder = Recorder(run, policy)
    limits = {"actions": 10, "model_calls": 4, "wall_seconds": 600, "cost": 50}
    limits.update(budget_overrides)
    budgets = Budgets(**limits)
    clock = FakeClock()
    lifecycle = Lifecycle(recorder, adapters or make_adapters(), budgets,
                          clock=clock, retry_limit=retry_limit,
                          no_progress_limit=no_progress_limit,
                          idempotent_tools=idempotent_tools)
    return recorder, lifecycle, clock


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "A retry is part of the attempt, not an edit to the record: an action gets "
    "one terminal outcome carrying its attempt count.",
)
def test_a_retry_lands_inside_one_terminal_outcome():
    recorder, lifecycle, _ = fresh()
    result = lifecycle.execute_with_retries("flaky_probe", DEST)
    assert result["status"] == "clean"
    assert result["attempts"] == 2
    outcome = recorder.snapshot()["outcomes"][result["action_id"]]
    assert outcome["status"] == "clean"
    assert "attempt 2" in outcome["detail"]
    dead = lifecycle.execute_with_retries("dead_probe", DEST)
    assert dead["status"] == "tool_error"
    assert dead["attempts"] == 2
    assert len([a for a in lifecycle.attempts
                if a["action_id"] == dead["action_id"]]) == 2


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "Budget exhaustion is an event with a named owner, and the remaining plan "
    "becomes recorded skips.",
)
def test_budget_exhaustion_names_its_owner_and_skips_the_rest():
    recorder, lifecycle, _ = fresh(actions=1)
    plan = [{"tool": "steady_probe", "destination": DEST},
            {"tool": "flaky_probe", "destination": DEST},
            {"tool": "dead_probe", "destination": DEST}]
    results = lifecycle.run_plan(plan)
    assert results[0]["status"] == "clean"
    assert all(r["status"] == "skipped" for r in results[1:])
    assert "policy.max_actions" in results[1]["reason"]
    exhausted = lifecycle.budgets.snapshot()["exhausted"]
    assert exhausted and exhausted[0]["owner"] == "policy.max_actions"


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "the wall clock is a budget like any other",
)
def test_the_wall_budget_stops_the_plan():
    recorder, lifecycle, clock = fresh(wall_seconds=30)
    clock.now = 31.0
    results = lifecycle.run_plan([{"tool": "steady_probe", "destination": DEST}])
    assert results[0]["status"] == "skipped"
    assert "wall" in results[0]["reason"]


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "Cancellation stops the loop and accounts for what it stopped.",
)
def test_cancellation_turns_remaining_work_into_recorded_skips():
    recorder, lifecycle, _ = fresh()
    lifecycle.cancel("operator asked for a stop")
    results = lifecycle.run_plan([{"tool": "steady_probe", "destination": DEST}])
    assert results[0]["status"] == "skipped"
    assert "operator asked for a stop" in results[0]["reason"]
    assert lifecycle.stop_reason == "operator asked for a stop"


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "No progress is a stop reason, not a loop.",
)
def test_no_progress_detection_stops_the_plan():
    recorder, lifecycle, _ = fresh(no_progress_limit=2, retry_limit=0)
    plan = [{"tool": "dead_probe", "destination": DEST},
            {"tool": "dead_probe", "destination": f"{DEST}two"},
            {"tool": "steady_probe", "destination": DEST}]
    results = lifecycle.run_plan(plan)
    assert [r["status"] for r in results[:2]] == ["tool_error", "tool_error"]
    assert results[2]["status"] == "skipped"
    assert "no progress" in results[2]["reason"]


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "A resumed run rebuilds through the same write boundary, and an "
    "interrupted action comes back unresolved.",
    "Reconciliation settles an unresolved action only on evidence; missing "
    "evidence never becomes success.",
)
def test_resume_reconciles_on_evidence_and_never_invents_success():
    recorder, lifecycle, clock = fresh()
    run_id = recorder.run.run_id
    admitted = recorder.record("action", {
        "run_id": run_id, "tool": "steady_probe", "destination": DEST,
        "arguments": {}})
    recorder.record("capture", {
        "run_id": run_id, "action_id": admitted["action_id"], "status": 200,
        "body": "captured before the crash"})
    ghost = recorder.record("action", {
        "run_id": run_id, "tool": "flaky_probe",
        "destination": f"{DEST}ghost", "arguments": {}})
    checkpoint = lifecycle.checkpoint()

    resumed = Lifecycle.resume(checkpoint, build_policy(), make_adapters(),
                               clock=clock)
    outcomes = resumed.recorder.snapshot()["outcomes"]
    assert outcomes[admitted["action_id"]]["status"] == "unresolved"
    assert outcomes[ghost["action_id"]]["status"] == "unresolved"

    report = {r["action_id"]: r for r in resumed.reconcile()}
    assert report[admitted["action_id"]]["settled"] == "clean"
    assert report[ghost["action_id"]]["settled"] == "unresolved"
    settled = resumed.recorder.snapshot()["outcomes"]
    assert settled[admitted["action_id"]]["status"] == "clean"
    assert settled[ghost["action_id"]]["status"] == "unresolved"


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "An unresolved action is not re-dispatched unless its tool is declared "
    "idempotent",
)
def test_only_a_declared_idempotent_tool_is_re_dispatched():
    recorder, lifecycle, clock = fresh()
    run_id = recorder.run.run_id
    ghost = recorder.record("action", {
        "run_id": run_id, "tool": "steady_probe",
        "destination": f"{DEST}ghost", "arguments": {}})
    checkpoint = lifecycle.checkpoint()

    cautious = Lifecycle.resume(checkpoint, build_policy(), make_adapters(),
                                clock=clock)
    report = {r["action_id"]: r for r in cautious.reconcile()}
    assert report[ghost["action_id"]]["settled"] == "unresolved"

    willing = Lifecycle.resume(checkpoint, build_policy(), make_adapters(),
                               clock=clock, idempotent_tools=("steady_probe",))
    report = {r["action_id"]: r for r in willing.reconcile()}
    assert "re-dispatched" in report[ghost["action_id"]]["settled"]
    assert report[ghost["action_id"]]["result"] == "clean"


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "Completion is refused while any planned action is unaccounted for",
    "a completed run is still not an accepted report",
)
def test_completion_is_gated_and_distinct_from_acceptance():
    recorder, lifecycle, _ = fresh()
    recorder.record("action", {
        "run_id": recorder.run.run_id, "tool": "steady_probe",
        "destination": DEST, "arguments": {}})
    refused = lifecycle.finish()
    assert refused["completed"] is False
    assert refused["pending"]

    recorder.record("outcome", {
        "run_id": recorder.run.run_id,
        "action_id": refused["pending"][0], "status": "skipped",
        "detail": "settled for the test"})
    finished = lifecycle.finish()
    assert finished["completed"] is True
    report = finished["report"]
    assert report["acceptance"] == "report acceptance is a separate human decision"
    assert report["coverage"]["planned"] == report["coverage"]["terminal"]


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "an aborted run gets the same accounting, under its abort reason",
)
def test_abort_produces_the_same_accounting_with_the_reason():
    recorder, lifecycle, _ = fresh()
    lifecycle.execute_with_retries("steady_probe", DEST)
    recorder.record("action", {
        "run_id": recorder.run.run_id, "tool": "flaky_probe",
        "destination": DEST, "arguments": {}})
    result = lifecycle.abort("operator pulled the plug")
    assert result["completed"] is True
    report = result["report"]
    assert report["aborted"] is True
    assert "operator pulled the plug" in report["stop_reason"]
    assert report["outcomes_by_status"]["skipped"] == 1
    assert report["omitted"][0]["reason"].startswith("run aborted")


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "the checkpoint carries the budgets already spent, so a resumed run cannot "
    "start its spending over",
)
def test_the_checkpoint_round_trips_budget_state():
    recorder, lifecycle, clock = fresh(actions=3)
    lifecycle.execute_with_retries("steady_probe", DEST)
    checkpoint = lifecycle.checkpoint()
    resumed = Lifecycle.resume(checkpoint, build_policy(), make_adapters(),
                               clock=clock)
    assert resumed.budgets.used["actions"] == 1
    assert resumed.budgets.limits["actions"] == 3
