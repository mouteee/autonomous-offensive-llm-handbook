"""The human review artifact: an operator's decision about one finding,
recorded beside a closed run instead of inside it.

A completed run is closed at its write boundary, and acceptance was always
documented as a separate human decision. This module is that separation made
concrete: the decision becomes its own small record that names the run, the
finding and the evidence it judged, carries the actor and the reason, and
binds to the exact report it reviewed through a digest -- so the closed run
stays immutable and the review is still accountable. Nothing here reopens a
run, and nothing here is accepted on a model's behalf.
"""

from .records import REVIEW_DECISIONS, RecordError, digest


def review_decision(report, *, finding_id, decision, reason, actor):
    """One operator decision over one finding of one terminal report.

    `report` is the application report (or any object carrying the terminal
    report at ["finish"]["report"]). The finding must exist in that report's
    own records; the artifact quotes the capture identity it judged and the
    digest of the run report it was looking at, so a later reader can tell
    exactly which evidence the decision was about -- and whether the report
    they hold is the one that was reviewed.
    """
    if decision not in REVIEW_DECISIONS:
        raise RecordError(f"unknown review decision {decision!r}; one of "
                          f"{', '.join(REVIEW_DECISIONS)}")
    for name, value in (("reason", reason), ("actor", actor)):
        if not isinstance(value, str) or not value.strip():
            raise RecordError(f"a review decision carries a nonempty {name}")
    try:
        terminal = report["finish"]["report"]
    except (KeyError, TypeError):
        raise RecordError("review_decision needs an application report "
                          "carrying finish.report") from None
    run_report = terminal["run_report"]
    finding = next((f for f in run_report["findings"]
                    if f["finding_id"] == finding_id), None)
    if finding is None:
        raise RecordError(
            f"finding {finding_id!r} is not in the reviewed report; a "
            "decision about evidence the report does not hold reviews "
            "nothing")
    return {
        "schema": "course-review-decision/v1",
        "run_id": run_report["run_id"],
        "report_digest": digest(run_report),
        "finding_id": finding_id,
        "capture_id": finding["capture_id"],
        "kind": finding["kind"],
        "severity": finding["severity"],
        "decision": decision,
        "reason": reason,
        "actor": actor,
        "note": "a separate artifact beside a closed run; the run itself is "
                "unchanged",
    }
