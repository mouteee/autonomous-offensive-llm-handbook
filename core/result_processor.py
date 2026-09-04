"""The narrow waist: one tool execution in, its recorded side effects out.

Every side effect derived from a single tool result -- the timeline row, the
coverage row, the dashboard status, the stored findings, the scan rollup, and an
optional fan-out to collaborators -- is written here and nowhere else on the
server-orchestrated path, so the model that proposes a tool call never writes the
database itself. It emits a proposal; this function executes and records it.

This module never sets a severity. It hands every finding to the store's single
write path, and that path is what normalises the evidence and governs the grade,
so a thin critical does not reach the table as a critical on account of anything
decided here. That grading behind the write rather than in front of it is the
property the narrow-waist chapter turns on; re-expressing it faithfully means
this module grades nothing of its own -- it assigns no severity and calls no
governor, and a version that did would diverge from the private architecture the
store double in the tests pins.

Honest about the second path, because that chapter publishes both. When a coding
agent orchestrates instead of a server-side model, this waist is a convention the
agent keeps, not a wall it cannot cross: the agent has a terminal of its own,
outside this function entirely, so writing through the shared sink is a
discipline rather than an enforced chokepoint.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PAYLOAD_SNIPPET = 200
_MEDIUM_AND_ABOVE = ("critical", "high", "medium")
_BELOW_MEDIUM = ("info", "low")


@dataclass
class ProcessedResult:
    """The record of what one `process_tool_result` call wrote.

    The findings field is `findings_stored`, and it holds the ids the store
    returned -- strings, since `add_finding` returns a content-hash prefix -- not
    a count and not the findings themselves.
    """

    findings_stored: List[str] = field(default_factory=list)
    tool_execution_id: Optional[int] = None
    timeline_id: Optional[str] = None
    coverage_updated: bool = False
    chains_triggered: List[str] = field(default_factory=list)
    memory_recorded: int = 0
    status_updated: bool = False
    rollup_findings_count: int = 0
    errors: List[str] = field(default_factory=list)


async def process_tool_result(
    store,
    tool_call: Dict[str, Any],
    result: Dict[str, Any],
    *,
    phase: str = "active_testing",
    response_analyzer=None,
    chain_executor=None,
    memory_engine=None,
    intel_bus=None,
    scheduler=None,
) -> ProcessedResult:
    """Write every side effect of one tool execution, in a deliberate order.

    The order is load-bearing. The execution and its result are recorded first,
    so a tool call that found nothing -- a hallucinated endpoint the model
    invented -- still leaves a complete record, and only then, when the result
    carried findings, is each finding stored: `add_finding` is not the first
    write but a later one, reached after the execution row, the coverage row and
    the status row already exist.

    Each step catches its own exception, appends it to `errors` naming the member
    that raised, and does not re-raise, so one failed side effect never blocks the
    rest and the caller gets a partial record plus a list of what went wrong. The
    coverage read feeding the status row is the one deliberate exception: its own
    failure is swallowed, because a missing coverage percentage must not stop the
    status row being written.

    The three expensive collaborators are optional and severity-gated, and the
    two severity gates have OPPOSITE POLARITY, which is why each is named here
    instead of generalised over. `intel_bus` is published for every stored
    finding. `chain_executor` is guarded by an allowlist, `_MEDIUM_AND_ABOVE`: a
    severity that is not a member of it never reaches that collaborator.
    `memory_engine` is guarded by a denylist, `_BELOW_MEDIUM`: only a member of
    that tuple is held back, so every other severity string does reach it, a
    differently-cased or whitespace-padded spelling of a low band included. An
    `info` or `low` finding reaches neither, which is the property the pair was
    built for, and a finding carrying no `severity` key behaves the same way
    because each gate reads that key as `finding.get("severity", "info")` and
    supplies the default itself, at the gate. The
    `candidate.setdefault("severity", "info")` earlier in this function is not
    what does it: it writes to a shallow copy bound for the store, never to the
    dict either gate reads. All three default to `None`, and a `None`
    collaborator is a documented no-op rather than an error.
    `response_analyzer` and `scheduler` are accepted for signature parity and are
    not consulted here at all.

    This function sets no severity of its own: the finding it stores is handed to
    the store unchanged in grade, and normalisation and governance happen there.
    """
    processed = ProcessedResult()

    is_dict = isinstance(result, dict)
    tool_name = tool_call.get("name", "") if isinstance(tool_call, dict) else ""
    args = (tool_call.get("arguments") or {}) if isinstance(tool_call, dict) else {}
    url = args.get("url", "") or ""
    method = (args.get("method") or "GET").upper()
    category = tool_name.replace("test_", "") if tool_name.startswith("test_") else tool_name

    findings_out = result.get("findings", []) if is_dict else []
    if not isinstance(findings_out, list):
        findings_out = []
    findings_count = len(findings_out)
    duration_s = (
        float(result.get("_duration_s") or result.get("duration_s") or 0.0)
        if is_dict else 0.0
    )

    if is_dict and result.get("error"):
        status = "error"
    elif is_dict and result.get("success") is False:
        status = "error"
    elif is_dict and result.get("skipped"):
        status = "skipped"
    else:
        status = "success"

    # timeline row
    try:
        await store.add_tool_result(tool=tool_name, arguments=args, result=result)
    except Exception as exc:
        processed.errors.append(f"add_tool_result: {exc}")

    # coverage row
    try:
        processed.tool_execution_id = await store.add_tool_execution(
            tool=tool_name, url=url, method=method, category=category,
            status=status, duration_s=duration_s, arguments=args,
            findings_count=findings_count,
        )
        processed.coverage_updated = True
    except Exception as exc:
        processed.errors.append(f"add_tool_execution: {exc}")

    # dashboard status row; the coverage read is best-effort and its own failure
    # is swallowed so it cannot stop the status row from being written
    coverage_pct = 0.0
    try:
        try:
            coverage = await store.get_coverage()
            coverage_pct = coverage.get("coverage_pct", 0.0)
        except Exception:
            pass
        await store.update_status(
            phase=phase, phase_iter=0, max_phase_iter=0, total_iter=0, max_iter=0,
            current_tool=tool_name, current_url=url, coverage_pct=coverage_pct,
            findings_count=0,
        )
        processed.status_updated = True
    except Exception as exc:
        processed.errors.append(f"update_status: {exc}")

    # findings: normalise the shape, then hand each to the governing write path
    stored_ids: List[str] = []
    origin = tool_call.get("_origin") if isinstance(tool_call, dict) else None
    for finding in findings_out:
        if not isinstance(finding, dict):
            continue
        candidate = dict(finding)
        if not candidate.get("source"):
            candidate["source"] = tool_name
        candidate.setdefault("type", "vulnerability")
        candidate.setdefault("severity", "info")
        candidate.setdefault("url", url)
        if origin:
            raw = candidate.get("raw_data")
            if not isinstance(raw, dict):
                raw = {}
            raw.setdefault("origin", origin)
            candidate["raw_data"] = raw
        try:
            stored_ids.append(await store.add_finding(candidate))
        except Exception as exc:
            processed.errors.append(f"add_finding: {exc}")

    seen: set = set()
    unique_ids: List[str] = []
    for finding_id in stored_ids:
        if finding_id not in seen:
            seen.add(finding_id)
            unique_ids.append(finding_id)
    processed.findings_stored = unique_ids

    # scan rollup; a conforming store returns a mapping, read by key
    try:
        stats = await store.rollup_scan_stats()
        processed.rollup_findings_count = stats.get("findings_count", 0)
    except Exception as exc:
        processed.errors.append(f"rollup_scan_stats: {exc}")

    # refresh the status row with the rolled-up count
    try:
        await store.update_status(
            phase=phase, phase_iter=0, max_phase_iter=0, total_iter=0, max_iter=0,
            current_tool=tool_name, current_url=url, coverage_pct=coverage_pct,
            findings_count=processed.rollup_findings_count,
        )
    except Exception as exc:
        processed.errors.append(f"update_status_post_rollup: {exc}")

    # chain triggers: optional, medium and above
    if chain_executor and stored_ids:
        for finding in findings_out:
            if not isinstance(finding, dict):
                continue
            if finding.get("severity", "info") not in _MEDIUM_AND_ABOVE:
                continue
            try:
                triggered = await chain_executor.check_triggers(finding)
                for chain in triggered or []:
                    chain_id = getattr(chain, "id", None) or (
                        chain.get("id") if isinstance(chain, dict) else str(chain)
                    )
                    if chain_id:
                        processed.chains_triggered.append(chain_id)
            except Exception as exc:
                processed.errors.append(f"chain_executor.check_triggers: {exc}")

    # memory engine: optional, medium and above
    if memory_engine and stored_ids:
        for finding in findings_out:
            if not isinstance(finding, dict):
                continue
            if finding.get("severity", "info") in _BELOW_MEDIUM:
                continue
            try:
                await memory_engine.record_success(
                    profile_hash=finding.get("profile_hash", ""),
                    tool=tool_name,
                    endpoint=finding.get("url", url),
                    param_name=finding.get("param_name", finding.get("parameter", "")),
                    payload=str(finding.get("payload_used", finding.get("evidence", "")))[:_PAYLOAD_SNIPPET],
                    bypass_technique=finding.get("bypass_technique", "none"),
                    waf_vendor=finding.get("waf_vendor", "none"),
                )
                processed.memory_recorded += 1
            except Exception as exc:
                processed.errors.append(f"memory_engine.record_success: {exc}")

    # intelligence bus: optional, every stored finding
    if intel_bus and stored_ids:
        for finding in findings_out:
            if not isinstance(finding, dict):
                continue
            try:
                await intel_bus.publish_finding(
                    store.scan_id, "",
                    {
                        "type": finding.get("type", ""),
                        "url": finding.get("url", url),
                        "tool": tool_name,
                        "severity": finding.get("severity", "info"),
                        "title": finding.get("title", ""),
                    },
                )
            except Exception as exc:
                processed.errors.append(f"intel_bus.publish_finding: {exc}")

    return processed
