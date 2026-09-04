"""An in-memory implementation of the single write path, governance included.

This is a reference implementation rather than a test double, and the difference is the
whole point: governance lives in the store's write path in the real system, not in the
result integrator, so a store that only persists what it is handed produces a run with no
governance at all and nothing raises. `add_finding` normalises the evidence and governs the
grade BEFORE persisting, matching the order the real write path uses.

The member signatures mirror `core.store_protocol.FindingStore`, including its deliberate
asymmetry: seven members are coroutines and `update_finding_governed` is not, because
`core/severity_governor.py` awaits `get_findings` and calls `update_finding_governed`
without awaiting it.
"""
from core.severity_governor import govern_finding, load_rules, normalize_finding_evidence


class WalkthroughStore:
    """A conforming store that records what it did, so a driver can assert a stage ran."""

    def __init__(self):
        self.findings = []
        self.tool_executions = []
        self.tool_results = []
        self.governance_records = []
        self.status_updates = []
        self.stages_run = []
        # Fixed literal, not derived from a clock/path/random source: the walkthrough's
        # committed artifacts must be byte-identical across runs and working directories,
        # so every value that can reach one -- this included -- has to be deterministic.
        self.scan_id = "walkthrough"
        self._rules = load_rules()
        if not self._rules:
            raise RuntimeError(
                "the severity ruleset loaded empty; load_rules() returns [] for a missing "
                "file as a documented degraded mode, so governance would run with no rules "
                "and look like nothing needed capping"
            )

    async def add_finding(self, finding):
        normalize_finding_evidence(finding)
        govern_finding(finding, rules=self._rules)
        record = finding.get("governance_record")
        if record:
            self.governance_records.append(record)
        fid = finding.get("id") or f"f{len(self.findings):04d}"
        finding["id"] = fid
        self.findings.append(finding)
        return fid

    async def get_findings(self, severity=None, finding_type=None, validated_only=False,
                           exclude_fp=True, limit=100, offset=0):
        out = [f for f in self.findings
               if (severity is None or f.get("severity") == severity)
               and (finding_type is None or f.get("type") == finding_type)
               and not (exclude_fp and f.get("false_positive"))]
        return out[offset:offset + limit]

    def update_finding_governed(self, finding_id, severity, raw_data, false_positive=False):
        """Write a governed grade back onto a stored finding. An unmatched id raises.

        The loop used to fall off its end and return None. `consolidate_scan` and
        `govern_scan` invoke this as a bare statement and read nothing back, so a write that
        matched nothing left no trace of itself: `govern_scan` still counted the change in its
        summary while the store kept the ungoverned grade, which is governance reported as
        having happened and not having happened at once. That is the shape `__init__` refuses
        an empty ruleset for, and this is the reference implementation of the governing write
        path rather than a test double, so it refuses here too instead of modelling the quiet
        version.

        The committed walkthrough never reaches the raise, and not because its ids line up:
        the run reaches this member no times at all, so the driver's own greenness says
        nothing either way and the refusal is asserted directly in
        tests/test_walkthrough_store.py.
        """
        for f in self.findings:
            if f.get("id") == finding_id:
                f["severity"] = severity
                f["raw_data"] = raw_data
                f["false_positive"] = false_positive
                return
        raise KeyError(
            f"no stored finding has id {finding_id!r}, so this governed write to {severity!r} "
            f"would be lost; a silent return here makes a governance record that was published "
            f"indistinguishable from one that was persisted"
        )

    async def add_tool_result(self, tool, arguments, result):
        self.tool_results.append({"tool": tool, "arguments": arguments, "result": result})

    async def add_tool_execution(self, tool, url="", method="GET", category="", status="success",
                                 duration_s=0.0, arguments=None, findings_count=0):
        self.tool_executions.append({"tool": tool, "url": url, "method": method,
                                     "category": category, "status": status,
                                     "duration_s": duration_s, "arguments": arguments or {},
                                     "findings_count": findings_count})
        return len(self.tool_executions)

    async def get_coverage(self):
        return {"tools_run": len(self.tool_executions), "findings": len(self.findings)}

    async def rollup_scan_stats(self):
        by_sev = {}
        for f in self.findings:
            by_sev[f.get("severity", "info")] = by_sev.get(f.get("severity", "info"), 0) + 1
        return {"findings_total": len(self.findings), "by_severity": by_sev}

    async def update_status(self, phase, phase_iter, max_phase_iter, total_iter, max_iter,
                            current_tool="", current_url="", coverage_pct=0, findings_count=0):
        self.status_updates.append({"phase": phase, "current_tool": current_tool})
