"""Deterministic structured retrieval: four lanes of plain SQL, no embeddings.

Free-text search answers "what do we remember about X". These lanes answer
narrower questions a planner actually asks -- which tools paid on stacks like
this one, what did earlier runs find on this same engagement, which learned
tactics apply -- and they answer with sample sizes attached, because a zero-hit
row over a real denominator is a directive while a zero over a lone try is noise.

Two properties travel with every lane. Negative results are first-class: a tool
that has been tried often and paid nothing is reported as exactly that, with
its denominator, and the rendering says deprioritize rather than skip. And
everything here is advisory: lane output is data carrying provenance
references; it reorders and annotates work, and the host's policy objects
remain the only authority on what may run.

Priors rank by the Wilson lower bound of the hit rate rather than the raw
ratio, because a raw ratio puts a single lucky try above a
well-evidenced partial rate, which is exactly backwards under small samples.
"""

import math


MIN_SIMILARITY = 0.5
DRY_MIN_SAMPLE = 3  # a zero-hit row needs at least this many tries to mean anything


def profile_similarity(a, b):
    """Component-wise similarity of two colon-joined stack fingerprints.

    Unequal component counts score 0.0 outright. Components where either side
    is unknown, none or empty are skipped as incomparable. The matched fraction
    is damped by min(1, comparable / 3), so a nearly-empty fingerprint that
    happens to agree on one component does not match everything at full
    confidence.
    """
    parts_a = (a or "").split(":")
    parts_b = (b or "").split(":")
    if len(parts_a) != len(parts_b):
        return 0.0
    neutral = {"unknown", "none", ""}
    matched = comparable = 0
    for x, y in zip(parts_a, parts_b):
        if x.lower() in neutral or y.lower() in neutral:
            continue
        comparable += 1
        if x.lower() == y.lower():
            matched += 1
    if not comparable:
        return 0.0
    confidence = min(1.0, comparable / 3.0)
    return (matched / comparable) * confidence


def wilson_lower_bound(hits, n, z=1.96):
    """The lower bound of the Wilson score interval for a hit rate."""
    if n <= 0:
        return 0.0
    phat = hits / n
    denom = 1 + z * z / n
    centre = phat + z * z / (2 * n)
    margin = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / denom)


def profile_priors(store, profile_hash, *, min_similarity=MIN_SIMILARITY):
    """Per-tool prior evidence, aggregated across similar profiles.

    Contributions are similarity-weighted: yield = sum(hits_i * sim_i) /
    sum(n_i * sim_i); the ranking confidence is the Wilson lower bound over the
    raw pooled counts. Priors order work and are not plan entries: a tool
    deprioritized on its own silence could otherwise no longer correct the
    record.
    """
    rows = store.connection.execute(
        "SELECT tool_name, profile_hash, executions, hits FROM tool_stats"
        " WHERE profile_hash != '__global__' AND executions > 0")
    per_tool = {}
    for row in rows:
        similarity = (1.0 if row["profile_hash"] == profile_hash
                      else profile_similarity(profile_hash, row["profile_hash"]))
        if similarity < min_similarity:
            continue
        entry = per_tool.setdefault(row["tool_name"], {
            "tool": row["tool_name"], "n": 0, "hits": 0,
            "weighted_n": 0.0, "weighted_hits": 0.0,
            "best_similarity": 0.0, "profiles": 0})
        entry["n"] += row["executions"]
        entry["hits"] += row["hits"]
        entry["weighted_n"] += row["executions"] * similarity
        entry["weighted_hits"] += row["hits"] * similarity
        entry["best_similarity"] = max(entry["best_similarity"], similarity)
        entry["profiles"] += 1
    out = []
    for entry in per_tool.values():
        entry["yield"] = round(entry["weighted_hits"] / entry["weighted_n"], 6) \
            if entry["weighted_n"] else 0.0
        entry["confidence"] = round(wilson_lower_bound(entry["hits"], entry["n"]), 6)
        entry["best_similarity"] = round(entry["best_similarity"], 6)
        entry["weighted_n"] = round(entry["weighted_n"], 6)
        entry["weighted_hits"] = round(entry["weighted_hits"], 6)
        entry["dry"] = entry["hits"] == 0 and entry["n"] >= DRY_MIN_SAMPLE
        out.append(entry)
    out.sort(key=lambda e: (-e["confidence"], -e["n"], e["tool"]))
    return out


def host_history(store, engagement, *, exclude_run_id=""):
    """Earlier findings on this engagement, and only this engagement.

    The scoping is the isolation mechanism: a global what-have-we-ever-found
    lane would surface one engagement's hostnames and parameters while working
    an unrelated target. False positives and informational findings are
    excluded; repeats collapse into a single deduplicated row with a times_seen count.
    """
    rows = store.connection.execute(
        "SELECT * FROM findings WHERE engagement = ? AND run_id != ?"
        " AND false_positive = 0 AND LOWER(severity) != 'info'"
        " ORDER BY created_at DESC", (engagement, exclude_run_id))
    collapsed = {}
    for row in rows:
        key = (row["url"], row["type"], row["severity"].lower())
        if key in collapsed:
            collapsed[key]["times_seen"] += 1
        else:
            collapsed[key] = {
                "severity": row["severity"], "title": row["title"],
                "url": row["url"], "type": row["type"], "times_seen": 1,
                "ref": f"finding:{row['finding_id']}"}
    return list(collapsed.values())


def learned_tactics(store, profile_hash, *, min_similarity=MIN_SIMILARITY,
                    per_tool=2):
    """Applicable long-term tactics: proven before hypothesis, refuted excluded.

    Refuted rows are excluded by the store's default read, so a refutation is
    visible here as an absence -- the demonstration the lesson runs. Each row
    keeps a provenance reference and its similarity to the asking profile.
    """
    rows = store.fetch(tier="longterm", record_type="tactic")
    import json as _json
    scored = []
    for row in rows:
        similarity = (1.0 if row["profile_hash"] == profile_hash
                      else profile_similarity(profile_hash, row["profile_hash"]))
        if similarity < min_similarity:
            continue
        meta = _json.loads(row["metadata"])
        scored.append({
            "tool": row["tool_name"], "url_pattern": row["url_pattern"],
            "param_name": meta.get("param_name"),
            "bypass_technique": meta.get("bypass_technique"),
            "evidence_grade": meta["evidence_grade"],
            "success_rate": meta["success_rate"],
            "total_attempts": meta["total_attempts"],
            "similarity": round(similarity, 6),
            "ref": f"tactic:{row['tool_name']}:{row['url_pattern']}"})
    scored.sort(key=lambda t: (t["evidence_grade"] != "proven",
                               -t["success_rate"], -t["total_attempts"],
                               -t["similarity"], t["ref"]))
    capped, seen = [], {}
    for tactic in scored:
        if seen.get(tactic["tool"], 0) >= per_tool:
            continue
        seen[tactic["tool"]] = seen.get(tactic["tool"], 0) + 1
        capped.append(tactic)
    return capped


def render_negative_evidence(priors):
    """The dry-tool section: zero-hit rows with their denominators.

    Only rows with enough tries to mean something appear; a zero over one try
    is left out as noise rather than promoted to a warning. The wording is
    deliberate: deprioritize, do not skip -- absence of evidence is not
    evidence of absence.
    """
    lines = ["Never yielded on this stack -- deprioritize, do not skip:"]
    for entry in priors:
        if entry["dry"]:
            lines.append(f"- {entry['tool']}: 0 hits in {entry['n']} tries")
    return "\n".join(lines) if len(lines) > 1 else ""
