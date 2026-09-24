"""Candidates and dispatch, held at the budget, the bound and the door."""

from core.controller import make_controller
from core.controller.contract import Candidate, State
from core.run.candidates import build_candidates, rank
from core.run.demo_dispatch import ADAPTERS, SURFACES, build_policy
from core.run.dispatch import Dispatcher
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



def fresh(unavailable_limit=2):
    policy = build_policy()
    run = make_run(policy.snapshot(), {"world": "dispatch-tests"})
    recorder = Recorder(run, policy)
    return policy, run, recorder, Dispatcher(recorder, policy, ADAPTERS,
                                             unavailable_limit=unavailable_limit)


def toy_state(run_id):
    return State(run_id=run_id, step=0, features={
        "bias": 1.0, "stage_progress": 0.0, "surface_known": 1.0,
        "recent_error_rate": 0.0, "budget_remaining": 1.0})


@chapter_claim(
    "handbook/course/05-candidates-and-dispatch.md",
    "Host-scope and destination-scope exclusions stay distinct in the "
    "candidate table.",
    "A coverage obligation with no eligible candidate is reported, not "
    "dropped.",
)
def test_exclusion_scopes_stay_distinct_and_coverage_is_reported():
    table = build_candidates(policy=build_policy(), surfaces=SURFACES,
                             unavailable_tools=["ancient_probe"],
                             coverage=[("form_probe", "https://lab.example/")])
    scopes = {e["scope"] for e in table["excluded"]}
    assert {"host", "destination", "coverage"} <= scopes
    host_rows = [e for e in table["excluded"] if e["scope"] == "host"]
    assert all("unavailable on this host" in e["reasons"][0] for e in host_rows)
    destination_rows = [e for e in table["excluded"]
                        if e["scope"] == "destination"]
    assert any("has_form" in r for e in destination_rows for r in e["reasons"])


@chapter_claim(
    "handbook/course/05-candidates-and-dispatch.md",
    "The ranking is deterministic: weight per unit cost, ties on the identity.",
)
def test_the_ranking_is_deterministic():
    table = build_candidates(policy=build_policy(), surfaces=SURFACES)
    forward = [c.candidate_id for c in rank(table["eligible"])]
    backward = [c.candidate_id for c in rank(table["eligible"][::-1])]
    assert forward == backward
    scores = [c.priority / c.cost for c in rank(table["eligible"])]
    assert scores == sorted(scores, reverse=True)


@chapter_claim(
    "handbook/course/05-candidates-and-dispatch.md",
    "A missing dependency does not become target evidence: an unavailable "
    "tool's outcome is tool_unavailable, never clean.",
    "Unavailability does not consume the action budget.",
)
def test_an_unavailable_tool_is_not_evidence_and_costs_no_budget():
    policy, run, recorder, dispatcher = fresh()
    result = dispatcher.dispatch("dns_survey", "https://lab.example/")
    assert result["status"] == "tool_unavailable"
    report = recorder.snapshot()
    assert report["captures"] == {}
    # The budget is untouched: every allowed action still fits afterwards.
    # Distinct paths, because a settled identity is refused rather than re-run.
    for i in range(policy.max_actions):
        assert dispatcher.dispatch("inspect_headers",
                                   f"https://lab.example/p{i}")["status"] == "clean"
    assert dispatcher.dispatch("inspect_headers",
                               "https://lab.example/x")["status"] == "skipped"


@chapter_claim(
    "handbook/course/05-candidates-and-dispatch.md",
    "Repeated unavailable work does not consume the entire budget: the "
    "re-queue bound turns it away after its limit.",
)
def test_the_requeue_bound_stops_repeated_unavailable_work():
    _, run, recorder, dispatcher = fresh(unavailable_limit=2)
    plan = [{"tool": "dns_survey", "destination": f"https://lab.example/u{i}"}
            for i in range(5)]
    results = dispatcher.run_plan(plan)
    statuses = [r["status"] for r in results]
    assert statuses == ["tool_unavailable", "tool_unavailable",
                        "not_requeued", "not_requeued", "not_requeued"]


@chapter_claim(
    "handbook/course/05-candidates-and-dispatch.md",
    "A controller cannot create a new permission: dispatch re-asks the policy "
    "for every action regardless of who chose it.",
)
def test_a_controller_cannot_create_a_new_permission():
    _, run, recorder, dispatcher = fresh()
    crafted = Candidate(
        candidate_id="inspect_headers -> https://elsewhere.example:443/",
        family="fam-recon",
        features={"tool": "inspect_headers",
                  "destination": "https://elsewhere.example/"},
        priority=99.0)
    result = dispatcher.select_and_run(make_controller("priority"),
                                       toy_state(run.run_id), [crafted])
    assert result["status"] == "refused"
    assert "outside the explicit authorized origins" in result["reason"]
    assert result["learning"]["applied"] is False
    last = recorder.snapshot()["events"][-1]
    assert last["event"] == "refused" and last["kind"] == "action"


@chapter_claim(
    "handbook/course/05-candidates-and-dispatch.md",
    "An executed choice feeds the controller under the shared feedback "
    "definition, and a refused one feeds it nothing.",
)
def test_an_executed_choice_feeds_the_controller():
    _, run, recorder, dispatcher = fresh()
    table = build_candidates(policy=build_policy(), surfaces=SURFACES)
    controller = make_controller("linucb", learn=True)
    result = dispatcher.select_and_run(controller, toy_state(run.run_id),
                                       rank(table["eligible"]))
    assert result["status"] in ("clean", "tool_error", "tool_unavailable")
    if result["status"] in ("clean", "tool_error"):
        assert result["learning"]["applied"] is True
    else:
        assert result["learning"]["applied"] is False


@chapter_claim(
    "handbook/course/05-candidates-and-dispatch.md",
    "A skip carries its reason into the ledger.",
)
def test_a_skip_carries_its_reason():
    _, run, recorder, dispatcher = fresh()
    result = dispatcher.skip("inspect_headers", "https://lab.example/health",
                             "deliberately out of time")
    assert result["status"] == "skipped"
    outcome = recorder.snapshot()["outcomes"][result["action_id"]]
    assert outcome["detail"] == "deliberately out of time"


@chapter_claim(
    "handbook/course/05-candidates-and-dispatch.md",
    "A bounded batch dispatches at most its bound, in plan order.",
)
def test_a_bounded_batch_stops_at_its_bound():
    _, run, recorder, dispatcher = fresh()
    plan = [{"tool": "inspect_headers", "destination": "https://lab.example/a"},
            {"tool": "inspect_headers", "destination": "https://lab.example/b"},
            {"tool": "inspect_headers", "destination": "https://lab.example/c"}]
    results = dispatcher.run_batch(plan, 2)
    assert len(results) == 2
    assert all(r["status"] == "clean" for r in results)


@chapter_claim(
    "handbook/course/05-candidates-and-dispatch.md",
    "an action identity that already carries a terminal outcome is refused at "
    "the door without running the adapter",
)
def test_a_settled_action_identity_is_not_re_run():
    policy, run, recorder, _ = fresh()
    calls = {"n": 0}

    def counting_adapter(url):
        calls["n"] += 1
        return {"status": 200, "body": f"counted response for {url}\n"}

    dispatcher = Dispatcher(recorder, policy,
                            {"inspect_headers": counting_adapter})
    first = dispatcher.dispatch("inspect_headers", "https://lab.example/x")
    assert first["status"] == "clean"
    again = dispatcher.dispatch("inspect_headers", "https://lab.example/x")
    assert again["status"] == "refused"
    assert "already has a recorded outcome" in again["reason"]
    assert calls["n"] == 1, "the adapter ran again for a settled identity"
    refusals = [e for e in recorder.snapshot()["events"]
                if e["event"] == "refused" and e["kind"] == "action"]
    assert any("duplicates do not re-run" in e["reason"] for e in refusals)
