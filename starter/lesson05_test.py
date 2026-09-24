"""The lesson 5 learner-owned completion check. Fails until you build it."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starter._loader import load

MARKER = "X-Meta-Notes: fictional-metadata-v1"


def test_my_tool_becomes_an_eligible_candidate_and_a_clean_capture():
    table, results, snapshot = load("lesson05").run_my_plan()
    identities = [c.candidate_id for c in table["eligible"]]
    assert "inspect_metadata -> https://lab.example:443/about" in identities
    clean = [r for r in results if r["status"] == "clean"]
    assert clean, results
    assert all(MARKER in c["body"] for c in snapshot["captures"].values())
    # One identity, followed through: the metadata action has an outcome.
    assert snapshot["outcomes"][
        "inspect_metadata -> https://lab.example:443/about"]["status"] == "clean"


def test_the_door_still_refuses_outside_my_origins():
    module = load("lesson05")
    from core.run.dispatch import Dispatcher
    from core.run.recorder import Recorder
    from core.run.records import make_run
    policy = load("lesson02").build_my_policy()
    run = make_run(policy.snapshot(), {"world": "starter-refusal"})
    dispatcher = Dispatcher(Recorder(run, policy), policy,
                            {"inspect_metadata": module.metadata_adapter})
    refused = dispatcher.dispatch("inspect_metadata",
                                  "https://other.example/about")
    assert refused["status"] == "refused"
    assert "outside" in refused["reason"]
