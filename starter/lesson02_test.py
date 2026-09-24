"""The lesson 2 learner-owned completion check. Fails until you build it."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starter._loader import load


def test_my_policy_declares_the_metadata_tool():
    policy = load("lesson02").build_my_policy()
    decision = policy.knows_tool("inspect_metadata")
    assert decision["allowed"], decision["reason"]
    tool = policy.tools["inspect_metadata"]
    assert tool.activity == "passive"
    assert tool.requires == {"has_meta": True}
    assert tool.family == "fam-meta"


def test_my_policy_still_refuses_what_it_never_granted():
    policy = load("lesson02").build_my_policy()
    outside = policy.allows_action("inspect_metadata",
                                   "https://other.example/about", {})
    assert not outside["allowed"]
    assert "outside" in outside["reason"]
    unknown = policy.knows_tool("shell")
    assert not unknown["allowed"]
    inside = policy.allows_action("inspect_metadata",
                                  "https://lab.example/about", {})
    assert inside["allowed"], inside["reason"]
