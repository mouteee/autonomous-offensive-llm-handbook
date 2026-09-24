"""Lesson 5's runnable demo: candidates with reasons, a ranked plan, and a
ledger where every outcome status appears under its own name.

Run it from the repository root:

    python3 -m core.run.demo_dispatch --out /tmp/dispatch-demo.json

The committed copy is data/course/dispatch-demo.json. The policy declares a
tool nobody installed and a tool whose adapter is broken, on purpose: the
candidate table separates host-scope from destination-scope exclusions, the
plan runs into a clean result, an error, unavailability with a bounded
re-queue, and an explicit skip -- and a controller's attempt to run work the
policy does not permit is turned away at the door and recorded.
"""

import argparse
import json
from pathlib import Path

from ..controller import make_controller
from ..controller.contract import Candidate, State
from .candidates import build_candidates, rank
from .dispatch import Dispatcher
from .policy import Policy, Tool
from .recorder import Recorder
from .records import make_run


def build_policy():
    return Policy(
        reference="training-authorization-0002",
        origins=["https://lab.example/"],
        tools=[
            Tool(tool_id="inspect_headers", activity="passive",
                 family="fam-recon", weight=3.0, cost=1.0),
            Tool(tool_id="form_probe", activity="active",
                 requires={"has_form": True}, family="fam-inject",
                 weight=4.0, cost=2.0),
            Tool(tool_id="broken_scanner", activity="active",
                 family="fam-scan", weight=2.0, cost=1.0),
            Tool(tool_id="dns_survey", activity="passive",
                 family="fam-recon", weight=1.0, cost=1.0),
            Tool(tool_id="ancient_probe", activity="passive",
                 family="fam-recon", weight=1.0, cost=1.0),
        ],
        max_actions=6, max_model_calls=4)


SURFACES = [
    {"surface_id": "login", "url": "https://lab.example/login",
     "facts": {"has_form": True}},
    {"surface_id": "landing", "url": "https://lab.example/",
     "facts": {"has_form": False}},
]

ADAPTERS = {
    "inspect_headers": lambda url: {"status": 200,
                                    "body": f"headers for {url}\nServer: lab\n"},
    "form_probe": lambda url: {"status": 200,
                               "body": f"probe response for {url}\nLAB_OK\n"},
    "broken_scanner": lambda url: (_ for _ in ()).throw(RuntimeError("boom")),
    # dns_survey has no adapter at all: declared, but unavailable host-wide.
}


def run_demo():
    policy = build_policy()
    run = make_run(policy.snapshot(), {"world": "dispatch-lesson-fixtures"})
    recorder = Recorder(run, policy)
    dispatcher = Dispatcher(recorder, policy, ADAPTERS, unavailable_limit=2)

    table = build_candidates(policy=policy, surfaces=SURFACES,
                             unavailable_tools=["ancient_probe"],
                             coverage=[("form_probe", "https://lab.example/")])
    ranked = rank(table["eligible"])
    plan = [{"tool": c.features["tool"], "destination": c.features["destination"]}
            for c in ranked]
    # Exercise unavailability twice, plus a third appearance that the
    # re-queue bound turns away without dispatching.
    plan = plan + [{"tool": "dns_survey", "destination": "https://lab.example/"}] * 2

    ledger = dispatcher.run_plan(plan)
    ledger.append(dispatcher.skip("inspect_headers", "https://lab.example/health",
                                  "deliberately out of time"))

    # A controller cannot mint permission: hand it a crafted candidate whose
    # destination the policy does not authorize, and watch the door.
    controller = make_controller("priority")
    state = State(run_id=run.run_id, step=0, features={
        "bias": 1.0, "stage_progress": 0.5, "surface_known": 1.0,
        "recent_error_rate": 0.0, "budget_remaining": 0.5})
    crafted = Candidate(candidate_id="inspect_headers -> https://elsewhere.example:443/",
                        family="fam-recon",
                        features={"tool": "inspect_headers",
                                  "destination": "https://elsewhere.example/"},
                        priority=99.0)
    refused = dispatcher.select_and_run(controller, state, [crafted])

    return {
        "schema": "dispatch-demo/v1",
        "candidates": {
            "eligible": [{"action_id": c.candidate_id, "family": c.family,
                          "priority": c.priority, "cost": c.cost}
                         for c in table["eligible"]],
            "excluded": table["excluded"],
        },
        "ranked_plan": plan,
        "ledger": ledger,
        "controller_cannot_create_permission": refused,
        "report": recorder.snapshot(),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(run_demo(), indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
