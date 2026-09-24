"""The lesson 4 learner-owned completion check. Fails until you build it."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starter._loader import load

OBSERVATIONS = {
    "about_status": {"field": "about_status", "value": 200,
                     "state": "measured", "source": "fixture:about"},
    "about_has_meta": {"field": "about_has_meta", "value": True,
                       "state": "measured", "source": "fixture:about"},
}
CONTEXT = {"instruction": "Propose one hypothesis over the observations.",
           "observations": OBSERVATIONS}


def test_my_provider_is_admitted_under_my_policy():
    from core.run.proposals import ProviderSession
    policy = load("lesson02").build_my_policy()
    provider = load("lesson04").my_provider
    report = ProviderSession(provider).propose(
        CONTEXT, observations=OBSERVATIONS, policy=policy)
    assert report["admitted"] is True, report
    assert report["action_id"] == \
        "inspect_metadata -> https://lab.example:443/about"
    assert report["usage"]["calls"] == 1


def test_my_proposal_binds_to_recorded_observations():
    import json
    proposal = json.loads(load("lesson04").my_provider(CONTEXT))
    assert proposal["surface"] in OBSERVATIONS
    assert proposal["evidence"]
    assert all(ref in OBSERVATIONS for ref in proposal["evidence"])
