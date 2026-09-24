"""The operational stage machine, held at its transitions and prerequisites."""

from core.run.demo_records import build_policy
from core.run.recorder import Recorder
from core.run.records import make_run
from core.run.stages import (HARNESS_MAPPING, OPERATIONAL_STAGES, StageMachine,
                             measured, observations_from_response,
                             requirements_met, unknown)


def chapter_claim(chapter, *sentences):
    """Anchor a test to the verbatim lesson sentence(s) it backs.

    Same declaration shape as tests/test_chapter_claims.py: verify_claims.sh's
    Check C parses these decorators and goes red when a declared sentence is
    no longer present in its chapter.
    """
    def deco(fn):
        return fn
    return deco



def machine_with(observation=False, gate=None):
    policy = build_policy()
    run = make_run(policy.snapshot(), {"world": "stage-tests"})
    recorder = Recorder(run, policy)
    if observation:
        recorder.record("observation", {"run_id": run.run_id,
                                        **measured("has_form", True,
                                                   "fixture:test")})
    if gate is not None:
        recorder.record("gate", {"run_id": run.run_id, "status": gate,
                                 "mode": "full" if gate == "proceed" else "passive",
                                 "inputs": {}})
    return StageMachine(recorder), recorder


@chapter_claim(
    "handbook/course/03-stages-and-observations.md",
    "Every operational stage maps onto the teaching harness's five stages, and "
    "the mapping is data the lesson can print.",
)
def test_every_operational_stage_maps_onto_the_harness_stages():
    harness_stages = {"observe", "plan", "execute", "review", "report"}
    assert set(HARNESS_MAPPING) == set(OPERATIONAL_STAGES)
    for stage, targets in HARNESS_MAPPING.items():
        assert targets, stage
        assert set(targets) <= harness_stages, stage
    covered = {t for targets in HARNESS_MAPPING.values() for t in targets}
    assert covered == harness_stages


@chapter_claim(
    "handbook/course/03-stages-and-observations.md",
    "An out-of-order transition is refused and recorded with the expected next "
    "stage named.",
    "The host enforces transitions; prompt text cannot advance the stage.",
)
def test_an_out_of_order_transition_is_refused_and_recorded():
    machine, recorder = machine_with(observation=True, gate="proceed")
    answer = machine.advance("active_testing")
    assert answer["allowed"] is False
    assert "expected 'detection'" in answer["reason"]
    assert machine.current == "discovery"
    last = recorder.snapshot()["events"][-1]
    assert last["event"] == "refused" and last["kind"] == "stage"


@chapter_claim(
    "handbook/course/03-stages-and-observations.md",
    "Detection requires at least one recorded observation.",
)
def test_detection_requires_an_observation():
    machine, recorder = machine_with(observation=False)
    answer = machine.advance("detection")
    assert answer["allowed"] is False
    assert "at least one recorded observation" in answer["reason"]
    assert machine.current == "discovery"


@chapter_claim(
    "handbook/course/03-stages-and-observations.md",
    "Active testing requires a recorded gate decision of proceed or limited.",
)
def test_active_testing_requires_a_favorable_gate():
    for gate, allowed in ((None, False), ("indeterminate", False),
                          ("limited", True), ("proceed", True)):
        machine, recorder = machine_with(observation=True, gate=gate)
        walk = ["detection", "crawling", "mining", "scanning"]
        # scanning itself needs a recorded gate; stop the walk there when
        # no gate exists so the probe isolates the active_testing rule.
        for stage in walk:
            result = machine.advance(stage)
            if not result["allowed"]:
                break
        if gate is None:
            assert machine.current == "mining"
            continue
        answer = machine.advance("active_testing")
        assert answer["allowed"] is allowed, (gate, answer)


@chapter_claim(
    "handbook/course/03-stages-and-observations.md",
    "A clean walk visits all seven stages in order and each advancement names "
    "its harness stages.",
)
def test_a_clean_walk_reaches_reporting():
    machine, recorder = machine_with(observation=True, gate="proceed")
    for stage in OPERATIONAL_STAGES[1:]:
        answer = machine.advance(stage)
        assert answer["allowed"] is True, (stage, answer)
        assert answer["harness_stages"] == list(HARNESS_MAPPING[stage])
    assert machine.current == "reporting"


@chapter_claim(
    "handbook/course/03-stages-and-observations.md",
    "An unknown observation does not satisfy a requirement, and a measured "
    "mismatch is reported as its own reason.",
)
def test_unknown_and_mismatch_are_distinct_requirement_failures():
    observations = {
        "has_form": {"field": "has_form", "value": None, "state": "unknown",
                     "source": ""},
        "has_script": {"field": "has_script", "value": False,
                       "state": "measured", "source": "fixture:x"},
    }
    unknown_case = requirements_met({"has_form": True}, observations)
    assert unknown_case["allowed"] is False
    assert "unknown" in unknown_case["reason"]
    mismatch = requirements_met({"has_script": True}, observations)
    assert mismatch["allowed"] is False
    assert "measured False, requires True" in mismatch["reason"]
    missing = requirements_met({"has_cookie": True}, observations)
    assert missing["allowed"] is False
    assert "not observed" in missing["reason"]


@chapter_claim(
    "handbook/course/03-stages-and-observations.md",
    "Observation records carry a value, a state and a source, and an unknown "
    "value is honestly absent.",
)
def test_observation_records_carry_value_state_and_source():
    rows = observations_from_response("login", {"status": 200,
                                                "body": "<form>"})
    for row in rows:
        assert row["state"] == "measured"
        assert row["source"] == "fixture:login"
    absent = unknown("waf_vendor")
    assert absent["state"] == "unknown" and absent["value"] is None
