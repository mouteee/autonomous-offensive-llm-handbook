"""The assembled application, held at its control boundaries.

These tests exist because an independent release review reproduced five
control-integration failures in the assembled path: budgets charged but not
enforced, a stop gate recorded but not obeyed, an unresolved side effect
repeated through ordinary dispatch, a finished run accepting new effects, and
a host fallback crediting a controller for an action it never chose. Each case
below asserts the corrected behavior by counting actual adapter and provider
invocations -- a refusal log line beside an executed callback is exactly the
failure shape this file refuses to accept as enforcement.
"""

import pytest

from core.controller.contract import Candidate, Controller, Outcome, State, \
    stable_best
from core.run.app import Application
from core.run.demo_app import (
    LAB, PROPOSAL_ADMITTED, PROPOSAL_REFUSED, WORLD, adapters, build_config,
    demo_verifier)
from core.run.demo_lifecycle import FakeClock
from core.run.dispatch import Dispatcher
from core.run.lifecycle import Budgets, Lifecycle
from core.run.policy import Policy, Tool
from core.run.proposals import FakeProvider, ProviderSession
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


def counting_adapters(counter):
    """The demo adapters, wrapped so every actual invocation is counted."""
    wrapped = {}
    for name, fn in adapters().items():
        def counted(url, _fn=fn, _name=name):
            counter[_name] = counter.get(_name, 0) + 1
            counter["total"] = counter.get("total", 0) + 1
            return _fn(url)
        wrapped[name] = counted
    return wrapped


def app_config(counter, **budget_overrides):
    config = build_config()
    config["adapters"] = counting_adapters(counter)
    config["budgets"].update(budget_overrides)
    return config


def outcomes_of(report):
    return report["finish"]["report"]["run_report"]["outcomes"]


# --- R1: budgets are enforced at the attempt, not logged beside it -------------

@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "An exhausted action, cost or wall budget executes zero further callbacks, "
    "and cancellation stops the run mid-plan.",
)
def test_the_action_budget_bounds_actual_adapter_invocations():
    counter = {}
    report = Application(app_config(counter, actions=1),
                         clock=FakeClock()).run(WORLD)
    assert counter.get("total", 0) == 1
    terminal = report["finish"]["report"]
    assert terminal["resource_use"]["used"]["actions"] == 1
    assert len(terminal["attempts"]) == 1
    skipped = [o for o in outcomes_of(report).values()
               if o["status"] == "skipped"]
    assert skipped and all("policy.max_actions" in o["detail"] for o in skipped)
    assert "actions" in terminal["stop_reason"]
    assert report["finish"]["completed"] is True


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "An exhausted action, cost or wall budget executes zero further callbacks, "
    "and cancellation stops the run mid-plan.",
)
def test_the_cost_ceiling_refuses_an_unaffordable_action_before_dispatch():
    counter = {}
    report = Application(app_config(counter, cost=1),
                         clock=FakeClock()).run(WORLD)
    # The controller's top pick declares cost two against an allowance of
    # one: it is refused before its adapter runs. The affordable cost-one
    # tool still executes -- once, exactly spending the ceiling -- and the
    # rest are recorded skips.
    assert counter.get("form_probe", 0) == 0, \
        "a declared cost-two action ran under a cost-one ceiling"
    assert counter.get("total", 0) == 1
    used = report["finish"]["report"]["resource_use"]["used"]["cost"]
    assert used == 1.0, "the ceiling was overspent"
    skips = [o["detail"] for o in outcomes_of(report).values()
             if o["status"] == "skipped"]
    assert any("declared cost" in d and "operator.cost_ceiling" in d
               for d in skips)
    assert any("budget exhausted: cost" in d for d in skips)
    assert report["finish"]["completed"] is True


def cost_fixture(*, cost, allowance, adapter=None, retry_limit=0, calls=None):
    calls = calls if calls is not None else []
    policy = Policy(reference="cost-preflight",
                    origins=["https://lab.example/"],
                    tools=[Tool(tool_id="probe", activity="passive",
                                cost=cost)],
                    max_actions=10, max_model_calls=1)
    run = make_run(policy.snapshot(), {"world": "cost-preflight"})
    recorder = Recorder(run, policy)

    def default(url):
        calls.append(url)
        return {"status": 200, "body": "counted"}

    lifecycle = Lifecycle(recorder, {"probe": adapter or default},
                          Budgets(actions=10, model_calls=1, wall_seconds=60,
                                  cost=allowance),
                          clock=FakeClock(), retry_limit=retry_limit)
    return recorder, lifecycle, calls


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "An action whose declared cost exceeds the remaining allowance is refused "
    "before its adapter runs, and affordable work may still continue.",
)
def test_a_declared_cost_two_action_under_allowance_one_never_runs():
    recorder, lifecycle, calls = cost_fixture(cost=2, allowance=1)
    result = lifecycle.execute_with_retries("probe", "https://lab.example/a")
    assert calls == [], "an unaffordable action invoked its adapter"
    assert result["status"] == "skipped"
    assert "declared cost" in result["reason"]
    assert lifecycle.budgets.used["cost"] == 0.0, \
        "a refused attempt still charged the budget"
    assert lifecycle.stop_reason is None, \
        "an affordability refusal stopped the whole run"


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "An action whose declared cost exceeds the remaining allowance is refused "
    "before its adapter runs, and affordable work may still continue.",
)
def test_a_declared_cost_that_exactly_fits_runs_once():
    recorder, lifecycle, calls = cost_fixture(cost=2, allowance=2)
    result = lifecycle.execute_with_retries("probe", "https://lab.example/a")
    assert result["status"] == "clean"
    assert len(calls) == 1
    assert lifecycle.budgets.used["cost"] == 2.0
    again = lifecycle.execute_with_retries("probe", "https://lab.example/b")
    assert again["status"] == "skipped" and len(calls) == 1


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "An action whose declared cost exceeds the remaining allowance is refused "
    "before its adapter runs, and affordable work may still continue.",
)
def test_a_retry_whose_cost_no_longer_fits_is_not_invoked():
    calls = []

    def failing(url):
        calls.append(url)
        raise RuntimeError("always")

    recorder, lifecycle, calls = cost_fixture(cost=2, allowance=3,
                                              adapter=failing,
                                              retry_limit=3, calls=calls)
    result = lifecycle.execute_with_retries("probe", "https://lab.example/a")
    # Attempt one charged two of the three; the retry's declared cost of two
    # no longer fits the remaining one, so no second invocation happened.
    assert len(calls) == 1, "a retry outspent the remaining cost allowance"
    assert result["status"] == "tool_error"
    assert lifecycle.budgets.used["cost"] == 2.0
    outcome = recorder.snapshot()["outcomes"][result["action_id"]]
    assert "retries stopped" in outcome["detail"]
    assert "declared cost" in outcome["detail"]


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "An action whose declared cost exceeds the remaining allowance is refused "
    "before its adapter runs, and affordable work may still continue.",
)
def test_an_expensive_action_cannot_bypass_a_small_positive_allowance():
    recorder, lifecycle, calls = cost_fixture(cost=100, allowance=0.5)
    result = lifecycle.execute_with_retries("probe", "https://lab.example/a")
    assert calls == [] and result["status"] == "skipped"
    assert lifecycle.budgets.used["cost"] == 0.0


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "An action whose declared cost exceeds the remaining allowance is refused "
    "before its adapter runs, and affordable work may still continue.",
)
def test_an_unaffordable_reconciliation_repeat_stays_unresolved():
    calls = []
    policy = Policy(reference="cost-reconcile",
                    origins=["https://lab.example/"],
                    tools=[Tool(tool_id="writer", activity="active", cost=2)],
                    max_actions=10, max_model_calls=1)
    run = make_run(policy.snapshot(), {"world": "cost-reconcile"})
    recorder = Recorder(run, policy)
    lifecycle = Lifecycle(recorder,
                          {"writer": lambda url: (calls.append(url)
                                                  or {"status": 200,
                                                      "body": "WROTE"})},
                          Budgets(actions=10, model_calls=1, wall_seconds=60,
                                  cost=1),
                          clock=FakeClock(), idempotent_tools=("writer",))
    admitted = recorder.record("action", {
        "run_id": run.run_id, "tool": "writer",
        "destination": "https://lab.example/write"})
    recorder.record("outcome", {
        "run_id": run.run_id, "action_id": admitted["action_id"],
        "status": "unresolved", "detail": "interrupted after dispatch"})
    report = {r["action_id"]: r for r in lifecycle.reconcile()}
    assert report[admitted["action_id"]]["settled"] == "unresolved"
    assert calls == [], "an unaffordable reconciliation repeat still ran"
    assert recorder.outcome(admitted["action_id"])["status"] == "unresolved"


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "An exhausted action, cost or wall budget executes zero further callbacks, "
    "and cancellation stops the run mid-plan.",
)
def test_an_exhausted_wall_budget_executes_zero_callbacks():
    # The probe configuration from the release review, asserted the other way
    # around: with no wall allowance at all, not one adapter runs, and the
    # report says the run stopped instead of narrating a completed plan.
    counter = {}
    report = Application(app_config(counter, actions=1, cost=1,
                                    wall_seconds=0)).run(WORLD)
    assert counter.get("total", 0) == 0
    terminal = report["finish"]["report"]
    assert terminal["attempts"] == []
    assert all(o["status"] == "skipped" for o in outcomes_of(report).values())
    assert "wall_seconds" in terminal["stop_reason"]


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "An exhausted action, cost or wall budget executes zero further callbacks, "
    "and cancellation stops the run mid-plan.",
)
def test_a_wall_budget_spent_mid_run_stops_the_remainder():
    counter = {}
    clock = FakeClock()
    config = app_config(counter, wall_seconds=15)
    slow = {}
    for name, fn in config["adapters"].items():
        def slowed(url, _fn=fn):
            clock.now += 10.0
            return _fn(url)
        slow[name] = slowed
    config["adapters"] = slow
    report = Application(config, clock=clock).run(WORLD)
    # Admission at 0 and 10 seconds passes, at 20 it does not: two callbacks.
    assert counter.get("total", 0) == 2
    assert "wall_seconds" in report["finish"]["report"]["stop_reason"]


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "An exhausted action, cost or wall budget executes zero further callbacks, "
    "and cancellation stops the run mid-plan.",
)
def test_cancellation_stops_the_assembled_run_mid_plan():
    counter = {}
    config = app_config(counter)
    holder = {}
    cancelling = {}
    for name, fn in config["adapters"].items():
        def cancelled(url, _fn=fn):
            result = _fn(url)
            holder["app"].lifecycle.cancel("operator stop during callback")
            return result
        cancelling[name] = cancelled
    config["adapters"] = cancelling
    app = Application(config, clock=FakeClock())
    holder["app"] = app
    report = app.run(WORLD)
    assert counter.get("total", 0) == 1
    assert report["finish"]["report"]["stop_reason"] == \
        "operator stop during callback"
    assert any("operator stop" in o["detail"]
               for o in outcomes_of(report).values()
               if o["status"] == "skipped")


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "A retry allowance never outspends the remaining action budget.",
)
def test_a_retry_allowance_larger_than_the_action_budget_is_bounded():
    calls = {"n": 0}

    def dying(url):
        calls["n"] += 1
        raise RuntimeError("always")

    policy = Policy(reference="retry-bound", origins=["https://lab.example/"],
                    tools=[Tool(tool_id="probe", activity="passive")],
                    max_actions=2, max_model_calls=1)
    run = make_run(policy.snapshot(), {"world": "retry-bound"})
    lifecycle = Lifecycle(Recorder(run, policy), {"probe": dying},
                          Budgets(actions=2, model_calls=1, wall_seconds=60,
                                  cost=50),
                          clock=FakeClock(), retry_limit=5,
                          no_progress_limit=99)
    result = lifecycle.execute_with_retries("probe", "https://lab.example/a")
    assert calls["n"] == 2, "the retry loop outspent the action budget"
    assert result["status"] == "tool_error"
    assert result["attempts"] == 2
    outcome = lifecycle.recorder.snapshot()["outcomes"][result["action_id"]]
    assert "retries stopped" in outcome["detail"]
    assert "actions" in outcome["detail"]


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "Proposal rounds, repair attempts and verifier calls spend one shared "
    "model-call budget, admitted before each call.",
)
def test_proposal_rounds_share_one_model_call_budget():
    provider = FakeProvider([PROPOSAL_ADMITTED, PROPOSAL_ADMITTED])
    config = build_config(provider=provider)
    config["budgets"]["model_calls"] = 1
    report = Application(config, clock=FakeClock()).run(WORLD)
    assert len(provider.contexts) == 1, \
        "a second proposal round called the provider past the budget"
    used = report["finish"]["report"]["resource_use"]["used"]["model_calls"]
    assert used == 1
    events = report["finish"]["report"]["run_report"]["events"]
    assert any(e["event"] == "refused" and e["kind"] == "proposal"
               and "model_calls" in e["reason"] for e in events)
    # A spent model budget stops model calls and nothing else: the planned
    # actions still executed under their own budgets.
    assert report["finish"]["report"]["attempts"]
    assert report["finish"]["completed"] is True


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "Proposal rounds, repair attempts and verifier calls spend one shared "
    "model-call budget, admitted before each call.",
)
def test_repair_attempts_spend_the_same_model_call_budget():
    provider = FakeProvider(["not json at all", PROPOSAL_ADMITTED])
    config = build_config(provider=provider)
    config["budgets"]["model_calls"] = 2
    report = Application(config, clock=FakeClock()).run(WORLD)
    # Round one spent both calls (one malformed, one repaired and admitted);
    # round two was refused without a call. A permitted repair works, and it
    # spends the shared meter.
    assert len(provider.contexts) == 2
    assert report["proposals"][0]["admitted"] is True
    assert report["finish"]["report"]["resource_use"]["used"]["model_calls"] == 2
    assert len(report["proposals"]) == 1


def session_lifecycle(clock, **budget_overrides):
    policy = Policy(reference="session-admission",
                    origins=["https://lab.example/"],
                    tools=[Tool(tool_id="probe", activity="passive")],
                    max_actions=10, max_model_calls=8)
    run = make_run(policy.snapshot(), {"world": "session-admission"})
    recorder = Recorder(run, policy)
    limits = {"actions": 10, "model_calls": 8, "wall_seconds": 60, "cost": 50}
    limits.update(budget_overrides)
    lifecycle = Lifecycle(recorder, {}, Budgets(**limits), clock=clock)
    return policy, recorder, lifecycle


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "A repair that would start after the wall deadline, after closure or "
    "after cancellation is a recorded refusal, not a call.",
)
def test_a_repair_never_starts_after_the_wall_deadline():
    # The coordinator reproduction, inverted: the first call starts at time
    # zero, crosses a one-second wall budget while running, and returns
    # malformed output. The repair must not start.
    clock = FakeClock()
    starts = []

    def delayed_malformed(context):
        starts.append(clock.now)
        if len(starts) == 1:
            clock.now += 2
            return "malformed JSON"
        return PROPOSAL_ADMITTED

    config = build_config(provider=delayed_malformed)
    config["budgets"]["wall_seconds"] = 1
    report = Application(config, clock=clock).run(WORLD)
    assert starts == [0.0], "a repair call started after the wall deadline"
    assert report["finish"]["report"]["resource_use"]["used"]["model_calls"] == 1
    assert report["proposals"][0]["status"] == "admission_refused"
    assert "wall_seconds" in report["proposals"][0]["reason"]
    assert "wall_seconds" in report["finish"]["report"]["stop_reason"]


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "A repair that would start after the wall deadline, after closure or "
    "after cancellation is a recorded refusal, not a call.",
)
def test_a_repair_never_starts_after_closure():
    # The technical reviewer's reproduction, inverted: the run closes during
    # the first call, which returns malformed output. The already-active
    # session must not call the provider again.
    counter = {}
    holder = {}
    closed_at_start = []

    def closes_during_first_reply(context):
        closed_at_start.append(holder["app"].lifecycle.closed)
        if len(closed_at_start) == 1:
            holder["app"].lifecycle.abort("operator closed during callback")
            return "malformed"
        return PROPOSAL_ADMITTED

    config = app_config(counter)
    config["provider"] = closes_during_first_reply
    app = Application(config, clock=FakeClock())
    holder["app"] = app
    report = app.run(WORLD)
    assert closed_at_start == [None], \
        "a provider call started after terminal closure"
    assert report["finish"]["report"]["resource_use"]["used"]["model_calls"] == 1
    assert report["proposals"][0]["status"] == "admission_refused"
    assert "closed" in report["proposals"][0]["reason"]
    assert counter.get("total", 0) == 0, \
        "an adapter ran after the mid-proposal closure"
    assert report["finish"]["report"]["aborted"] is True


@chapter_claim(
    "handbook/course/04-model-proposals.md",
    "The host's admission check is consulted before every call, repairs "
    "included: a call already running may finish past the run's stops, and "
    "no further call starts after them.",
)
def test_cancellation_after_a_malformed_reply_stops_repair():
    clock = FakeClock()
    policy, recorder, lifecycle = session_lifecycle(clock)
    starts = []

    def cancels_then_malformed(context):
        starts.append(len(starts))
        lifecycle.cancel("operator stop mid-session")
        return "malformed"

    session = ProviderSession(cancels_then_malformed,
                              admission=lifecycle.run_halted)
    report = session.propose(
        {"instruction": "x"}, observations={}, policy=policy)
    assert len(starts) == 1, "a repair call started after cancellation"
    assert report["admitted"] is False
    assert report["status"] == "admission_refused"
    assert report["reason"] == "operator stop mid-session"
    assert report["usage"]["calls"] == 1


@chapter_claim(
    "handbook/course/04-model-proposals.md",
    "The model-call budget bounds a session across attempts.",
)
def test_a_spent_model_allowance_cannot_be_bypassed_through_repair():
    provider = FakeProvider(["malformed", PROPOSAL_ADMITTED])
    session = ProviderSession(provider, max_model_calls=1)
    report = session.propose(
        {"instruction": "x"}, observations={},
        policy=Policy(reference="budget-bypass",
                      origins=["https://lab.example/"],
                      tools=[Tool(tool_id="probe", activity="passive")],
                      max_actions=10, max_model_calls=1))
    assert len(provider.contexts) == 1, \
        "a repair call started past the model-call allowance"
    assert report["admitted"] is False
    assert report["status"] == "model_call_budget_exhausted"
    assert report["usage"]["calls"] == 1


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "Proposal rounds, repair attempts and verifier calls spend one shared "
    "model-call budget, admitted before each call.",
)
def test_verifier_calls_spend_the_same_model_call_budget():
    verifier_calls = {"n": 0}

    def counting_verifier(packet):
        verifier_calls["n"] += 1
        return demo_verifier(packet)

    provider = FakeProvider([PROPOSAL_REFUSED, PROPOSAL_ADMITTED])
    config = build_config(provider=provider, verifier=counting_verifier)
    config["budgets"]["model_calls"] = 3
    report = Application(config, clock=FakeClock()).run(WORLD)
    # Two proposal rounds spent two calls; the demo world yields four findings
    # (the login body is captured by both tools), so exactly one verifier call
    # fit the remaining budget and three were refused with the reason recorded.
    assert len(provider.contexts) == 2
    assert verifier_calls["n"] == 1
    assert report["finish"]["report"]["resource_use"]["used"]["model_calls"] == 3
    events = report["finish"]["report"]["run_report"]["events"]
    refused = [e for e in events if e["event"] == "refused"
               and e["kind"] == "verdict" and "model_calls" in e["reason"]]
    assert len(refused) == 3, "the over-budget verifier calls left no record"


# --- R2: gate and stage refusals stop execution ---------------------------------

@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "A stop gate executes zero testing callbacks: the run halts, every "
    "planned row becomes a recorded skip, and the terminal report says it "
    "stopped and why.",
)
def test_a_stop_gate_executes_zero_callbacks():
    counter = {}
    config = app_config(counter)
    provider = FakeProvider([PROPOSAL_ADMITTED, PROPOSAL_ADMITTED])
    config["provider"] = provider
    world = {"name": WORLD["name"],
             "surfaces": [{**s, "response": {**s["response"], "status": 503}}
                          for s in WORLD["surfaces"]]}
    report = Application(config, clock=FakeClock()).run(world)
    assert counter.get("total", 0) == 0, "a stop gate still executed callbacks"
    assert len(provider.contexts) == 0, "a stop gate still called the provider"
    assert report["halted"] is not None
    assert "stop" in report["halted"]["reason"]
    terminal = report["finish"]["report"]
    assert terminal["aborted"] is True
    assert terminal["attempts"] == []
    assert report["decisions"] == []
    assert all(o["status"] == "skipped" for o in outcomes_of(report).values())
    gate = terminal["run_report"]["gate"]
    assert gate["status"] == "indeterminate" and gate["mode"] == "stop"


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "A missing gate halts execution exactly like a stop gate.",
)
def test_a_missing_gate_executes_zero_callbacks():
    counter = {}
    app = Application(app_config(counter), clock=FakeClock())
    app._start(WORLD)
    run_id = app.recorder.run.run_id
    # The observations land, the stages advance, and the one thing missing is
    # the gate decision itself -- the state the review's missing-gate case
    # names.
    from core.run.stages import observations_from_response
    for surface in WORLD["surfaces"]:
        for row in observations_from_response(surface["surface_id"],
                                              surface["response"]):
            app.recorder.record("observation", {"run_id": run_id, **row})
    app.machine.advance("detection")
    app.machine.advance("crawling")
    _, ranked = app._plan(WORLD)
    app._execute(ranked, [])
    assert counter.get("total", 0) == 0, "a gateless run executed callbacks"
    assert app.halted is not None
    assert "no recorded gate" in app.halted["reason"]
    # The door holds independently of the halt: a direct dispatch attempt in
    # this gateless staged run is refused too.
    direct = app.lifecycle.execute_with_retries(
        "inspect_headers", f"{LAB}/health")
    assert direct["status"] == "skipped"
    assert counter.get("total", 0) == 0


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "A passive gate excludes active callbacks and runs the passive remainder.",
)
def test_a_passive_gate_excludes_active_callbacks():
    counter = {}
    config = app_config(counter)
    world = {"name": WORLD["name"], "surfaces": [dict(s) for s in WORLD["surfaces"]]}
    world["surfaces"][2] = {**world["surfaces"][2],
                            "response": {"status": 503, "body": "down"}}
    report = Application(config, clock=FakeClock()).run(world)
    gate = report["finish"]["report"]["run_report"]["gate"]
    assert gate["status"] == "limited" and gate["mode"] == "passive"
    assert counter.get("form_probe", 0) == 0, \
        "a passive gate still executed the active tool"
    assert counter.get("inspect_headers", 0) > 0
    assert report["halted"] is None
    passive_skips = [o for o in outcomes_of(report).values()
                     if o["status"] == "skipped"
                     and "passive" in o["detail"]]
    assert passive_skips
    assert report["finish"]["completed"] is True


@chapter_claim(
    "handbook/course/05-candidates-and-dispatch.md",
    "Dispatch re-asks the recorded gate and stage: a stop gate admits "
    "nothing, a passive gate admits no active tool, and a staged run "
    "dispatches only in its executable stages.",
)
def test_the_dispatch_door_enforces_a_recorded_gate_directly():
    calls = {"n": 0}

    def counting(url):
        calls["n"] += 1
        return {"status": 200, "body": "counted"}

    policy = Policy(reference="door-gate", origins=["https://lab.example/"],
                    tools=[Tool(tool_id="reader", activity="passive"),
                           Tool(tool_id="writer", activity="active")],
                    max_actions=10, max_model_calls=1)
    run = make_run(policy.snapshot(), {"world": "door-gate"})
    recorder = Recorder(run, policy)
    dispatcher = Dispatcher(recorder, policy,
                            {"reader": counting, "writer": counting})
    recorder.record("gate", {"run_id": run.run_id, "status": "indeterminate",
                             "mode": "stop", "inputs": {}})
    stopped = dispatcher.dispatch("reader", "https://lab.example/a")
    assert stopped["status"] == "skipped"
    assert "stop" in stopped["reason"]
    assert calls["n"] == 0

    # A fresh run under a passive gate: the active tool is refused at the
    # door, the passive one runs.
    run2 = make_run(policy.snapshot(), {"world": "door-gate-passive"})
    recorder2 = Recorder(run2, policy)
    dispatcher2 = Dispatcher(recorder2, policy,
                             {"reader": counting, "writer": counting})
    recorder2.record("gate", {"run_id": run2.run_id, "status": "limited",
                              "mode": "passive", "inputs": {}})
    active = dispatcher2.dispatch("writer", "https://lab.example/w")
    assert active["status"] == "skipped"
    assert "passive" in active["reason"]
    assert calls["n"] == 0
    passive = dispatcher2.dispatch("reader", "https://lab.example/r")
    assert passive["status"] == "clean"
    assert calls["n"] == 1

    # The same rules hold at the lifecycle's door.
    run3 = make_run(policy.snapshot(), {"world": "door-gate-lifecycle"})
    recorder3 = Recorder(run3, policy)
    lifecycle = Lifecycle(recorder3, {"reader": counting, "writer": counting},
                          Budgets(actions=10, model_calls=1, wall_seconds=60,
                                  cost=50), clock=FakeClock())
    recorder3.record("gate", {"run_id": run3.run_id, "status": "indeterminate",
                              "mode": "stop", "inputs": {}})
    stopped3 = lifecycle.execute_with_retries("reader", "https://lab.example/a")
    assert stopped3["status"] == "skipped" and calls["n"] == 1


# --- R3: unresolved actions are refused at ordinary dispatch --------------------

def unresolved_writer_fixture(calls, **lifecycle_kwargs):
    policy = Policy(reference="unresolved", origins=["https://lab.example/"],
                    tools=[Tool(tool_id="writer", activity="active"),
                           Tool(tool_id="reader", activity="passive")],
                    max_actions=20, max_model_calls=4)
    run = make_run(policy.snapshot(), {"world": "unresolved"})
    recorder = Recorder(run, policy)

    def writer(url):
        calls.append(url)
        return {"status": 200, "body": "WROTE"}

    lifecycle = Lifecycle(recorder, {"writer": writer},
                          Budgets(actions=10, model_calls=4, wall_seconds=600,
                                  cost=50),
                          clock=FakeClock(), **lifecycle_kwargs)
    admitted = recorder.record("action", {
        "run_id": run.run_id, "tool": "writer",
        "destination": "https://lab.example/write"})
    recorder.record("outcome", {
        "run_id": run.run_id, "action_id": admitted["action_id"],
        "status": "unresolved", "detail": "interrupted after dispatch"})
    return policy, run, recorder, lifecycle, admitted["action_id"]


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "Ordinary dispatch refuses an unresolved identity; reconciliation is the "
    "only path that may repeat it, and only for a tool declared idempotent.",
)
def test_an_unresolved_action_is_refused_at_ordinary_dispatch():
    calls = []
    policy, run, recorder, lifecycle, action_id = unresolved_writer_fixture(calls)
    result = lifecycle.execute_with_retries("writer",
                                            "https://lab.example/write")
    assert result["status"] == "refused"
    assert "unresolved" in result["reason"]
    assert calls == [], "ordinary dispatch repeated an unresolved side effect"
    assert recorder.outcome(action_id)["status"] == "unresolved"

    dispatcher = Dispatcher(recorder, policy,
                            {"writer": lambda url: calls.append(url)
                             or {"status": 200, "body": "WROTE"}})
    again = dispatcher.dispatch("writer", "https://lab.example/write")
    assert again["status"] == "refused"
    assert "unresolved" in again["reason"]
    assert calls == [], "the dispatcher repeated an unresolved side effect"


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "Ordinary dispatch refuses an unresolved identity; reconciliation is the "
    "only path that may repeat it, and only for a tool declared idempotent.",
)
def test_reconciliation_repeats_only_a_declared_idempotent_tool():
    withheld = []
    _, _, _, cautious, action_id = unresolved_writer_fixture(withheld)
    report = {r["action_id"]: r for r in cautious.reconcile()}
    assert report[action_id]["settled"] == "unresolved"
    assert withheld == []

    allowed = []
    _, _, recorder, willing, action_id = unresolved_writer_fixture(
        allowed, idempotent_tools=("writer",))
    report = {r["action_id"]: r for r in willing.reconcile()}
    assert "re-dispatched" in report[action_id]["settled"]
    assert report[action_id]["result"] == "clean"
    assert len(allowed) == 1
    assert recorder.outcome(action_id)["status"] == "clean"


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "Ordinary dispatch refuses an unresolved identity; reconciliation is the "
    "only path that may repeat it, and only for a tool declared idempotent.",
)
def test_resume_keeps_the_unresolved_refusal_at_ordinary_dispatch():
    calls = []
    policy, run, recorder, lifecycle, action_id = unresolved_writer_fixture(calls)
    checkpoint = lifecycle.checkpoint()

    def writer(url):
        calls.append(url)
        return {"status": 200, "body": "WROTE"}

    resumed = Lifecycle.resume(checkpoint, policy, {"writer": writer},
                               clock=FakeClock())
    direct = resumed.execute_with_retries("writer",
                                          "https://lab.example/write")
    assert direct["status"] == "refused"
    assert "unresolved" in direct["reason"]
    assert calls == []

    willing = Lifecycle.resume(checkpoint, policy, {"writer": writer},
                               clock=FakeClock(),
                               idempotent_tools=("writer",))
    report = {r["action_id"]: r for r in willing.reconcile()}
    assert "re-dispatched" in report[action_id]["settled"]
    assert len(calls) == 1


# --- R4: finish and abort close the run -----------------------------------------

@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "A completed finish closes the run: a closed run refuses every later "
    "effect, and closure survives checkpoint and resume.",
)
def test_finish_closes_the_run_against_later_effects():
    calls = []
    policy, run, recorder, lifecycle, _ = unresolved_writer_fixture(calls)
    finished = lifecycle.finish()
    assert finished["completed"] is True
    assert lifecycle.closed == "finished"

    late = lifecycle.execute_with_retries("writer",
                                          "https://lab.example/after-finish")
    assert late["status"] == "refused"
    assert "closed" in late["reason"]
    assert calls == [], "a closed run executed a new callback"

    ghost_action = recorder.record("action", {
        "run_id": run.run_id, "tool": "writer",
        "destination": "https://lab.example/ghost"})
    assert ghost_action["recorded"] is False
    ghost_outcome = recorder.record("outcome", {
        "run_id": run.run_id, "action_id": "writer -> anything",
        "status": "clean", "detail": "late"})
    assert ghost_outcome["recorded"] is False

    again = lifecycle.finish()
    assert again["completed"] is True
    assert again["report"]["aborted"] is False


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "A completed finish closes the run: a closed run refuses every later "
    "effect, and closure survives checkpoint and resume.",
)
def test_closure_survives_checkpoint_and_resume():
    calls = []
    policy, run, recorder, lifecycle, _ = unresolved_writer_fixture(calls)
    assert lifecycle.finish()["completed"] is True
    checkpoint = lifecycle.checkpoint()

    def writer(url):
        calls.append(url)
        return {"status": 200, "body": "WROTE"}

    resumed = Lifecycle.resume(checkpoint, policy, {"writer": writer},
                               clock=FakeClock(),
                               idempotent_tools=("writer",))
    assert resumed.closed == "finished"
    late = resumed.execute_with_retries("writer", "https://lab.example/late")
    assert late["status"] == "refused" and "closed" in late["reason"]
    assert resumed.reconcile() == [], "a closed run reconciled new work"
    assert calls == []


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "Abort closes the run the same way, and a closed run refuses a second "
    "closure.",
)
def test_abort_closes_the_run_and_refuses_a_second_closure():
    calls = []
    policy, run, recorder, lifecycle, _ = unresolved_writer_fixture(calls)
    aborted = lifecycle.abort("operator pulled the plug")
    assert aborted["completed"] is True
    assert lifecycle.closed == "aborted"

    late = lifecycle.execute_with_retries("writer",
                                          "https://lab.example/after-abort")
    assert late["status"] == "refused" and calls == []

    second = lifecycle.abort("again")
    assert second["completed"] is False
    assert "already closed" in second["reason"]
    replay = lifecycle.finish()
    assert replay["completed"] is True
    assert replay["report"]["aborted"] is True, \
        "finish after abort rewrote the closure"


# --- The recheck round: stops hold mid-attempt, across resume, in reconcile -----

@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "a run that stops mid-attempt stops its own retry",
)
def test_a_gate_recorded_mid_attempt_stops_the_retry():
    calls = {"n": 0}
    policy = Policy(reference="mid-attempt-gate",
                    origins=["https://lab.example/"],
                    tools=[Tool(tool_id="probe", activity="passive")],
                    max_actions=10, max_model_calls=1)
    run = make_run(policy.snapshot(), {"world": "mid-attempt-gate"})
    recorder = Recorder(run, policy)

    def flip_and_fail(url):
        calls["n"] += 1
        recorder.record("gate", {"run_id": run.run_id,
                                 "status": "indeterminate", "mode": "stop",
                                 "inputs": {}})
        raise RuntimeError("boom")

    lifecycle = Lifecycle(recorder, {"probe": flip_and_fail},
                          Budgets(actions=10, model_calls=1, wall_seconds=60,
                                  cost=50),
                          clock=FakeClock(), retry_limit=3)
    result = lifecycle.execute_with_retries("probe", "https://lab.example/a")
    assert calls["n"] == 1, "a retry executed under a recorded stop gate"
    assert result["status"] == "tool_error"
    outcome = recorder.snapshot()["outcomes"][result["action_id"]]
    assert "retries stopped" in outcome["detail"]
    assert "stop" in outcome["detail"]


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "a run that stops mid-attempt stops its own retry",
)
def test_closure_mid_attempt_stops_the_retry():
    calls = {"n": 0}
    holder = {}

    def abort_and_fail(url):
        calls["n"] += 1
        holder["lifecycle"].abort("adapter pulled the plug")
        raise RuntimeError("boom")

    policy = Policy(reference="mid-attempt-close",
                    origins=["https://lab.example/"],
                    tools=[Tool(tool_id="probe", activity="passive")],
                    max_actions=10, max_model_calls=1)
    run = make_run(policy.snapshot(), {"world": "mid-attempt-close"})
    recorder = Recorder(run, policy)
    lifecycle = Lifecycle(recorder, {"probe": abort_and_fail},
                          Budgets(actions=10, model_calls=1, wall_seconds=60,
                                  cost=50),
                          clock=FakeClock(), retry_limit=3)
    holder["lifecycle"] = lifecycle
    result = lifecycle.execute_with_retries("probe", "https://lab.example/a")
    assert calls["n"] == 1, "a retry executed after the run closed"
    assert lifecycle.closed == "aborted"
    # The abort settled the in-flight action as skipped before closure, and
    # the closed write boundary refused any later rewrite of it.
    outcome = recorder.snapshot()["outcomes"][result["action_id"]]
    assert outcome["status"] == "skipped"


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "A completed finish closes the run: a closed run refuses every later "
    "effect, and closure survives checkpoint and resume.",
)
def test_a_closed_run_halts_model_spending_too():
    calls = []
    policy, run, recorder, lifecycle, _ = unresolved_writer_fixture(calls)
    assert lifecycle.run_halted() is None
    assert lifecycle.finish()["completed"] is True
    halted = lifecycle.run_halted()
    assert halted is not None and "closed" in halted


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "The executable stage survives checkpoint and resume.",
)
def test_the_executable_stage_survives_checkpoint_and_resume():
    from core.run.stages import StageMachine, measured

    calls = {"n": 0}

    def counting(url):
        calls["n"] += 1
        return {"status": 200, "body": "counted"}

    policy = Policy(reference="stage-survival",
                    origins=["https://lab.example/"],
                    tools=[Tool(tool_id="probe", activity="passive")],
                    max_actions=10, max_model_calls=1)
    run = make_run(policy.snapshot(), {"world": "stage-survival"})
    recorder = Recorder(run, policy)
    machine = StageMachine(recorder)
    recorder.record("observation", {
        "run_id": run.run_id,
        **measured("landing_status", 200, "fixture:landing")})
    machine.advance("detection")
    machine.advance("crawling")
    recorder.record("gate", {"run_id": run.run_id, "status": "proceed",
                             "mode": "full", "inputs": {}})
    machine.advance("mining")
    lifecycle = Lifecycle(recorder, {"probe": counting},
                          Budgets(actions=10, model_calls=1, wall_seconds=60,
                                  cost=50), clock=FakeClock())
    before = lifecycle.execute_with_retries("probe", "https://lab.example/a")
    assert before["status"] == "skipped" and "mining" in before["reason"]

    resumed = Lifecycle.resume(lifecycle.checkpoint(), policy,
                               {"probe": counting}, clock=FakeClock())
    assert resumed.recorder.stage == "mining"
    after = resumed.execute_with_retries("probe", "https://lab.example/b")
    assert after["status"] == "skipped" and "mining" in after["reason"]
    assert calls["n"] == 0, "resume forgot the stage and the door opened"

    # The positive control: a run checkpointed inside its executable stages
    # resumes dispatchable.
    machine.advance("scanning")
    machine.advance("active_testing")
    working = Lifecycle.resume(lifecycle.checkpoint(), policy,
                               {"probe": counting}, clock=FakeClock())
    assert working.recorder.stage == "active_testing"
    ran = working.execute_with_retries("probe", "https://lab.example/c")
    assert ran["status"] == "clean" and calls["n"] == 1


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "A repeat that the gate or budgets refuse leaves the action unresolved "
    "rather than relabeling it.",
)
def test_a_refused_reconciliation_redispatch_keeps_the_action_unresolved():
    calls = []
    policy, run, recorder, lifecycle, action_id = unresolved_writer_fixture(
        calls, idempotent_tools=("writer",))
    recorder.record("gate", {"run_id": run.run_id, "status": "indeterminate",
                             "mode": "stop", "inputs": {}})
    report = {r["action_id"]: r for r in lifecycle.reconcile()}
    assert report[action_id]["settled"] == "unresolved"
    assert "not admitted" in report[action_id]["reason"] or \
        "stop" in report[action_id]["reason"]
    assert calls == [], "a stop-gated reconciliation still re-dispatched"
    assert recorder.outcome(action_id)["status"] == "unresolved", \
        "the refusal relabeled the unresolved outcome"
    events = recorder.snapshot()["events"]
    assert any(e["event"] == "refused" and e["kind"] == "reconcile"
               and "stays unresolved" in e["reason"] for e in events)


# --- Controller fallback: credit goes to what ran -------------------------------

class UnofferedController(Controller):
    """Selects the host's best candidate, then lies about its identity."""

    name = "priority"

    def _choose(self, state, candidates):
        chosen = stable_best(candidates, score_of=lambda c: c.priority,
                             tiebreak_of=lambda c: c.candidate_id)
        forged = Candidate(candidate_id="ghost -> https://lab.example:443/x",
                           family=chosen.family, features=chosen.features,
                           priority=chosen.priority)
        return forged, {"rule": "forged"}


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "Invalid controller advice earns no credit: the host fallback executes "
    "under the host's own ranking, and the ledger entry names the action "
    "that actually ran.",
)
def test_a_host_fallback_credits_the_action_that_actually_ran():
    app = Application(build_config(), clock=FakeClock())
    app.controller = UnofferedController()
    report = app.run(WORLD)
    assert report["finish"]["completed"] is True
    assert report["decisions"], "the fallback path executed nothing"
    for entry in report["decisions"]:
        assert entry["candidate_id"] != "ghost -> https://lab.example:443/x", \
            "the ledger credited the controller's unoffered choice"
        assert entry["candidate_id"] in report["plan"]
        assert entry["fallback"]["controller_candidate_id"] == \
            "ghost -> https://lab.example:443/x"
        assert entry["feedback"]["learning"]["applied"] is False
        assert "no credit" in entry["feedback"]["learning"]["reason"]
    assert app.controller._pending == {}, \
        "the controller kept a pending record for a decision that was settled"
