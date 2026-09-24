"""The shared controller contract, held at its boundaries.

Covers the properties the controller lessons rely on: every controller answers
through the same records, a shadow recommendation earns no learning credit, an
unexecuted decision earns none either, feedback lands only on the decision an
outcome names, and snapshot/restore round-trips the whole mutable state.
"""

import pytest

from core.controller import controller_names, make_controller
from core.controller.contract import (
    Candidate, ContractError, Outcome, State, decision_id)


def chapter_claim(chapter, *sentences):
    """Anchor a test to the verbatim lesson sentence(s) it backs.

    Same declaration shape as tests/test_chapter_claims.py: verify_claims.sh's
    Check C parses these decorators and fails when a declared sentence is no
    longer present in its chapter.
    """
    def deco(fn):
        return fn
    return deco


def toy_state(step=0, run_id="run-a"):
    return State(run_id=run_id, step=step,
                 features={"bias": 1.0, "signal": 0.0},
                 schema_version="toy-v1")


def toy_candidates():
    return [
        Candidate(candidate_id="probe:alpha", family="fam-a", priority=2.0, cost=1.0),
        Candidate(candidate_id="probe:beta", family="fam-a", priority=1.0, cost=0.5),
        Candidate(candidate_id="probe:gamma", family="fam-b", priority=3.0, cost=2.0),
    ]


@pytest.mark.parametrize("name", controller_names())
@chapter_claim(
    "handbook/course/10-controller-laboratory.md",
    "Every controller selects from the same records: identical state, identical candidates, and a decision carrying the scores it used.",
)
def test_every_controller_selects_from_the_same_records(name):
    controller = make_controller(name)
    decision = controller.select(toy_state(), toy_candidates())
    assert decision.candidate_id in {c.candidate_id for c in toy_candidates()}
    assert decision.controller == name
    assert decision.shadow is False
    assert decision.selected_features == [1.0, 0.0]


@pytest.mark.parametrize("name", controller_names())
@chapter_claim(
    "handbook/course/10-controller-laboratory.md",
    "an empty candidate list yields no decision rather than an invented one",
)
def test_empty_candidates_yield_no_decision(name):
    assert make_controller(name).select(toy_state(), []) is None


@pytest.mark.parametrize("name", controller_names())
@chapter_claim(
    "handbook/course/10-controller-laboratory.md",
    "Selection is stable under input order",
)
def test_selection_is_stable_under_input_order(name):
    forward = make_controller(name).select(toy_state(), toy_candidates())
    backward = make_controller(name).select(toy_state(), toy_candidates()[::-1])
    assert forward.candidate_id == backward.candidate_id


@pytest.mark.parametrize("name", controller_names())
@chapter_claim(
    "handbook/course/10-controller-laboratory.md",
    "A shadow decision receives no learning credit",
)
def test_a_shadow_decision_receives_no_learning_credit(name):
    controller = make_controller(name, learn=True)
    decision = controller.select(toy_state(), toy_candidates(), shadow=True)
    assert decision.shadow is True
    outcome = Outcome(decision_id=decision.decision_id,
                      candidate_id=decision.candidate_id,
                      run_id="run-a", status="clean", feedback=1.0)
    assert controller.observe(outcome)["applied"] is False


@pytest.mark.parametrize("name", controller_names())
@chapter_claim(
    "handbook/course/10-controller-laboratory.md",
    "neither does a decision whose outcome says it was not executed",
)
def test_an_unexecuted_decision_receives_no_learning_credit(name):
    controller = make_controller(name, learn=True)
    decision = controller.select(toy_state(), toy_candidates())
    outcome = Outcome(decision_id=decision.decision_id,
                      candidate_id=decision.candidate_id,
                      run_id="run-a", status="skipped", feedback=1.0,
                      executed=False)
    assert controller.observe(outcome)["applied"] is False


@pytest.mark.parametrize("name", controller_names())
@chapter_claim(
    "handbook/course/10-controller-laboratory.md",
    "An outcome naming a different candidate than its decision chose is refused with a recorded reason.",
)
def test_an_outcome_naming_a_different_candidate_is_refused(name):
    controller = make_controller(name, learn=True)
    decision = controller.select(toy_state(), toy_candidates())
    other = next(c.candidate_id for c in toy_candidates()
                 if c.candidate_id != decision.candidate_id)
    outcome = Outcome(decision_id=decision.decision_id, candidate_id=other,
                      run_id="run-a", status="clean", feedback=1.0)
    report = controller.observe(outcome)
    assert report["applied"] is False
    assert "different candidate" in report["reason"]
    # The refusal spends nothing: the correctly addressed outcome still lands
    # on a pending record the mis-addressed one did not consume.
    corrected = Outcome(decision_id=decision.decision_id,
                        candidate_id=decision.candidate_id,
                        run_id="run-a", status="clean", feedback=1.0)
    assert controller.observe(corrected).get("reason") != "unknown or shadow decision"


@pytest.mark.parametrize("name", controller_names())
@chapter_claim(
    "handbook/course/10-controller-laboratory.md",
    "A duplicate observation is not applied twice.",
)
def test_a_duplicate_observation_is_not_applied_twice(name):
    controller = make_controller(name, learn=True)
    decision = controller.select(toy_state(), toy_candidates())
    outcome = Outcome(decision_id=decision.decision_id,
                      candidate_id=decision.candidate_id,
                      run_id="run-a", status="clean", feedback=1.0)
    controller.observe(outcome)
    assert controller.observe(outcome)["applied"] is False


@pytest.mark.parametrize("name", controller_names())
@chapter_claim(
    "handbook/course/10-controller-laboratory.md",
    "A snapshot restores into a fresh instance of the same controller",
)
def test_snapshot_and_restore_round_trip(name):
    controller = make_controller(name, learn=True)
    controller.select(toy_state(step=0), toy_candidates())
    saved = controller.snapshot()
    twin = make_controller(name, learn=True)
    twin.restore(saved)
    assert twin.snapshot() == saved


@chapter_claim(
    "handbook/course/10-controller-laboratory.md",
    "is refused by any other",
)
def test_a_snapshot_from_another_controller_is_refused():
    saved = make_controller("priority").snapshot()
    with pytest.raises(ContractError):
        make_controller("legacy").restore(saved)


@chapter_claim(
    "handbook/course/10-controller-laboratory.md",
    "The outcome's status comes from a fixed vocabulary",
)
def test_an_unknown_outcome_status_is_refused():
    with pytest.raises(ContractError):
        Outcome(decision_id="d", candidate_id="c", run_id="r",
                status="triumph", feedback=1.0)


@chapter_claim(
    "handbook/course/10-controller-laboratory.md",
    "refuses missing or non-finite values",
)
def test_a_state_missing_a_schema_feature_is_refused():
    state = State(run_id="r", step=0, features={"bias": 1.0},
                  schema_version="toy-v1")
    with pytest.raises(ContractError):
        state.vector()


@chapter_claim(
    "handbook/course/10-controller-laboratory.md",
    "The decision_id names one act of choosing, and feedback is keyed by it.",
)
def test_decision_ids_are_stable_and_distinct():
    same = decision_id("run-a", 3, "probe:alpha")
    assert same == decision_id("run-a", 3, "probe:alpha")
    assert same != decision_id("run-a", 4, "probe:alpha")
    assert same != decision_id("run-a", 3, "probe:beta")
