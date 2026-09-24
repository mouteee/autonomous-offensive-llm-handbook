"""The sparse mushroom-body controller, held against its lesson.

Covers the encoder's sparsity contract, the activation terms, lateral
inhibition, deterministic exploration, habituation's three-state rule and its
decay, and event-history reconstruction.
"""

import pytest

from core.controller import make_controller
from core.controller.contract import Candidate, Outcome, State
from core.controller.mb import (
    COVERAGE_BOOST, Habituation, MushroomBodyController, SparseEncoder,
    surface_class)


def chapter_claim(chapter, *sentences):
    """Anchor a test to the verbatim lesson sentence(s) it backs.

    Same declaration shape as tests/test_chapter_claims.py: verify_claims.sh's
    Check C parses these decorators and fails when a declared sentence is no
    longer present in its chapter.
    """
    def deco(fn):
        return fn
    return deco





def full_state(step=0):
    return State(run_id="mb-test", step=step, features={
        "bias": 1.0, "stage_progress": 0.5, "surface_known": 1.0,
        "recent_error_rate": 0.0, "budget_remaining": 0.5})


def two_families():
    return [
        Candidate(candidate_id="probe:a", family="fam-a", priority=6.0, cost=3.0,
                  features={"url": "https://lab.example/api/users"}),
        Candidate(candidate_id="probe:b", family="fam-b", priority=4.0, cost=1.0,
                  features={"url": "https://lab.example/docs"}),
    ]


def run_script(controller, steps=6):
    decisions = []
    for step in range(steps):
        decision = controller.select(full_state(step), two_families())
        controller.observe(Outcome(
            decision_id=decision.decision_id, candidate_id=decision.candidate_id,
            run_id="mb-test", status="tool_error", feedback=0.0))
        decisions.append(decision)
    return decisions


@chapter_claim(
    "handbook/course/12-mushroom-body-controller.md", "Identical frozen inputs and seeds replay the selection.")
def test_identical_inputs_and_seeds_replay_the_selection():
    first = run_script(MushroomBodyController(seed=3))
    second = run_script(MushroomBodyController(seed=3))
    assert [d.candidate_id for d in first] == [d.candidate_id for d in second]
    assert [d.scores for d in first] == [d.scores for d in second]


@chapter_claim(
    "handbook/course/12-mushroom-body-controller.md", "Only an error or a clean response habituates; verified "
                    "evidence, skips, unavailable tools and unresolved "
                    "executions do not.")
def test_only_error_and_clean_habituate():
    hab = Habituation()
    for signature in ("hit", "skipped", "unavailable", "unresolved"):
        hab.observe("page:d1:nq", "fam-a", signature)
    assert hab.penalty("page:d1:nq", "fam-a") == 0.0
    hab.observe("page:d1:nq", "fam-a", "error")
    with_error = hab.penalty("page:d1:nq", "fam-a")
    assert with_error > 0.0
    hab.observe("page:d1:nq", "fam-a", "clean")
    assert hab.penalty("page:d1:nq", "fam-a") > with_error


@chapter_claim(
    "handbook/course/12-mushroom-body-controller.md", "The penalty saturates below one and decays every select, "
                    "so a suppressed family drifts back into contention.")
def test_the_penalty_saturates_and_decays():
    hab = Habituation()
    for _ in range(50):
        hab.observe("page:d1:nq", "fam-a", "error")
    saturated = hab.penalty("page:d1:nq", "fam-a")
    assert 0.0 < saturated < 1.0
    hab.decay_step()
    assert hab.penalty("page:d1:nq", "fam-a") < saturated
    # A trace decayed long enough is pruned outright.
    small = Habituation()
    small.observe("page:d1:nq", "fam-a", "error")
    for _ in range(60):
        small.decay_step()
    assert small.penalty("page:d1:nq", "fam-a") == 0.0


@chapter_claim(
    "handbook/course/12-mushroom-body-controller.md", "The winner is chosen after lateral inhibition and the "
                    "runner-up and margin stay in the record.")
def test_lateral_inhibition_and_the_margin_are_recorded():
    controller = MushroomBodyController(seed=3)
    decision = controller.select(full_state(), two_families())
    scores = decision.scores
    assert scores["winner"] == decision.family
    assert scores["runner_up"] in ("fam-a", "fam-b")
    assert scores["runner_up"] != scores["winner"]
    for family, signal in scores["by_family"].items():
        assert signal["activation"] <= signal["activation_before_inhibition"], family
    if not scores["exploration"]:
        assert scores["margin"] == pytest.approx(
            scores["by_family"][scores["winner"]]["activation"]
            - scores["by_family"][scores["runner_up"]]["activation"])


@chapter_claim(
    "handbook/course/12-mushroom-body-controller.md", "A coverage obligation raises a family's prior by the "
                    "documented boost.")
def test_a_coverage_obligation_raises_the_prior():
    controller = MushroomBodyController(seed=3)
    plain = two_families()
    boosted = [
        Candidate(candidate_id="probe:a", family="fam-a", priority=6.0, cost=3.0,
                  features={"url": "https://lab.example/api/users",
                            "coverage_obligation": True}),
        plain[1],
    ]
    base = controller.select(full_state(0), plain).scores["by_family"]["fam-a"]
    with_boost = controller.select(
        full_state(1), boosted).scores["by_family"]["fam-a"]
    assert with_boost["prior"] == pytest.approx(base["prior"] + COVERAGE_BOOST)


@chapter_claim(
    "handbook/course/12-mushroom-body-controller.md", "The encoder keeps at most k units and only positively "
                    "activated ones.")
def test_the_encoder_is_sparse_and_positive_only():
    encoder = SparseEncoder(seed=3, n_inputs=5)
    z = encoder.encode([1.0, 0.5, 1.0, 0.0, 0.5])
    assert 0 < len(z) <= encoder.k
    assert list(z) == sorted(z)
    # A zero vector excites no unit strictly positively, and the encoder
    # answers with an empty code rather than inventing active units.
    assert encoder.encode([0.0, 0.0, 0.0, 0.0, 0.0]) == ()


@chapter_claim(
    "handbook/course/12-mushroom-body-controller.md", "Rebuilding from the event history reproduces the "
                    "habituation state.")
def test_hydration_reproduces_the_habituation_state():
    live = MushroomBodyController(seed=3)
    events = []
    for step in range(5):
        decision = live.select(full_state(step), two_families())
        live.observe(Outcome(
            decision_id=decision.decision_id, candidate_id=decision.candidate_id,
            run_id="mb-test", status="tool_error", feedback=0.0))
        events.append({
            "decision_id": decision.decision_id,
            "family": decision.family,
            "surface": surface_class(
                two_families()[0].features["url"]
                if decision.family == "fam-a"
                else two_families()[1].features["url"]),
            "signature": "error",
        })
    twin = MushroomBodyController(seed=3)
    twin.hydrate(events)
    assert twin.snapshot()["habituation"] == live.snapshot()["habituation"]
    assert twin.snapshot()["step"] == live.snapshot()["step"]


@chapter_claim(
    "handbook/course/12-mushroom-body-controller.md", "An exploration draw is deterministic under the seed and "
                    "is recorded on the decision.")
def test_exploration_is_deterministic_and_recorded():
    flags_a = [MushroomBodyController(seed=7).select(
        full_state(step), two_families()).scores["exploration"]
        for step in range(40)]
    flags_b = [MushroomBodyController(seed=7).select(
        full_state(step), two_families()).scores["exploration"]
        for step in range(40)]
    assert flags_a == flags_b
    assert any(flags_a), "expected at least one exploration draw in the sweep"
    assert not all(flags_a)


@chapter_claim(
    "handbook/course/12-mushroom-body-controller.md", "The surface class buckets a destination by kind, depth "
                    "and query shape.")
def test_surface_classes_bucket_destinations():
    assert surface_class("https://lab.example/api/users") == "api:d2:nq"
    assert surface_class("https://lab.example/app.js") == "asset:d1:nq"
    assert surface_class("https://lab.example/docs?page=2") == "page:d1:q"
    assert surface_class("") == "page:d0:nq"


@chapter_claim(
    "handbook/course/12-mushroom-body-controller.md", "A learned dimension is pinned at first use and another "
                    "dimension is refused loudly.")
def test_the_encoder_dimension_is_pinned_at_first_use():
    controller = MushroomBodyController(seed=3)
    controller.select(full_state(), two_families())
    toy = State(run_id="mb-test", step=9, features={"bias": 1.0, "signal": 0.0},
                schema_version="toy-v1")
    with pytest.raises(ValueError):
        controller.select(toy, two_families())


@chapter_claim(
    "handbook/course/12-mushroom-body-controller.md",
    "The candidate builder supplies the fields this controller reads: url for "
    "the surface class and coverage_obligation for the declared boost.",
)
def test_the_candidate_builder_satisfies_the_controller_contract():
    from core.run.candidates import build_candidates
    from core.run.policy import Policy, Tool

    policy = Policy(reference="mb-contract", origins=["https://lab.example/"],
                    tools=[Tool(tool_id="probe", activity="passive",
                                family="fam-a"),
                           Tool(tool_id="form_probe", activity="active",
                                family="fam-b", requires={"has_form": True})],
                    max_actions=10, max_model_calls=1)
    surfaces = [
        {"surface_id": "api", "url": "https://lab.example/api/orders",
         "facts": {"has_form": False}},
        {"surface_id": "login", "url": "https://lab.example/login",
         "facts": {"has_form": True}},
    ]
    table = build_candidates(
        policy=policy, surfaces=surfaces,
        coverage=[("probe", "https://lab.example/api/orders")])
    assert table["eligible"], "the contract fixture built no candidates"
    for candidate in table["eligible"]:
        assert candidate.features["url"] == candidate.features["destination"]
        assert "coverage_obligation" in candidate.features
    flagged = [c.candidate_id for c in table["eligible"]
               if c.features["coverage_obligation"]]
    assert flagged == ["probe -> https://lab.example:443/api/orders"]


@chapter_claim(
    "handbook/course/12-mushroom-body-controller.md",
    "The candidate builder supplies the fields this controller reads: url for "
    "the surface class and coverage_obligation for the declared boost.",
)
def test_builder_candidates_drive_surface_habituation_and_coverage():
    from core.controller.mb import COVERAGE_BOOST
    from core.run.candidates import build_candidates
    from core.run.policy import Policy, Tool

    policy = Policy(reference="mb-through-builder",
                    origins=["https://lab.example/"],
                    tools=[Tool(tool_id="probe", activity="passive",
                                family="fam-a")],
                    max_actions=10, max_model_calls=1)
    surfaces = [
        {"surface_id": "api", "url": "https://lab.example/api/orders"},
        {"surface_id": "login", "url": "https://lab.example/login"},
    ]
    table = build_candidates(policy=policy, surfaces=surfaces)
    by_surface = {c.features["surface_id"]: c for c in table["eligible"]}
    api, login = by_surface["api"], by_surface["login"]

    controller = make_controller("mb")
    decision = controller.select(full_state(0), [api])
    controller.observe(Outcome(decision_id=decision.decision_id,
                               candidate_id=api.candidate_id,
                               run_id="mb-test", status="tool_error",
                               feedback=-0.4))
    # The error habituated the api surface class only: the same family on the
    # login page surface carries no penalty.
    hurt = controller.select(full_state(1), [api])
    assert hurt.scores["by_family"]["fam-a"]["habituation"] > 0
    unhurt = controller.select(full_state(2), [login])
    assert unhurt.scores["by_family"]["fam-a"]["habituation"] == 0.0

    # A declared coverage obligation raises exactly the flagged pool's prior.
    flagged_table = build_candidates(
        policy=policy, surfaces=surfaces,
        coverage=[("probe", "https://lab.example/api/orders")])
    flagged = {c.features["surface_id"]: c for c in flagged_table["eligible"]}
    fresh = make_controller("mb")
    with_boost = fresh.select(full_state(0), [flagged["api"]])
    without = fresh.select(full_state(1), [flagged["login"]])
    boost = (with_boost.scores["by_family"]["fam-a"]["prior"]
             - without.scores["by_family"]["fam-a"]["prior"])
    assert round(boost, 6) == COVERAGE_BOOST


@chapter_claim(
    "handbook/course/12-mushroom-body-controller.md",
    "The candidate builder supplies the fields this controller reads: url for "
    "the surface class and coverage_obligation for the declared boost.",
)
def test_the_assembled_application_carries_coverage_into_the_table():
    from core.run.app import Application
    from core.run.demo_app import LAB, WORLD, build_config
    from core.run.demo_lifecycle import FakeClock

    config = build_config()
    config["coverage"] = [["inspect_headers", f"{LAB}/"]]
    app = Application(config, clock=FakeClock())
    app._start(WORLD)
    app._observe(WORLD)
    table, _ = app._plan(WORLD)
    flagged = [c.candidate_id for c in table["eligible"]
               if c.features["coverage_obligation"]]
    assert flagged == ["inspect_headers -> https://lab.example:443/"]


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md",
    "A shadow selection lays no eligibility trace: a later legitimate outcome "
    "cannot credit units only the shadow activated.",
)
def test_a_shadow_consultation_does_not_advance_the_episode():
    consulted = MushroomBodyController(seed=3)
    control = MushroomBodyController(seed=3)

    # Same warm-up on both: one executed error habituates one surface class.
    for controller in (consulted, control):
        decision = controller.select(full_state(0), two_families())
        controller.observe(Outcome(
            decision_id=decision.decision_id,
            candidate_id=decision.candidate_id,
            run_id="mb-test", status="tool_error", feedback=0.0))

    before = consulted.snapshot()
    shadow = consulted.select(full_state(1), two_families(), shadow=True)
    assert shadow is not None and shadow.shadow is True
    after = consulted.snapshot()
    assert after["habituation"] == before["habituation"], \
        "a shadow consultation decayed the habituation counters"
    assert after["step"] == before["step"]
    assert after["surfaces"] == before["surfaces"]
    assert shadow.decision_id not in after["pending"]

    # And the next real selection is exactly what it would have been had the
    # shadow consultation never happened.
    with_shadow = consulted.select(full_state(1), two_families())
    without = control.select(full_state(1), two_families())
    assert with_shadow.candidate_id == without.candidate_id
    assert with_shadow.scores == without.scores
