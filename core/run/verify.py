"""From a tool result to a reviewed finding: grading, verdicts, consolidation.

The pipeline here is deliberately stricter than the originating implementation
at three points, and lesson 8 labels each as a teaching correction beside the
source behavior it corrects: quote containment is re-checked in host code at
verdict time, an unrecognized verdict string is refused instead of being read
as confirmation, and consolidation gives absorbed findings their own status
instead of overloading the false-positive flag. Everything else keeps the
source's shape: the grade vocabulary, the thin-evidence ceiling, the skeptical
needs-review default, the digit-stripped consolidation signature, and the rule
that the deterministic layer only ever moves severity downward while a raise
needs quoted proof.

A verbatim quote is citation integrity, not exploitability. Nothing in this
module accepts a report on anyone's behalf: acceptance is a human review
decision recorded separately.
"""

from urllib.parse import urlsplit

from .proposals import ProposalError, parse_strict
from .records import SEVERITIES


SEVERITY_RANK = {name: index for index, name in enumerate(SEVERITIES)}

# The grade vocabulary and the holding ceiling, same shape as the originating
# implementation's: thin evidence cannot hold more than medium.
EVIDENCE_GRADES = ("strong", "moderate", "thin")
EVIDENCE_CEILING = {"thin": "medium", "moderate": "critical", "strong": "critical"}

# What a RAISE may reach, by grade -- deliberately stricter than the holding
# ceiling, a labeled teaching policy: raising a severity needs more evidence
# than keeping one. The originating implementation uses its single holding
# table for both, so a moderate-graded finding there can be raised to
# critical; lesson 8 states the difference where the rule is built.
RAISE_CEILING = {"thin": "medium", "moderate": "high", "strong": "critical"}
MIN_STRING_EVIDENCE_CHARS = 40

VERDICTS = ("accept", "reject", "needs_review", "adjust_severity")
VERDICT_KEYS = frozenset({"verdict", "reason", "quote", "severity"})


def evidence_grade(*, request=None, response_body="", string_evidence=""):
    """Grade what the record supports: strong, moderate or thin.

    Both sides of the exchange present grades strong; one side, or a bare
    string of evidence at least MIN_STRING_EVIDENCE_CHARS long, grades
    moderate; anything less grades thin. The grade measures record
    completeness, not truth: a complete capture of an innocent response still
    grades strong.
    """
    has_request = isinstance(request, dict) and bool(request)
    has_response = isinstance(response_body, str) and bool(response_body.strip())
    if has_request and has_response:
        return "strong"
    if has_request or has_response:
        return "moderate"
    if isinstance(string_evidence, str) and \
            len(string_evidence.strip()) >= MIN_STRING_EVIDENCE_CHARS:
        return "moderate"
    return "thin"


def apply_ceiling(severity, grade):
    """The grade ceiling, applied monotonically downward."""
    ceiling = EVIDENCE_CEILING[grade]
    if SEVERITY_RANK[severity] > SEVERITY_RANK[ceiling]:
        return ceiling
    return severity


def govern_finding(finding, *, grade):
    """The deterministic severity policy over one finding.

    This layer only ever lowers: the ceiling for the finding's evidence grade
    is applied, and the record keeps the original severity beside the final
    one. Raising is not this function's power at all; a raise happens only
    through a verdict carrying quoted proof, below.
    """
    final = apply_ceiling(finding.severity, grade)
    return {
        "finding_id": finding.finding_id,
        "original_severity": finding.severity,
        "severity": final,
        "evidence_grade": grade,
        "ceiling_enforced": final != finding.severity,
    }


def verifier_packet(finding, capture):
    """Exactly what the verifier is shown: this finding, its capture, nothing else.

    Isolation is structural: the packet is built from the one capture the
    finding cites, so a verifier cannot read a foreign capture because no
    foreign capture is in front of it.
    """
    if capture.capture_id != finding.capture_id:
        raise ValueError("packet capture is not the finding's capture")
    return {
        "finding": {
            "finding_id": finding.finding_id,
            "kind": finding.kind,
            "title": finding.title,
            "severity": finding.severity,
            "quote": finding.quote,
        },
        "capture": {
            "capture_id": capture.capture_id,
            "status": capture.status,
            "body": capture.body,
        },
        "verdict_schema": {
            "verdict": list(VERDICTS),
            "reason": "nonempty string",
            "quote": "verbatim from the capture body, required for a raise",
            "severity": "target severity, required for adjust_severity",
        },
    }


def run_verifier(provider, finding, capture):
    """One provider call over the isolated packet; strict parse of the answer."""
    packet = verifier_packet(finding, capture)
    try:
        raw = provider(packet)
    except Exception as exc:
        return {"parsed": False, "reason": f"provider error: {type(exc).__name__}"}
    try:
        reply = parse_strict(raw)
    except ProposalError as exc:
        return {"parsed": False, "reason": str(exc)}
    unknown = set(reply) - VERDICT_KEYS
    if unknown:
        return {"parsed": False,
                "reason": f"verdict carries unknown fields: {sorted(unknown)}"}
    return {"parsed": True, "reply": reply}


class VerificationPipeline:
    """Host-validated verdicts over a run's findings, with their own ledger.

    The pipeline reads immutable records (findings and captures) from the
    recorder and keeps the governed view plus an ordered verdict ledger of its
    own; verdicts it turns away are also recorded through the run's write
    boundary as refusals, so the run's story carries them too.
    """

    def __init__(self, recorder):
        self.recorder = recorder
        self._governed = {}
        self._ledger = []

    def govern(self, finding, *, request=None):
        held = self.recorder.snapshot()["findings"]
        if not any(f["finding_id"] == finding.finding_id for f in held):
            return {"applied": False,
                    "reason": "finding is not held by this run's recorder"}
        capture = self.recorder.capture(finding.capture_id)
        grade = evidence_grade(request=request,
                               response_body=capture.body if capture else "",
                               string_evidence=finding.quote)
        row = govern_finding(finding, grade=grade)
        row.update({"kind": finding.kind, "title": finding.title,
                    "capture_id": finding.capture_id, "quote": finding.quote,
                    "false_positive": False, "status": "governed",
                    "verdicts": []})
        self._governed[finding.finding_id] = row
        return dict(row)

    def governed(self, finding_id):
        row = self._governed.get(finding_id)
        return dict(row) if row else None

    def _refuse(self, finding_id, reason):
        self.recorder.refuse("verdict", reason, {"finding_id": finding_id,
                                                 "run_id": self.recorder.run.run_id})
        entry = {"finding_id": finding_id, "applied": False, "reason": reason}
        self._ledger.append(entry)
        return dict(entry)

    def apply_verdict(self, finding_id, verifier_answer):
        """Validate one verifier answer in host code and apply what it may do."""
        row = self._governed.get(finding_id)
        if row is None:
            return self._refuse(finding_id, "verdict names an ungoverned finding")
        if not verifier_answer.get("parsed"):
            return self._refuse(finding_id,
                                f"unusable verifier answer: "
                                f"{verifier_answer.get('reason', 'unparsed')}")
        reply = verifier_answer["reply"]
        verdict = reply.get("verdict")
        if verdict not in VERDICTS:
            # The originating implementation's verdict branch read anything it
            # did not recognize as a true-positive confirmation; here an
            # unknown verdict changes nothing and leaves a recorded reason.
            return self._refuse(finding_id,
                                f"unknown verdict {verdict!r}; a verdict is one "
                                f"of {', '.join(VERDICTS)}")
        reason = reply.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            return self._refuse(finding_id, "a verdict carries a nonempty reason")

        capture = self.recorder.capture(row["capture_id"])
        before = row["severity"]
        entry = {"finding_id": finding_id, "verdict": verdict, "reason": reason,
                 "before": before, "applied": True}

        if verdict == "accept":
            entry["after"] = before
        elif verdict == "reject":
            row["false_positive"] = True
            row["status"] = "rejected"
            entry["after"] = before
            # The finding and its evidence stay visible: a rejection is a
            # verifier's opinion on the record, and a human can overrule it.
        elif verdict == "needs_review":
            if SEVERITY_RANK[before] > SEVERITY_RANK["medium"]:
                row["severity"] = "medium"
            row["status"] = "needs_review"
            entry["after"] = row["severity"]
        else:  # adjust_severity
            target = reply.get("severity")
            if target not in SEVERITIES:
                return self._refuse(finding_id,
                                    f"adjust_severity needs a known severity, "
                                    f"got {target!r}")
            if SEVERITY_RANK[target] <= SEVERITY_RANK[before]:
                row["severity"] = target
                entry["after"] = target
            else:
                refusal = self._raise_refusal(row, reply, capture)
                if refusal is not None:
                    return self._refuse(finding_id, refusal)
                row["severity"] = target
                entry["after"] = target
                entry["raised_against_proof"] = True

        row["verdicts"].append(entry)
        self._ledger.append(entry)
        return dict(entry)

    def _raise_refusal(self, row, reply, capture):
        """Why a raise may not happen, or None when the proof carries it."""
        quote = reply.get("quote")
        if not isinstance(quote, str) or not quote.strip():
            return "a raise needs a quote"
        if capture is None or quote not in capture.body:
            # The originating implementation checked only that the quote was
            # nonempty at verdict time; containment lived in a prompt
            # contract. Here the host re-checks the bytes.
            return "the raise quote does not occur verbatim in the finding's " \
                   "own capture"
        target = reply["severity"]
        ceiling = RAISE_CEILING[row["evidence_grade"]]
        if SEVERITY_RANK[target] > SEVERITY_RANK[ceiling]:
            return (f"the finding's evidence grade "
                    f"({row['evidence_grade']}) caps a raise at {ceiling}")
        return None

    # Consolidation --------------------------------------------------------------

    def consolidation_signature(self, row):
        """The source-shaped signature: kind plus the digit-stripped title."""
        title = "".join(ch for ch in row["title"] if not ch.isdigit())
        title = " ".join(title.split()).lower()
        return (row["kind"].lower(), title)

    def _host_of(self, row):
        capture = self.recorder.capture(row["capture_id"])
        if capture is None:
            return None
        destination = capture.action_id.split(" -> ", 1)[-1]
        host = urlsplit(destination).hostname
        return host.lower() if host else None

    def consolidate(self):
        """Collapse one signature spanning two or more hosts into a primary.

        Absorbed members keep their evidence and get their own status,
        "absorbed", pointing at the primary. The originating implementation
        instead set the absorbed members' false-positive flag, giving a column
        that means "not real" a second meaning; chapter 05 records why that
        overloading is a hazard, and this pipeline keeps the two populations
        in separate words.
        """
        groups = {}
        for finding_id, row in sorted(self._governed.items()):
            if row["false_positive"] or row["status"] == "absorbed":
                continue
            host = self._host_of(row)
            if host is None:
                continue  # hostless findings are never grouped
            key = self.consolidation_signature(row)
            groups.setdefault(key, []).append((finding_id, row, host))

        report = []
        for key, members in sorted(groups.items()):
            hosts = {host for _, _, host in members}
            if len(hosts) < 2:
                continue
            primary_id, primary, _ = max(
                members, key=lambda item: (SEVERITY_RANK[item[1]["severity"]],
                                           item[0]))
            for finding_id, row, _ in members:
                if finding_id != primary_id:
                    row["status"] = "absorbed"
                    row["consolidated_into"] = primary_id
            primary["affected_hosts"] = sorted(hosts)
            report.append({"signature": list(key), "primary_id": primary_id,
                           "affected_hosts": sorted(hosts),
                           "absorbed_ids": sorted(fid for fid, _, _ in members
                                                  if fid != primary_id)})
        return report

    def snapshot(self):
        return {
            "governed": {fid: dict(row)
                         for fid, row in sorted(self._governed.items())},
            "verdict_ledger": [dict(e) for e in self._ledger],
        }
