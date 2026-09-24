"""The graph arm, held at the boundaries lesson 14 teaches.

Topology controls preserve what they claim, the plastic site is the edge set
and nothing else, the frozen arm learns nothing, replay is exact, and the
no-hop control isolates the hop.
"""

import pytest

from core.controller.contract import Candidate, Outcome, State
from core.controller.demo_graph import FIXTURE, build_arms
from core.controller.graph import (
    EdgeEligibility, GraphController, ToyGraph, random_variant,
    shuffled_variant)
from core.controller.research import run_condition
from core.controller.worlds import make_world


def chapter_claim(chapter, *sentences):
    """Anchor a test to the verbatim lesson sentence(s) it backs.

    Same declaration shape as tests/test_chapter_claims.py: verify_claims.sh's
    Check C parses these decorators and fails when a declared sentence is no
    longer present in its chapter.
    """
    def deco(fn):
        return fn
    return deco




def toy_graph():
    return ToyGraph.load(FIXTURE)


def toy_state(step=0):
    return State(run_id="graph-test", step=step,
                 features={"bias": 1.0, "signal": 0.5},
                 schema_version="toy-v1")


def candidates():
    return [Candidate(candidate_id="a", family="fam-a", priority=1.0),
            Candidate(candidate_id="b", family="fam-b", priority=1.0)]


@chapter_claim(
    "handbook/course/14-graph-controller-experiments.md",
    "Identical seeds and identical frozen inputs replay the same choices.",
)
def test_identical_seeds_and_inputs_replay_the_same_choices():
    first = GraphController(graph=toy_graph(), seed=3)
    second = GraphController(graph=toy_graph(), seed=3)
    for step in range(5):
        a = first.select(toy_state(step), candidates())
        b = second.select(toy_state(step), candidates())
        assert a.candidate_id == b.candidate_id
        assert a.scores == b.scores


@chapter_claim(
    "handbook/course/14-graph-controller-experiments.md",
    "The frozen arm's learned weights stay at zero and its traces stay empty.",
)
def test_the_frozen_arm_never_learns():
    frozen = GraphController(graph=toy_graph(), seed=3, learn=False)
    for step in range(4):
        decision = frozen.select(toy_state(step), candidates())
        frozen.observe(Outcome(decision_id=decision.decision_id,
                               candidate_id=decision.candidate_id,
                               run_id="graph-test", status="clean",
                               feedback=1.0))
    assert frozen._weights.weights() == {}
    assert frozen._elig.traces() == {}


@chapter_claim(
    "handbook/course/14-graph-controller-experiments.md",
    "The shuffled control preserves every node's in and out degree, and the "
    "random control preserves the node count, the edge count and the weight "
    "multiset.",
)
def test_the_topology_controls_preserve_what_they_claim():
    toy = toy_graph()
    shuffled = shuffled_variant(toy, seed=1007)
    assert shuffled.degree_sequences() == toy.degree_sequences()
    assert sorted(w for _, _, w in shuffled.edges) == sorted(
        w for _, _, w in toy.edges)
    randomized = random_variant(toy, seed=1007)
    assert randomized.n == toy.n
    assert len(randomized.edges) == len(toy.edges)
    assert sorted(w for _, _, w in randomized.edges) == sorted(
        w for _, _, w in toy.edges)
    assert {(p, q) for p, q, _ in randomized.edges} != {
        (p, q) for p, q, _ in toy.edges}


@chapter_claim(
    "handbook/course/14-graph-controller-experiments.md",
    "Every learned key is an association edge of the arm's own graph.",
)
def test_learning_lands_on_association_edges_only():
    arm = build_arms()["toy"]
    run_condition(arm, make_world("decoy-delay", seed=7))
    learned = arm._weights.weights()
    assert learned, "the demo episode is expected to move some edge weight"
    edge_set = {(pre, post) for pre, post, _ in arm.graph.edges}
    assert set(learned) <= edge_set


@chapter_claim(
    "handbook/course/14-graph-controller-experiments.md",
    "The no-hop control's final active set is its step-zero active set.",
)
def test_the_no_hop_control_isolates_the_hop():
    toy = toy_graph()
    hopless = GraphController(graph=toy, seed=3, hop=False)
    hopping = GraphController(graph=toy, seed=3)
    x = toy_state().vector()
    no_hop = hopless.forward(x)
    assert no_hop["active"] == no_hop["active0"]
    assert no_hop["co_keys"] == ()
    with_hop = hopping.forward(x)
    assert with_hop["active0"] == no_hop["active0"]
    assert with_hop["co_keys"], "the hop is expected to co-activate edges"


@chapter_claim(
    "handbook/course/14-graph-controller-experiments.md",
    "The update rule is the lesson 13 rule reused by import, clipping included.",
)
def test_the_update_rule_is_reused_and_clips():
    from core.controller.plasticity import LearnedWeights
    arm = GraphController(graph=toy_graph(), seed=3, learn=True)
    assert isinstance(arm._weights, LearnedWeights)
    arm._elig.on_coactivation([(0, 1)])
    for _ in range(60):
        arm._weights.update(arm._elig.traces(), 1.0)
    assert arm._weights.weights()[(0, 1)] == arm._weights.w_max


@chapter_claim(
    "handbook/course/14-graph-controller-experiments.md",
    "This run shows edge updates changing selections; it does not establish "
    "an advantage for the toy topology.",
)
def test_the_demo_runs_every_arm_to_completion_without_ranking():
    from core.controller.demo_graph import run_demo
    demo = run_demo()
    assert set(demo["arms"]) == {"toy", "shuffled", "random", "no-hop",
                                 "toy-frozen"}
    for arm in demo["arms"].values():
        assert "total_reward" in arm and "parity" in arm
    # The artifact carries per-arm facts and no ranking, winner or verdict
    # field; interpretation stays in the lesson's scoped prose.
    assert not any(key in demo for key in ("winner", "ranking", "verdict"))


@chapter_claim(
    "handbook/course/14-graph-controller-experiments.md",
    "hand the arm a state vector of the wrong dimension after its first "
    "selection and it refuses loudly rather than reshaping",
)
def test_a_dimension_change_is_refused_after_pinning():
    arm = GraphController(graph=toy_graph(), seed=3)
    arm.forward([1.0, 0.5])
    with pytest.raises(ValueError):
        arm.forward([1.0, 0.5, 0.25])


@chapter_claim(
    "handbook/course/14-graph-controller-experiments.md",
    "every control arm receives the toy arm's anchor rather than computing "
    "its own",
)
def test_controls_share_the_toy_arms_normalization_anchor():
    arms = build_arms()
    anchor = arms["toy"].w95_anchor
    assert all(arm.w95_anchor == anchor for arm in arms.values())


@chapter_claim(
    "handbook/course/14-graph-controller-experiments.md",
    "Lesson 13's refusal unwind travels with the reuse: a selection the host "
    "reports as not executed has what remains of its edge deposit subtracted "
    "exactly, so a later outcome cannot credit edges only a refused selection "
    "co-activated.",
)
def test_a_refused_graph_selection_earns_no_later_edge_credit():
    arm = GraphController(graph=toy_graph(), seed=3, learn=True)
    doomed = arm.select(toy_state(0), candidates())
    doomed_keys = set(arm._elig.traces())
    assert doomed_keys, "the probe selection co-activated no edges"
    report = arm.observe(Outcome(
        decision_id=doomed.decision_id, candidate_id=doomed.candidate_id,
        run_id="graph-test", status="skipped", feedback=0.0, executed=False))
    assert report == {"applied": False, "reason": "decision was not executed"}
    assert arm._elig.traces() == {}, \
        "the refusal left the refused selection's edge deposit alive"

    other = State(run_id="graph-test", step=1,
                  features={"bias": 0.2, "signal": -1.0},
                  schema_version="toy-v1")
    executed = arm.select(other, candidates())
    arm.observe(Outcome(
        decision_id=executed.decision_id, candidate_id=executed.candidate_id,
        run_id="graph-test", status="verified_evidence", feedback=1.0))
    live = set(arm._elig.traces())
    leaked = {key: w for key, w in arm._weights.weights().items()
              if key in doomed_keys - live and w != 0}
    assert leaked == {}, \
        f"a later outcome credited refused-only edges: {leaked}"


@chapter_claim(
    "handbook/course/14-graph-controller-experiments.md",
    "Lesson 13's refusal unwind travels with the reuse: a selection the host "
    "reports as not executed has what remains of its edge deposit subtracted "
    "exactly, so a later outcome cannot credit edges only a refused selection "
    "co-activated.",
)
def test_a_dead_edge_deposits_late_refusal_takes_nothing_from_a_successor():
    # The follow-up review's reproduction: on the reviewed tree this sequence
    # left the fresh edge at one minus the dead deposit's computed residual,
    # because on_coactivation deposited without recording the key's rebirth.
    elig = EdgeEligibility()
    elig.on_coactivation([(0, 1)])
    dead_marker = elig.marker()
    while (0, 1) in elig.traces():
        elig.on_coactivation([])        # decay until the share prunes away
    elig.on_coactivation([(0, 1)])      # a successor recreates the edge
    elig.unwind([(0, 1)], dead_marker)
    assert elig.traces()[(0, 1)] == 1.0, \
        "a dead edge deposit's late refusal was subtracted from its successor"

    # And through the controller contract: the same sequence driven by
    # selections, with the first decision's refusal arriving last.
    arm = GraphController(graph=toy_graph(), seed=3, learn=True)
    doomed = arm.select(toy_state(0), candidates())
    doomed_keys = set(arm._elig.traces())
    step = 1
    while set(arm._elig.traces()) & doomed_keys:
        arm._elig.on_coactivation([])   # age the traces to pruning
        step += 1
    # A later step with the same features projects the same co-activation
    # keys while keeping its own decision identity.
    fresh = arm.select(toy_state(step), candidates())
    fresh_traces = dict(arm._elig.traces())
    assert set(fresh_traces) == doomed_keys and \
        set(fresh_traces.values()) == {1.0}
    arm.observe(Outcome(
        decision_id=doomed.decision_id, candidate_id=doomed.candidate_id,
        run_id="graph-test", status="skipped", feedback=0.0, executed=False))
    assert dict(arm._elig.traces()) == fresh_traces, \
        "the dead first selection's refusal changed the fresh edge deposits"
    # The fresh selection itself still unwinds exactly when IT is refused.
    arm.observe(Outcome(
        decision_id=fresh.decision_id, candidate_id=fresh.candidate_id,
        run_id="graph-test", status="skipped", feedback=0.0, executed=False))
    assert arm._elig.traces() == {}
