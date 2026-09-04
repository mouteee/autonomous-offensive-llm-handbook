"""The failure museum: a regression test per false positive the public tree can pin.

Each test names one false positive from the spec's failure museum and pins the
shipped rule that kills it, so that removing the rule reddens that test and only
that test. `core/severity_governor.py` is the module that refuses all of them and
`core/severity_rules.json` holds the rules; what differs between these tests is
which rule id fires.

That discrimination was measured rather than assumed. Each rule named below was
deleted in turn from a scratch copy of `core/severity_rules.json`, and every
deletion reddened the test naming that rule while leaving the rest of this file
green. Deletion alone would only pin that a rule exists, so two of the caps were
inverted as well -- the wildcard cap raised a band, and the tokenization rule's
environment split swapped -- and each inverted cap reddened the test asserting
its value. The observables live in the ledger entry for this docstring in
`tests/docstring_claims_audited.txt`, where they cannot rot into this paragraph.

Not every museum entry has a test here, and that is the honest outcome rather
than a shortfall. The spec describes the private system and this repository is a
subset of it. An unanchored `injectable` match in a tool's negative output, an
analyst verdict written into `raw_data` against its own evidence, and a WAF-block
heuristic downgrading access control are all corrected somewhere in that private
system, and nothing in `core/` refuses any of them. `analyst_verdict`,
`analyst_notes` and `forbidden` appear nowhere under `core/`, and the scope of that
needs stating more carefully than it once was here. The first two appear nowhere in
this repository at all, outside prose about them; an earlier wording said each of the
three occurs elsewhere, which was measured and is true only of the third. `forbidden`
does occur elsewhere, as a body snippet in an http-evidence test and inside the symbol
``_FORBIDDEN_PROVENANCE`` in ``walkthrough/fixture_schema.py``, whose entries are
``host``, ``client``, ``scan_id`` and ``url`` rather than anything about an analyst; a
bare ``analyst`` sits in a fixture's provenance prose. None of those is a governance
decision path. The only `injectable` under `core/` is an unrelated
dependency-injection hook in `core/llm_control.py`, and the one WAF-shaped symbol,
`WAF_BLOCK` at `core/response_analyzer.py:64`, is defined and never read. A test
for any of those could not fail, which is the decorative-gate failure at test
scale and the exact defect this file exists to pin, so they are reported as
unpinnable instead of given a test that asserts nothing.
"""
from core.severity_governor import govern_finding, load_rules, normalize_finding_evidence


def _strong(evidence, url, **over):
    """A `raw_data` block whose evidence grades `strong`, and why that matters.

    A request beside a response is one route to that grade and a curl line beside
    its output is the other, per `core/severity_governor.py:224`. Both are here,
    because `evidence-ceiling` pulls a thin finding down to medium, and a rule
    whose cap already sits at medium is then indistinguishable from it: the
    severity comes out the same and the reason does not. Stated that way rather
    than as "the ceiling caps it first", which was measured and is not what
    happens -- a matching rule still fires. The case in this file where thin
    evidence changes an outcome outright is the tokenization rule's production
    cap, where the ceiling overrides high with medium and the environment split
    asserted below disappears.

    What the grade assertion buys is not the same in every cap test, because the
    fixtures degrade differently: strip the artifacts and the CORS evidence string
    grades `thin`, whose ceiling IS medium, while the longer CSP string still
    grades `moderate`, whose ceiling is critical. So for CORS the assertion is what
    makes the rule's deletion visible in the severity at all, and for CSP deletion
    shows critical at either grade and the assertion pins the fixture's quality
    instead. Their messages say their own reason rather than a shared one.

    So the cap tests assert the grade and the `mark_fp` tests do not, which is a
    decision and not an oversight. `mark_fp` moves a finding to `info`, the
    floor, and the ceiling acts only on a severity ranking ABOVE it -- so no
    ceiling can mask a `mark_fp` rule, and a grade assertion beside one would
    pin something that cannot come out any other way.

    The proof-of-concept keys are `poc_curl` and `poc_output`, never `curl` and
    `output`. A block written with the obvious names grades `thin`.
    """
    base = {"evidence": evidence,
            "request": {"method": "GET", "url": url},
            "response": {"status": 200, "headers": {"Content-Type": "text/html"},
                         "body": evidence},
            "poc_curl": "curl -i " + url,
            "poc_output": evidence}
    base.update(over)
    return base


def _governed(finding):
    """Normalise, govern, and hand back the record the governor wrote.

    The ruleset is asserted non-empty here rather than in each test, and what
    that assertion buys is a DIAGNOSIS and not a verdict -- a distinction worth
    stating, because the sentence that stood here claimed the verdict and was
    measured false. `load_rules` treats a file it cannot find as a documented
    degraded mode and returns an empty ruleset rather than raising, so a wrong
    path yields governance with no rules at all. Point it at one and every test
    below still fails, on the record assertion in the next paragraph, whether or
    not this guard is here; what the guard changes is that the failure then reads
    `returned no rules` instead of `no rule acted`, which are different repairs.
    The per-rule assertions are what keep a pass from being vacuous.

    The absent-record case reads as its own sentence rather than as a `KeyError`:
    `govern_finding` writes `governance_record` only when a severity or a
    false-positive flag actually moved, so a finding that matched no rule carries
    no record at all. That is the shape every rule deletion in this file's
    discrimination proof produces, and this is the assertion each one lands on.

    `normalize_finding_evidence` runs first because that is the order the real
    write path uses. It is called for fidelity to that path rather than because
    these fixtures need it: `_strong` writes its request and response where the
    grader's own fallback already reads them, so the findings here grade `strong`
    either way, and deleting this call reddens nothing in this file.
    """
    rules = load_rules()
    assert rules, "load_rules() returned no rules, so every assertion below is vacuous"
    normalize_finding_evidence(finding)
    govern_finding(finding, rules=rules)
    assert "governance_record" in finding, (
        "the governor recorded nothing, so no rule acted; severity is "
        + repr(finding.get("severity"))
    )
    return finding["governance_record"]


def test_an_unauthenticated_bounce_page_is_not_a_successful_write():
    """A login bounce behind a 200 is not an unauthenticated write.

    The detector read the status line and called it a write that succeeded; the
    body says the request bounced to a login page and changed nothing. The
    `read-via-post-bounce` rule needs BOTH halves -- a title matching the
    unauth-write claim and evidence matching the bounce -- so a title alone
    cannot mark a real finding as a false positive.

    `mark_fp` is checked on the finding and not only in the record, because the
    severity floor and the flag are separate outcomes and a rule that moved one
    without the other would still look governed.
    """
    url = "https://portal.shop.example.com/profile/update"
    finding = {"type": "unauth_write", "severity": "high",
               "title": "Unauthenticated write succeeded on the profile endpoint",
               "url": url,
               "raw_data": _strong(
                   "HTTP/1.1 200 OK\n"
                   "<h1>Your session has expired, please log in again.</h1>",
                   url,
                   request={"method": "POST", "url": url, "body": "name=probe"})}
    record = _governed(finding)
    assert record["rules_fired"] == ["read-via-post-bounce"]
    assert record["original_severity"] == "high"
    assert record["final_severity"] == "info"
    assert finding["false_positive"] is True
    assert finding["fp_reason"] == "read-via-post-bounce"


def test_a_csp_best_practice_finding_cannot_hold_critical():
    """Policy advice cannot outrank the findings a reader came for.

    `unsafe-inline` weakens defence in depth; it is not an exploited path, and a
    page of policy findings holding critical is what buries the injection and
    object-authorization findings underneath it. `csp-weakness` matches on type
    alone and carries a single severity target with no environment split, so its
    cap cannot vary by tier. This test drives the prod tier; the uat direction of
    that sentence is a property of the rule's data rather than something asserted
    here.
    """
    url = "https://portal.shop.example.com/"
    finding = {"type": "csp_weakness", "severity": "critical",
               "title": "Content-Security-Policy permits unsafe-inline",
               "url": url,
               "raw_data": _strong(
                   "content-security-policy: default-src 'self'; "
                   "script-src 'self' 'unsafe-inline'", url)}
    record = _governed(finding)
    assert record["rules_fired"] == ["csp-weakness"]
    assert record["original_severity"] == "critical"
    assert record["final_severity"] == "medium"
    assert record["evidence_grade"] == "strong", \
        "this cap must be recorded on a replayable capture, not a bare evidence string"


def test_a_wildcard_cors_origin_is_capped_below_critical():
    """A literal `Access-Control-Allow-Origin: *` cannot hold critical.

    A browser refuses to honour the wildcard together with
    `Access-Control-Allow-Credentials`, so no credentialed cross-origin read is
    possible and the finding is not critical. Two details are load-bearing, and
    the cross-product of both was measured rather than argued. The type must be
    `wildcard`, which is what `cors-wildcard` matches -- a `cors_misconfiguration`
    type matches no public rule at all. And the evidence must be strong. Get both
    wrong together and the finding STILL arrives at medium, by `evidence-ceiling`
    rather than by the rule, which is indistinguishable from the outcome asserted
    here if only the final severity is read; that combination is what this plan's
    pre-flight hit. So `rules_fired` and `evidence_grade` are asserted too, and
    they are what tell the two apart.
    """
    url = "https://shop.example.com/api"
    finding = {"type": "wildcard", "severity": "critical", "title": "CORS wildcard",
               "url": url,
               "raw_data": _strong("Access-Control-Allow-Origin: *", url)}
    record = _governed(finding)
    assert record["rules_fired"] == ["cors-wildcard"]
    assert record["original_severity"] == "critical"
    assert record["final_severity"] == "medium"
    assert record["evidence_grade"] == "strong", \
        "strong evidence is what makes this medium the rule's own: at thin, " \
        "deleting the rule still yields medium through the ceiling"


def test_an_spa_index_shell_is_not_a_live_api_response():
    """A single-page app's index shell under `/api/` is client-side routing.

    The app serves that shell for any unmatched path, so the 200 is not an API
    response and the route it appears to prove does not exist. Both conditions in
    `spa-fallback-api-200` are exercised here: the url carries `/api/` and the
    evidence carries the shell marker. The rule also carries an `exclude_type`
    list covering the types where a reflected shell can still be the real bug, so
    an access-control or injection finding is never silenced by it. That last
    sentence is a property of the rule's match block and not something this test
    asserts -- this fixture's type is `api_endpoint` -- so it is measured in the
    ledger row rather than left as an unbacked aside.
    """
    url = "https://portal.shop.example.com/api/v1/accounts"
    finding = {"type": "api_endpoint", "severity": "high",
               "title": "Unauthenticated API route answered 200",
               "url": url,
               "raw_data": _strong("<!doctype html><app-root></app-root>", url)}
    record = _governed(finding)
    assert record["rules_fired"] == ["spa-fallback-api-200"]
    assert record["original_severity"] == "high"
    assert record["final_severity"] == "info"
    assert finding["false_positive"] is True
    assert finding["fp_reason"] == "spa-fallback-api-200"


def test_a_public_by_design_gateway_key_is_not_a_leaked_secret():
    """A payment gateway's client-side key is real, and it is not a secret.

    It is shipped to the browser on purpose, it cannot process a transaction and
    it cannot read the vault, so `tokenization-key-public` caps rather than
    dismisses it -- the finding is not a false positive either. The cap splits by
    environment, and both halves are asserted because a test reading one of them
    cannot tell whether the environment key was consulted at all: the same key in
    production is worth more attention than in a test tier, and the governor
    resolves that tier from the hostname.
    """
    for host, environment, expected in (("pay.shop.example.com", "prod", "high"),
                                        ("pay-uat.shop.example.com", "uat", "medium")):
        url = "https://" + host + "/static/config.json"
        finding = {"type": "secret_exposure", "severity": "critical",
                   "title": "Payment gateway client key in the front-end bundle",
                   "url": url,
                   "raw_data": _strong('"authorizationKey": "sandbox_zx9q_kf3t"', url)}
        record = _governed(finding)
        assert record["rules_fired"] == ["tokenization-key-public"], host
        assert record["environment"] == environment, host
        assert record["original_severity"] == "critical", host
        assert record["final_severity"] == expected, host
        assert record["evidence_grade"] == "strong", host
        assert not finding.get("false_positive"), host
