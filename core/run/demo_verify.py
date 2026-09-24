"""Lesson 8's runnable demo: captures, verdicts of every kind, consolidation.

Run it from the repository root:

    python3 -m core.run.demo_verify --out /tmp/verify-demo.json

The committed copy is data/course/verify-demo.json. The scripted verifier is
deliberately imperfect: it accepts one finding, wrongly rejects a genuine one,
wrongly lowers another, sends one to review, raises one against contained
proof, and tries one raise the evidence grade refuses -- so the artifact shows
the host validating verdicts rather than trusting the verifier. Two
consolidation groups reproduce recorded signature collisions on purpose.
"""

import argparse
import json
from pathlib import Path

from .dispatch import Dispatcher
from .policy import Policy, Tool
from .recorder import Recorder
from .records import make_run
from .verify import VerificationPipeline, run_verifier


def build_policy():
    return Policy(
        reference="training-authorization-0003",
        origins=["https://lab.example/", "https://lab-two.example/",
                 "https://lab-three.example/"],
        tools=[
            Tool(tool_id="inspect_headers", activity="passive",
                 family="fam-recon", weight=3.0, cost=1.0),
            Tool(tool_id="tls_probe", activity="passive",
                 family="fam-recon", weight=2.0, cost=1.0),
        ],
        max_actions=12, max_model_calls=8)


BODIES = {
    ("inspect_headers", "https://lab.example/"):
        "HTTP/1.1 200 OK\nAccess-Control-Allow-Origin: *\n"
        "Content-Security-Policy: default-src * 'unsafe-inline'\n"
        "X-Lab-Marker: LAB_CONFIRMED\nUnauthenticated GET returns 3389-byte response body",
    ("inspect_headers", "https://lab-two.example/"):
        "HTTP/1.1 200 OK\nAccess-Control-Allow-Origin: *\n"
        "Unauthenticated GET returns 1602-byte response body",
    ("inspect_headers", "https://lab-three.example/"):
        "HTTP/1.1 200 OK\nAccess-Control-Allow-Origin: *\n"
        "Unauthenticated GET returns 2048-byte response body",
    ("tls_probe", "https://lab-three.example/"):
        "handshake ok\nprotocol: TLS 1.3 supported",
    ("tls_probe", "https://lab.example/"):
        "handshake ok\nprotocol: TLS 1.0 supported",
    ("tls_probe", "https://lab-two.example/"):
        "handshake ok\nprotocol: TLS 1.2 supported",
}


def scripted_verifier(replies):
    def provider(packet):
        return json.dumps(replies[packet["finding"]["title"]])
    return provider


def run_demo():
    policy = build_policy()
    run = make_run(policy.snapshot(), {"world": "verify-lesson"})
    recorder = Recorder(run, policy)
    dispatcher = Dispatcher(recorder, policy,
                            {tool: (lambda url, t=tool: {
                                "status": 200, "body": BODIES[(t, url)]})
                             for tool in ("inspect_headers", "tls_probe")})
    captures = {}
    for tool in ("inspect_headers", "tls_probe"):
        for destination in ("https://lab.example/", "https://lab-two.example/",
                            "https://lab-three.example/"):
            result = dispatcher.dispatch(tool, destination)
            captures[(tool, destination)] = result["capture_id"]

    def finding(tool, destination, kind, title, severity, quote):
        recorded = recorder.record("finding", {
            "run_id": run.run_id, "capture_id": captures[(tool, destination)],
            "kind": kind, "title": title, "severity": severity, "quote": quote})
        return recorded["finding_id"]

    ids = {
        "cors_a": finding("inspect_headers", "https://lab.example/",
                          "unauth_data_leak",
                          "Unauthenticated GET returns 3389-byte response",
                          "high", "Access-Control-Allow-Origin: *"),
        "cors_b": finding("inspect_headers", "https://lab-two.example/",
                          "unauth_data_leak",
                          "Unauthenticated GET returns 1602-byte response",
                          "medium", "Access-Control-Allow-Origin: *"),
        "cors_c": finding("inspect_headers", "https://lab-three.example/",
                          "unauth_data_leak",
                          "Unauthenticated GET returns 2048-byte response",
                          "medium", "Access-Control-Allow-Origin: *"),
        "csp": finding("inspect_headers", "https://lab.example/",
                       "csp_weakness",
                       "Content Security Policy allows unsafe-inline",
                       "high", "'unsafe-inline'"),
        "tls_a": finding("tls_probe", "https://lab.example/", "weak_tls",
                         "TLS 1.0 supported", "medium", "TLS 1.0 supported"),
        "tls_b": finding("tls_probe", "https://lab-two.example/", "weak_tls",
                         "TLS 1.2 supported", "low", "TLS 1.2 supported"),
        "marker": finding("inspect_headers", "https://lab.example/",
                          "lab_marker", "Synthetic lab marker present",
                          "medium", "X-Lab-Marker: LAB_CONFIRMED"),
    }

    pipeline = VerificationPipeline(recorder)
    snapshot = recorder.snapshot()
    request_evidence = {"method": "GET", "note": "request side recorded"}
    for name, finding_id in ids.items():
        record = next(f for f in snapshot["findings"]
                      if f["finding_id"] == finding_id)
        from .records import Finding
        pipeline.govern(Finding(**record),
                        request=request_evidence if name != "tls_b" else None)

    replies = {
        "Unauthenticated GET returns 3389-byte response":
            {"verdict": "accept", "reason": "wildcard origin confirmed in capture"},
        "Unauthenticated GET returns 1602-byte response":
            {"verdict": "reject",
             "reason": "verifier saw no impact (a wrong call: the capture "
                       "shows the same wildcard)"},
        "TLS 1.0 supported":
            {"verdict": "adjust_severity", "severity": "low",
             "reason": "verifier judged legacy TLS minor here (a wrong "
                       "downward call the record keeps visible)"},
        "TLS 1.2 supported":
            {"verdict": "adjust_severity", "severity": "critical",
             "quote": "TLS 1.2 supported",
             "reason": "attempted raise past what a moderate grade may reach"},
        "Unauthenticated GET returns 2048-byte response":
            {"verdict": "accept", "reason": "same wildcard origin, third host"},
        "Content Security Policy allows unsafe-inline":
            {"verdict": "needs_review",
             "reason": "policy weakness, not a demonstrated path; the "
                       "skeptical default caps an unverified high at medium"},
        "Synthetic lab marker present":
            {"verdict": "adjust_severity", "severity": "high",
             "quote": "X-Lab-Marker: LAB_CONFIRMED",
             "reason": "marker quoted verbatim; raise within the strong-grade "
                       "ceiling"},
    }
    provider = scripted_verifier(replies)
    verdicts = []
    for name, finding_id in ids.items():
        row = pipeline.governed(finding_id)
        record = next(f for f in snapshot["findings"]
                      if f["finding_id"] == finding_id)
        from .records import Finding
        answer = run_verifier(provider, Finding(**record),
                              recorder.capture(record["capture_id"]))
        verdicts.append({"finding": name,
                         "grade": row["evidence_grade"],
                         "packet_capture": record["capture_id"][:12],
                         "result": pipeline.apply_verdict(finding_id, answer)})

    refusals = {
        "unknown_verdict": pipeline.apply_verdict(
            ids["cors_a"], {"parsed": True, "reply": {
                "verdict": "CONFIRMED", "reason": "sounds authoritative"}}),
        "fabricated_quote_raise": pipeline.apply_verdict(
            ids["marker"], {"parsed": True, "reply": {
                "verdict": "adjust_severity", "severity": "critical",
                "quote": "ADMIN_TOKEN=deadbeef",
                "reason": "quote not in the capture"}}),
    }

    consolidation = pipeline.consolidate()

    review = recorder.record("review", {
        "run_id": run.run_id, "finding_id": ids["cors_a"],
        "decision": "accepted", "reason": "verified and consolidated; "
        "primary for the wildcard-origin class", "actor": "human reviewer"})

    return {
        "schema": "verify-demo/v1",
        "verdicts": verdicts,
        "host_refusals": refusals,
        "consolidation": consolidation,
        "pipeline": pipeline.snapshot(),
        "human_review": review,
        "run_report": recorder.snapshot(),
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
