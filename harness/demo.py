"""Run the synthetic tutorial and serialize its report."""

import argparse
import copy
import json
import re
from pathlib import Path

from .runtime import Harness, PolicyError, canonical_bytes


def inputs():
    root = Path(__file__).parent
    manifest = json.loads((root / "port.json").read_text())
    fixtures = json.loads((root / "fixtures.json").read_text())
    return manifest, fixtures


def observations(fixtures):
    responses = [fixtures[name] for name in ("headers", "marker")]
    bodies = [response["body"] for response in responses]
    signals = {"waf_detected": any("WAF_BLOCKED" in body for body in bodies),
               "total_responses": len(responses),
               "error_rate": sum(response["status"] >= 400 for response in responses) / len(responses),
               "parameters_found": sum(len(re.findall(r'name="[^"]+"', body)) for body in bodies),
               "forms_found": sum(len(re.findall(r"<form\b", body)) for body in bodies),
               "pages_crawled": sum(response["status"] < 400 for response in responses),
               "scripts_found": sum(len(re.findall(r"<script\b", body)) for body in bodies)}
    profile = {"state": "measured", "value": all(100 <= r["status"] <= 599 for r in responses),
               "source": "fixtures:headers,marker"}
    return profile, signals


def run_demo():
    manifest, fixtures = inputs()
    manifest["profile"]["has_http"], signals = observations(fixtures)
    adapters = {t["id"]: (lambda url, fixture=t["fixture"]: copy.deepcopy(fixtures[fixture]))
                for t in manifest["tools"]}
    run = Harness(manifest, adapters, fixtures)
    run.observe(signals)
    run.advance("plan")
    plan = run.plan("https://lab.example/")
    run.advance("execute")
    captures = {row["tool"]: run.execute(row["tool"], row["url"]) for row in plan}
    run.advance("review")
    run.propose_finding(finding_id="header", title="Wildcard header", kind="header",
                        severity="critical", evidence_id=captures["inspect_headers"]["evidence_id"],
                        quote="Access-Control-Allow-Origin: *")
    run.propose_finding(finding_id="marker", title="Synthetic lab marker", kind="lab_marker",
                        severity="critical", evidence_id=captures["check_lab_marker"]["evidence_id"],
                        quote="LAB_CONFIRMED")
    rejected = []
    try:
        run.verify_raise(finding_id="header", evidence_id=captures["inspect_headers"]["evidence_id"],
                         quote="Access-Control-Allow-Origin: *", severity="high", rule_id="synthetic-lab-proof")
    except PolicyError as exc:
        rejected.append({"case": "real quote without proof predicate", "finding_id": "header",
                         "rule_id": "synthetic-lab-proof", "reason": str(exc)})
    run.verify_raise(finding_id="marker", evidence_id=captures["check_lab_marker"]["evidence_id"],
                     quote="LAB_CONFIRMED", severity="high", rule_id="synthetic-lab-proof")
    run.advance("report")
    report = run.finish()
    report["demonstration_rejections"] = rejected
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(canonical_bytes(run_demo()))
    print(args.out)


if __name__ == "__main__":
    main()
