"""The fixture contract: what a committed walkthrough input may contain.

A fixture is a captured exchange or a replayed model response, never a live request --
`core/` has no network layer, so nothing here is intercepted or replayed over a socket.
Validation returns a list of problems rather than raising, so a regeneration run can report
every defect in a batch instead of stopping at the first.

Provenance names the rule that fired and the finding type, and validation REFUSES the fields
that would identify a target: any of `host`, `client`, `scan_id` or `url` inside provenance is
a problem, whatever its value. That is a match condition on the key, not a scan of the value,
so it cannot be defeated by an identifier nobody enumerated.
"""
import json

FIXTURE_KINDS = ("exchange", "insights")
_FORBIDDEN_PROVENANCE = ("host", "client", "scan_id", "url")
_MIN_INSIGHTS = 3


def load_fixture(path):
    """Read one fixture from `path`. Malformed JSON raises, it is never skipped."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def validate_fixture(obj):
    """Every problem with `obj`, as a list of human-readable strings; empty means valid."""
    problems = []
    if not isinstance(obj, dict):
        return ["fixture is not an object"]
    kind = obj.get("kind")
    if kind not in FIXTURE_KINDS:
        problems.append(f"kind {kind!r} is not one of {FIXTURE_KINDS}")
    prov = obj.get("provenance")
    if not isinstance(prov, dict):
        problems.append("provenance is missing")
    else:
        for key in ("rule_id", "finding_type"):
            if not prov.get(key):
                problems.append(f"provenance.{key} is missing")
        for key in _FORBIDDEN_PROVENANCE:
            if key in prov:
                problems.append(f"provenance.{key} identifies a target and is refused")
    if kind == "exchange":
        req, resp = obj.get("request"), obj.get("response")
        if not isinstance(req, dict):
            problems.append("request is missing")
        else:
            for key in ("method", "url"):
                if not req.get(key):
                    problems.append(f"request.{key} is missing")
        if not isinstance(resp, dict):
            problems.append("response is missing")
        else:
            if "status" not in resp:
                problems.append("response.status is missing")
            if "url" not in resp:
                problems.append("response.url is missing")
    elif kind == "insights":
        ins = obj.get("insights")
        if not isinstance(ins, list) or len(ins) < _MIN_INSIGHTS:
            problems.append(
                f"insights needs at least three entries; one triggers the critic's "
                f"forced-keep floor and masks containment"
            )
        if not obj.get("intel_context"):
            problems.append("intel_context is missing")
    return problems
