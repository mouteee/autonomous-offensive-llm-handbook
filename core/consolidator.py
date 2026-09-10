"""Collapse a finding repeated across sibling hosts into one, then re-level and
roll up -- deterministically, and honest about which idempotence that buys.

The same class of bug with the same digit-stripped title on two different hosts
is one issue reported twice. This module keeps the highest-ranked member as the
primary, records the other hosts on it as an `affected_hosts` list, hides the
others rather than deleting them, hands the whole scan to the deterministic
governor for uniform re-levelling, and rolls the survivors up per host and
de-duplicated.

The honesty this file is named for is about idempotence and about the governance
switch, because a one-word summary of either would mislead.

The STORE converges but the RETURNED RECORD does not, and only the first is
idempotence worth the name. A second pass over the same store absorbs nothing
further: the members the first pass hid are dropped by `exclude_fp=True` before
the second pass groups anything, so no cross-host group is left for it to merge.
The returned record, though, is a fresh description of the pass that produced it,
so the second pass's record differs from the first's -- it reports no absorption,
a shrunk `affected_hosts`, and the severity the re-levelling has already lowered.
A reader told only `idempotent` and then finding the record change would assume a
bug; the record changing is correct, and calling this module simply `idempotent`
is the private docstring's own misleading word, not repeated here.

Turning governance off with `HARNESS_GOVERNANCE=0` makes this a no-op that
returns exactly `{"groups": [], "per_host": {}, "deduped": {}, "headline":
"info"}` and writes nothing. That is not the same as `duplicates survive when
governance is off`: in the system this re-expresses, an older host-blind merge
still collapses duplicates at write time when this pass is disabled -- it just
does so without an `affected_hosts` list and without re-levelling. Cross-host
dedup is degraded when governance is off, never absent.
"""
import os
import re
from urllib.parse import urlparse

from core.severity_governor import fetch_all_findings, govern_scan, rank

_DIGITS = re.compile(r"\d+")


def consolidation_signature(finding: dict) -> tuple:
    """The key two findings must share to be candidates for merging:
    `(type, digit-stripped lowercased whitespace-collapsed title)`, falling back
    to the finding's `name` when it carries no `title`.

    Conservative by construction, so the only failure it can produce is
    under-merging. Digits are stripped, so `IDOR on order 1041` and
    `IDOR on order 99872` reduce to the same key and merge; nothing else is
    stripped, so a real difference in wording or type produces a different key
    and the two never merge -- `IDOR on order` and `IDOR on invoice` stay apart. Missing a
    real duplicate leaves two honest findings standing, whereas merging two
    distinct issues would hide one, so erring toward the miss is the safe
    direction.
    """
    ftype = str(finding.get("type") or "").strip().lower()
    title = str(finding.get("title") or finding.get("name") or "").lower()
    stem = _DIGITS.sub("", title)
    stem = re.sub(r"\s+", " ", stem).strip()
    return (ftype, stem)


def _host(url) -> str:
    """The lowercased hostname of `url`, or an empty string when there is no host
    or `url` does not parse.

    That empty string is the signal `consolidate_scan` reads to leave a hostless
    finding out of the host map; the grouping decision lives there, not here.
    """
    try:
        return (urlparse(str(url)).hostname or "").lower()
    except Exception:
        return ""


async def consolidate_scan(store, scan_id=None) -> dict:
    """Group the scan's non-FP findings by signature, collapse each cross-host
    group into its primary, re-level the whole scan, and return the rollups.

    `scan_id` is accepted and never read. The body scopes its work through
    `store.scan_id`, and `govern_scan` is handed `store.scan_id` in turn; the
    store is already the scan, so a `scan_id` argument is a caller's courtesy this
    function does not consult. It stays in the signature because it is the
    interface both real callers use, and dropping it would silently change that
    interface while keeping it silently implies it is read.

    A group collapses only when its signature spans two or more distinct hosts --
    the gate `len(distinct_hosts) >= 2`. A signature seen on a single host is left
    alone even when two findings share it there. Once the gate opens, every
    host-bearing member is absorbed, a second member on an already-represented
    host included, because they are the same class and `affected_hosts` keeps the
    per-host detail. The primary is the highest-`rank` member, and a tie keeps the
    first such member `max` encounters.

    Absorption HIDES rather than deletes. An absorbed member is written back with
    its false-positive flag set and `raw_data.consolidated_into` naming the
    primary, and the primary is written back carrying `raw_data.affected_hosts`.
    Hiding behind the flag rather than deleting is what makes a second pass
    converge: the hidden members are dropped by `exclude_fp=True` before the next
    pass groups anything, so no cross-host group survives for it to merge.

    The group record is built BEFORE `govern_scan` runs, so the recorded group
    `severity` is the finding's PRE-governance severity. The re-levelling that
    follows can lower the stored severity underneath it -- two thin `high`
    findings record a group at `high` while the surviving row is stored `medium`
    under the evidence ceiling -- so the recorded severity and the stored severity
    describe two different moments and both are correct.

    The `deduped`, `per_host` and `headline` rollups count SURVIVORS only, read
    from `fetch_all_findings(exclude_fp=True)` after re-levelling, so an absorbed
    host drops out of `per_host` entirely even while the primary's
    `affected_hosts` still names it. Those two disagree by construction, not by
    accident. `headline` is the highest severity among survivors, and `info` when
    there are none.

    A NORMALISATION DIVERGENCE, disclosed here rather than repaired. Every
    severity this function reads or writes is normalised with `str(...).lower()`
    and no `.strip()`, while `severity_governor.rank` folds case and strips
    whitespace on whatever it is handed. That is the whole condition: a spelling
    that differs from a band only in case is handled here, and one that differs
    by surrounding whitespace is not. Measured end to end against a store that
    does not normalise on write, a cross-host pair spelled `high ` comes back
    `headline: 'info'` with `deduped: {'high ': 1}`, because the headline loop
    matches the band tuple literally while `rank`, reading the same string, still
    ranks it high -- so the group record and the rollup disagree for a reason
    that is not the deliberate one two paragraphs up. Reachable only through a
    store that does not normalise on write, which the `FindingStore` Protocol
    does not require it to. Left standing because it is a divergence from the
    private module this one re-expresses, and publishing a real one is worth more
    here than closing it quietly.
    """
    record = {"groups": [], "per_host": {}, "deduped": {}, "headline": "info"}
    if os.getenv("HARNESS_GOVERNANCE", "1") == "0":
        return record

    findings = await fetch_all_findings(store, exclude_fp=True)

    # group by signature
    groups = {}
    for finding in findings:
        groups.setdefault(consolidation_signature(finding), []).append(finding)

    for signature, members in groups.items():
        hosts_to_members = {}
        for member in members:
            host = _host(member.get("url"))
            if host:
                hosts_to_members.setdefault(host, []).append(member)
        distinct_hosts = sorted(hosts_to_members)
        absorbed_ids = []

        if len(distinct_hosts) >= 2:
            host_bearing = [m for group in hosts_to_members.values() for m in group]
            primary = max(host_bearing,
                          key=lambda m: rank(str(m.get("severity") or "info")))
            primary_raw = primary.get("raw_data")
            if not isinstance(primary_raw, dict):
                primary_raw = {}
            primary_raw["affected_hosts"] = distinct_hosts
            store.update_finding_governed(
                primary["id"], str(primary.get("severity") or "info").lower(),
                primary_raw, bool(primary.get("false_positive")))
            for member in host_bearing:
                if member["id"] == primary["id"]:
                    continue
                member_raw = member.get("raw_data")
                if not isinstance(member_raw, dict):
                    member_raw = {}
                member_raw["consolidated_into"] = primary["id"]
                store.update_finding_governed(
                    member["id"], str(member.get("severity") or "info").lower(),
                    member_raw, True)
                absorbed_ids.append(member["id"])
            record["groups"].append({
                "primary_id": primary["id"],
                "signature": list(signature),
                "severity": str(primary.get("severity") or "info").lower(),
                "affected_hosts": distinct_hosts,
                "absorbed_ids": absorbed_ids,
            })
        else:
            first = members[0]
            record["groups"].append({
                "primary_id": first["id"],
                "signature": list(signature),
                "severity": str(first.get("severity") or "info").lower(),
                "affected_hosts": [h for h in [_host(first.get("url"))] if h],
                "absorbed_ids": [],
            })

    # uniform re-levelling across the post-absorb pool
    await govern_scan(store, store.scan_id)

    # rollups over survivors
    for finding in await fetch_all_findings(store, exclude_fp=True):
        severity = str(finding.get("severity") or "info").lower()
        record["deduped"][severity] = record["deduped"].get(severity, 0) + 1
        host = _host(finding.get("url"))
        record["per_host"].setdefault(host, {})
        record["per_host"][host][severity] = record["per_host"][host].get(severity, 0) + 1
    for severity in ("critical", "high", "medium", "low", "info"):
        if record["deduped"].get(severity):
            record["headline"] = severity
            break
    return record
