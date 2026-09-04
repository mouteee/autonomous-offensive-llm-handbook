"""
core/store_protocol.py — the store contract, documented and never implemented

``consolidate_scan``, ``process_tool_result`` and the governor's scan-wide pass
(``govern_scan`` and the ``fetch_all_findings`` helper it materialises through)
all take a store, and this repository ships no store to give them: persistence
is deliberately out of scope for a reference implementation about decisions, and
a half-real store would be worse than none at all — it would be the most
plausible-looking wrong thing in the tree. A ``typing.Protocol`` closes that gap
the honest way. It states what a store must provide for those consumers to be
read, reviewed and tested, and it implements nothing: every method body below is
an ellipsis, and ``FindingStore()`` raises
``TypeError: Protocols cannot be instantiated``, so it cannot be mistaken for a
working store even by accident.

**An in-memory double, when the tests need one, belongs in ``tests/`` and never
here.** That is a rule about where a fake may live, and it is load-bearing rather
than tidy. This handbook's argument is that every side effect flows through one
real write path, and a plausible store sitting in ``core/`` beside the modules
that call it invites precisely the misreading that argument cannot afford: a
reader who finds a store in ``core/`` has no way to tell that it is a stub,
while a reader who finds one in ``tests/`` already knows.

**Every member here re-expresses the surface the underlying system's write path
exposes to those consumers, including where that surface is ugly.** The
asymmetry is the ugly part and it is reproduced on purpose: ``add_finding`` and
``get_findings`` are coroutines, ``update_finding_governed`` is not, and
``scan_id`` is an attribute rather than an accessor. Tidying any of those into a
uniform shape would produce a contract that reads better and fails silently, so
each one is stated as measured and the reason is written beside it.

**The surface grows only when a shipped consumer calls a new member.** A member
declared here that nothing under ``core/`` calls is a contract a reader cannot
implement against, and a list padded with dead entries looks broader than it is;
tests/test_store_protocol.py refuses that by reading the declared members off
this class and naming any one of them that no module calls.
"""
from typing import Dict, List, Optional, Protocol


class FindingStore(Protocol):
    """The store surface the findings consumers need, and nothing beyond it.

    ``scan_id`` is a plain attribute, because that is what the consumers read:
    both the consolidator and the result processor scope their work by reaching
    for it directly rather than asking for it, and every write below is already
    scoped to it by the store.

    Structural rather than nominal: any object exposing these members satisfies
    the contract, so a consumer needs no import of a store class and a double
    needs no inheritance. Nothing here is enforced at runtime — this repository
    runs no type checker, so the Protocol's whole effect is on the reader, and on
    whatever checker a consumer of the handbook chooses to point at it.

    Deliberately not ``runtime_checkable``, which would make that enforcement
    look real without making it so: an ``isinstance`` check against a Protocol
    proves only that the member *names* are present, never their signatures and
    never their semantics. Without the decorator the check refuses outright,
    with ``TypeError: Instance and class checks can only be used with
    @runtime_checkable protocols``.
    """

    scan_id: str

    async def add_finding(self, finding: Dict) -> str:
        """Persist a finding and return its string id.

        A store may derive the id itself from the finding's content when the
        caller supplies none, so a caller that needs the id afterwards reads
        this return value instead of assuming the one it sent.

        A conforming store normalises the finding's evidence and governs its
        severity before it persists the row, so a store that skips that step
        silently ships the ungoverned severity it was handed -- the narrow waist
        that calls this sets no severity of its own and relies on this write path
        to grade.
        """
        ...

    async def get_findings(
        self,
        severity: Optional[str] = None,
        finding_type: Optional[str] = None,
        validated_only: bool = False,
        exclude_fp: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict]:
        """Findings for the store's own scan, filtered and paged.

        ``limit`` and ``offset`` are load-bearing rather than a convenience. The
        caller that materialises a whole scan pages over them, asking for
        successive windows until a short one comes back, so a substitute that
        accepts the arguments and ignores them returns a full window every time
        and that loop never sees its short batch. The failure is not a truncated
        result but a pager that keeps asking, which is why a substitute must
        honour both rather than treat them as hints.
        """
        ...

    def update_finding_governed(
        self,
        finding_id: str,
        severity: str,
        raw_data: Dict,
        false_positive: bool = False,
    ) -> None:
        """Persist a governor re-rating: severity, the governance record it is
        carried in, and the false-positive flag, scoped to the store's own scan.

        **Synchronous, and a substitute must not make it a coroutine.** Every
        other member here is awaited and this one is not: its callers invoke it
        as a bare statement, so an ``async def`` substitute would hand a
        coroutine back into a discarded expression and the write would never
        happen — no exception, no failed assertion, and a re-rated severity left
        sitting at its old value. Python says so only through a
        ``RuntimeWarning`` about a coroutine that was never awaited, which a test
        suite is free to ignore. That is the one direction in this contract that
        fails silently, which is why the asymmetry is reproduced rather than
        tidied.
        """
        ...

    async def add_tool_result(self, tool: str, arguments: Dict, result: Dict) -> None:
        """Append the full result payload of one tool call to the timeline.

        This is the wide record -- the arguments and the whole result -- kept
        apart from the narrow coverage row `add_tool_execution` writes, so a
        tool call that produced no finding still leaves its execution behind.
        """
        ...

    async def add_tool_execution(
        self,
        tool: str,
        url: str = "",
        method: str = "GET",
        category: str = "",
        status: str = "success",
        duration_s: float = 0.0,
        arguments: Optional[Dict] = None,
        findings_count: int = 0,
    ) -> int:
        """Record one invocation in the narrow coverage table and return its row id.

        Indexed by scan and by the url and tool pair, so the coverage matrix
        reads back cheaply. Separate from `add_tool_result`, which carries the
        payload; the caller keeps this return value as the execution id.
        """
        ...

    async def get_coverage(self) -> Dict:
        """Return the coverage matrix for the store's own scan.

        Carries a `coverage_pct` the caller reads for the live status row. That
        read is best-effort at the call site, so a store is free to compute the
        matrix lazily.
        """
        ...

    async def rollup_scan_stats(self) -> Dict:
        """Recompute the scan's finding totals and return them as a mapping.

        The caller reads `findings_count` off the returned mapping, so a
        conforming store returns a mapping here and not `None`; a `None` return
        would be read with `.get` and raise at the call site.
        """
        ...

    async def update_status(
        self,
        phase: str,
        phase_iter: int,
        max_phase_iter: int,
        total_iter: int,
        max_iter: int,
        current_tool: str = "",
        current_url: str = "",
        coverage_pct: float = 0,
        findings_count: int = 0,
    ) -> None:
        """Write the lightweight status row the dashboard polls.

        Called twice per tool result -- once with a placeholder count and again
        with the rolled-up `findings_count` -- so the live view lands on the
        authoritative total once the rollup has run.
        """
        ...
