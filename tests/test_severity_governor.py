"""The governor: gravity points down, and there is no path back up."""
import itertools, json, pathlib, pytest
from core.severity_governor import (
    SEVERITY_RANK, EVIDENCE_CEILING, rank, evidence_grade, govern_finding,
    load_rules, match_rules, normalize_finding_evidence, resolve_environment,
    govern_scan, fetch_all_findings, _validated_rules,
)

SEVS = ["info", "low", "medium", "high", "critical"]
GRADES = ["thin", "moderate", "strong"]


_REQ = {"method": "GET", "url": "https://shop.example/x"}
_RESP = {"status": 200, "body": "x"}


def _finding(sev, grade, **kw):
    """Fixtures built from the MEASURED grader, not from its docstring.

    `strong` is request AND response. `moderate` is exactly ONE of the two --
    a request+response pair is already strong, so a fixture carrying both and
    calling itself moderate grades strong and quietly tests nothing.
    """
    f = {"type": "vulnerability", "title": "t", "severity": sev, "url": "https://shop.example/x"}
    if grade == "strong":
        f["raw_data"] = {"request": dict(_REQ), "response": dict(_RESP)}
    elif grade == "moderate":
        f["raw_data"] = {"response": dict(_RESP)}       # one side only
    f.update(kw)
    return f


def test_the_governor_never_escalates_over_the_whole_space():
    """Swept, not sampled: no (severity, grade, environment) triple raises."""
    rules = load_rules()
    for sev, grade, env in itertools.product(SEVS, GRADES, ["uat", "prod"]):
        before = rank(sev)
        after = rank(govern_finding(_finding(sev, grade), rules=rules, env=env)["severity"])
        assert after <= before, f"escalated: {sev}/{grade}/{env} -> {after}"


def test_thin_evidence_caps_at_medium_whatever_is_claimed():
    for sev in ["high", "critical"]:
        out = govern_finding(_finding(sev, "thin"), rules=load_rules(), env="prod")
        assert rank(out["severity"]) <= SEVERITY_RANK["medium"]


def test_evidence_grade_reads_the_artifacts_not_the_claim():
    """A finding that merely asserts its own grade does not get it: the grade is
    read off the artifacts and the asserted key is never consulted."""
    assert evidence_grade(_finding("critical", "thin")) == "thin"
    assert evidence_grade(_finding("low", "moderate")) == "moderate"
    assert evidence_grade(_finding("low", "strong")) == "strong"
    lying = _finding("critical", "thin")
    lying["evidence_grade"] = "strong"
    assert evidence_grade(lying) == "thin"


def test_the_grader_reads_the_poc_keys_and_not_the_obvious_ones():
    """Measured, and it is the trap in this task. The grader looks for
    `poc_curl`/`poc` and `poc_output` -- NOT `curl` and `output`. A fixture
    using the obvious names grades thin, and a re-implementation reading the
    obvious names passes a test that never exercised the branch."""
    obvious = {"type": "v", "title": "t", "severity": "high", "url": "u",
               "raw_data": {"curl": "curl u", "output": "x"}}
    assert evidence_grade(obvious) == "thin"
    real = {"type": "v", "title": "t", "severity": "high", "url": "u",
            "raw_data": {"poc_curl": "curl u", "poc_output": "x"}}
    assert evidence_grade(real) == "strong"


def test_one_side_alone_is_moderate_and_an_empty_dict_is_not_a_side():
    assert evidence_grade({"raw_data": {"request": dict(_REQ)}}) == "moderate"
    assert evidence_grade({"raw_data": {"response": dict(_RESP)}}) == "moderate"
    assert evidence_grade({"raw_data": {}}) == "thin"
    # An empty request dict is not a request.
    assert evidence_grade({"raw_data": {"request": {}, "response": dict(_RESP)}}) == "moderate"
    assert evidence_grade({"raw_data": {"request": {}}}) == "thin"


def test_a_long_evidence_string_grades_moderate():
    """A 40-character-or-longer string `evidence` counts as moderate. Nothing
    in the plan's first draft mentioned this branch."""
    assert evidence_grade({"raw_data": {"evidence": "x" * 40}}) == "moderate"
    assert evidence_grade({"raw_data": {"evidence": "x" * 39}}) == "thin"


def test_moderate_and_strong_reach_the_same_ceiling():
    """Three grades, two distinct ceilings. A reader will assume moderate is
    capped somewhere and it is not -- only thin caps."""
    assert EVIDENCE_CEILING["thin"] == "medium"
    assert EVIDENCE_CEILING["moderate"] == EVIDENCE_CEILING["strong"] == "critical"


def test_a_missing_rules_file_yields_no_rules_and_does_not_raise():
    """Documented behaviour: missing file -> [], governor still runs its own checks."""
    assert load_rules("/nonexistent/path/severity_rules.json") == []
    out = govern_finding(_finding("critical", "thin"), rules=[], env="prod")
    assert rank(out["severity"]) <= SEVERITY_RANK["medium"]      # evidence check still ran


def test_cvss_reconcile_fails_closed_on_an_unlabelled_vector():
    """An unlabelled vector is NOT treated as authored, so it produces NO
    downgrade. The private branch treats a missing cvss_source key as authored
    and lowers on it; this one leaves the asserted severity alone and records
    that it skipped, so a scan can report how often a vector went unattributed
    instead of losing the number.

    The skip is reported on the finding and NOT inside `raw_data`, which is where
    a record would be persisted from. A skip is not a change and a stored record
    on an unchanged row is what makes a coverage count mean something other than
    its name, so both halves are asserted: the report is present and the record
    is absent."""
    f = _finding("critical", "strong")
    f["cvss_vector"] = "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:L/I:N/A:N"   # scores 4.3
    out = govern_finding(f, rules=load_rules(), env="prod")
    assert out["severity"] == "critical"
    assert not out.get("rules_fired")
    assert out["reconcile_skipped"] == ["cvss-reconcile-skipped-unattributed"]
    assert out.get("governance_record") in (None, {}, [])
    assert "governance" not in out["raw_data"]


def test_a_governance_record_is_written_only_when_something_changed():
    unchanged = govern_finding(_finding("low", "strong"), rules=load_rules(), env="uat")
    assert not unchanged.get("rules_fired")
    assert unchanged.get("governance_record") in (None, {}, [])


def test_every_shipped_rule_parses_and_carries_a_rationale():
    """Measured shapes: `cap_at` splits by environment on two of the shipped
    rules and does not on two others, and `mark_fp` carries no severity target
    at all. Flattening the split silently caps a PRODUCTION tokenization-key
    leak at medium, which is why the split is asserted per rule and not as a
    property of the file."""
    rules = load_rules()
    assert rules, "the shipped rules file must not be empty"
    assert len(rules) == 6
    assert [r["id"] for r in rules] == [
        "tokenization-key-public", "read-via-post-bounce", "spa-fallback-api-200",
        "source-map-disclosure", "csp-weakness", "cors-wildcard",
    ]
    for r in rules:
        assert r.get("id") and r.get("action") and r.get("rationale"), r
        assert r["action"] in {"mark_fp", "downgrade_to", "cap_at"}
    by_id = {r["id"]: r for r in rules}
    assert by_id["tokenization-key-public"]["severity_uat"] == "medium"
    assert by_id["tokenization-key-public"]["severity_prod"] == "high"
    assert by_id["csp-weakness"]["severity"] == "medium"
    assert "severity" not in by_id["read-via-post-bounce"]


def test_every_regex_in_the_rules_file_compiles():
    """A translation slip in a pattern carrying | [ (?i) or an escaped dot fails
    here rather than silently matching nothing for the rest of the project."""
    import re as _re
    keys = ("evidence_regex", "title_regex", "url_regex")
    seen = 0
    for r in load_rules():
        for k in keys:
            if r.get("match", {}).get(k):
                _re.compile(r["match"][k])
                seen += 1
    assert seen >= 5, f"expected at least five regex conditions, found {seen}"


def test_no_rationale_cites_source_this_phase_does_not_ship():
    """No rationale may name a source file or a private-looking symbol.

    The rationale this rule was written for ended by naming two symbols from a
    module that is not in this repository, which is citing past what ships --
    the defect the chapters were corrected for. It is asserted by SHAPE rather
    than by a list of the symbols, because a list would carry those names into
    the public tree to guard against them, which is the thing it is guarding
    against. What the shape catches is a `.py` path and an identifier opening
    with an underscore; a bare method name with no distinguishing shape cannot
    be caught mechanically and stays a review item, stated here so nobody reads
    this check as covering more than it does.
    """
    import pathlib as _p
    import re as _re
    src = _p.Path("core/severity_rules.json").read_text(encoding="utf-8")
    for rule in json.loads(src)["rules"]:
        rationale = rule["rationale"]
        assert not _re.search(r"[\w/]+\.py\b", rationale), rule["id"]
        assert not _re.search(r"(?<![\w])_[A-Za-z]\w*", rationale), rule["id"]


def test_the_rules_path_is_derived_from_the_module_and_is_not_absolute():
    """An absolute default would carry a home directory and a repository name
    into a public file. The sanitization gate would reject it; it should not
    have to be the thing that catches it."""
    from core.severity_governor import DEFAULT_RULES_PATH
    assert not str(DEFAULT_RULES_PATH).startswith("/Users")
    assert "severity_rules.json" in str(DEFAULT_RULES_PATH)


class _Store:
    """Double for the two store members `govern_scan` reaches. `get_findings`
    pages; `update_finding_governed` is SYNCHRONOUS and both callers invoke it
    without `await`, so a double that makes it a coroutine silently records
    nothing."""

    def __init__(self, findings):
        self.rows = [dict(f) for f in findings]
        self.scan_id = "scan-1"
        self.governed = []

    async def get_findings(self, severity=None, finding_type=None, validated_only=False,
                           exclude_fp=True, limit=100, offset=0):
        rows = [f for f in self.rows if not (exclude_fp and f.get("false_positive"))]
        return [dict(r) for r in rows[offset:offset + limit]]

    def update_finding_governed(self, finding_id, severity, raw_data, false_positive=False):
        self.governed.append((finding_id, severity, bool(false_positive)))
        for f in self.rows:
            if f["id"] == finding_id:
                f["severity"] = severity
                f["raw_data"] = raw_data
                f["false_positive"] = bool(false_positive)


def test_govern_scan_writes_only_what_changed():
    import asyncio
    store = _Store([dict(_finding("critical", "thin"), id="1"),
                    dict(_finding("low", "strong"), id="2")])
    summary = asyncio.run(govern_scan(store, rules=load_rules()))
    assert summary["total"] == 2
    assert summary["changed"] == 1                      # only the thin critical moved
    assert [c["id"] for c in summary["changes"]] == ["1"]
    assert [g[0] for g in store.governed] == ["1"]      # the unchanged row was never written


def test_fetch_all_findings_pages_past_the_store_limit():
    """The paging is a correctness property, not a convenience: a single-page
    fetch silently truncates a large consolidation."""
    import asyncio
    store = _Store([dict(_finding("low", "strong"), id=str(i)) for i in range(25)])
    assert len(asyncio.run(fetch_all_findings(store, page=10))) == 25


# --- Added here, not in the brief, each for a measured reason ---------------

# One fixture per shipped rule, for the cross-product sweep below. Why that
# sweep exists is in its own docstring, where the audit reads it.
_MATCHING = [
    {"type": "csp_weakness", "title": "CSP allows unsafe-inline"},
    {"type": "wildcard", "title": "Access-Control-Allow-Origin wildcard"},
    {"type": "secret", "title": "key in bundle",
     "raw_data": {"evidence": "authorizationKey found in bundle"}},
    {"type": "source_code_disclosure", "title": "source map exposed"},
    {"type": "access_control", "title": "unauthenticated write succeeded",
     "raw_data": {"evidence": "session expired, please log in"}},
    {"type": "misconfiguration", "title": "endpoint returned 200",
     "url": "https://shop.example/api/v1/orders",
     "raw_data": {"evidence": "<app-root></app-root>"}},
]


_PLAIN = {"type": "vulnerability", "title": "t"}
# Severity spellings the sweep feeds. See the sweep's own docstring for what
# the whitespace ones do and do not reach.
_SPELLINGS = SEVS + [s + " " for s in SEVS] + [" " + s.title() for s in SEVS]
_BELOW = "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:L/I:N/A:N"     # scores into medium
_ABOVE = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"     # scores into critical


def _probe(base, sev, grade, vector=None, source=None):
    """A fixture crossing one rule-matching shape with one grade and one vector."""
    probe = _finding(sev, grade)
    raw = dict(probe.get("raw_data") or {})
    extra = json.loads(json.dumps(base))
    raw.update(extra.pop("raw_data", None) or {})
    probe.update(extra)
    probe["severity"] = sev
    probe["raw_data"] = raw
    if vector:
        probe["cvss_vector"] = vector
    if source:
        probe["cvss_source"] = source
    return probe


def test_no_combination_of_the_three_signals_can_raise_a_severity():
    """The whole space, because each guard that can change a severity needs
    something watching it and the sweep above watches one of them.

    Measured, and it is why this test exists: the swept fixture above carries no
    CVSS vector and matches no rule, so it exercises the evidence ceiling alone.
    Flipping the CVSS guard so a higher-scoring vector raises, or a rule's cap
    guard so a higher cap raises, leaves it green -- both mutations were run.
    This crosses every rule-matching shape with every severity, grade,
    environment, vector position and provenance label, and fails on all three
    mutations.

    It also feeds severities spelled with stray whitespace, and it must be said
    that those do NOT make it catch the whitespace-bypass class. Measured: with
    the strips removed from both `rank` and this module's own reading of the
    claimed severity, a thin `"critical "` comes back ungoverned as
    `"critical "`, and both sides of the comparison below rank zero, so this
    sweep passes. The class is caught by
    test_a_severity_carrying_stray_whitespace_is_governed_identically, which
    asserts equality with the stripped spelling instead. The spellings stay here
    because exercising the path costs nothing; the guarantee is next door.
    """
    rules = load_rules()
    assert not match_rules(_probe(_PLAIN, "high", "thin"), rules), (
        "the plain fixture is supposed to match no rule -- that is the gap this covers")
    for base in [_PLAIN] + _MATCHING:
        matching = base is not _PLAIN
        for sev, grade, env in itertools.product(_SPELLINGS, GRADES, ["uat", "prod"]):
            for vector in (None, _BELOW, _ABOVE):
                for source in (None, "authored", "derived(severity+unauth-network)"):
                    probe = _probe(base, sev, grade, vector, source)
                    if matching:
                        assert match_rules(probe, rules), f"matches no rule: {base}"
                    after = rank(govern_finding(probe, rules=rules, env=env)["severity"])
                    assert after <= rank(sev), (
                        f"escalated: {base['type']}/{sev}/{grade}/{env}/"
                        f"{'vector' if vector else 'no vector'}/{source}")


def test_a_vector_scoring_above_the_claim_changes_nothing():
    """Reconciliation is a ratchet, and it only turns downwards.

    The legible companion to the sweep above, kept separate because the hole it
    covers was real: with the CVSS guard flipped from `rank(band) >= rank(current)`
    to `==`, a low finding carrying an authored vector in the critical band came
    back critical and every other test in this file stayed green.
    """
    out = govern_finding(_finding("low", "strong", cvss_vector=_ABOVE,
                                 cvss_source="authored"), rules=[], env="prod")
    assert out["severity"] == "low"
    assert not out.get("rules_fired")


def test_the_environment_split_is_load_bearing_on_a_production_key_leak():
    """Flattening severity_uat/severity_prod to one severity is silent, so the
    split is asserted through the governor rather than only in the rules file."""
    rules = load_rules()
    leak = {"type": "secret", "title": "key in bundle", "severity": "critical",
            "url": "https://shop.example/x",
            "raw_data": {"request": dict(_REQ), "response": dict(_RESP),
                         "evidence": "authorizationKey found in bundle"}}
    prod = govern_finding(json.loads(json.dumps(leak)), rules=rules, env="prod")
    uat = govern_finding(json.loads(json.dumps(leak)), rules=rules, env="uat")
    assert prod["severity"] == "high"
    assert uat["severity"] == "medium"


def test_only_an_authored_vector_reconciles_and_the_rest_are_skipped():
    """Where this module diverges, with the label deciding the outcome.

    Private: `if vector and not cvss_source.startswith("derived")`, so an absent
    key reconciles exactly as an authored vector does -- the corpus defect the
    brief's fourth invariant cites, where eight of nine downgraded rows carried
    no key and all nine were filed as `cvss-reconcile`. Here provenance is asked
    positively: an authored vector reconciles, and a vector nothing vouched for
    never lowers a severity at all.

    An UNRECOGNISED label is grouped with the missing one rather than given its
    own outcome, and that is the point of the third case below. Both mean nobody
    vouched for the vector, so filing a misspelled label under a different
    verdict would reproduce the mis-attribution this divergence removes.
    """
    vector = "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:L/I:N/A:N"          # scores 4.3
    rules = load_rules()

    authored = _finding("critical", "strong", cvss_vector=vector)
    authored["cvss_source"] = "authored"
    out = govern_finding(authored, rules=rules, env="prod")
    assert out["severity"] == "medium"
    assert out["rules_fired"] == ["cvss-reconcile"]
    assert not out["governance_record"]["skipped"]
    assert not out.get("reconcile_skipped")

    unlabelled = govern_finding(_finding("critical", "strong", cvss_vector=vector),
                                rules=rules, env="prod")
    assert unlabelled["severity"] == "critical"
    assert unlabelled["reconcile_skipped"] == ["cvss-reconcile-skipped-unattributed"]
    assert "governance" not in unlabelled["raw_data"]

    mislabelled = _finding("critical", "strong", cvss_vector=vector)
    mislabelled["cvss_source"] = "llm-guess"
    out = govern_finding(mislabelled, rules=rules, env="prod")
    assert out["severity"] == "critical"
    assert out["reconcile_skipped"] == ["cvss-reconcile-skipped-unattributed"]

    derived = _finding("critical", "strong")
    derived["raw_data"]["cvss_vector"] = vector
    derived["raw_data"]["cvss_source"] = "derived(severity+unauth-network)"
    out = govern_finding(derived, rules=rules, env="prod")
    assert out["severity"] == "critical"
    assert not out.get("rules_fired")


def test_the_vector_is_read_from_the_finding_or_from_raw_data():
    """Measured against the private module, which reads raw_data only, so a
    caller holding the vector on the finding got no reconciliation at all."""
    vector = "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:L/I:N/A:N"
    on_raw = _finding("critical", "strong", cvss_source="authored")
    on_raw["raw_data"]["cvss_vector"] = vector
    assert govern_finding(on_raw, rules=[], env="prod")["severity"] == "medium"
    on_finding = _finding("critical", "strong", cvss_vector=vector, cvss_source="authored")
    assert govern_finding(on_finding, rules=[], env="prod")["severity"] == "medium"


def test_an_unscorable_vector_changes_nothing():
    """A vector CVSS cannot score yields no band, and no band is not a severity
    of zero -- a governor that read it as one would demote every finding
    carrying a malformed vector."""
    out = govern_finding(_finding("critical", "strong", cvss_vector="CVSS:3.1/AV:N",
                                  cvss_source="authored"), rules=[], env="prod")
    assert out["severity"] == "critical"
    assert not out.get("rules_fired")


def test_a_rules_file_whose_regex_does_not_compile_fails_at_load_time(tmp_path):
    """Loud where the private loader is silent: it caught re.error and stored
    None, and a None condition is SKIPPED rather than failed, so a typo widened
    the rule instead of disabling it -- a mark_fp rule matching more findings,
    not fewer.
    """
    bad = tmp_path / "severity_rules.json"
    bad.write_text(json.dumps({"rules": [
        {"id": "broken", "action": "cap_at", "severity": "low",
         "rationale": "r", "match": {"title_regex": "(unclosed"}}
    ]}), encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_rules(str(bad))
    assert "broken" in str(excinfo.value)


def test_a_rule_naming_an_unknown_action_fails_at_load_time(tmp_path):
    """The action chain is an if/elif with no else, so an unknown action does
    nothing at all and the rule looks fired-and-harmless in every report."""
    bad = tmp_path / "severity_rules.json"
    bad.write_text(json.dumps({"rules": [
        {"id": "typo", "action": "downgrade", "severity": "low",
         "rationale": "r", "match": {"type": ["csp_weakness"]}}
    ]}), encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_rules(str(bad))
    assert "typo" in str(excinfo.value)


def test_normalize_finding_evidence_fabricates_nothing_and_clobbers_nothing():
    """It promotes evidence the finding already carries and invents none.

    A bare url is the case that matters: it is not request evidence, and a
    normaliser that promoted it would turn every thin finding into a moderate
    one and lift the thin ceiling off the whole corpus.
    """
    bare = {"url": "https://shop.example/x", "raw_data": {}}
    normalize_finding_evidence(bare)
    assert "evidence" not in bare["raw_data"]
    assert evidence_grade(bare) == "thin"

    promoted = {"url": "https://shop.example/x",
                "raw_data": {"method": "POST", "payload": "id=2", "status_code": 200}}
    normalize_finding_evidence(promoted)
    assert promoted["raw_data"]["evidence"]["request"]["method"] == "POST"
    assert promoted["raw_data"]["evidence"]["response"]["status"] == 200
    assert evidence_grade(promoted) == "strong"

    authored = {"raw_data": {"evidence": {"request": dict(_REQ)}}}
    normalize_finding_evidence(authored)
    assert authored["raw_data"]["evidence"] == {"request": dict(_REQ)}

    text = {"url": "https://shop.example/x",
            "raw_data": {"evidence": "a sentence someone wrote by hand",
                         "status_code": 403}}
    normalize_finding_evidence(text)
    assert text["raw_data"]["evidence"]["summary"] == "a sentence someone wrote by hand"


def test_resolve_environment_reads_whole_hostname_segments_only():
    """Segment-anchored at BOTH ends, so a production host spelled with the
    letters of a non-prod token is not demoted for its spelling.

    The two ends need separate probes and used to have only one. `deposits`
    CONTAINS a token, and re.match's implicit start anchor already excludes it,
    so that assertion passes with the trailing `$` deleted. `sitemap` BEGINS
    with one, and it is the only one of the two that the trailing anchor
    decides: delete the `$` and this host resolves to `uat`, which caps a
    production finding at the pre-production band.
    """
    assert resolve_environment("https://wwwuat30.shop.example/a") == "uat"
    assert resolve_environment("https://sit.shop.example") == "uat"
    assert resolve_environment("https://deposits.shop.example") == "prod"
    assert resolve_environment("https://sitemap.shop.example") == "prod"
    assert resolve_environment("https://testimonials.shop.example") == "prod"
    assert resolve_environment("https://development.shop.example") == "prod"
    assert resolve_environment("https://shop.example/uat/x") == "prod"
    assert resolve_environment(None) == "prod"


def test_a_raw_data_json_string_is_read_and_not_ignored():
    """A store round-trip hands raw_data back as JSON text, and a grader that
    only accepted a dict would grade every persisted finding thin."""
    persisted = {"type": "v", "title": "t", "severity": "high", "url": "u",
                 "raw_data": json.dumps({"request": _REQ, "response": _RESP})}
    assert evidence_grade(persisted) == "strong"


def test_govern_scan_returns_a_zero_summary_for_an_empty_store():
    import asyncio
    summary = asyncio.run(govern_scan(_Store([]), rules=load_rules()))
    assert summary == {"total": 0, "changed": 0, "skipped": 0, "changes": []}


def test_a_relative_rules_path_is_resolved_against_the_module_not_the_cwd(monkeypatch, tmp_path):
    """The default is a bare filename, so resolving it against the working
    directory would make `load_rules()` return `[]` from anywhere but `core/`,
    and the governor would then run with no ruleset and never say so."""
    import os
    from core.severity_governor import DEFAULT_RULES_PATH
    assert not os.path.isabs(DEFAULT_RULES_PATH)
    monkeypatch.chdir(tmp_path)
    assert len(load_rules()) == 6


def test_a_severity_target_that_is_not_a_band_fails_at_load_time(tmp_path):
    """Measured before it was closed: with no check here, a misspelled cap
    target went straight into `finding["severity"]` as the literal string, and
    `rank` gave it zero -- so a typo demoted a critical to a word no consumer
    can order. The guarantee cannot live in the comparison, because every guard
    reads "is the new rank lower" and zero is lower than everything.
    """
    bad = tmp_path / "severity_rules.json"
    bad.write_text(json.dumps({"rules": [
        {"id": "typo-band", "action": "cap_at", "severity": "banana",
         "rationale": "r", "match": {"type": ["csp_weakness"]}}
    ]}), encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_rules(str(bad))
    assert "typo-band" in str(excinfo.value) and "banana" in str(excinfo.value)


def test_a_match_condition_the_governor_does_not_read_fails_at_load_time(tmp_path):
    """An unrecognised match key is not a no-op, it is a dropped condition:
    `_matches` reads the keys it knows and ignores the rest, so a misspelled
    `titel_regex` widens the rule to everything its other conditions allow."""
    bad = tmp_path / "severity_rules.json"
    bad.write_text(json.dumps({"rules": [
        {"id": "typo-key", "action": "mark_fp", "rationale": "r",
         "match": {"titel_regex": "anything"}}
    ]}), encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_rules(str(bad))
    assert "typo-key" in str(excinfo.value)


def test_no_shipped_rule_caps_production_below_uat():
    """The split exists to treat production at least as seriously, so the
    direction is asserted rather than trusted to whoever edits the file."""
    for rule in load_rules():
        if rule.get("severity_uat") and rule.get("severity_prod"):
            assert rank(rule["severity_prod"]) >= rank(rule["severity_uat"]), rule["id"]


def test_a_severity_carrying_stray_whitespace_is_governed_identically():
    """The whitespace bypass, and why the never-escalate sweep cannot see it.

    Before `rank` stripped, `rank("critical ")` was zero: a severity arriving
    with a stray space bypassed every cap, the evidence ceiling and the
    governance record. A never-escalate sweep is blind to that class in
    principle, not by accident -- with the strip removed, both sides of its
    comparison are zero and zero is not above zero, so the sweep passes on a
    finding that was never governed at all. The discriminating assertion is
    therefore equality with the stripped spelling, not the absence of a rise.
    """
    rules = load_rules()
    assert rank("critical ") == rank(" critical") == rank(" Critical\t") \
        == SEVERITY_RANK["critical"]
    for sev in SEVS:
        expected = govern_finding(_finding(sev, "thin"), rules=rules, env="prod")
        for spelling in (sev + " ", " " + sev, " " + sev.title() + "\t", sev.upper()):
            out = govern_finding(_finding(spelling, "thin"), rules=rules, env="prod")
            assert out["severity"] == expected["severity"], spelling
            assert bool(out.get("rules_fired")) == bool(expected.get("rules_fired"))


def test_a_caller_supplied_rule_is_validated_at_the_entry_point(tmp_path):
    """The suppression channel `rules=` used to open, closed at the entry point.

    `_matches` reads the COMPILED pattern key, so a hand-built rule carrying
    `title_regex` and no compiled twin had that condition SKIPPED rather than
    applied -- and a `mark_fp` rule whose only condition is skipped matches
    everything. Passing `rules=` was therefore a route around every refusal
    `load_rules` makes, and a way to persist an arbitrary critical finding as a
    false positive at `info`. Both directions are asserted: a well-formed
    hand-built rule still works and its pattern really applies, and a malformed
    one is refused rather than silently widened.
    """
    real = {"type": "sensitive_data", "title": "unauthenticated PII disclosure",
            "severity": "critical", "url": "https://shop.example/api/customers",
            "raw_data": {"request": dict(_REQ), "response": dict(_RESP)}}

    hand_made = [{"id": "suppress-everything", "action": "mark_fp", "rationale": "r",
                  "match": {"title_regex": "this cannot possibly match"}}]
    out = govern_finding(json.loads(json.dumps(real)), rules=hand_made, env="prod")
    assert out["severity"] == "critical"
    assert not out.get("false_positive")

    malformed = [{"id": "no-rationale", "action": "mark_fp", "match": {"type": ["x"]}}]
    with pytest.raises(ValueError) as excinfo:
        govern_finding(json.loads(json.dumps(real)), rules=malformed, env="prod")
    assert "no-rationale" in str(excinfo.value)


def test_validating_the_same_rules_twice_is_not_an_error():
    """`_validate_rule` writes the compiled patterns back under underscored
    keys, so a second pass would read them as conditions the module does not
    understand and the rules would be refused. Idempotence is what lets
    `govern_scan` validate once and `govern_finding` validate again per finding
    without its own work being rejected.
    """
    rules = load_rules()
    for _ in range(3):
        assert len(_validated_rules(rules)) == 6
    probe = {"type": "csp_weakness", "title": "t", "severity": "high",
             "url": "https://shop.example/x",
             "raw_data": {"request": dict(_REQ), "response": dict(_RESP)}}
    assert govern_finding(probe, rules=rules, env="prod")["severity"] == "medium"


def test_every_environment_spelling_resolves_and_the_cap_always_fires():
    """The silently-disabled cap, fixed by totality rather than by raising.

    An env of `PROD` used to find neither a `severity_PROD` key nor a plain
    `severity` on a split rule, so the cap silently did not apply and a
    production tokenization-key leak stayed critical with nothing recorded.
    Raising on it would trade a silent failure for a noisy one on a perfectly
    readable input, so instead every spelling resolves to `uat` or `prod` by the
    same non-production-token rule the url classifier uses, and the split cap
    therefore always fires with one of the two.

    The second assertion is the one that matters: not merely that the severity
    is right, but that the rule appears in `rules_fired`. A cap that was skipped
    and a cap that fired can agree on the severity by coincidence, so agreement
    alone would pass on a governor that skipped it.
    """
    rules = load_rules()
    leak = {"type": "secret", "title": "key in bundle", "severity": "critical",
            "url": "https://shop.example/x",
            "raw_data": {"request": dict(_REQ), "response": dict(_RESP),
                         "evidence": "authorizationKey found in bundle"}}
    spellings = {"prod": "high", "PROD": "high", " Prod ": "high",
                 "production": "high", "prd": "high",
                 "uat": "medium", "UAT": "medium", "uat2": "medium",
                 "staging": "medium", "sit": "medium", "nonprod": "medium"}
    for spelling, expected in spellings.items():
        out = govern_finding(json.loads(json.dumps(leak)), rules=rules, env=spelling)
        assert out["severity"] == expected, spelling
        assert out["rules_fired"] == ["tokenization-key-public"], spelling
    # Blank means "the caller has not said", so the url decides.
    blank = govern_finding(json.loads(json.dumps(leak)), rules=rules, env="  ")
    assert blank["severity"] == "high"          # shop.example is a production host
    assert blank["rules_fired"] == ["tokenization-key-public"]


def test_downgrade_to_takes_no_environment_split(tmp_path):
    """It reads a plain `severity` and nothing else, which is what the system
    this re-expresses does. A rule carrying `severity_prod` on a `downgrade_to`
    would have that key ignored, so it is refused at load time instead."""
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"rules": [
        {"id": "always-low", "action": "downgrade_to", "severity": "low",
         "rationale": "r", "match": {"type": ["csp_weakness"]}}]}), encoding="utf-8")
    rules = load_rules(str(good))
    probe = {"type": "csp_weakness", "title": "t", "severity": "critical",
             "url": "https://shop.example/x",
             "raw_data": {"request": dict(_REQ), "response": dict(_RESP)}}
    for env in ("uat", "prod"):
        out = govern_finding(json.loads(json.dumps(probe)), rules=rules, env=env)
        assert out["severity"] == "low", env

    split = tmp_path / "split.json"
    split.write_text(json.dumps({"rules": [
        {"id": "split-downgrade", "action": "downgrade_to", "severity": "low",
         "severity_prod": "high", "rationale": "r",
         "match": {"type": ["csp_weakness"]}}]}), encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_rules(str(split))
    assert "split-downgrade" in str(excinfo.value)
    assert "severity_prod" in str(excinfo.value)


def test_the_downgrade_branch_itself_ignores_a_split_even_if_one_reaches_it(monkeypatch):
    """The governor's own branch, observed with the loader's door held open.

    The refusal above means a split `downgrade_to` never reaches
    `govern_finding` through any supported path, so the branch's behaviour is
    unobservable while that refusal stands -- and an unobservable behaviour is
    one a later loader change can silently invert. Validation is therefore
    stubbed out here, which is the only way to see the branch at all: it reads
    `severity` and ignores `severity_prod`, so `prod` and `uat` give the same
    answer.
    """
    import core.severity_governor as governor
    monkeypatch.setattr(governor, "_validate_rule", lambda rule: None)
    smuggled = [{"id": "split-downgrade", "action": "downgrade_to", "severity": "low",
                 "severity_prod": "high", "rationale": "r",
                 "match": {"type": ["csp_weakness"]}}]
    probe = {"type": "csp_weakness", "title": "t", "severity": "critical",
             "url": "https://shop.example/x",
             "raw_data": {"request": dict(_REQ), "response": dict(_RESP)}}
    answers = {env: govern_finding(json.loads(json.dumps(probe)),
                                   rules=smuggled, env=env)["severity"]
               for env in ("uat", "prod")}
    assert answers == {"uat": "low", "prod": "low"}, answers


def test_the_governance_switch_takes_the_whole_pass_out(monkeypatch):
    """Off, no finding is read at all and the zero summary comes back; on, the
    same store governs normally. Both directions, because a switch asserted in
    one direction only cannot tell 'disabled' from 'did nothing'."""
    import asyncio
    rows = [dict(_finding("critical", "thin"), id="1")]
    monkeypatch.setenv("HARNESS_GOVERNANCE", "0")
    off = _Store(rows)
    assert asyncio.run(govern_scan(off, rules=load_rules())) == {
        "total": 0, "changed": 0, "skipped": 0, "changes": []}
    assert off.governed == []
    assert off.rows[0]["severity"] == "critical"

    monkeypatch.setenv("HARNESS_GOVERNANCE", "1")
    on = _Store(rows)
    assert asyncio.run(govern_scan(on, rules=load_rules()))["changed"] == 1
    assert on.rows[0]["severity"] == "medium"


def test_the_evidence_ceiling_switch_leaves_the_rest_of_the_pass_running(monkeypatch):
    """Off, the thin cap does not apply but the ruleset still does -- which is
    the distinction that makes this a separate switch rather than a second name
    for the first one."""
    import asyncio
    thin_critical = dict(_finding("critical", "thin"), id="1")
    capped = dict(_finding("critical", "thin"), id="2", type="csp_weakness",
                  title="CSP allows unsafe-inline")
    monkeypatch.setenv("HARNESS_GOVERNANCE_EVIDENCE_CEILING", "0")
    store = _Store([thin_critical, capped])
    summary = asyncio.run(govern_scan(store, rules=load_rules()))
    by_id = {r["id"]: r for r in store.rows}
    assert by_id["1"]["severity"] == "critical"       # the ceiling did not cap it
    assert by_id["2"]["severity"] == "medium"         # the csp rule still did
    assert summary["changed"] == 1

    monkeypatch.setenv("HARNESS_GOVERNANCE_EVIDENCE_CEILING", "1")
    store = _Store([dict(_finding("critical", "thin"), id="1")])
    asyncio.run(govern_scan(store, rules=load_rules()))
    assert store.rows[0]["severity"] == "medium"


def test_govern_scan_counts_a_skipped_reconciliation_without_writing_it():
    """The count is returned and never stored, and both halves are asserted.

    A skip is not a change, so persisting a record for it would put a record on
    a row whose severity did not move -- the shape that makes a coverage count
    mean something other than its name. The number of vectors nobody vouched for
    is a scan-level statistic, so the summary carries it and the store does not.
    """
    import asyncio
    unattributed = dict(_finding("critical", "strong"), id="1",
                        cvss_vector="CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:L/I:N/A:N")
    quiet = dict(_finding("low", "strong"), id="2")
    store = _Store([unattributed, quiet])
    summary = asyncio.run(govern_scan(store, rules=load_rules()))
    assert summary["total"] == 2
    assert summary["changed"] == 0                    # nothing moved
    assert summary["skipped"] == 1                    # and the skip was counted
    assert store.governed == []                       # and nothing was written
    for row in store.rows:
        assert "governance" not in row["raw_data"]
    assert store.rows[0]["severity"] == "critical"


def test_a_derived_vector_is_skipped_without_being_reported():
    """A derived vector is expected to be skipped and there is nothing for a
    reader to act on, so it never enters the unattributed count -- which is what
    keeps that count meaning what its name says."""
    derived = _finding("critical", "strong")
    derived["raw_data"]["cvss_vector"] = "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:L/I:N/A:N"
    derived["raw_data"]["cvss_source"] = "derived(severity+unauth-network)"
    out = govern_finding(derived, rules=load_rules(), env="prod")
    assert out["severity"] == "critical"
    assert not out.get("reconcile_skipped")
    assert out.get("governance_record") in (None, {}, [])


def test_a_vector_that_would_not_lower_anything_reports_no_skip():
    """Nothing is skipped when the band is not below the claim, so nothing is
    recorded either: a skip counted there would never correspond to a downgrade
    it cost, and the count would read higher than the thing it measures."""
    out = govern_finding(_finding("low", "strong", cvss_vector=_ABOVE),
                        rules=load_rules(), env="prod")
    assert out["severity"] == "low"
    assert not out.get("reconcile_skipped")
    assert out.get("governance_record") in (None, {}, [])
