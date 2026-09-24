"""LinUCB, held against the lesson's own hand arithmetic.

The worked example in the LinUCB lesson is computed by hand on the two
dimensional toy schema and re-derived here by the code, so the chapter's
numbers and the implementation agree by test rather than by transcription.
"""

import math

import pytest

from core.controller import make_controller
from core.controller.contract import Candidate, Outcome, State
from core.controller.linucb import identity, solve


def chapter_claim(chapter, *sentences):
    """Anchor a test to the verbatim lesson sentence(s) it backs.

    Same declaration shape as tests/test_chapter_claims.py: verify_claims.sh's
    Check C parses these decorators and fails when a declared sentence is no
    longer present in its chapter.
    """
    def deco(fn):
        return fn
    return deco


ALPHA = 0.5


def toy_state(step=0):
    return State(run_id="toy-run", step=step,
                 features={"bias": 1.0, "signal": 0.0},
                 schema_version="toy-v1")


def one_family():
    return [Candidate(candidate_id="probe:a", family="fam-a", priority=1.0)]


def bandit(learn=True):
    controller = make_controller("linucb", learn=learn)
    controller.alpha = ALPHA
    return controller


@chapter_claim(
    "handbook/course/11-linucb.md",
    "The lesson's initial score is exactly alpha",
)
def test_the_lessons_initial_score_is_exactly_alpha():
    scores = bandit().family_score("fam-a", [1.0, 0.0])
    assert scores["predicted"] == 0.0
    assert scores["bonus"] == pytest.approx(ALPHA)
    assert scores["score"] == pytest.approx(ALPHA)


@chapter_claim(
    "handbook/course/11-linucb.md",
    "the lesson's update produces the lesson's next score",
)
def test_the_lessons_update_produces_the_lessons_next_score():
    controller = bandit()
    decision = controller.select(toy_state(step=0), one_family())
    outcome = Outcome(decision_id=decision.decision_id,
                      candidate_id=decision.candidate_id,
                      run_id="toy-run", status="verified_evidence", feedback=1.0)
    assert controller.observe(outcome)["applied"] is True

    family = controller.snapshot()["families"]["fam-a"]
    assert family["A"] == [[2.0, 1.0 * 0.0], [0.0 * 1.0, 1.0]]
    assert family["b"] == [1.0, 0.0]

    scores = controller.family_score("fam-a", [1.0, 0.0])
    assert scores["predicted"] == pytest.approx(0.5)
    assert scores["bonus"] == pytest.approx(ALPHA / math.sqrt(2))
    assert scores["score"] == pytest.approx(0.5 + ALPHA / math.sqrt(2))


@chapter_claim(
    "handbook/course/11-linucb.md",
    "Frozen mode performs the selection but leaves state unchanged.",
)
def test_frozen_mode_performs_the_selection_but_leaves_state_unchanged():
    controller = bandit(learn=False)
    before = controller.select(toy_state(step=0), one_family())
    assert before is not None
    outcome = Outcome(decision_id=before.decision_id,
                      candidate_id=before.candidate_id,
                      run_id="toy-run", status="verified_evidence", feedback=1.0)
    report = controller.observe(outcome)
    assert report["applied"] is False
    assert report["reason"] == "learning is frozen"
    scores = controller.family_score("fam-a", [1.0, 0.0])
    assert scores["score"] == pytest.approx(ALPHA)


@chapter_claim(
    "handbook/course/11-linucb.md",
    "Interleaved decisions credit their own families",
)
def test_interleaved_decisions_credit_their_own_families():
    controller = bandit()
    first = controller.select(toy_state(step=0),
                              [Candidate(candidate_id="probe:a", family="fam-a")])
    second = controller.select(toy_state(step=1),
                               [Candidate(candidate_id="probe:b", family="fam-b")])
    # Feedback arrives out of order; each decision still lands on its family.
    controller.observe(Outcome(decision_id=second.decision_id,
                               candidate_id="probe:b", run_id="toy-run",
                               status="clean", feedback=2.0))
    controller.observe(Outcome(decision_id=first.decision_id,
                               candidate_id="probe:a", run_id="toy-run",
                               status="clean", feedback=1.0))
    families = controller.snapshot()["families"]
    assert families["fam-a"]["b"] == [1.0, 0.0]
    assert families["fam-b"]["b"] == [2.0, 0.0]


@chapter_claim(
    "handbook/course/11-linucb.md",
    "The family wins on score and the candidate on priority",
)
def test_the_family_wins_on_score_and_the_candidate_on_priority():
    controller = bandit()
    rewarded = controller.select(toy_state(step=0),
                                 [Candidate(candidate_id="probe:a", family="fam-a")])
    controller.observe(Outcome(decision_id=rewarded.decision_id,
                               candidate_id="probe:a", run_id="toy-run",
                               status="verified_evidence", feedback=1.0))
    candidates = [
        Candidate(candidate_id="probe:a2", family="fam-a", priority=0.5),
        Candidate(candidate_id="probe:a1", family="fam-a", priority=2.0),
        Candidate(candidate_id="probe:b1", family="fam-b", priority=9.0),
    ]
    decision = controller.select(toy_state(step=1), candidates)
    # fam-a holds learned reward, so it outscores fam-b despite fam-b's
    # highest-priority candidate; within fam-a, priority picks probe:a1.
    assert decision.scores["chosen_family"] == "fam-a"
    assert decision.candidate_id == "probe:a1"


@chapter_claim(
    "handbook/course/11-linucb.md",
    "equal family scores break ties lexicographically",
)
def test_equal_family_scores_break_ties_lexicographically():
    controller = bandit()
    decision = controller.select(toy_state(), [
        Candidate(candidate_id="probe:z", family="fam-z", priority=5.0),
        Candidate(candidate_id="probe:a", family="fam-a", priority=1.0),
    ])
    assert decision.scores["chosen_family"] == "fam-a"


@chapter_claim(
    "handbook/course/11-linucb.md",
    "A learned family refuses a vector of another dimension.",
)
def test_a_learned_family_refuses_a_vector_of_another_dimension():
    controller = bandit()
    controller.family_score("fam-a", [1.0, 0.0])
    with pytest.raises(ValueError):
        controller.family_score("fam-a", [1.0, 0.0, 0.0])


@chapter_claim(
    "handbook/course/11-linucb.md",
    "the pivot exists so a corrupted snapshot produces a loud error instead of a quiet wrong answer",
)
def test_the_solver_inverts_what_it_is_given():
    assert solve(identity(3), [3.0, -1.0, 2.0]) == [3.0, -1.0, 2.0]
    assert solve([[2.0, 0.0], [0.0, 4.0]], [1.0, 1.0]) == [0.5, 0.25]
    with pytest.raises(ValueError):
        solve([[1.0, 1.0], [1.0, 1.0]], [1.0, 1.0])


@chapter_claim(
    "handbook/course/11-linucb.md",
    "Reset forgets learning and snapshot restores it.",
)
def test_reset_forgets_learning_and_snapshot_restores_it():
    controller = bandit()
    decision = controller.select(toy_state(), one_family())
    controller.observe(Outcome(decision_id=decision.decision_id,
                               candidate_id="probe:a", run_id="toy-run",
                               status="clean", feedback=1.0))
    saved = controller.snapshot()
    controller.reset()
    assert controller.family_score("fam-a", [1.0, 0.0])["score"] == pytest.approx(ALPHA)
    controller.restore(saved)
    assert controller.family_score("fam-a", [1.0, 0.0])["predicted"] == pytest.approx(0.5)
