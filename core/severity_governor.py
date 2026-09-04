"""The deterministic severity governor: it can only lower a severity.

The whole argument this handbook makes reduces to one property of this module,
so it is stated first and it is the only property worth checking before any
other: `govern_finding` is structurally incapable of escalation. Every branch
that can change a severity is guarded by a comparison that admits the change
only when the new rank is strictly below the current one, and there is no
branch that admits the reverse. Raising a severity is a judgement about
impact; this file makes no judgements, it applies rules. So the model that
proposed a critical cannot argue its way to keeping one, and a reviewer
reading a demotion never has to ask whether something upstream promoted it
first.

tests/test_severity_governor.py sweeps that property rather than sampling it,
and it does so twice because one sweep is not enough. A sweep over claimed
severity, evidence grade and environment reaches the evidence ceiling and
nothing else: its findings carry no CVSS vector and match no shipped rule, so
the guards inside the reconciliation and inside the rule actions are never
executed by it. The second sweep crosses every rule-matching shape with every
vector position and provenance label as well, and it is the one that fails when
a rule cap or the reconciliation is made able to raise.

Three signals decide the outcome, applied in this order: an authored CVSS
vector, the semantic ruleset in `severity_rules.json`, and the evidence
ceiling. The order matters only in that the ceiling comes last, so no rule can
lift a cap the evidence has already imposed. Each guard is a comparison of two
`SEVERITY_RANK` ordinals, which is what makes never-escalating a property of
the comparisons rather than a promise in prose.

The evidence ceiling is where a reader's assumption usually goes wrong.
`EVIDENCE_CEILING` maps three grades onto two distinct outcomes: `thin`
evidence caps a finding at `medium` no matter what severity it claims or what
CVSS vector it carries, while `moderate` and `strong` both map to `critical`,
which is the top of the scale and therefore no cap at all. So only `thin` caps
anything, and a `moderate` finding is not held down anywhere in this file.

A grade is computed from the artifacts the finding carries and never read from
a claim inside it. A finding arriving with `evidence_grade: "strong"` and
nothing but a title still grades `thin`, because `evidence_grade` looks at
requests, responses and proof-of-concept output and never at that key.

`govern_scan` sits behind two environment switches, `AUTOMATOR_GOVERNANCE` and
`AUTOMATOR_GOVERNANCE_EVIDENCE_CEILING`, both defaulting to on, which is what
the system this is re-expressed from does and where it does it.
`govern_finding` itself is unswitched: a caller reaching it directly is
governed unconditionally, and the switches gate the scan-wide pass. Nothing in
this module raises on a caller's input except a malformed ruleset: an
environment word it does not recognise is classified rather than refused, and an
unscorable CVSS vector changes nothing rather than failing.

Deliberate divergences from that system follow. Each is stated here rather than
left for a reader to find, and none is a liberty taken for convenience.

The ruleset is JSON where the original is YAML. `core/` here is stdlib-only, so
there is no yaml module to read the original with, and a hand-written parser
for a YAML subset would mis-read exactly the alternation, character-class and
escaped-dot characters these patterns are made of. `json` reads them exactly.

The reconciliation fails closed on a vector nothing vouched for. The original
asks whether the provenance label is *not* `derived`, so a vector carrying no
label at all passes as authored and lowers a severity on evidence nobody
attributed. Here only a label recognised as `authored` reconciles; an
unlabelled vector, or one carrying a label this module does not recognise,
produces no downgrade at all. The skip is reported rather than silent -- on the
returned finding, and as a count in `govern_scan`'s summary -- so a scan can say
how often a vector went unattributed instead of losing the number. It is
reported and never stored, because a record on a row whose severity did not move
is what makes a coverage count mean something other than its name. A `derived`
label is skipped in both and silently in both, because a vector computed from a
severity band is not evidence against that band.

That trade is worth naming rather than hiding. Against a corpus whose vectors
are mostly unlabelled the rule fires rarely, and a dormant control is worse
than no control. But the dormancy is a property of that corpus's labelling and
not of the rule -- a reader using this module labels their own vectors -- and a
rule that lowers a severity on unattributed evidence is the failure this module
exists to prevent, one layer over: an unlabelled vector could have come from
anywhere, a model included.

`load_rules` refuses where the original tolerates. A pattern that will not
compile, an action this module does not implement, a severity target that is
not a band, and a match condition nothing reads are each an error at load time
here. Every one of them is a silent widening in the original: a compiled
pattern stored as `None` is skipped rather than failed, so a typo makes its
rule match more findings instead of fewer, and an unknown action falls off the
end of the action chain while the rule sits in the file looking applied.

The CVSS vector is read off the finding as well as out of `raw_data`. The
original reads `raw_data` alone, so a caller holding the vector on the finding
got no reconciliation at all.

`DEFAULT_RULES_PATH` is a bare filename resolved against `__file__`, where the
original writes an absolute path. An absolute default carries an author's home
directory into a public file, and a working-directory-relative one finds
nothing from any other directory and says nothing about it.

A governance record is written only when something moved, where the original
writes one on every pass. A record whose `rules_fired` is empty makes a count of
governed findings mean how many were looked at rather than how many changed.
"""
import json
import os
import re

from urllib.parse import urlparse

from core.cvss import band_from_score, cvss_base_score

# The one ordering in this file. See the module docstring for what the ranks buy.
SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

# Grade -> the highest severity that grade can carry. See the module docstring.
EVIDENCE_CEILING = {"thin": "medium", "moderate": "critical", "strong": "critical"}

# The rule vocabulary. Reasoning for each set is in _validate_rule's docstring,
# which is where the audit reads it.
_ACTIONS = ("mark_fp", "downgrade_to", "cap_at")
_REGEX_CONDITIONS = ("title_regex", "evidence_regex", "url_regex")
_MATCH_CONDITIONS = ("type", "exclude_type", "source") + _REGEX_CONDITIONS
_SEVERITY_TARGETS = ("severity", "severity_uat", "severity_prod")
_SPLIT_TARGETS = ("severity_uat", "severity_prod")

# The environments a split severity target may key on. See _resolved_environment.
_ENVIRONMENTS = ("uat", "prod")

# Provenance prefixes on a CVSS vector's cvss_source. See _reconcile_cvss.
_AUTHORED = "authored"
_DERIVED = "derived"
_SKIPPED_UNATTRIBUTED = "cvss-reconcile-skipped-unattributed"

# The scan-wide pass reads both, defaulting to on. See govern_scan.
_GOVERNANCE_SWITCH = "AUTOMATOR_GOVERNANCE"
_CEILING_SWITCH = "AUTOMATOR_GOVERNANCE_EVIDENCE_CEILING"

# Hostname segments that mark a non-production tier. See resolve_environment.
_NONPROD_SEGMENT = re.compile(
    r"^(?:www)?(?:uat|sit|sandbox|staging|stg|dev|qa|test|preprod|pprd|nonprod)\d*$"
)

# A bare filename. See load_rules for the path it becomes.
DEFAULT_RULES_PATH = "severity_rules.json"


def rank(sev) -> int:
    """The ordinal of a severity band, and zero for anything unrecognised.

    Surrounding whitespace is stripped as well as case being folded, and the
    strip is not cosmetic. Without it `rank("critical ")` is zero, so a severity
    that arrives with a stray space bypasses every cap, the evidence ceiling and
    the governance record -- and a never-escalate sweep cannot see that class at
    all, because both sides of its comparison rank zero and zero is not above
    zero.

    Unrecognised input still ranks at the bottom rather than raising, and that
    is deliberately NOT relied on as a safety property: every guard reads "is
    the new rank lower", so a band-shaped nonsense word ranks zero, compares as
    lower than anything, and would be adopted. A `cap_at` rule with a misspelled
    target once left the literal string in the finding's severity, unrankable by
    every consumer downstream. `load_rules` refuses a severity target that is
    not a band, so the guarantee lives at the door and not in this comparison.
    """
    return SEVERITY_RANK.get(str(sev or "").strip().lower(), 0)


def _present(value) -> bool:
    """Whether a value carries real content, so emptiness is checked and not
    merely presence.

    An empty dict is not a request and an empty string is not a response. The
    JSON spellings of emptiness count as empty too, because a store that
    round-trips a finding through a text column hands back `"{}"` where the
    caller wrote `{}`, and a grader fooled by that would promote every
    persisted finding by one grade.
    """
    if value is None:
        return False
    if isinstance(value, str):
        text = value.strip()
        return bool(text) and text not in ("{}", "[]", "null", '""')
    if isinstance(value, (dict, list, tuple)):
        return len(value) > 0
    return bool(value)


def _as_dict(value) -> dict:
    """A raw_data-shaped value as a dict: parsed when it is JSON text, `{}` when
    it is anything else.

    Never raises. A finding read back out of a store arrives with `raw_data` as
    text, and one built in memory arrives with it as a dict; both reach every
    reader in this file through here, so no reader needs to know which it got.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _side(finding: dict, raw: dict, key: str):
    """One side of the exchange -- `request` or `response` -- resolved through
    the layers a finding can carry it in, in order.

    The layers are `raw_data.evidence.<key>` first, because that is the
    canonical place `normalize_finding_evidence` writes; then the finding's own
    `<key>_data` column; then `raw_data.<key>`, where a tool that never
    normalised leaves it. Each layer is skipped when what it holds is empty, so
    an authored-but-blank canonical slot does not mask a real capture sitting
    one layer down.
    """
    evidence = raw.get("evidence")
    if isinstance(evidence, dict) and _present(evidence.get(key)):
        return evidence[key]
    own = finding.get(key + "_data")
    if _present(own):
        return own
    return raw.get(key)


def evidence_grade(finding: dict) -> str:
    """How replayable a finding's evidence is: `strong`, `moderate` or `thin`.

    Computed from the artifacts, never from a claim. A finding asserting
    `evidence_grade: "strong"` over nothing but a title grades `thin`, because
    this function does not read that key at all -- there is no branch here in
    which a finding's own opinion of its evidence can affect its grade.

    `strong` is a request AND a response, or a curl line AND its output.
    `moderate` is exactly one of those sides, or a curl line alone, or a string
    `evidence` whose length is at least 40 once surrounding whitespace has been
    stripped, which is the comparison the code makes and not the raw length.
    Everything else is `thin`.

    The proof-of-concept keys are `poc_curl`, `poc` and `poc_output`, and not
    `curl` and `output`. That is worth stating because the obvious names are
    the wrong ones: a fixture written with them grades `thin`, and an
    implementation reading them passes a test that never exercised the branch.
    `poc_output` falls back to the resolved response, so a curl line beside a
    captured response is `strong` without a separate output capture.
    """
    raw = _as_dict(finding.get("raw_data"))
    evidence = raw.get("evidence")
    request = _side(finding, raw, "request")
    response = _side(finding, raw, "response")
    curl = raw.get("poc_curl") if _present(raw.get("poc_curl")) else raw.get("poc")
    output = raw.get("poc_output") if _present(raw.get("poc_output")) else response

    has_request, has_response = _present(request), _present(response)
    has_curl = _present(curl)
    if (has_request and has_response) or (has_curl and _present(output)):
        return "strong"
    if has_request or has_response or has_curl:
        return "moderate"
    if isinstance(evidence, str) and len(evidence.strip()) >= 40:
        return "moderate"
    return "thin"


def resolve_environment(url: str) -> str:
    """`uat` when the target's HOSTNAME carries a non-production token as a
    whole segment, `prod` otherwise.

    Two narrowings, and each one is a defect this would otherwise have. Only
    the hostname is read, never the path or the query, so a production host
    serving `/uat/` is still production. And a segment must equal the token
    rather than contain it, so `deposits`, `latest`, `visitor`, `website` and
    `positions` stay production instead of being demoted for the letters they
    happen to spell.

    Absent or unparseable input resolves to `prod`. What the returned word does
    is select a key and nothing else: a `cap_at` rule under `prod` reads
    `severity_prod` and under `uat` reads `severity_uat`, falling back to a
    single `severity` when the rule carries no split. Any statement about one of
    those caps being higher than the other is a claim about the shipped rules'
    data rather than about this function, and it stops being true the day a rule
    is added.
    """
    text = str(url or "").strip().lower()
    host = urlparse(text).hostname if "//" in text else text.split("/", 1)[0].split("?", 1)[0]
    segments = re.split(r"[.\-]", host or "")
    return "uat" if any(_NONPROD_SEGMENT.match(s) for s in segments) else "prod"


def load_rules(path: str = DEFAULT_RULES_PATH) -> list:
    """The semantic ruleset, parsed and with its patterns compiled.

    A missing file yields `[]` and is not an error: the governor still runs its
    CVSS reconciliation and its evidence ceiling, so a deployment with no
    ruleset is degraded rather than broken. Nothing else is tolerated. A file
    that is unreadable, that is not JSON, or that holds a rule with no id, an
    action outside `_ACTIONS`, no rationale, a cap with no severity target, a
    severity target that is not a band, a match condition this module does not
    read, or a pattern that will not compile raises, naming the rule.

    That strictness is where this deliberately departs from the shape
    it was re-expressed from, and the reason is the direction the old failure
    took. There, a pattern that would not compile was caught and stored as
    `None`, and a `None` condition is SKIPPED at match time rather than failed
    -- so a typo in a regex made its rule match MORE findings, not fewer, and a
    `mark_fp` rule silently suppressed findings it was never written for. An
    unknown action failed the other way and just as quietly: the action chain
    is a series of comparisons with no fallback, so a misspelled action does
    nothing while the rule still looks present in the file. Both are refused
    here, at load time, before any finding is judged.

    A relative `path` is resolved against THIS module's directory rather than
    against the working directory. That is what lets `DEFAULT_RULES_PATH` be a
    bare filename: written out as an absolute path it would carry an author's
    home directory and a repository name into a public file. It also removes the
    failure that a working-directory-relative default has: run from anywhere
    but `core/`, such a default finds no file, returns `[]` under the
    missing-file rule above, and leaves the governor running with no ruleset
    and saying nothing about it.
    """
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except FileNotFoundError:
        return []
    rules = document.get("rules", []) if isinstance(document, dict) else []
    for rule in rules:
        _validate_rule(rule)
    return rules


def _validate_rule(rule: dict) -> None:
    """Refuse a rule that cannot do what it says, naming it in the message.

    The vocabulary this enforces, and why each set is closed. `_ACTIONS` holds
    the actions `govern_finding` implements; anything else falls off the end of
    its action chain and does nothing while the rule sits in the file looking
    applied. `downgrade_to` is accepted and no shipped rule uses it: it reads a
    single `severity` and takes no environment split, which is exactly what the
    system this is re-expressed from does, so a rule carrying `severity_uat` or
    `severity_prod` on a `downgrade_to` is refused rather than silently ignored.
    `_MATCH_CONDITIONS` holds the conditions `_matches` reads; an unrecognised
    key is not a no-op but a dropped condition, so a misspelled `title_regex`
    widens its rule to whatever the remaining conditions allow, and for a
    `mark_fp` rule that means suppressing findings it was never written for.
    `source` is accepted and read while no shipped rule uses it, for the same
    reason `downgrade_to` is: narrowing an accepted set turns a rule somebody
    writes tomorrow from working into refused.

    Idempotent, which matters because it runs on caller-supplied rules as well
    as on loaded ones. It writes the compiled patterns back under underscored
    keys, so a second pass would see them as unrecognised conditions; keys
    opening with an underscore are therefore exempt from the unknown-key check
    rather than fed back into it.
    """
    identifier = str(rule.get("id") or "").strip()
    if not identifier:
        raise ValueError(f"rule with no id: {rule!r}")
    action = rule.get("action")
    if action not in _ACTIONS:
        raise ValueError(f"rule {identifier!r}: action {action!r} is not one of {_ACTIONS}")
    if not str(rule.get("rationale") or "").strip():
        raise ValueError(f"rule {identifier!r}: no rationale")
    targets = {key: rule[key] for key in _SEVERITY_TARGETS if rule.get(key)}
    if action in ("cap_at", "downgrade_to") and not targets:
        raise ValueError(f"rule {identifier!r}: {action} with no severity target")
    if action == "downgrade_to":
        split = sorted(key for key in _SPLIT_TARGETS if rule.get(key))
        if split:
            raise ValueError(
                f"rule {identifier!r}: downgrade_to takes no environment split, "
                f"so {split} would be ignored -- use cap_at")
        if not rule.get("severity"):
            raise ValueError(f"rule {identifier!r}: downgrade_to needs a severity")
    for key, value in targets.items():
        if str(value).strip().lower() not in SEVERITY_RANK:
            raise ValueError(
                f"rule {identifier!r}: {key} is {value!r}, not a severity band")
    match = rule.get("match") or {}
    if not isinstance(match, dict):
        raise ValueError(f"rule {identifier!r}: match is not a mapping")
    unknown = sorted(k for k in match
                     if not k.startswith("_") and k not in _MATCH_CONDITIONS)
    if unknown:
        raise ValueError(f"rule {identifier!r}: match conditions not understood: {unknown}")
    rule["match"] = match
    for key in _REGEX_CONDITIONS:
        if match.get(key):
            try:
                match["_" + key] = re.compile(match[key])
            except re.error as exc:
                raise ValueError(
                    f"rule {identifier!r}: {key} does not compile: {exc}") from exc


def _text_of(finding: dict) -> str:
    """The haystack an `evidence_regex` searches: the finding's own evidence
    field, whatever `raw_data.evidence` holds, and the description.

    A dict evidence block is searched as its JSON text rather than skipped, so
    a pattern still reaches a captured body that has already been canonicalised
    into `{request, response}`.
    """
    raw = _as_dict(finding.get("raw_data"))
    evidence = raw.get("evidence")
    if isinstance(evidence, str):
        rendered = evidence
    elif evidence:
        rendered = json.dumps(evidence)
    else:
        rendered = ""
    return " ".join([str(finding.get("evidence") or ""), rendered,
                     str(finding.get("description") or "")])


def _matches(finding: dict, match: dict) -> bool:
    """Whether every condition in one match block holds. Conditions AND."""
    finding_type = str(finding.get("type") or "").lower()
    excluded = [t.lower() for t in (match.get("exclude_type") or [])]
    if excluded and (finding_type in excluded
                     or any(token in finding_type for token in excluded)):
        return False
    allowed = [t.lower() for t in (match.get("type") or [])]
    if allowed and finding_type not in allowed \
            and not any(token in finding_type for token in allowed):
        return False
    sources = [s.lower() for s in (match.get("source") or [])]
    if sources and str(finding.get("source") or "").lower() not in sources:
        return False
    for key, target in (("_title_regex", str(finding.get("title") or "")),
                        ("_url_regex", str(finding.get("url") or "")),
                        ("_evidence_regex", _text_of(finding))):
        pattern = match.get(key)
        if pattern is not None and not pattern.search(target):
            return False
    return True


def match_rules(finding: dict, rules: list) -> list:
    """Every rule whose match block is fully satisfied by this finding."""
    return [r for r in rules if _matches(finding, r.get("match") or {})]


def _validated_rules(rules):
    """Rules ready to match against, validated at the entry point.

    `None` loads the shipped file. A caller-supplied list is validated here and
    not only inside `load_rules`, and that is a correctness fix rather than
    defensive tidiness: `_matches` reads the COMPILED pattern key, so a
    hand-built rule carrying `title_regex` and no compiled twin has that
    condition skipped rather than applied. A `mark_fp` rule assembled that way
    matches on whatever conditions remain, which for a rule with one condition
    is everything -- so passing `rules=` was a route around every refusal
    `load_rules` makes, and a way to suppress an arbitrary finding as a false
    positive at `info`. Validating here compiles the patterns and closes it.
    """
    if rules is None:
        return load_rules()
    for rule in rules:
        _validate_rule(rule)
    return rules


def _resolved_environment(env, url):
    """The environment key a `cap_at` split will be read under.

    TOTAL: every input resolves to `uat` or `prod`, and nothing here raises.
    That totality is the guarantee, not a convenience. A `cap_at` rule reads
    `severity_<env>` and falls back to a plain `severity`, so an env of `PROD`
    or `production` used to find neither key on a split rule and the cap silently
    did not apply -- a production tokenization-key leak stayed critical with
    nothing recorded. Because every value now resolves to one of the two
    targets, a split cap always fires with one of them and no value can disable
    it. Raising instead would trade a silent failure for a noisy one on an input
    that is perfectly readable, which is a different defect rather than the fix.

    A word that is not already `uat` or `prod` is classified by the SAME rule the
    url classifier uses, by calling it: `resolve_environment` treats a bare word
    as a hostname, so `staging` and `uat2` carry a non-production token as a
    whole segment and give `uat`, while `production` and `prd` do not and give
    `prod`. The rule is not restated here, it is called, so the two cannot drift
    apart.

    An absent or blank `env` means the caller has not said, so the environment is
    derived from the finding's url instead.
    """
    if env is None or not str(env).strip():
        return resolve_environment(url)
    key = str(env).strip().lower()
    return key if key in _ENVIRONMENTS else resolve_environment(key)


def _reconcile_cvss(finding: dict, raw: dict, current: str):
    """The CVSS reconciliation, as `(severity, fired id, skipped id)`.

    The vector is read off the finding first and out of `raw_data` second,
    because both are places a caller really puts it and a reconciliation that
    reads only one of them silently does nothing for callers using the other.

    Provenance decides everything, and it is asked positively: only a
    `cvss_source` recognised as `authored` reconciles. That is the fail-closed
    divergence the module docstring names, and the direction matters. Lowering a
    severity because of a vector nobody vouched for suppresses a finding on
    unattributed evidence, and an unattributed vector could have been written by
    anything, a model included -- so the conservative outcome is to leave the
    asserted severity alone until something vouches for a lower one.

    A `derived` label is skipped silently, because a vector computed from a
    severity band is not evidence against that band and there is nothing for a
    reader to act on. Anything else -- no label, or a label this module does not
    recognise -- is skipped and REPORTED, as `cvss-reconcile-skipped-unattributed`.
    An unrecognised label is grouped with the missing one on purpose: both mean
    nobody has vouched for the vector, and filing a misspelled label under a
    different outcome would be the same mis-attribution this divergence exists
    to remove.

    The skip is only reported when it would have mattered. A vector whose band
    is not below the current severity changes nothing under any provenance, so
    there is nothing there to have been skipped, and reporting one would make a
    corpus count of unattributed vectors read higher than the number of
    downgrades it actually cost.

    A vector CVSS cannot score yields no band and changes nothing. An absent
    band is not a severity of zero, and a governor that read it as one would
    demote every finding carrying a malformed vector.
    """
    vector = finding.get("cvss_vector") or raw.get("cvss_vector")
    if not _present(vector):
        return current, None, None
    band = band_from_score(cvss_base_score(vector))
    if not band or rank(band) >= rank(current):
        return current, None, None
    source = str(finding.get("cvss_source") or raw.get("cvss_source") or "").strip().lower()
    if source.startswith(_AUTHORED):
        return band, "cvss-reconcile", None
    if source.startswith(_DERIVED):
        return current, None, None
    return current, None, _SKIPPED_UNATTRIBUTED


def govern_finding(finding: dict, rules: list = None, env: str = None,
                   enforce_evidence_ceiling: bool = True) -> dict:
    """Reconcile one finding's severity and false-positive flag, and record why.

    Mutates and returns the finding. There is no path through this function
    that raises a severity: the CVSS branch acts only when the vector's band
    ranks below the current severity, a `cap_at` or `downgrade_to` rule acts
    only when its target ranks below it, `mark_fp` moves to `info`, which is the
    floor, and the evidence ceiling acts only when the current severity ranks
    above the ceiling. Flip any one of those comparisons and a sweep in
    tests/test_severity_governor.py fails, naming the combination that rose --
    though only the ceiling flip is caught by the three-axis sweep, because that
    sweep's findings carry no vector and match no rule; the other two are caught
    by the cross-product sweep beside it.

    `cap_at` and `downgrade_to` read their target differently and are not merged
    here. A cap reads `severity_<env>` and falls back to a plain `severity`; a
    downgrade reads `severity` alone and takes no environment split, which is
    what the system this is re-expressed from does. `load_rules` refuses a
    `downgrade_to` carrying split keys, so the difference cannot be tripped over
    silently.

    A governance record is written only when the severity or the false-positive
    flag actually moved. Writing one on every pass is how a corpus fills with
    records whose `rules_fired` is empty, and a count of governed findings then
    measures how many were looked at rather than how many changed. When
    something did move, the record goes both on the finding as
    `governance_record` and inside `raw_data.governance`, because the store's
    governed write persists `raw_data` and nothing else, so a record living only
    at the top level would not survive the round trip.

    A skipped reconciliation is NOT a change and does not earn a record. It is
    reported on the returned finding under `reconcile_skipped`, deliberately at
    the top level and deliberately outside `raw_data`, so that no caller can
    persist it by writing `raw_data` back: a stored record on a row whose
    severity did not move is the shape that makes a coverage count mean
    something other than its name. `govern_scan` reads that key to count skips
    into its summary, which is where a scan-level statistic belongs. When a
    finding both moved and skipped, the record it earns for moving carries the
    skip under `skipped` as well, because that record exists on its own merits.

    `enforce_evidence_ceiling` gates the ceiling alone, for a caller that wants
    the CVSS and ruleset passes on a corpus whose tools do not yet capture
    evidence. Turning it off cannot raise anything either -- it removes a
    lowering step, it does not add a raising one.
    """
    rules = _validated_rules(rules)
    raw = _as_dict(finding.get("raw_data"))
    finding["raw_data"] = raw

    original = str(finding.get("severity") or "info").strip().lower()
    current = original
    was_false_positive = bool(finding.get("false_positive"))
    grade = evidence_grade(finding)
    env = _resolved_environment(env, finding.get("url"))
    fired, skipped = [], []

    current, cvss_fired, cvss_skipped = _reconcile_cvss(finding, raw, current)
    if cvss_fired:
        fired.append(cvss_fired)
    if cvss_skipped:
        skipped.append(cvss_skipped)

    for rule in match_rules(finding, rules):
        action = rule.get("action")
        if action == "mark_fp":
            finding["false_positive"] = True
            finding["fp_reason"] = rule["id"]
            current = "info"
            fired.append(rule["id"])
        elif action == "cap_at":
            target = str(rule.get("severity_" + env) or rule.get("severity") or "")
            if target and rank(target) < rank(current):
                current = target.strip().lower()
                fired.append(rule["id"])
        elif action == "downgrade_to":
            target = str(rule.get("severity") or "")
            if target and rank(target) < rank(current):
                current = target.strip().lower()
                fired.append(rule["id"])

    if enforce_evidence_ceiling:
        ceiling = EVIDENCE_CEILING.get(grade)
        if ceiling and rank(current) > rank(ceiling):
            current = ceiling
            fired.append("evidence-ceiling")

    finding["severity"] = current
    if skipped:
        finding["reconcile_skipped"] = list(skipped)
    changed = (current != original
               or bool(finding.get("false_positive")) != was_false_positive)
    if changed:
        record = {
            "original_severity": original,
            "final_severity": current,
            "rules_fired": list(fired),
            "skipped": list(skipped),
            "evidence_grade": grade,
            "cvss_source": str(finding.get("cvss_source")
                               or raw.get("cvss_source") or "none"),
            "environment": env,
            "ceiling_enforced": enforce_evidence_ceiling,
        }
        if fired:
            finding["rules_fired"] = list(fired)
        finding["governance_record"] = record
        raw["governance"] = record
    return finding


def _request_from(finding: dict, raw: dict):
    """A request dict assembled from evidence the finding already carries, or
    `None`.

    A bare target url is never request evidence, so a method, payload, params or
    body must be present beside it. Drop that condition and every finding
    carrying a url normalises into a request, grades `moderate` instead of
    `thin`, and the thin ceiling caps nothing anywhere in the corpus.
    """
    for candidate in (_as_dict(finding.get("request_data")), _as_dict(raw.get("request"))):
        if candidate:
            return candidate
    url = finding.get("url") or raw.get("url") or raw.get("test_url")
    method = raw.get("method") or raw.get("http_method")
    extras = (("method", str(method).upper() if _present(method) else None),
              ("payload", raw.get("payload")),
              ("params", raw.get("params")),
              ("body", raw.get("request_body")))
    present = {key: value for key, value in extras if _present(value)}
    if url and present:
        return dict({"url": url}, **present)
    return None


def _response_from(finding: dict, raw: dict):
    """A response dict assembled from evidence the finding already carries, or
    `None`. A status, a body fragment or a header block is enough; nothing at
    all yields nothing.
    """
    for candidate in (_as_dict(finding.get("response_data")), _as_dict(raw.get("response"))):
        if candidate:
            return candidate
    status = raw.get("status_code") or raw.get("status")
    body = (raw.get("response_snippet") or raw.get("body_preview")
            or raw.get("body") or raw.get("snippet"))
    headers = raw.get("response_headers")
    parts = (("status", status), ("headers", headers), ("body_snippet", body))
    present = {key: value for key, value in parts if _present(value)}
    return present or None


def normalize_finding_evidence(finding: dict) -> dict:
    """Canonicalise the evidence a finding already carries into
    `raw_data.evidence = {request, response, summary?}`. Mutates and returns.

    It fabricates nothing and clobbers nothing. An authored evidence dict is
    left as it is, a pre-existing string is preserved as `summary` beside the
    canonical pair rather than overwritten, and a finding carrying no artifacts
    comes back with no evidence block at all.

    One shape is rewritten rather than left alone: an evidence dict holding a
    captured body under its own keys -- a snippet, optionally with a status --
    and neither a request nor a response is folded into `evidence.response`, so
    `evidence_grade` credits the capture as a side instead of grading the
    finding thin. That is a move, not an invention: the snippet and the status
    were both observed by whatever wrote them.

    This runs before `govern_finding` in `govern_scan` because the ceiling is
    only as fair as the grade beneath it, and a real capture filed under an
    unexpected key would otherwise be capped as if nothing had been captured.
    """
    raw = finding.get("raw_data")
    if not isinstance(raw, dict):
        raw = _as_dict(raw)
        finding["raw_data"] = raw
    evidence = raw.get("evidence")
    if isinstance(evidence, dict) and evidence:
        if not _present(evidence.get("request")) and not _present(evidence.get("response")) \
                and _present(evidence.get("snippet")):
            response = {"body_snippet": evidence["snippet"]}
            if _present(evidence.get("status")):
                response = {"status": evidence["status"],
                            "body_snippet": evidence["snippet"]}
            evidence["response"] = response
        return finding
    request = _request_from(finding, raw)
    response = _response_from(finding, raw)
    if request or response:
        canonical = {}
        if request:
            canonical["request"] = request
        if response:
            canonical["response"] = response
        if isinstance(evidence, str) and evidence.strip():
            canonical["summary"] = evidence
        raw["evidence"] = canonical
    return finding


async def fetch_all_findings(store, exclude_fp: bool = True, page: int = 1000) -> list:
    """Every finding in the store's scan, paged past the store's own limit.

    The paging is a correctness property and not a convenience. `get_findings`
    answers with at most its limit, so a caller asking once and treating the
    answer as the whole scan truncates silently as soon as the scan outgrows
    that limit -- and a consolidation run over a truncated corpus reports a
    clean result for work it never did. This asks for successive windows until
    a short one comes back.

    Offset paging is safe here because of how callers use it: they read the
    full list up front and only then mutate, so the table is not moving under
    the offsets while they advance. A caller that wrote as it paged would need
    a different strategy.
    """
    if page <= 0:
        page = 1000
    findings, offset = [], 0
    while True:
        batch = await store.get_findings(exclude_fp=exclude_fp, limit=page, offset=offset)
        findings.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return findings


async def govern_scan(store, scan_id=None, rules=None) -> dict:
    """Re-govern every finding in a scan, persisting only what moved.

    Returns `{"total", "changed", "skipped", "changes"}`. Idempotent: a second
    pass over an already-governed scan changes nothing and writes nothing,
    because the governor is a pure function of the finding and the ruleset.

    Two environment switches gate this pass and both default to on, which is
    where and how the system this is re-expressed from puts them.
    `AUTOMATOR_GOVERNANCE` set to `0` returns the zero summary without reading a
    single finding, so governance can be taken out of a run entirely.
    `AUTOMATOR_GOVERNANCE_EVIDENCE_CEILING` set to `0` runs the reconciliation
    and the ruleset but not the thin-evidence cap, which is the switch a corpus
    needs while its tools do not yet capture evidence: capping before capture
    would penalise a finding for missing artifacts nothing was collecting.
    Neither switch can raise a severity -- each one removes work, and every
    piece of work this module does lowers or leaves alone.

    False positives are fetched rather than excluded, and the reason is
    arithmetic rather than corrective. `total` is meant to count the scan's
    findings, and excluding flagged rows would make it count the unflagged ones
    while still being called the total. Re-governing a flagged row changes
    nothing: `mark_fp` re-derives the same flag, and `info` is already the floor
    so no cap can move it. **This module never clears a false-positive flag.**
    `finding["false_positive"] = True` is the only assignment to that key
    anywhere in the file and there is no path that sets it False, because
    clearing a flag would return a suppressed finding to visibility, which is an
    escalation under another name. So flagged rows contribute to `total` and to
    no other field, and a rule correction that ought to unflag one is a job for
    a caller that is allowed to raise, not for this pass.

    `store.update_finding_governed` is called WITHOUT `await`. That store member
    is synchronous while `get_findings` beside it is a coroutine, and the
    asymmetry is reproduced rather than tidied: awaiting a plain function raises,
    while calling a coroutine as a bare statement writes nothing at all and
    raises nothing, so the tidy-looking version is the one that fails silently.

    A write happens only when a severity or a flag moved. A skipped
    reconciliation is counted and never stored, and the split is deliberate: the
    number of vectors nobody vouched for is a scan-level statistic, so it belongs
    in this summary, while a persisted record on a row whose severity did not
    move is the shape that makes a coverage count mean something other than its
    name. So the count is returned rather than written down.

    `changed` and `skipped` are independent counts over the same population, not
    a partition of it. `changed` counts findings whose severity or flag moved;
    `skipped` counts findings whose reconciliation was skipped for want of an
    attributed vector. A finding can be in both, so neither number is a subset of
    the other and adding them together means nothing.

    `scan_id` is accepted and unused. The store is already scoped to a single
    scan, so a caller passing one is telling this function something it does not
    need to read; the parameter stays because callers pass it.
    """
    summary = {"total": 0, "changed": 0, "skipped": 0, "changes": []}
    if os.getenv(_GOVERNANCE_SWITCH, "1") == "0":
        return summary
    enforce_ceiling = os.getenv(_CEILING_SWITCH, "1") != "0"
    rules = _validated_rules(rules)
    for finding in await fetch_all_findings(store, exclude_fp=False):
        summary["total"] += 1
        before_severity = str(finding.get("severity") or "info").strip().lower()
        before_fp = bool(finding.get("false_positive"))
        normalize_finding_evidence(finding)
        govern_finding(finding, rules=rules,
                       enforce_evidence_ceiling=enforce_ceiling)
        after_severity = str(finding.get("severity") or "info").strip().lower()
        after_fp = bool(finding.get("false_positive"))
        if finding.get("reconcile_skipped"):
            summary["skipped"] += 1
        moved = after_severity != before_severity or after_fp != before_fp
        if not moved:
            continue
        store.update_finding_governed(finding["id"], after_severity,
                                      finding.get("raw_data") or {}, after_fp)
        summary["changed"] += 1
        summary["changes"].append({"id": finding["id"], "from": before_severity,
                                   "to": after_severity, "false_positive": after_fp})
    return summary
