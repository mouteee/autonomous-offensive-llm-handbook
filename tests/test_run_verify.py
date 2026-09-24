"""The verification pipeline, held at the host's validation points."""

import json

from core.run.demo_verify import build_policy, BODIES
from core.run.dispatch import Dispatcher
from core.run.recorder import Recorder
from core.run.records import Finding, make_run
from core.run.verify import (
    RAISE_CEILING, VerificationPipeline, apply_ceiling, evidence_grade,
    run_verifier, verifier_packet)


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
    run = make_run(policy.snapshot(), {"world": "verify-tests"})
    recorder = Recorder(run, policy)
    dispatcher = Dispatcher(recorder, policy,
                            {tool: (lambda url, t=tool: {
                                "status": 200, "body": BODIES[(t, url)]})
                             for tool in ("inspect_headers", "tls_probe")})
    return run, recorder, dispatcher


def governed_finding(recorder, dispatcher, *, severity="high",
                     destination="https://lab.example/",
                     quote="Access-Control-Allow-Origin: *", request=None):
    capture_id = dispatcher.dispatch("inspect_headers", destination)["capture_id"]
    recorded = recorder.record("finding", {
        "run_id": recorder.run.run_id, "capture_id": capture_id,
        "kind": "unauth_data_leak", "title": "Wildcard origin",
        "severity": severity, "quote": quote})
    finding = Finding(**next(f for f in recorder.snapshot()["findings"]
                             if f["finding_id"] == recorded["finding_id"]))
    pipeline = VerificationPipeline(recorder)
    pipeline.govern(finding, request=request)
    return pipeline, finding


@chapter_claim(
    "handbook/course/08-evidence-and-verification.md",
    "a finding cites a capture this run holds, and its quote occurs verbatim "
    "in that capture, or it is refused with a recorded reason",
)
def test_a_fabricated_quote_or_foreign_capture_cannot_become_a_finding():
    run, recorder, dispatcher = fresh()
    capture_id = dispatcher.dispatch(
        "inspect_headers", "https://lab.example/")["capture_id"]
    fabricated = recorder.record("finding", {
        "run_id": run.run_id, "capture_id": capture_id,
        "kind": "unauth_data_leak", "title": "Invented", "severity": "high",
        "quote": "ADMIN_TOKEN=deadbeef"})
    assert fabricated["recorded"] is False
    foreign = recorder.record("finding", {
        "run_id": run.run_id, "capture_id": "not-a-capture-this-run-holds",
        "kind": "unauth_data_leak", "title": "Foreign", "severity": "high",
        "quote": "Access-Control-Allow-Origin: *"})
    assert foreign["recorded"] is False
    refusals = [e for e in recorder.snapshot()["events"]
                if e["event"] == "refused"]
    assert len(refusals) >= 2


@chapter_claim(
    "handbook/course/08-evidence-and-verification.md",
    "The verifier sees exactly one finding and its own capture, and nothing else.",
)
def test_the_verifier_packet_is_isolated_to_the_findings_own_capture():
    run, recorder, dispatcher = fresh()
    pipeline, finding = governed_finding(recorder, dispatcher)
    other_capture_id = dispatcher.dispatch(
        "tls_probe", "https://lab.example/")["capture_id"]
    packet = verifier_packet(finding, recorder.capture(finding.capture_id))
    text = json.dumps(packet)
    assert finding.capture_id in text
    assert other_capture_id not in text
    assert "TLS 1.0" not in text
    try:
        verifier_packet(finding, recorder.capture(other_capture_id))
        raised = False
    except ValueError:
        raised = True
    assert raised


@chapter_claim(
    "handbook/course/08-evidence-and-verification.md",
    "An unknown verdict changes nothing",
    "the originating implementation read any unrecognized verdict string as a "
    "confirmation",
)
def test_an_unknown_verdict_is_refused_not_read_as_confirmation():
    run, recorder, dispatcher = fresh()
    pipeline, finding = governed_finding(recorder, dispatcher)
    before = pipeline.governed(finding.finding_id)
    result = pipeline.apply_verdict(finding.finding_id, {
        "parsed": True, "reply": {"verdict": "CONFIRMED", "reason": "sure"}})
    assert result["applied"] is False
    assert "unknown verdict" in result["reason"]
    after = pipeline.governed(finding.finding_id)
    assert after["severity"] == before["severity"]
    assert after["false_positive"] is False


@chapter_claim(
    "handbook/course/08-evidence-and-verification.md",
    "A rejected finding stays visible with its evidence, so a human can "
    "overrule a wrong rejection.",
)
def test_a_false_rejection_is_kept_visible_not_deleted():
    run, recorder, dispatcher = fresh()
    pipeline, finding = governed_finding(recorder, dispatcher)
    result = pipeline.apply_verdict(finding.finding_id, {
        "parsed": True, "reply": {"verdict": "reject",
                                  "reason": "verifier saw no impact"}})
    assert result["applied"] is True
    row = pipeline.governed(finding.finding_id)
    assert row["false_positive"] is True
    assert row["status"] == "rejected"
    assert row["quote"] == finding.quote
    assert recorder.capture(row["capture_id"]) is not None


@chapter_claim(
    "handbook/course/08-evidence-and-verification.md",
    "a wrong downward adjustment applies freely and stays visible in the "
    "record, before beside after",
)
def test_a_wrong_downward_adjustment_applies_and_is_recorded():
    run, recorder, dispatcher = fresh()
    pipeline, finding = governed_finding(recorder, dispatcher)
    result = pipeline.apply_verdict(finding.finding_id, {
        "parsed": True, "reply": {"verdict": "adjust_severity",
                                  "severity": "low",
                                  "reason": "verifier misjudged impact"}})
    assert result["applied"] is True
    assert (result["before"], result["after"]) == ("high", "low")
    row = pipeline.governed(finding.finding_id)
    assert row["severity"] == "low"
    assert row["verdicts"][-1]["before"] == "high"


@chapter_claim(
    "handbook/course/08-evidence-and-verification.md",
    "A raise happens only against contained proof and within what the "
    "evidence grade allows",
)
def test_raises_need_contained_proof_and_a_grade_that_reaches_the_target():
    run, recorder, dispatcher = fresh()
    pipeline, finding = governed_finding(
        recorder, dispatcher, severity="medium",
        request={"method": "GET"})
    fabricated = pipeline.apply_verdict(finding.finding_id, {
        "parsed": True, "reply": {"verdict": "adjust_severity",
                                  "severity": "high",
                                  "quote": "NOT IN THE CAPTURE",
                                  "reason": "invented proof"}})
    assert fabricated["applied"] is False
    assert "verbatim" in fabricated["reason"]
    proven = pipeline.apply_verdict(finding.finding_id, {
        "parsed": True, "reply": {"verdict": "adjust_severity",
                                  "severity": "high",
                                  "quote": "Access-Control-Allow-Origin: *",
                                  "reason": "wildcard quoted from the capture"}})
    assert proven["applied"] is True
    assert proven.get("raised_against_proof") is True

    pipeline2, moderate = governed_finding(recorder, dispatcher,
                                           severity="low", request=None,
                                           destination="https://lab-two.example/")
    assert pipeline2.governed(moderate.finding_id)["evidence_grade"] == "moderate"
    past_grade = pipeline2.apply_verdict(moderate.finding_id, {
        "parsed": True, "reply": {"verdict": "adjust_severity",
                                  "severity": "critical",
                                  "quote": "Access-Control-Allow-Origin: *",
                                  "reason": "raise past the moderate ceiling"}})
    assert past_grade["applied"] is False
    assert RAISE_CEILING["moderate"] in past_grade["reason"]


@chapter_claim(
    "handbook/course/08-evidence-and-verification.md",
    "The deterministic policy layer never raises",
)
def test_the_policy_layer_only_moves_severity_downward():
    for grade in ("strong", "moderate", "thin"):
        for severity in ("info", "low", "medium", "high", "critical"):
            capped = apply_ceiling(severity, grade)
            order = ("info", "low", "medium", "high", "critical")
            assert order.index(capped) <= order.index(severity)


@chapter_claim(
    "handbook/course/08-evidence-and-verification.md",
    "Two findings that differ only in their digits share a signature",
    "an absorbed finding keeps its evidence and gets its own status",
    "Findings with no resolvable host never group.",
)
def test_consolidation_collides_on_digits_and_absorbs_without_the_fp_flag():
    run, recorder, dispatcher = fresh()
    pipeline = VerificationPipeline(recorder)
    for destination, title in (
            ("https://lab.example/", "Returns 3389-byte response"),
            ("https://lab-two.example/", "Returns 1602-byte response")):
        capture_id = dispatcher.dispatch("inspect_headers", destination)["capture_id"]
        recorded = recorder.record("finding", {
            "run_id": run.run_id, "capture_id": capture_id,
            "kind": "unauth_data_leak", "title": title, "severity": "medium",
            "quote": "Access-Control-Allow-Origin: *"})
        finding = Finding(**next(f for f in recorder.snapshot()["findings"]
                                 if f["finding_id"] == recorded["finding_id"]))
        pipeline.govern(finding)
    groups = pipeline.consolidate()
    assert len(groups) == 1
    assert len(groups[0]["affected_hosts"]) == 2
    absorbed = pipeline.governed(groups[0]["absorbed_ids"][0])
    assert absorbed["status"] == "absorbed"
    assert absorbed["false_positive"] is False
    assert absorbed["quote"]
    # The same signature on ONE host does not group, and a hostless finding
    # never joins: the signature check needs two distinct resolvable hosts.
    assert pipeline._host_of(absorbed) is not None


@chapter_claim(
    "handbook/course/08-evidence-and-verification.md",
    "Acceptance is a separate human decision; no verdict flips a finding to "
    "accepted.",
)
def test_acceptance_is_a_recorded_human_decision_not_a_verdict_effect():
    run, recorder, dispatcher = fresh()
    pipeline, finding = governed_finding(recorder, dispatcher)
    pipeline.apply_verdict(finding.finding_id, {
        "parsed": True, "reply": {"verdict": "accept",
                                  "reason": "verified against the capture"}})
    assert pipeline.governed(finding.finding_id)["status"] == "governed"
    review = recorder.record("review", {
        "run_id": run.run_id, "finding_id": finding.finding_id,
        "decision": "accepted", "reason": "human reviewed", "actor": "reviewer"})
    assert review["recorded"] is True
    assert recorder.snapshot()["reviews"][-1]["actor"] == "reviewer"


@chapter_claim(
    "handbook/course/08-evidence-and-verification.md",
    "a verdict that cannot be parsed changes nothing either",
)
def test_a_malformed_verifier_reply_is_refused():
    run, recorder, dispatcher = fresh()
    pipeline, finding = governed_finding(recorder, dispatcher)
    answer = run_verifier(lambda packet: "not json at all",
                          finding, recorder.capture(finding.capture_id))
    assert answer["parsed"] is False
    result = pipeline.apply_verdict(finding.finding_id, answer)
    assert result["applied"] is False
    assert pipeline.governed(finding.finding_id)["severity"] == "high"


@chapter_claim(
    "handbook/course/08-evidence-and-verification.md",
    "the grade measures record completeness, not truth",
)
def test_evidence_grades_follow_record_completeness():
    assert evidence_grade(request={"method": "GET"},
                          response_body="a body") == "strong"
    assert evidence_grade(request=None, response_body="a body") == "moderate"
    assert evidence_grade(request={"method": "GET"},
                          response_body="") == "moderate"
    assert evidence_grade(string_evidence="x" * 40) == "moderate"
    assert evidence_grade(string_evidence="short") == "thin"
