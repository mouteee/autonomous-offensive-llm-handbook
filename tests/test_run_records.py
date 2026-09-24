"""The record vocabulary and the write boundary, held at their refusals."""

import pytest

from core.run.demo_records import build_policy
from core.run.records import (RecordError, action_identity, make_action,
                              make_capture, make_run)
from core.run.recorder import Recorder


def chapter_claim(chapter, *sentences):
    """Anchor a test to the verbatim lesson sentence(s) it backs.

    Same declaration shape as tests/test_chapter_claims.py: verify_claims.sh's
    Check C parses these decorators and goes red when a declared sentence is
    no longer present in its chapter.
    """
    def deco(fn):
        return fn
    return deco



def fresh():
    policy = build_policy()
    run = make_run(policy.snapshot(), {"world": "test"})
    return policy, run, Recorder(run, policy)


def admitted_capture(recorder, run):
    action = recorder.record("action", {
        "run_id": run.run_id, "tool": "inspect_headers",
        "destination": "https://lab.example/login", "arguments": {}})
    return recorder.record("capture", {
        "run_id": run.run_id, "action_id": action["action_id"],
        "status": 200, "body": "Access-Control-Allow-Origin: *\n"})


@chapter_claim(
    "handbook/course/02-policy-and-records.md",
    "The action identity is one normalized string carrying the tool and the "
    "canonical destination.",
)
def test_action_identity_is_one_normalized_string():
    assert action_identity("probe", "https://lab.example:443/x") == \
        "probe -> https://lab.example:443/x"
    with pytest.raises(RecordError):
        action_identity("probe", "")
    with pytest.raises(RecordError):
        make_action("r", "probe", " ")


@chapter_claim(
    "handbook/course/02-policy-and-records.md",
    "A capture is content-addressed: its identity is a digest of its own bytes "
    "bound to its run.",
)
def test_a_capture_is_content_addressed():
    a = make_capture("run-a", "probe -> x", 200, "body")
    b = make_capture("run-a", "probe -> x", 200, "body")
    c = make_capture("run-a", "probe -> x", 200, "body2")
    assert a.capture_id == b.capture_id
    assert a.capture_id != c.capture_id
    d = make_capture("run-b", "probe -> x", 200, "body")
    assert a.capture_id != d.capture_id


@chapter_claim(
    "handbook/course/02-policy-and-records.md",
    "An undeclared tool and an unauthorized destination each produce a refusal "
    "event naming the reason.",
    "A rejected operation leaves no adapter side effect and carries a recorded "
    "reason in the same ledger as the work that was admitted.",
)
def test_undeclared_tool_and_unauthorized_destination_are_refused():
    _, run, recorder = fresh()
    for payload, needle in (
        ({"tool": "shell", "destination": "https://lab.example/"},
         "not declared"),
        ({"tool": "inspect_headers", "destination": "https://other.example/"},
         "outside the explicit authorized origins"),
    ):
        answer = recorder.record("action", {"run_id": run.run_id,
                                            "arguments": {}, **payload})
        assert answer["recorded"] is False
        assert needle in answer["reason"]
    report = recorder.snapshot()
    refusals = [e for e in report["events"] if e["event"] == "refused"]
    assert len(refusals) == 2
    assert report["outcomes"] == {} and report["captures"] == {}


@chapter_claim(
    "handbook/course/02-policy-and-records.md",
    "An operation naming another run's identity is turned away before any "
    "store changes.",
)
def test_a_mismatched_run_id_is_turned_away():
    _, run, recorder = fresh()
    answer = recorder.record("capture", {
        "run_id": "someone-else", "action_id": "probe -> x", "status": 200,
        "body": "hello"})
    assert answer["recorded"] is False
    assert "does not belong to this run" in answer["reason"]
    assert recorder.snapshot()["captures"] == {}


@chapter_claim(
    "handbook/course/02-policy-and-records.md",
    "A malformed payload is recorded as a refusal rather than raising out of "
    "the boundary.",
)
def test_a_malformed_payload_is_a_recorded_refusal():
    _, run, recorder = fresh()
    answer = recorder.record("outcome", {"run_id": run.run_id})
    assert answer["recorded"] is False
    assert "malformed payload" in answer["reason"]
    assert recorder.snapshot()["events"][-1]["event"] == "refused"


@chapter_claim(
    "handbook/course/02-policy-and-records.md",
    "A finding whose quote does not occur verbatim in its cited capture is "
    "turned away at the write boundary.",
)
def test_a_fabricated_quote_is_turned_away():
    _, run, recorder = fresh()
    capture = admitted_capture(recorder, run)
    answer = recorder.record("finding", {
        "run_id": run.run_id, "capture_id": capture["capture_id"],
        "kind": "header", "title": "Fabricated", "severity": "critical",
        "quote": "root password: hunter2"})
    assert answer["recorded"] is False
    assert "verbatim" in answer["reason"]
    good = recorder.record("finding", {
        "run_id": run.run_id, "capture_id": capture["capture_id"],
        "kind": "header", "title": "Wildcard header", "severity": "medium",
        "quote": "Access-Control-Allow-Origin: *"})
    assert good["recorded"] is True


@chapter_claim(
    "handbook/course/02-policy-and-records.md",
    "A finding cites a capture the run actually holds.",
)
def test_a_finding_citing_a_foreign_capture_is_turned_away():
    _, run, recorder = fresh()
    answer = recorder.record("finding", {
        "run_id": run.run_id, "capture_id": "no-such-digest", "kind": "header",
        "title": "Foreign evidence", "severity": "low", "quote": "anything"})
    assert answer["recorded"] is False
    assert "does not hold" in answer["reason"]


@chapter_claim(
    "handbook/course/02-policy-and-records.md",
    "A second terminal outcome for the same action is turned away.",
)
def test_a_second_terminal_outcome_is_turned_away():
    _, run, recorder = fresh()
    capture = admitted_capture(recorder, run)
    action_id = recorder.snapshot()["captures"][capture["capture_id"]]["action_id"]
    first = recorder.record("outcome", {"run_id": run.run_id,
                                        "action_id": action_id,
                                        "status": "clean", "detail": ""})
    assert first["recorded"] is True
    second = recorder.record("outcome", {"run_id": run.run_id,
                                         "action_id": action_id,
                                         "status": "skipped", "detail": ""})
    assert second["recorded"] is False
    assert "already recorded" in second["reason"]


@chapter_claim(
    "handbook/course/02-policy-and-records.md",
    "An unresolved outcome may later be settled, and a settled one may not.",
)
def test_only_an_unresolved_outcome_can_be_settled_later():
    _, run, recorder = fresh()
    action = recorder.record("action", {
        "run_id": run.run_id, "tool": "inspect_headers",
        "destination": "https://lab.example/", "arguments": {}})
    recorder.record("outcome", {"run_id": run.run_id,
                                "action_id": action["action_id"],
                                "status": "unresolved",
                                "detail": "interrupted before recording"})
    settled = recorder.record("outcome", {"run_id": run.run_id,
                                          "action_id": action["action_id"],
                                          "status": "skipped",
                                          "detail": "reconciled as not run"})
    assert settled["recorded"] is True
