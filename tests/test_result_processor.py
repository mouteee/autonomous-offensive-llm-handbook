"""The narrow waist: proposals in, recorded facts out."""
import asyncio, pytest
from core.result_processor import process_tool_result, ProcessedResult


class FakeStore:
    """Complete double for the SEVEN members this module touches.

    Incompleteness here is a trap rather than an inconvenience: every step of
    the write path catches its own exception and records it, so a missing member
    quietly fills `errors` and makes the collaborators-are-optional test below
    fail for a reason that has nothing to do with collaborators. Ids are
    STRINGS, because the real `add_finding` returns a sha256 prefix and
    `ProcessedResult.findings_stored` is `List[str]`.
    """

    def __init__(self):
        self.findings = []
        self.scan_id = "scan-1"
        self.calls = []
        self.tool_executions = []
        self.tool_results = []
        self.status = None
        self.rollups = 0

    async def add_finding(self, finding):
        finding["id"] = f"f{len(self.findings) + 1:015x}"
        self.findings.append(finding)
        self.calls.append("add_finding")
        return finding["id"]

    async def get_findings(self, severity=None, finding_type=None, validated_only=False,
                           exclude_fp=True, limit=100, offset=0):
        rows = [f for f in self.findings if not (exclude_fp and f.get("false_positive"))]
        return [dict(r) for r in rows[offset:offset + limit]]

    async def add_tool_execution(self, *a, **kw):
        self.tool_executions.append((a, kw))
        self.calls.append("add_tool_execution")
        return len(self.tool_executions)

    async def add_tool_result(self, *a, **kw):
        self.tool_results.append((a, kw))
        self.calls.append("add_tool_result")
        return f"t{len(self.tool_results)}"

    async def get_coverage(self, *a, **kw):
        self.calls.append("get_coverage")
        return {}

    async def rollup_scan_stats(self, *a, **kw):
        self.rollups += 1
        self.calls.append("rollup_scan_stats")
        # MUST return a dict: the caller does .get() on the result, and a None
        # return puts a spurious "'NoneType' object has no attribute 'get'" into
        # `errors` on every invocation -- which then makes the collaborator tests
        # fail for a reason that has nothing to do with collaborators.
        return {"findings_count": len(self.findings)}

    async def update_status(self, *a, **kw):
        self.status = (a, kw)
        self.calls.append("update_status")


class GoverningStore(FakeStore):
    """A store that does what a conforming store must: normalise the evidence
    and govern the severity BEFORE persisting. That is where governance lives in
    the real system -- core/store.py's add_finding, not this module -- so a
    double that skips it stores whatever severity it was handed."""

    async def add_finding(self, finding):
        from core.severity_governor import (govern_finding, load_rules,
                                            normalize_finding_evidence)
        normalize_finding_evidence(finding)
        govern_finding(finding, rules=load_rules())
        return await super().add_finding(finding)


class Exploding:
    def __getattr__(self, name):
        def _boom(*a, **kw): raise RuntimeError("collaborator failed")
        return _boom


def _call(tool="test_idor"):
    """A tool call in the vocabulary the module actually reads.

    The keys are `name` and `arguments`, which is what `process_tool_result`
    asks for and what `core.llm_control.ToolCall` produces. This helper used to
    say `tool` and `args`; both were dropped on the floor, so every test below
    ran against an empty tool identity and the `source` default, the `url`
    default and the `test_`-strip category derivation were all unexercised while
    passing. `test_the_tool_identity_reaches_the_records` pins the fix, because
    a fixture correction that nothing asserts is a change no test can keep.
    """
    return {"name": tool, "arguments": {"url": "https://shop.example/x"}}


def test_the_tool_identity_reaches_the_records():
    """The identity the module derives from a tool call, everywhere it lands.

    `source` defaults to the tool name, `url` defaults to the call's url, the
    execution row carries both, and `category` is the tool name with a leading
    `test_` removed. Revert `_call` to the `tool`/`args` spelling and every
    assertion below fails with an empty string, which is what the fixture was
    silently handing the module before.
    """
    store = FakeStore()
    result = {"findings": [{"type": "idor", "title": "t", "severity": "low"}]}
    asyncio.run(process_tool_result(store, _call(), result))
    _args, kw = store.tool_executions[0]
    assert kw["tool"] == "test_idor"
    assert kw["url"] == "https://shop.example/x"
    assert kw["category"] == "idor"
    assert store.findings[0]["source"] == "test_idor"


def test_the_result_carries_nine_fields_and_the_ids_are_strings():
    """The field is `findings_stored`, not `findings`, and it holds ids -- which
    are the store's sha256 prefixes, not integers. An earlier draft of this task
    asserted `out.findings` and would have failed on its first line."""
    import dataclasses
    assert {f.name for f in dataclasses.fields(ProcessedResult)} == {
        "findings_stored", "tool_execution_id", "timeline_id", "coverage_updated",
        "chains_triggered", "memory_recorded", "status_updated",
        "rollup_findings_count", "errors",
    }
    store = FakeStore()
    result = {"findings": [{"type": "idor", "title": "t", "severity": "low",
                            "raw_data": {"request": {"method": "GET", "url": "u"},
                                         "response": {"status": 200, "body": "b"}}}]}
    out = asyncio.run(process_tool_result(store, _call(), result))
    assert out.findings_stored and all(isinstance(i, str) for i in out.findings_stored)


def test_the_waist_never_sets_a_severity_and_the_store_is_what_governs():
    """Measured: this module contains no governance. A thin critical passed
    through a NON-governing store is stored as `critical`; through a store whose
    add_finding normalises and governs, the identical finding is stored as
    `medium`. Both are asserted, because the pair is the actual property -- the
    narrow-waist chapter puts governance in "the store method on the other
    side"."""
    plain, governing = FakeStore(), GoverningStore()
    thin = {"type": "idor", "title": "t", "severity": "critical", "source": "test_idor"}
    asyncio.run(process_tool_result(plain, _call(), {"findings": [dict(thin)]}))
    asyncio.run(process_tool_result(governing, _call(), {"findings": [dict(thin)]}))
    assert plain.findings[0]["severity"] == "critical"       # the waist changed nothing
    assert governing.findings[0]["severity"] == "medium"     # the store capped it
    assert plain.findings and governing.findings             # recorded either way


def test_the_execution_record_is_written_before_any_finding():
    """The measured write order, and the mechanism behind the narrow-waist
    chapter's hallucinated endpoint: the execution and its result are recorded
    before any finding, so a tool call that found nothing still leaves a complete
    record. Reorder the writes and this exact-sequence assertion fails."""
    store = FakeStore()
    result = {"findings": [{"type": "idor", "title": "t", "severity": "low",
                            "source": "test_idor"}]}
    asyncio.run(process_tool_result(store, _call(), result))
    assert store.calls == ["add_tool_result", "add_tool_execution", "get_coverage",
                           "update_status", "add_finding", "rollup_scan_stats",
                           "update_status"]


def test_a_hallucinated_endpoint_is_a_recorded_404_not_a_finding():
    store = FakeStore()
    result = {"status": 404, "url": "https://shop.example/invented", "findings": []}
    out = asyncio.run(process_tool_result(store, _call(), result))
    assert store.findings == []
    assert isinstance(out, ProcessedResult)


@pytest.mark.parametrize("name,method", [
    ("memory_engine", "record_success"),
    ("chain_executor", "check_triggers"),
    ("intel_bus", "publish_finding"),
])
def test_a_failing_collaborator_is_recorded_by_name_and_blocks_nothing(name, method):
    """The severity here is `medium` on purpose: two of these three are gated at
    medium and above, so the same test with a `low` fixture fails two of its
    three cases while looking like a module defect."""
    store = FakeStore()
    result = {"findings": [{"type": "idor", "title": "t", "severity": "medium",
                            "source": "test_idor",
                            "raw_data": {"request": {"method": "GET", "url": "u"},
                                         "response": {"status": 200, "body": "b"}}}]}
    out = asyncio.run(process_tool_result(store, _call(), result, **{name: Exploding()}))
    assert store.findings, "the finding was still written"
    assert out.errors == [f"{name}.{method}: collaborator failed"]


@pytest.mark.parametrize("severity,reaches_memory_and_chains", [
    ("info", False), ("low", False),
    ("medium", True), ("high", True), ("critical", True),
])
def test_the_expensive_side_effects_are_severity_gated(severity, reaches_memory_and_chains):
    """Measured: intel_bus sees every finding; memory and chain-triggering see
    `medium` and above only. An exploding double is the probe -- an error means
    the collaborator was reached."""
    def _errors(name):
        store = FakeStore()
        result = {"findings": [{"type": "idor", "title": "t", "severity": severity,
                                "source": "test_idor"}]}
        return asyncio.run(
            process_tool_result(store, _call(), result, **{name: Exploding()})).errors
    assert _errors("intel_bus"), "intel_bus is reached at every severity"
    assert bool(_errors("memory_engine")) is reaches_memory_and_chains
    assert bool(_errors("chain_executor")) is reaches_memory_and_chains


@pytest.mark.parametrize("name", ["response_analyzer", "scheduler"])
def test_two_collaborators_are_not_reached_on_this_path_and_that_is_stated(name):
    """Measured, and kept as a test rather than dropped: an exploding double
    handed in as response_analyzer or scheduler produces NO error, so either
    this path does not consult them or it consults them in a way the double
    never sees. Asserting the silence is what stops the table above from
    quietly implying all five are covered."""
    store = FakeStore()
    result = {"findings": [{"type": "idor", "title": "t", "severity": "low",
                            "source": "test_idor"}]}
    out = asyncio.run(process_tool_result(store, _call(), result, **{name: Exploding()}))
    assert out.errors == []
    assert store.findings


def test_the_tier_three_collaborators_are_optional_no_ops():
    store = FakeStore()
    out = asyncio.run(process_tool_result(store, _call(), {"findings": []}))
    assert out.errors == []


def test_findings_stored_drops_an_id_the_store_returned_twice():
    """Ids are content-addressed, so a store's add_finding can hand back one id
    for two findings it treats as the same; findings_stored preserves order and
    drops the repeat rather than listing it twice."""
    class CollapsingStore(FakeStore):
        async def add_finding(self, finding):
            self.findings.append(finding)
            self.calls.append("add_finding")
            return "same-id"

    store = CollapsingStore()
    result = {"findings": [
        {"type": "idor", "title": "a", "severity": "low", "source": "test_idor"},
        {"type": "idor", "title": "b", "severity": "low", "source": "test_idor"},
    ]}
    out = asyncio.run(process_tool_result(store, _call(), result))
    assert store.calls.count("add_finding") == 2
    assert out.findings_stored == ["same-id"]


def test_a_failed_coverage_read_is_swallowed_and_the_status_row_still_writes():
    """The coverage read that feeds the status row is best-effort: break it and
    the step records no error, because a missing coverage percentage must not
    stop the status row being written. The sibling update_status is NOT
    best-effort -- breaking it does record."""
    store = FakeStore()

    async def _boom(*a, **kw):
        raise RuntimeError("no coverage")

    store.get_coverage = _boom
    out = asyncio.run(process_tool_result(store, _call(), {"findings": []}))
    assert out.errors == []
    assert out.status_updated is True
