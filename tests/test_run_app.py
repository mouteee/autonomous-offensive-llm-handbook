"""The assembled application, held to lesson 16's three invariances.

The application is composition, so these tests hold the joints: configuration
refusals, the provider/controller swap invariances, learning off on the
ordinary path, and the resumed run finishing with the same accounting.
"""

import pytest

from core.run.app import Application, AppConfigError, validate_config
from core.run.demo_app import (
    PROPOSAL_ADMITTED, PROPOSAL_REFUSED, WORLD, build_config, demo_verifier,
    run_demo)
from core.run.proposals import FakeProvider


def chapter_claim(chapter, *sentences):
    """Anchor a test to the verbatim lesson sentence(s) it backs.

    Same declaration shape as tests/test_chapter_claims.py: verify_claims.sh's
    Check C parses these decorators and fails when a declared sentence is no
    longer present in its chapter.
    """
    def deco(fn):
        return fn
    return deco


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "The documented clean-install path exercises the complete lifecycle.",
)
def test_the_documented_clean_install_path_exercises_the_complete_lifecycle():
    demo = run_demo()
    report = demo["complete_run"]
    assert report["finish"]["completed"] is True
    stages = [e["stage"] for e in report["finish"]["report"]["run_report"]["events"]
              if e["event"] == "stage"]
    assert stages == ["discovery", "detection", "crawling", "mining",
                      "scanning", "active_testing", "reporting"]
    admitted = [p for p in report["proposals"] if p["admitted"]]
    refused = [p for p in report["proposals"] if not p["admitted"]]
    assert admitted and refused
    assert report["verification"]["verdict_ledger"]
    assert report["consolidation"], "the demo world must produce a cross-host group"


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "Changing the provider changes proposals, and changes no permission",
)
def test_changing_the_provider_changes_proposals_but_not_permissions():
    reports = {}
    for label, replies in (("compliant", [PROPOSAL_ADMITTED, PROPOSAL_ADMITTED]),
                           ("hostile", [PROPOSAL_REFUSED, PROPOSAL_REFUSED])):
        app = Application(build_config(provider=FakeProvider(replies)))
        reports[label] = app.run(WORLD)
    a, b = reports["compliant"], reports["hostile"]
    assert a["config"]["policy_digest"] == b["config"]["policy_digest"]
    assert a["candidate_table"] == b["candidate_table"]
    assert all(p["admitted"] for p in a["proposals"])
    assert all(p["status"] == "refused_by_policy" for p in b["proposals"])
    hostile_events = b["finish"]["report"]["run_report"]["events"]
    assert any(e["event"] == "refused" and e["kind"] == "proposal"
               for e in hostile_events)
    # The hostile provider's target never became an action, a capture or an
    # outcome: the report carries its refusal and nothing else about it.
    assert not any("outside.example" in str(e)
                   for e in hostile_events if e["event"] != "refused")


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "Changing the controller changes the order of work, and changes neither "
    "the eligibility table nor the feedback definition",
)
def test_changing_the_controller_changes_order_never_eligibility_or_feedback():
    demo = run_demo()
    swap = demo["controller_swap"]
    assert swap["priority"]["eligible"] == swap["legacy"]["eligible"]
    assert swap["priority"]["execution_order"] != swap["legacy"]["execution_order"]
    assert swap["priority"]["feedback_weights"] == \
        swap["legacy"]["feedback_weights"] == ["feedback-v1"]


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "The ordinary configuration runs the complete lifecycle with learning off "
    "everywhere",
)
def test_the_ordinary_path_runs_with_learning_off_everywhere():
    app = Application(build_config())
    report = app.run(WORLD)
    assert report["config"]["controller"]["learn"] is False
    assert report["decisions"]
    assert all(d["feedback"]["learning"]["applied"] is False
               for d in report["decisions"])
    assert report["finish"]["completed"] is True


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "An unknown configuration key is refused with a named reason",
)
def test_an_unknown_configuration_key_is_refused():
    config = build_config()
    config["telemetry"] = True
    with pytest.raises(AppConfigError) as caught:
        validate_config(config)
    assert "telemetry" in str(caught.value)


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "turning learning on takes the controller key and the separate research "
    "flag together",
)
def test_learning_requires_the_separate_research_flag():
    config = build_config()
    config["controller"] = {"name": "linucb", "seed": 0, "learn": True}
    with pytest.raises(AppConfigError) as caught:
        validate_config(config)
    assert "research" in str(caught.value)
    config["research"] = True
    normalized = validate_config(config)
    assert normalized["controller"]["learn"] is True


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "A provider cannot widen scope mid-run.",
)
def test_a_provider_proposal_cannot_widen_scope_mid_run():
    app = Application(build_config(
        provider=FakeProvider([PROPOSAL_REFUSED, PROPOSAL_REFUSED])))
    report = app.run(WORLD)
    assert all(p["status"] == "refused_by_policy" for p in report["proposals"])
    outcomes = report["finish"]["report"]["run_report"]["outcomes"]
    assert not any("outside.example" in action_id for action_id in outcomes)


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "A resumed run finishes with the same accounting as an uninterrupted one",
)
def test_a_resumed_run_finishes_with_the_same_accounting():
    interrupted = run_demo()["interrupted_and_resumed"]
    assert interrupted["finish"] is True
    settled = {row["action_id"]: row["settled"]
               for row in interrupted["reconciliation"]}
    assert "clean" in settled.values()
    assert "unresolved" in settled.values()
    assert interrupted["coverage"]["unresolved"] == [
        action_id for action_id, how in sorted(settled.items())
        if how == "unresolved"]


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "the configuration accepts only callable adapters",
)
def test_a_non_callable_adapter_is_refused():
    config = build_config()
    config["adapters"] = {"inspect_headers": "https://a-live-transport.example"}
    with pytest.raises(AppConfigError) as caught:
        validate_config(config)
    assert "callable" in str(caught.value)


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "verifier is a callable the host validates, never a trusted writer",
)
def test_the_configured_verifier_cannot_write_outside_its_verdict():
    app = Application(build_config(verifier=demo_verifier))
    report = app.run(WORLD)
    rejected = [row for row in report["verification"]["governed"].values()
                if row["status"] == "rejected"]
    assert rejected, "the demo verifier rejects the form finding"
    # The rejection kept the finding and its evidence visible.
    assert all(row["quote"] and row["capture_id"] for row in rejected)
