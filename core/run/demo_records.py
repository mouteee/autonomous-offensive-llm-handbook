"""Lesson 2's runnable demo: one admitted chain and four recorded refusals.

Run it from the repository root:

    python3 -m core.run.demo_records --out /tmp/records-demo.json

The committed copy is data/course/records-demo.json, held byte-identical by a
sync test. Everything is authored and deterministic; the interesting part of
the output is the refusal events, each carrying its reason, next to the
admitted chain from action to review.
"""

import argparse
import json
from pathlib import Path

from .policy import Policy, Tool
from .recorder import Recorder
from .records import make_run


def build_policy():
    return Policy(
        reference="training-authorization-0001",
        origins=["https://lab.example/"],
        tools=[
            Tool(tool_id="inspect_headers", activity="passive",
                 family="fam-recon", weight=2.0, cost=1.0),
            Tool(tool_id="form_probe", activity="active",
                 requires={"has_form": True}, family="fam-inject",
                 weight=3.0, cost=2.0),
        ],
        max_actions=4, max_model_calls=4)


def run_demo():
    policy = build_policy()
    run = make_run(policy.snapshot(), {"world": "records-lesson-fixtures"})
    recorder = Recorder(run, policy)
    r = run.run_id

    admitted = []
    admitted.append(recorder.record("observation", {
        "run_id": r, "field": "has_form", "value": True, "state": "measured",
        "source": "fixture:login"}))
    action = recorder.record("action", {
        "run_id": r, "tool": "inspect_headers",
        "destination": "https://lab.example/login", "arguments": {}})
    admitted.append(action)
    capture = recorder.record("capture", {
        "run_id": r, "action_id": action["action_id"], "status": 200,
        "body": "HTTP/1.1 200 OK\nAccess-Control-Allow-Origin: *\n"})
    admitted.append(capture)
    admitted.append(recorder.record("outcome", {
        "run_id": r, "action_id": action["action_id"], "status": "clean",
        "detail": capture["capture_id"]}))
    finding = recorder.record("finding", {
        "run_id": r, "capture_id": capture["capture_id"], "kind": "header",
        "title": "Wildcard cross-origin header",
        "severity": "medium", "quote": "Access-Control-Allow-Origin: *"})
    admitted.append(finding)
    admitted.append(recorder.record("review", {
        "run_id": r, "finding_id": finding["finding_id"],
        "decision": "needs_review", "reason": "awaiting human acceptance",
        "actor": "human_review_required"}))

    refused = [
        recorder.record("action", {
            "run_id": r, "tool": "inspect_headers",
            "destination": "https://other.example/", "arguments": {}}),
        recorder.record("action", {
            "run_id": r, "tool": "shell",
            "destination": "https://lab.example/", "arguments": {}}),
        recorder.record("capture", {
            "run_id": "some-other-run", "action_id": action["action_id"],
            "status": 200, "body": "irrelevant"}),
        recorder.record("finding", {
            "run_id": r, "capture_id": capture["capture_id"], "kind": "header",
            "title": "Fabricated quotation", "severity": "critical",
            "quote": "root password: hunter2"}),
        recorder.record("outcome", {
            "run_id": r, "action_id": action["action_id"]}),
    ]

    return {
        "schema": "records-demo/v1",
        "admitted": admitted,
        "refused": refused,
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
