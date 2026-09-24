"""The capstone, executable: your model behind the course application.

This is the file the connection guide's bridge is a smoke test for. It builds
the assembled application's configuration with real Python callables -- a
proposal provider and a verifier, each wrapping one transport -- and runs the
complete offline lifecycle against the course's fixture world. The default
transport is a deterministic fake, so the whole connection is testable with no
model installed; `--model NAME` swaps in the local Ollama transport from the
connection guide, and nothing else changes. Swapping the transport never
changes scope, budgets or permissions.

One command runs it:

    python3 -m examples.app_agent --out /tmp/agent-report.json

Operating it is three more commands, exercised by lesson 16's ending:

    python3 -m examples.app_agent --out /tmp/agent-interrupted.json \
        --checkpoint /tmp/agent-checkpoint.json --interrupt-after 1
    python3 -m examples.app_agent --resume /tmp/agent-checkpoint.json \
        --out /tmp/agent-resumed.json
    python3 -m examples.app_agent --review /tmp/agent-report.json \
        --finding FINDING_ID --decision needs_review \
        --reason "Synthetic evidence needs independent validation" --actor reader \
        --out /tmp/review-0001.json

The proposal contract difference from the old bridge, in one table: the
bridge's reply is {action, tool, url}; the application's provider replies with
a hypothesis {kind, surface, evidence, action{tool, destination, arguments}}.
The wrappers below construct the exact schema and tool descriptions the model
needs, so the transport is the only swappable part.
"""

import argparse
import json
import sys
from pathlib import Path

from core.run.acceptance import review_decision
from core.run.app import Application
from core.run.demo_app import BETA, LAB, WORLD, build_config
from core.run.records import RecordError


# --- Schemas: what the model must return, stated as data ---------------------

def proposal_schema(tool_ids):
    """The hypothesis contract from the proposals lesson, as a JSON schema."""
    return {
        "type": "object",
        "properties": {
            "kind": {"type": "string"},
            "surface": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}},
            "action": {
                "type": "object",
                "properties": {
                    "tool": {"type": "string", "enum": sorted(tool_ids)},
                    "destination": {"type": "string"},
                    "arguments": {"type": "object"},
                },
                "required": ["tool", "destination", "arguments"],
            },
        },
        "required": ["kind", "surface", "evidence", "action"],
    }


def verdict_schema():
    return {
        "type": "object",
        "properties": {
            "verdict": {"type": "string",
                        "enum": ["accept", "reject", "needs_review",
                                 "adjust_severity"]},
            "reason": {"type": "string"},
            "quote": {"type": "string"},
            "severity": {"type": "string"},
        },
        "required": ["verdict", "reason"],
    }


def tool_descriptions(config):
    return [{"tool": row["tool_id"], "activity": row["activity"],
             "purpose": "fixture HTTP inspection" if row["activity"] == "passive"
             else "fixture form probe", "cost": row["cost"]}
            for row in config["tools"]]


# --- Wrappers: the application's contexts, packed for one transport ----------

def make_provider(transport, config):
    """The application's proposal provider around one transport callable.

    The application hands this callable its proposal context (instruction,
    observations, optional evidence and advisory memory, and the validation
    error on a repair round). The wrapper adds what a real model needs and the
    context deliberately omits: the output schema and the tool vocabulary.
    The transport's reply text goes back to the session's strict parser
    unchanged -- parsing and admission stay the host's job.
    """
    tool_ids = [row["tool_id"] for row in config["tools"]]

    def provider(context):
        packet = {
            "instruction": context["instruction"] + " Reply with exactly one "
                           "JSON object matching output_schema.",
            "output_schema": proposal_schema(tool_ids),
            "tools": tool_descriptions(config),
            "observations": context["observations"],
            "evidence": context.get("evidence", []),
            "advisory_memory": context.get("advisory_memory", ""),
            "validation_error": context.get("validation_error"),
        }
        return transport(packet)

    return provider


def make_verifier(transport):
    """The verifier wrapper: the isolated packet plus its verdict schema."""

    def verifier(packet):
        wrapped = {
            "instruction": "Judge whether the quoted evidence supports the "
                           "finding. Reply with exactly one JSON object "
                           "matching output_schema.",
            "output_schema": verdict_schema(),
            "finding": packet["finding"],
            "capture": packet["capture"],
            "verdict_schema": packet["verdict_schema"],
        }
        return transport(wrapped)

    return verifier


# --- Transports ---------------------------------------------------------------

def fake_transport(packet):
    """A deterministic stand-in model: useful proposals, honest verdicts.

    Proposal packets get the health-path hypothesis first; once the packet
    carries captured evidence, the reply cites it and proposes the login form
    probe. Verdict packets accept findings whose quote appears in the capture.
    No network, no model, fully offline.
    """
    if "verdict" in json.dumps(packet.get("output_schema", {})):
        finding = packet["finding"]
        capture = packet["capture"]
        if finding["kind"] == "form-exposure":
            # A deliberately WRONG rejection, mirroring the lesson demo: the
            # form really is in the capture, and overruling this verdict is
            # exactly what the review command exists for.
            return json.dumps({"verdict": "reject",
                               "reason": "judged a template artifact; a "
                                         "human should check this"})
        if finding["quote"] in capture["body"]:
            return json.dumps({"verdict": "accept",
                               "reason": "the quote occurs in the capture"})
        return json.dumps({"verdict": "reject",
                           "reason": "the quote is not in the capture"})
    if packet.get("evidence"):
        # The captured evidence shows the shared banner on both hosts; the
        # follow-up checks whether the beta host leaks the same health path
        # the lab host did -- a new action drawn from what the last one found.
        return json.dumps({
            "kind": "shared-banner-follow-up",
            "surface": "beta_status",
            "evidence": ["beta_status", "landing_status"],
            "action": {"tool": "inspect_headers",
                       "destination": f"{BETA}/health",
                       "arguments": {}}})
    return json.dumps({
        "kind": "health-endpoint-disclosure",
        "surface": "landing_status",
        "evidence": ["landing_status"],
        "action": {"tool": "inspect_headers",
                   "destination": f"{LAB}/health",
                   "arguments": {}}})


def broken_transport(packet):
    """The connection-failure fixture: every call raises, none is hidden."""
    raise ConnectionError("no model transport is reachable")


def ollama_transport(model):
    """The connection guide's local transport, reused unchanged."""
    from .ollama_client import make_proposer
    return make_proposer(model)


# --- Assembly and operation ----------------------------------------------------

def agent_config(transport, store_path=None):
    config = build_config()
    config["provider"] = make_provider(transport, config)
    config["verifier"] = make_verifier(transport)
    if store_path:
        # The durable store may outlive many runs; the scope is what keeps
        # this engagement's reads and write-backs inside this engagement.
        config["retrieval"] = {"enabled": True, "store": store_path,
                               "records": [],
                               "query": "shared banner inspect_headers",
                               "budget": 400,
                               "scope": {
                                   "engagement": WORLD["name"],
                                   "profile_hash": f"fixture:{WORLD['name']}"}}
    return config


def proposal_summary(report):
    return [{"phase": p.get("phase"), "status": "admitted" if p["admitted"]
             else p["status"], "reason": p.get("reason")}
            for p in report["proposals"]]


def run_agent(args):
    transport = fake_transport
    if args.broken_transport:
        transport = broken_transport
    elif args.model:
        transport = ollama_transport(args.model)
    config = agent_config(transport, args.store)

    if args.interrupt_after is not None:
        app = Application(config)
        app._start(WORLD)
        app._observe(WORLD)
        _, ranked = app._plan(WORLD)
        if not 0 < args.interrupt_after < len(ranked):
            print(f"--interrupt-after must leave work pending: this world "
                  f"plans {len(ranked)} actions, so pick a value between 1 "
                  f"and {len(ranked) - 1}", file=sys.stderr)
            return 2
        app.machine.advance("scanning")
        app.machine.advance("active_testing")
        for candidate in ranked[:args.interrupt_after]:
            app.lifecycle.execute_with_retries(candidate.features["tool"],
                                               candidate.features["destination"])
        # The interruption: one more action authorized, its outcome never
        # recorded -- then this process exits. The checkpoint is the only
        # thing the next process gets.
        pending = ranked[args.interrupt_after]
        app.recorder.record("action", {
            "run_id": app.recorder.run.run_id,
            "tool": pending.features["tool"],
            "destination": pending.features["destination"]})
        checkpoint = app.checkpoint()
        Path(args.checkpoint).write_text(
            json.dumps(checkpoint, indent=1, sort_keys=True) + "\n",
            encoding="utf-8")
        summary = {"interrupted": True,
                   "executed": args.interrupt_after,
                   "pending_action": pending.candidate_id,
                   "checkpoint": str(args.checkpoint)}
        Path(args.out).write_text(json.dumps(summary, indent=1) + "\n",
                                  encoding="utf-8")
        print(f"interrupted after {args.interrupt_after} action(s); "
              f"checkpoint: {args.checkpoint}")
        return 0

    if args.resume:
        checkpoint = json.loads(Path(args.resume).read_text(encoding="utf-8"))
        try:
            app, reconciliation = Application.resume(checkpoint, config)
        except ValueError as exc:
            print(f"resume refused: {exc}", file=sys.stderr)
            return 2
        finish = app.lifecycle.finish()
        result = {"resumed_from": str(args.resume),
                  "reconciliation": reconciliation,
                  "finish_completed": finish["completed"],
                  "coverage": finish["report"]["coverage"],
                  "resource_use": finish["report"]["resource_use"]}
        Path(args.out).write_text(json.dumps(result, indent=1) + "\n",
                                  encoding="utf-8")
        print(f"resumed in a fresh process; unresolved kept unresolved: "
              f"{finish['report']['coverage']['unresolved']}")
        return 0

    app = Application(config)
    report = app.run(WORLD)
    Path(args.out).write_text(json.dumps(report, indent=1, sort_keys=True,
                                         default=str) + "\n", encoding="utf-8")
    print("proposals:", json.dumps(proposal_summary(report)))
    print("verdicts:", json.dumps([
        {"finding": e["finding_id"], "applied": e["applied"],
         **({"verdict": e["verdict"]} if e.get("verdict") else
            {"reason": e.get("reason")})}
        for e in report["verification"]["verdict_ledger"]]))
    rejected = [e["finding_id"]
                for e in report["verification"]["verdict_ledger"]
                if e.get("verdict") == "reject"]
    if rejected:
        print("review a rejection (full id, copy verbatim):")
        print(f"  python3 -m examples.app_agent --review {args.out} "
              f"--finding {rejected[0]} --decision needs_review "
              f"--reason 'Synthetic evidence needs independent validation' "
              f"--actor YOUR_NAME --out /tmp/review-0001.json")
    if report["retrieval"]:
        print("memory:", json.dumps({
            "included": report["retrieval"]["observation"]["included"],
            "written": [w.get("record_id") or w.get("declined")
                        for w in report["memory_written"]]}))
    print("completed:", report["finish"]["completed"],
          "| findings:", len(report["finish"]["report"]["run_report"]["findings"]))
    failed = [p for p in report["proposals"] if not p["admitted"]]
    if failed and all(not p["admitted"] for p in report["proposals"]):
        print("model connection NOT established:",
              json.dumps(proposal_summary(report)))
        return 1
    return 0


def run_review(args):
    report = json.loads(Path(args.review).read_text(encoding="utf-8"))
    try:
        artifact = review_decision(report, finding_id=args.finding,
                                   decision=args.decision, reason=args.reason,
                                   actor=args.actor)
    except RecordError as exc:
        print(f"review refused: {exc}", file=sys.stderr)
        return 2
    Path(args.out).write_text(json.dumps(artifact, indent=1, sort_keys=True)
                              + "\n", encoding="utf-8")
    print(f"review recorded: {artifact['decision']} by {artifact['actor']} "
          f"on finding {args.finding[:12]}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", help="local Ollama model name; default is "
                                        "the offline fake transport")
    parser.add_argument("--broken-transport", action="store_true",
                        help="demonstrate a failed connection honestly")
    parser.add_argument("--store", help="SQLite path for durable memory")
    parser.add_argument("--checkpoint", type=Path,
                        help="where --interrupt-after writes the checkpoint")
    parser.add_argument("--interrupt-after", type=int,
                        help="execute this many actions, checkpoint, exit")
    parser.add_argument("--resume", type=Path,
                        help="resume from a checkpoint file in this process")
    parser.add_argument("--review", type=Path,
                        help="record a review decision over a saved report")
    parser.add_argument("--finding")
    parser.add_argument("--decision")
    parser.add_argument("--reason")
    parser.add_argument("--actor")
    args = parser.parse_args(argv)
    if args.review:
        return run_review(args)
    if args.interrupt_after is not None and not args.checkpoint:
        parser.error("--interrupt-after needs --checkpoint")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    return run_agent(args)


if __name__ == "__main__":
    raise SystemExit(main())
