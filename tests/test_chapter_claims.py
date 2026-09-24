"""Executable assertions for the behavioural claims the handbook makes about ``core/``.

``scripts/verify_claims.sh`` proves that a cited symbol exists and that a cited
number resolves. It cannot prove that a *sentence about behaviour* is true, and
that is the gap chapter 00 fell through once already: a ranking claim was
written from a single profile, generalised past what had been run, and shipped
wrong. A claim nobody can execute is a claim nobody can check.

So every reproducible behavioural claim in a chapter gets an assertion here.
Each test's anchor names the chapter and quotes the sentence it backs, and
records no line number -- line numbers drift and the quote is the durable
anchor. Where a line number does appear it is in the prose around a test, which
nothing reads: strip every one of them and the suite stays green and
tests/test_gates.sh still reports gates verified. If a test here fails, either
``core/`` changed under a chapter or the chapter was wrong; both need a human.

Scope: chapters 00 through 05, plus the README, which is anchored the same way
because it copies the five laws and the attribution line out of chapter 00. Do
not backfill claims for chapters that do not exist, and do not write a test that
asserts something *adjacent* to a chapter sentence about a module this repository
does not ship -- an approximate test is worse than a visible gap. Chapter 03 is
the first chapter whose subject is not in ``core/`` at all, so its tests assert
against the published corpus figures in ``data/stats.json`` and say so; they pin
what the chapter counts, never how the unshipped governor behaves.
"""

import dataclasses
import itertools
import pathlib

import pytest

from core import tool_recommender
from core.consolidator import consolidation_signature
from core.fingerprint import TargetProfile
from core.gate_check import decide_gate_status
from core.response_analyzer import ResponseAnalyzer, SecurityProfile
from core.scheduler import ExecutionResult, SmartScheduler
from core.tool_recommender import (
    RELEVANCE,
    ToolRecommender,
    ToolRelevance,
    _condition_field_label,
    _evaluate_condition,
)


def chapter_claim(chapter, *sentences):
    """Mark a test as backing one or more verbatim sentences in *chapter*.

    A no-op at runtime -- it returns the decorated function unchanged. The
    chapter path and sentence text are read statically, via ``ast`` and with no
    import of this module, by scripts/verify_claims.sh Check C.

    WHAT THE ANCHOR CATCHES: a declared sentence its chapter no longer carries
    -- whether the chapter was edited under a fixed anchor or the anchor was
    edited to a wording the chapter does not have, since both are the one
    comparison. The gate prints ``CHAPTER CLAIM FAIL`` above the line ``<test>
    claims a sentence not found in <chapter>`` and exits 1. A test in a file
    that uses this decorator and declares nothing of its own fails the same gate
    with ``has no chapter_claim() anchor``. Sentence presence is read only for a
    chapter inside the target of the invocation, so a run over handbook/ never
    reads a README anchor, and a run over README.md never reads a chapter one.

    WHAT THE ANCHOR CANNOT CATCH, structurally rather than pending a stricter
    matcher: one edit that changes the chapter sentence and this anchor
    together. The anchor is the only text the check has to compare the chapter
    against, so a coordinated edit is compared with itself and matches. Exact
    matching, bounded matching and hashing each read the anchor, so each of them
    passes it too; there is no matcher here that closes this. Measured rather
    than reasoned: narrowing "after the first" to "after the first two" in a
    sentence and in its anchor at once leaves this gate silent, which
    tests/test_gates.sh reconstructs on a scratch tree.

    WHAT CARRIES THAT CASE INSTEAD: the content assertions in the test bodies
    below, which read the chapter and README text themselves and hold their own
    expectations rather than quoting the anchor's. The ones that pin WORDING are
    bounded matches, because a bare ``in`` test is defeated by an inserted word
    -- the comment above ADMISSION_CLAUSE records the narrowing that was run
    against one and walked through. Two are bare on purpose and are not pinning
    wording: the sentence locator, which fails loudly by finding nothing, and the
    num-ok category filters, which are backed by exact counts. For what none of
    them reaches, a human reads the diff.

    Quote the sentence exactly as it reads on the page, whole: the comparison is
    containment, so a fragment of a chapter sentence is accepted as readily as
    the sentence, and an anchor trimmed to a fragment quietly stops pinning the
    words it dropped. The gate strips citations, backticks and HTML comments,
    collapses every run of whitespace -- which is what makes paragraph-internal
    line-wrap invisible, and a doubled space with it -- and skips fenced blocks
    entirely, so a sentence that lives only inside a fence cannot be anchored at
    all. It changes nothing else -- no case-folding, no punctuation-stripping.
    """

    def decorator(fn):
        return fn

    return decorator


# The literal condition strings this file reasons about, read from the
# catalogue rather than retyped, so an edit to either gate fails loudly here
# instead of silently invalidating the assertions below.
SQLI_REQUIRES_ANY = RELEVANCE["test_sqli"].requires_any
NOSQL_REQUIRES = RELEVANCE["test_injection_nosql"].requires
MONGO_PENALTY_CONDITION = "likely_database == 'mongodb'"

# Databases that satisfy test_sqli's requires_any gate.
SQL_FAMILY = ["mysql", "postgresql", "mssql", "oracle", "sqlite", "unknown"]

# Fields the chapter's prose ("a PHP, Laravel, MySQL profile") leaves unsaid.
# These are exactly the fields whose variation moved test_sqli's *position*
# between #1 and #10; membership has to survive all of them.
VARIANTS = [
    pytest.param("low", False, [], id="quiet-nowaf-notypes"),
    pytest.param("high", False, ["form", "json"], id="verbose-nowaf-formjson"),
    pytest.param("low", True, ["json"], id="quiet-waf-json"),
    pytest.param("high", True, [], id="verbose-waf-notypes"),
]

BACKENDS = ["php", "node", "python", "java"]


def _profile(backend, database, verbosity, waf, content_types):
    return TargetProfile(
        backend_language=backend,
        likely_database=database,
        error_verbosity=verbosity,
        waf_detected=waf,
        waf_vendor="cloudflare" if waf else None,
        content_types_accepted=list(content_types),
        api_types=["rest"],
    )


def _ranked(profile):
    return [name for name, _score, _reason in ToolRecommender().recommend(profile)]


# ---------------------------------------------------------------------------
# Claim 1 -- the membership invariant.
#
# handbook/00-thesis.md:78 (as of this commit):
#   "Run the reference implementation in core/ against a PHP, Laravel, MySQL
#    profile and the NoSQL injection tool never enters the ranked list at all.
#    [...] Change those three fields to Node, Express, MongoDB and the exclusion
#    reverses exactly: the NoSQL tool is scored, and the SQL injection tool is
#    the one that never appears [...]"
#
# and handbook/00-thesis.md:80:
#   "Membership does not move."
#
# What breaks these tests: any edit that loosens test_sqli's requires_any or
# test_injection_nosql's requires, or that adds either database to the other's
# gate. That is the whole load-bearing surface of the chapter's one falsifiable
# demonstration.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("database", SQL_FAMILY)
@pytest.mark.parametrize("verbosity, waf, content_types", VARIANTS)
@chapter_claim(
    'handbook/00-thesis.md',
    'the NoSQL injection tool never enters the ranked list at all',
)
def test_nosql_tool_absent_from_every_sql_family_profile(
    database, verbosity, waf, content_types
):
    for backend in BACKENDS:
        profile = _profile(backend, database, verbosity, waf, content_types)
        ranked = _ranked(profile)
        assert "test_injection_nosql" not in ranked, (
            f"chapter 00 claims the NoSQL tool never enters the list on a "
            f"{database} profile, but it did: {profile.profile_hash()}"
        )
        assert "test_sqli" in ranked, (
            f"chapter 00 claims the SQL injection tool is scored and present "
            f"on a {database} profile, but it was dropped: "
            f"{profile.profile_hash()}"
        )


@pytest.mark.parametrize("verbosity, waf, content_types", VARIANTS)
@chapter_claim(
    'handbook/00-thesis.md',
    'the NoSQL tool is scored, and the SQL injection tool is the one that never appears',
)
def test_sqli_tool_absent_from_every_mongodb_profile(verbosity, waf, content_types):
    for backend in BACKENDS:
        profile = _profile(backend, "mongodb", verbosity, waf, content_types)
        ranked = _ranked(profile)
        assert "test_sqli" not in ranked, (
            "chapter 00 claims the SQL injection tool never appears on a "
            f"MongoDB profile, but it did: {profile.profile_hash()}"
        )
        assert "test_injection_nosql" in ranked, (
            "chapter 00 claims the exclusion reverses exactly, so the NoSQL "
            f"tool must be scored here, and it was not: {profile.profile_hash()}"
        )


@chapter_claim(
    'handbook/00-thesis.md',
    "Its requires gate asks for likely_database == 'mongodb'",
    'MongoDB is missing from its requires_any list',
)
def test_membership_claim_rests_on_the_two_gates_it_names():
    """The chapter attributes the exclusions to specific fields. Pin that too.

    Backs handbook/00-thesis.md:78, "Its ``requires`` gate asks for
    ``likely_database == 'mongodb'``" and "MongoDB is missing from its
    ``requires_any`` list". If someone moves the exclusion to a different
    mechanism the sweeps above still pass while the prose goes stale.
    """
    assert NOSQL_REQUIRES == [MONGO_PENALTY_CONDITION]
    assert len(SQLI_REQUIRES_ANY) == 1
    assert "mongodb" not in SQLI_REQUIRES_ANY[0]
    for database in SQL_FAMILY:
        assert f"'{database}'" in SQLI_REQUIRES_ANY[0]


# ---------------------------------------------------------------------------
# Claim 2 -- the dead-config finding.
#
# handbook/00-thesis.md:56 (as of this commit):
#   "The SQL injection entry carries both, and its mongodb penalty of 0.1
#    turns out to be unreachable, because requires_any has already excluded
#    MongoDB by the time that multiplier could apply."
#
# What breaks this test: adding mongodb to test_sqli's requires_any, or moving
# the penalty behind a condition the gate does not already exclude. Either
# would make the penalty live and the sentence false.
# ---------------------------------------------------------------------------


@chapter_claim(
    'handbook/00-thesis.md',
    'its mongodb penalty of 0.1 can never fire',
)
def test_mongodb_penalty_on_sqli_never_fires(monkeypatch):
    """Instrumented sweep: the condition is asked, and never comes back true.

    Note the shape of this assertion, because the obvious one is wrong. The
    condition IS evaluated, on every scoring pass where the gate is open --
    ``recommend()`` walks the whole ``penalizes`` map after requirements pass,
    so the dead entry still costs a dictionary lookup each time. What it never
    does is hold. The first version of this test asserted "never evaluated"
    and failed on its first run, which is the argument for the file existing.
    """
    assert MONGO_PENALTY_CONDITION in RELEVANCE["test_sqli"].penalizes, (
        "the penalty this test calls dead is no longer in the catalogue; "
        "chapter 00's sentence about it needs rewriting, not this assertion"
    )

    # Score test_sqli alone, so any evaluation of the mongodb condition can
    # only have come from its penalizes map.
    recommender = ToolRecommender({"test_sqli": RELEVANCE["test_sqli"]})
    satisfied = []
    real_evaluate = tool_recommender._evaluate_condition

    def spy(profile, condition):
        result = real_evaluate(profile, condition)
        if result:
            satisfied.append(condition)
        return result

    monkeypatch.setattr(tool_recommender, "_evaluate_condition", spy)

    for database in SQL_FAMILY + ["mongodb", "redis", None]:
        for verbosity, waf, content_types in [
            ("low", False, []),
            ("high", True, ["form", "json"]),
        ]:
            for backend in BACKENDS:
                recommender.recommend(
                    _profile(backend, database, verbosity, waf, content_types)
                )

    assert satisfied, "the spy never fired; the sweep is not exercising the scorer"
    assert MONGO_PENALTY_CONDITION not in satisfied, (
        "chapter 00 calls this penalty dead, but it held during scoring"
    )


@chapter_claim(
    'handbook/00-thesis.md',
    'requires_any has already excluded MongoDB by the time that multiplier would apply',
)
def test_mongodb_penalty_on_sqli_is_structurally_unreachable():
    """The stronger form: whenever the penalty would hold, the gate has closed.

    A sweep samples. This asserts the implication itself, so it holds for
    profiles the sweep above never constructs.
    """
    relevance = RELEVANCE["test_sqli"]
    recommender = ToolRecommender()
    for database in SQL_FAMILY + ["mongodb", "redis", "cassandra", None]:
        profile = _profile("php", database, "high", False, ["json"])
        penalty_would_hold = tool_recommender._evaluate_condition(
            profile, MONGO_PENALTY_CONDITION
        )
        gate_open = recommender._requirements_met(profile, relevance)
        assert not (penalty_would_hold and gate_open), (
            f"the mongodb penalty is reachable after all on {database!r}: "
            "chapter 00's dead-config claim is wrong"
        )


# ---------------------------------------------------------------------------
# Claim 2b -- the documented signature runs.
#
# handbook/00-thesis.md:155 and README.md:35 both invite a reader to run the
# code under core/. Nothing executed recommend()'s SECOND parameter until this
# test: every assertion above calls it with a profile alone, and the
# two-argument form shipped raising AttributeError, because the indicator
# accessor it calls lived only on ResponseAnalyzer while the annotation, the
# docstring and the usage example all say SecurityProfile. An invitation to run
# code that raises on its own advertised signature is the one defect a public
# reference implementation cannot carry, and no citation check can see it: the
# symbol both modules name exists, in the wrong class.
# ---------------------------------------------------------------------------


@chapter_claim(
    'handbook/00-thesis.md',
    'the profiling, the scoring, the scheduling, and the validation are real and runnable',
)
def test_recommend_runs_on_both_of_its_documented_signatures():
    profile = _profile("php", "mysql", "low", False, ["json"])
    recommender = ToolRecommender()

    one_arg = dict((n, s) for n, s, _ in recommender.recommend(profile))
    # The second parameter is annotated SecurityProfile, so hand it one.
    empty = SecurityProfile()
    assert empty.indicators() == []
    two_arg = dict((n, s) for n, s, _ in recommender.recommend(profile, empty))
    assert two_arg == one_arg, "an empty SecurityProfile must not move a score"

    # And it has to do the thing the docstring says it does: an active
    # indicator raises the tool _INDICATOR_BOOSTS names, by that multiplier,
    # unattenuated by field confidence (the indicator is an observation, not
    # a fingerprint guess, so there is no confidence to weight it by).
    tagged = SecurityProfile()
    tagged._active_tags.add("sql_error")
    assert tagged.indicators() == ["sql_error"]
    boosted = dict((n, s) for n, s, _ in recommender.recommend(profile, tagged))
    expected = tool_recommender._INDICATOR_BOOSTS["sql_error"]["test_sqli"]
    # abs= absorbs recommend()'s own round(score, 2), which is applied once to
    # each of the two scores being compared; the signal being asserted is a
    # num-ok: 1.5 is _INDICATOR_BOOSTS["sql_error"]["test_sqli"] in core/tool_recommender.py, read into `expected` above rather than retyped -- a source literal, not a measurement
    # multiplier of 1.5 on a score in the twenties, so the tolerance is three
    # orders of magnitude smaller than the difference it has to detect.
    assert boosted["test_sqli"] == pytest.approx(
        one_arg["test_sqli"] * expected, abs=0.02
    )
    # Only the named tool moves.
    for name, score in boosted.items():
        if name != "test_sqli":
            assert score == pytest.approx(one_arg[name]), name

    # One tag set, one implementation: the analyzer delegates to the profile.
    analyzer = ResponseAnalyzer()
    assert analyzer.indicators() == analyzer.get_security_profile().indicators()


# ===========================================================================
# Chapter 01 -- handbook/01-fixed-procedure.md
#
# Same rule as above: chapter 01 asserts things about core/ that a citation
# check cannot verify, so each one is executed here. Several of them are
# claims of *absence* ("this penalty can never fire", "membership never
# changes"), which a sample cannot establish, so those are swept over the
# whole space the condition language can distinguish rather than over a few
# hand-picked profiles.
# ===========================================================================

# Fields the condition DSL exposes, grouped by the shape of their domain.
_BOOL_FIELDS = frozenset({
    "waf_detected", "rate_limited", "cors_enabled", "cors_permissive",
    "jwt_detected", "has_graphql", "has_websocket", "has_file_upload",
    "has_search", "accepts_xml",
})
_LIST_FIELDS = frozenset({"api_types", "content_types_accepted", "auth_mechanisms"})
_STR_FIELDS = frozenset({
    "backend_language", "framework", "frontend_framework", "server_software",
    "waf_vendor", "likely_database", "error_verbosity",
})
_DSL_FIELDS = _BOOL_FIELDS | _LIST_FIELDS | _STR_FIELDS

# Confidence attributes _field_confidence knows about, and the fields they
# attenuate. Retyped from the helper's own map on purpose: if the helper
# changes, the assertions that depend on the split should fail, not adapt.
_CONFIDENCE_TRACKED = ("likely_database", "backend_language", "framework",
                       "waf_detected", "waf_vendor")


def _catalogue_literals():
    """Every literal value the catalogue compares each DSL field against.

    The condition language only ever compares a field to a literal, so two
    values that appear in no condition are indistinguishable to it. Harvesting
    the literals and adding one sentinel for "some other value" therefore
    covers every case the DSL can tell apart, which is what makes the
    unreachability sweeps below exhaustive rather than merely wide.
    """
    found = {f: set() for f in _DSL_FIELDS}
    for rel in RELEVANCE.values():
        conditions = (list(rel.requires) + list(rel.requires_any)
                      + list(rel.boosts) + list(rel.penalizes))
        for cond in conditions:
            field = _condition_field_label(cond)
            if field not in found:
                continue
            if cond.startswith("'") and "' in " in cond:
                found[field].add(cond.split("' in ", 1)[0].lstrip("'"))
            elif " in [" in cond:
                rhs = cond.split(" in [", 1)[1].rstrip("] ")
                found[field].update(v.strip().strip("'\" ") for v in rhs.split(","))
            else:
                for sep in ("==", "!="):
                    if sep in cond:
                        found[field].add(cond.split(sep, 1)[1].strip().strip("'\" "))
                        break
    return found


_LITERALS = _catalogue_literals()


def _domain(field):
    if field in _BOOL_FIELDS:
        return [True, False]
    values = sorted(v for v in _LITERALS[field] if v not in ("True", "False"))
    if field in _LIST_FIELDS:
        return [[]] + [[v] for v in values] + [values]
    return values + ["unknown", "__some_other_value__", None]


def _profiles_over(fields):
    """Every profile the DSL can distinguish, varying only *fields*."""
    if not fields:
        yield TargetProfile()
        return
    for combo in itertools.product(*(_domain(f) for f in fields)):
        yield TargetProfile(**dict(zip(fields, combo)))


def _fields_touched_by(rel):
    conditions = list(rel.requires) + list(rel.requires_any) + list(rel.penalizes)
    return sorted({
        _condition_field_label(c) for c in conditions
        if _condition_field_label(c) in _DSL_FIELDS
    })


def _unreachable_penalties():
    """(tool, condition) pairs where no distinguishable profile opens the gate
    and satisfies the penalty at the same time."""
    recommender = ToolRecommender()
    dead = []
    for name, rel in RELEVANCE.items():
        profiles = list(_profiles_over(_fields_touched_by(rel)))
        for condition in rel.penalizes:
            reachable = any(
                recommender._requirements_met(p, rel)
                and _evaluate_condition(p, condition)
                for p in profiles
            )
            if not reachable:
                dead.append((name, condition))
    return dead


# ---------------------------------------------------------------------------
# Claim 3 -- the profile, and what the hash throws away.
#
# handbook/01-fixed-procedure.md:20  "it is 30 fields wide"
# handbook/01-fixed-procedure.md:22  "which projects those fields down to six
#                                     components"
# handbook/01-fixed-procedure.md:31  "All four confidence scores go. So does
#                                     the entire attack-surface block [...] a
#                                     target where nothing was detected is
#                                     filed under REST, indistinguishable from
#                                     one where REST was positively identified."
# ---------------------------------------------------------------------------


@chapter_claim(
    'handbook/01-fixed-procedure.md',
    'it is 30 fields wide',
    'which projects those fields down to six components',
)
def test_profile_is_thirty_fields_and_the_hash_keeps_six():
    assert len(dataclasses.fields(TargetProfile)) == 30
    assert len(TargetProfile().profile_hash().split(":")) == 6
    assert list(TargetProfile().profile_components()) == [
        "backend", "database", "waf_status", "waf_vendor", "api_type", "framework",
    ]


@chapter_claim(
    'handbook/01-fixed-procedure.md',
    'All four confidence scores go.',
    'the two pool their statistics',
)
def test_hash_discards_confidence_and_attack_surface():
    plain = TargetProfile(
        backend_language="php", likely_database="mysql",
        framework="laravel", api_types=["rest"],
    )
    loaded = TargetProfile(
        backend_language="php", likely_database="mysql",
        framework="laravel", api_types=["rest"],
        backend_confidence=1.0, database_confidence=1.0,
        framework_confidence=1.0, waf_confidence=1.0,
        has_file_upload=True, has_search=True, accepts_xml=True,
        error_verbosity="high", jwt_detected=True, cors_permissive=True,
        auth_mechanisms=["jwt"], server_software="nginx",
    )
    assert plain.profile_hash() == loaded.profile_hash(), (
        "chapter 01 claims the two pool their statistics, which requires the "
        "hash to collapse them onto one key"
    )


@chapter_claim(
    'handbook/01-fixed-procedure.md',
    'a target where nothing was detected is filed under REST, indistinguishable from one where REST was positively identified',
)
def test_undetected_api_type_is_filed_under_rest():
    assert TargetProfile().profile_hash() == TargetProfile(api_types=["rest"]).profile_hash()


# ---------------------------------------------------------------------------
# Claim 3b -- the tier label is inert inside the recommender.
#
# handbook/01-fixed-procedure.md:40  "Force it to return SKIP for every tool
#   and the ranked list comes back in the same order with the same scores and
#   different prose. The tiers are advice to whatever runs the list, not a
#   decision the scorer takes."
# ---------------------------------------------------------------------------


@chapter_claim(
    'handbook/01-fixed-procedure.md',
    'Force it to return SKIP for every tool and the ranked list comes back in the same order with the same scores and different prose.',
    'The tiers are advice to whatever runs the list, not a decision the scorer takes.',
)
def test_tier_label_changes_only_the_reason_string():
    profile = TargetProfile(
        backend_language="php", likely_database="mysql", framework="laravel",
        api_types=["rest"], has_search=True, error_verbosity="high",
    )
    recommender = ToolRecommender()
    honest = recommender.recommend(profile)

    recommender.tier = lambda score: "SKIP"
    lying = recommender.recommend(profile)

    assert [(n, s) for n, s, _r in honest] == [(n, s) for n, s, _r in lying], (
        "chapter 01 claims the tier label reaches nothing but the reason "
        "string; forcing it changed the ranking or the scores"
    )
    assert all(r.startswith("SKIP") for _n, _s, r in lying)
    assert honest[0][2] != lying[0][2]


# ---------------------------------------------------------------------------
# Claim 4 -- two ways out of the ranked list.
#
# handbook/01-fixed-procedure.md:44  "A penalizes entry with a multiplier of
#   zero drives the relevance product to zero, and recommend() discards
#   anything whose score lands at or below zero. Same outcome, different
#   route, and the catalogue uses both."
# ---------------------------------------------------------------------------


@chapter_claim(
    'handbook/01-fixed-procedure.md',
    'A penalizes entry with a multiplier of zero drives the relevance product to zero',
    'discards anything whose score lands at or below zero',
)
def test_a_zero_penalty_alone_drops_a_tool_with_no_gate_at_all():
    ungated = ToolRelevance(
        tool_name="probe", base_priority=8.0, impact_potential=5.0,
        cost_estimate=4.0, penalizes={"has_search == False": 0.0},
    )
    recommender = ToolRecommender({"probe": ungated})
    assert recommender.recommend(TargetProfile(has_search=False)) == [], (
        "chapter 01 claims a zero penalty is a second route out of the list; "
        "with no requires gate present, only the score <= 0 branch can do it"
    )
    assert [n for n, _s, _r in recommender.recommend(TargetProfile(has_search=True))] == ["probe"]


# ---------------------------------------------------------------------------
# Claim 5 -- the graphql entry's penalty, and seven more like it.
#
# handbook/01-fixed-procedure.md:67  "When has_graphql is false the gate closes
#   and the penalizes map is never walked; when it is true the condition is
#   asked and comes back false."
# handbook/01-fixed-procedure.md:72  "8 of the 21 penalty conditions in a
#   catalogue of 26 tools can never fire. Every one is already excluded by a
#   gate on the same field in the same entry."
# ---------------------------------------------------------------------------


@chapter_claim(
    'handbook/01-fixed-procedure.md',
    'When has_graphql is false the gate closes and the penalizes map is never walked; when it is true the condition is asked and comes back false.',
)
def test_graphql_penalty_is_never_walked_and_never_holds(monkeypatch):
    recommender = ToolRecommender({"test_graphql": RELEVANCE["test_graphql"]})
    asked = []
    real_evaluate = tool_recommender._evaluate_condition

    def spy(profile, condition):
        asked.append(condition)
        return real_evaluate(profile, condition)

    monkeypatch.setattr(tool_recommender, "_evaluate_condition", spy)

    asked.clear()
    recommender.recommend(TargetProfile(has_graphql=False))
    assert "has_graphql == False" not in asked, (
        "chapter 01 says the penalizes map is never walked when the gate closes"
    )

    asked.clear()
    ranked = recommender.recommend(TargetProfile(has_graphql=True))
    assert "has_graphql == False" in asked, (
        "chapter 01 says the condition is asked once the gate opens"
    )
    assert [n for n, _s, _r in ranked] == ["test_graphql"], (
        "the penalty held, so the tool was dropped; chapter 01 says it comes "
        "back false"
    )


@chapter_claim(
    'handbook/01-fixed-procedure.md',
    '8 of the 21 penalty conditions in a catalogue of 26 tools can never fire. Every one is already excluded by a gate on the same field in the same entry.',
    'The sweep found seven more, spread across six tools. Five of those repeat a single idiom, a 0.0 penalty behind a gate on the field it names, which is the shape the GraphQL entry above comments do not run and the other four leave uncommented; the remaining two are 0.1 penalties on the NoSQL entry, shut out by that entry\'s own requires.',
)
def test_eight_of_twentyone_penalties_cannot_fire():
    """The commented entry is found by its source region, not by a substring.

    The sentence attributes the ``# do not run`` comment to the GraphQL entry,
    which is a claim about where a line SITS. Reading it as ``"has_graphql" in
    line`` proves only that some line mentioning that field carries the comment:
    move the comment onto a has_graphql penalty planted in another entry's map
    and the substring test still holds while the attribution has become false.
    So the line index is bounded by the start of the test_graphql entry and the
    start of the next one. Proving an attribution by substring is the recurring
    error shape in this handbook, and a [[code:...]] citation is substring
    matching too, which is why this is read off the file at all.
    """
    total_penalties = sum(len(rel.penalizes) for rel in RELEVANCE.values())
    dead = _unreachable_penalties()
    assert len(RELEVANCE) == 26
    assert total_penalties == 21
    assert len(dead) == 8, f"chapter 01 says 8; the sweep found {len(dead)}: {dead}"

    # Chapter 00 found the test_sqli one by hand; chapter 01 claims seven
    # more across SIX tools, of which FIVE share the 0.0 idiom. The first
    # draft said five tools for both halves, which is wrong on the first --
    # nothing mechanical catches a miscounted spelled cardinal, so it is
    # asserted here or nowhere.
    beyond_chapter_00 = [(t, c) for t, c in dead if t != "test_sqli"]
    assert len(beyond_chapter_00) == 7
    assert len({t for t, _c in beyond_chapter_00}) == 6, (
        "chapter 01 says the seven beyond chapter 00's one span six tools"
    )

    zero_multiplier = [(t, c) for t, c in dead if RELEVANCE[t].penalizes[c] == 0.0]
    assert len({t for t, _c in zero_multiplier}) == 5, (
        "chapter 01 says five of those six repeat the 0.0 'do not run' idiom"
    )
    non_zero = [(t, c) for t, c in beyond_chapter_00 if RELEVANCE[t].penalizes[c] != 0.0]
    assert {t for t, _c in non_zero} == {"test_injection_nosql"}
    assert all(RELEVANCE[t].penalizes[c] == 0.1 for t, c in non_zero), (
        "chapter 01 says the two that are not the 0.0 idiom are 0.1 penalties "
        "on the NoSQL entry"
    )

    # The chapter also says the `# do not run` comment sits on the GraphQL
    # entry and that the other four zero penalties carry no comment. That is a
    # claim about what the SOURCE SAYS, not about what it does, and a
    # [[code:...]] citation is a substring match that resolves green either
    # way -- which is exactly how a false version of this sentence shipped
    # once. So it is read off the file.
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "core" / "tool_recommender.py").read_text(encoding="utf-8")
    lines = source.splitlines()
    commented = [
        i for i, line in enumerate(lines)
        if ": 0.0," in line and "do not run" in line
    ]
    assert len(commented) == 1, (
        "chapter 01 attributes the 'do not run' comment to the GraphQL entry "
        f"alone; the source now carries it on {[lines[i] for i in commented]}"
    )
    starts = [i for i, line in enumerate(lines) if "tool_name=" in line]
    graphql_start = next(i for i in starts if 'tool_name="test_graphql"' in lines[i])
    graphql_end = next((i for i in starts if i > graphql_start), len(lines))
    assert graphql_start < commented[0] < graphql_end, (
        "chapter 01 puts the 'do not run' comment inside the test_graphql entry "
        f"(source lines {graphql_start + 1}-{graphql_end}); it now sits on line "
        f"{commented[0] + 1}: {lines[commented[0]]!r}"
    )
    uncommented = [
        line for line in source.splitlines()
        if ": 0.0," in line and "#" not in line and "SKIP" not in line
    ]
    assert len(uncommented) == 4, (
        "chapter 01 says the other four zero penalties are uncommented; the "
        f"source has {len(uncommented)}"
    )

    # "Every one is already excluded by a gate on the same field in the same
    # entry" -- the field the penalty names must also appear in that entry's
    # own requires / requires_any.
    for tool, condition in dead:
        rel = RELEVANCE[tool]
        gate_fields = {
            _condition_field_label(c) for c in list(rel.requires) + list(rel.requires_any)
        }
        assert _condition_field_label(condition) in gate_fields, (
            f"{tool}'s dead penalty {condition!r} is not excluded by a gate on "
            "the same field, so chapter 01's explanation is wrong even though "
            "its count is right"
        )


@chapter_claim(
    'handbook/01-fixed-procedure.md',
    'Point the scorer at a Python, Django, PostgreSQL profile and the prototype-pollution and NoSQL-injection tools are gone before scoring begins, because that stack cannot host either bug, and the run spends its budget somewhere it might pay.',
)
def test_django_postgres_profile_drops_prototype_and_nosql_before_scoring():
    """The chapter's one claim about what the table buys, not what it costs.

    The profile is given in full rather than described, and the exclusion is
    asserted at the gate rather than at the score, because "gone before
    scoring begins" is the specific thing being claimed.
    """
    profile = TargetProfile(
        backend_language="python", framework="django",
        likely_database="postgresql", api_types=["rest"],
    )
    recommender = ToolRecommender()
    ranked = [name for name, _s, _r in recommender.recommend(profile)]

    for tool in ("test_injection_prototype", "test_injection_nosql"):
        assert tool not in ranked
        assert not recommender._requirements_met(profile, RELEVANCE[tool]), (
            f"{tool} left the list on its score, not on its gate; the chapter "
            "says 'before scoring begins'"
        )
    assert ranked, "the table dropped everything, which is not the claim either"


# ---------------------------------------------------------------------------
# Claim 6 -- the confidence asymmetry.
#
# handbook/01-fixed-procedure.md:82  "Sweep any profile across the confidence
#   range and the membership of the ranked list never changes. Only the
#   numbers move [...] so I will not claim a direction."
# handbook/01-fixed-procedure.md:87  "Put a zero penalty on a
#   confidence-tracked field and at partial confidence the multiplier becomes
#   one minus that confidence, which is not zero, and the tool runs."
# handbook/01-fixed-procedure.md:90  "A confidence of exactly 0.0 is read as
#   never set and returned as 1.0 [...] a field the fingerprinter is barely
#   sure of scores lower than the same field with no confidence recorded."
# ---------------------------------------------------------------------------

_CONFIDENCE_SWEEP = (0.05, 0.2, 0.5, 0.8, 1.0)


@pytest.mark.parametrize("database", SQL_FAMILY + ["mongodb", None])
@pytest.mark.parametrize("waf", [True, False])
@chapter_claim(
    'handbook/01-fixed-procedure.md',
    'Sweep any profile across the confidence range and the membership of the ranked list never changes.',
)
def test_confidence_never_changes_which_tools_are_ranked(database, waf):
    recommender = ToolRecommender()
    memberships = set()
    for confidence in _CONFIDENCE_SWEEP:
        profile = TargetProfile(
            backend_language="php", backend_confidence=confidence,
            likely_database=database, database_confidence=confidence,
            framework="laravel", framework_confidence=confidence,
            waf_detected=waf, waf_vendor="cloudflare" if waf else None,
            waf_confidence=confidence,
            error_verbosity="high", api_types=["rest"],
            content_types_accepted=["json", "form"],
        )
        memberships.add(frozenset(n for n, _s, _r in recommender.recommend(profile)))
    assert len(memberships) == 1, (
        "chapter 01 claims membership never moves with confidence; it moved "
        f"across {_CONFIDENCE_SWEEP}"
    )


@chapter_claim(
    'handbook/01-fixed-procedure.md',
    'the SQL injection tool drops out of the medium tier and into the low one as the fingerprinter gets more sure of itself',
)
def test_scores_do_move_with_confidence_but_not_in_one_direction():
    """The chapter declines to claim a direction. Show why that was right.

    Both profiles are given in full, because "a profile with a WAF" would
    describe several objects with different answers -- the mistake chapter 00
    made once already.
    """
    recommender = ToolRecommender({"test_sqli": RELEVANCE["test_sqli"]})

    def sqli_score(profile):
        return recommender.recommend(profile)[0][1]

    # Tracked conditions here are all boosts (mysql, php), so the score rises.
    rising = [
        sqli_score(TargetProfile(
            backend_language="php", backend_confidence=c,
            likely_database="mysql", database_confidence=c,
            waf_detected=False, waf_vendor=None, waf_confidence=c,
            error_verbosity="high", api_types=["rest"],
        ))
        for c in _CONFIDENCE_SWEEP
    ]
    assert rising == sorted(rising) and rising[0] < rising[-1]

    # Same tool, same sweep. Ruby and Oracle earn no tracked boost and the WAF
    # penalty is the only tracked condition left, so the score falls as
    # confidence rises, and crosses a tier boundary on the way down. A
    # directional claim would have been false on exactly this profile.
    falling_profiles = [
        TargetProfile(
            backend_language="ruby", backend_confidence=c,
            likely_database="oracle", database_confidence=c,
            waf_detected=True, waf_vendor="akamai", waf_confidence=c,
            error_verbosity="low", api_types=["rest"],
        )
        for c in _CONFIDENCE_SWEEP
    ]
    falling = [sqli_score(p) for p in falling_profiles]
    assert falling == sorted(falling, reverse=True) and falling[0] > falling[-1]
    assert recommender.tier(falling[0]) == "MEDIUM"
    assert recommender.tier(falling[-1]) == "LOW", (
        "chapter 01 says this profile crosses out of the medium tier as "
        "confidence rises"
    )


@chapter_claim(
    'handbook/01-fixed-procedure.md',
    'Put one on a tracked field and at partial confidence the multiplier comes out at one minus that confidence, which is not zero, and the tool runs.',
)
def test_zero_penalty_on_a_tracked_field_does_not_zero_the_score():
    tracked = ToolRelevance(
        tool_name="probe", base_priority=8.0, impact_potential=5.0,
        cost_estimate=4.0, penalizes={"likely_database == 'mongodb'": 0.0},
    )
    assert "likely_database" in _CONFIDENCE_TRACKED
    recommender = ToolRecommender({"probe": tracked})
    ranked = recommender.recommend(
        TargetProfile(likely_database="mongodb", database_confidence=0.6)
    )
    assert [n for n, _s, _r in ranked] == ["probe"], (
        "chapter 01 claims the documented 0.0-means-skip contract fails on a "
        "confidence-tracked field; here it held, so the sentence is wrong"
    )


@chapter_claim(
    'handbook/01-fixed-procedure.md',
    'A confidence of exactly 0.0 is read as never set and returned as 1.0',
    'a field the fingerprinter is barely sure of scores lower than the same field with no confidence recorded at all',
)
def test_zero_confidence_is_read_as_full_confidence():
    recommender = ToolRecommender({"test_sqli": RELEVANCE["test_sqli"]})

    def score(confidence):
        profile = TargetProfile(
            backend_language="php", backend_confidence=confidence,
            likely_database="mysql", database_confidence=confidence,
            error_verbosity="high", api_types=["rest"],
        )
        return recommender.recommend(profile)[0][1]

    assert score(0.0) == score(1.0), (
        "chapter 01 says a confidence of exactly zero is returned as 1.0"
    )
    assert score(0.05) < score(0.0), (
        "chapter 01 calls this a discontinuity at the bottom of the scale: a "
        "barely-confident field must score below an unrecorded one"
    )


# ---------------------------------------------------------------------------
# Claim 7 -- fatigue.
#
# handbook/01-fixed-procedure.md:97  "At 0.8 and a floor of 0.3, the floor
#   binds from the sixth consecutive failure onward, and every failure after
#   that changes nothing."
# ---------------------------------------------------------------------------


@chapter_claim(
    'handbook/01-fixed-procedure.md',
    'At 0.8 and a floor of 0.3, the floor binds from the sixth consecutive failure onward, and every failure after that changes nothing.',
)
def test_fatigue_floor_binds_from_the_sixth_consecutive_failure():
    scheduler = SmartScheduler()
    base = [("test_sqli", 20.0, "reason")]
    scores = []
    for _ in range(9):
        scheduler.record("test_sqli", ExecutionResult.FAIL, "php:mysql:nowaf:none:rest:laravel")
        scores.append(scheduler.adjust(base)[0][1])

    assert scores[4] > scores[5], "the floor should not have bound yet at five failures"
    assert scores[5] == scores[6] == scores[7] == scores[8], (
        "chapter 01 says every failure after the sixth changes nothing"
    )
    assert SmartScheduler.FATIGUE_DECAY ** 5 > SmartScheduler.FATIGUE_FLOOR
    assert SmartScheduler.FATIGUE_DECAY ** 6 < SmartScheduler.FATIGUE_FLOOR


# ---------------------------------------------------------------------------
# Claim 8 -- profile-hash similarity.
#
# handbook/01-fixed-procedure.md:102  "Two profiles that agree on neither
#   backend nor database cannot reach the cutoff no matter what else they
#   share, even with the partial credit that unknown components earn."
# handbook/01-fixed-procedure.md:104  "that pair clears the cutoff by exactly
#   the weight of the framework component and nothing more. Change laravel to
#   symfony at the same time and it drops under."
# ---------------------------------------------------------------------------

_FUZZY_CUTOFF = 0.6  # the literal in _contextual_rate_for_hash


@chapter_claim(
    'handbook/01-fixed-procedure.md',
    'Two profiles that agree on neither backend nor database cannot reach the cutoff no matter what else they share, even with the partial credit that unknown components earn.',
)
def test_disagreeing_on_backend_and_database_never_reaches_the_cutoff():
    backends = ["php", "node", "python", "unknown"]
    databases = ["mysql", "mongodb", "postgresql", "unknown"]
    rest = [["waf", "nowaf"], ["cloudflare", "akamai", "none"],
            ["rest", "graphql"], ["laravel", "express", "unknown"]]
    tails = list(itertools.product(*rest))
    worst = 0.0
    for a_back, a_db, b_back, b_db in itertools.product(backends, databases, backends, databases):
        if a_back == b_back or a_db == b_db:
            continue  # agrees on one of the two; not the case being claimed
        for tail in tails:
            a = ":".join((a_back, a_db) + tail)
            b = ":".join((b_back, b_db) + tail)  # maximal agreement elsewhere
            worst = max(worst, TargetProfile.hash_similarity(a, b))
    assert worst < _FUZZY_CUTOFF, (
        f"chapter 01's invariant is false: a pair reached {worst}"
    )


@chapter_claim(
    'handbook/01-fixed-procedure.md',
    'That pair scores 0.65 against a cutoff of 0.6, so it clears by 0.05, which is half the framework component\'s weight of 0.10 and not the whole of it.',
)
def test_the_postgres_carryover_clears_the_cutoff_by_half_the_framework_weight():
    stored = "php:mysql:waf:cloudflare:rest:laravel"
    same_framework = "php:postgresql:waf:cloudflare:rest:laravel"
    other_framework = "php:postgresql:waf:cloudflare:rest:symfony"

    clears = TargetProfile.hash_similarity(stored, same_framework)
    drops = TargetProfile.hash_similarity(stored, other_framework)
    framework_weight = 0.10  # the literal in hash_similarity's weights list

    assert clears >= _FUZZY_CUTOFF
    assert drops < _FUZZY_CUTOFF
    assert clears - drops == pytest.approx(framework_weight)
    assert clears == pytest.approx(0.65)
    assert drops == pytest.approx(0.55)
    assert clears - _FUZZY_CUTOFF == pytest.approx(0.05)
    assert clears - _FUZZY_CUTOFF == pytest.approx(framework_weight / 2), (
        "chapter 01 says this pair clears the cutoff by half the framework "
        "component's weight, not by the whole of it -- the first draft said "
        "'exactly the weight', which this same assertion already disproved "
        "while the failure message repeated the error. If the margin moves, "
        "the chapter sentence has to move with it"
    )


# ---------------------------------------------------------------------------
# Claim 9 -- the correlation edge points backwards.
#
# handbook/01-fixed-procedure.md:114  "the edge that increments runs from the
#   second tool to the first. correlation_boost() then looks up
#   recently-successful-to-candidate, which means the boost is offered to
#   whichever tool succeeded first."
# ---------------------------------------------------------------------------


PROFILE_HASH = "php:mysql:nowaf:none:rest:laravel"
URLS = [f"http://target.invalid/{i}" for i in range(4)]


def _run_order(events):
    scheduler = SmartScheduler()
    for tool, url in events:
        scheduler.record(tool, ExecutionResult.SUCCESS, PROFILE_HASH,
                         found=1, target=url)
    return scheduler


@chapter_claim(
    'handbook/01-fixed-procedure.md',
    'the only edge available to carry that co-occurrence is the one pointing from the second tool back to the first',
    'so the boost goes to whichever tool got there first',
)
def test_correlation_edge_runs_from_the_second_tool_to_the_first():
    scheduler = _run_order([("A", u) for u in URLS] + [("B", u) for u in URLS])
    assert scheduler._correlations["B→A"]["cooccurrence"] == len(URLS)
    assert scheduler._correlations.get("A→B", {"cooccurrence": 0})["cooccurrence"] == 0
    # A succeeded first, so A is the one that gets the boost.
    assert scheduler.correlation_boost("A", ["B"])[0] > 1.0
    assert scheduler.correlation_boost("B", ["A"])[0] == 1.0


@chapter_claim(
    'handbook/01-fixed-procedure.md',
    'Interleave them in a stable per-URL order and you get the same lopsided result, and since ranking is deterministic and the top-ranked tool tends to go first, a stable order is the case to expect.',
)
def test_a_stable_per_url_order_is_just_as_lopsided():
    scheduler = _run_order([(t, u) for u in URLS for t in ("A", "B")])
    assert scheduler._correlations["A→B"]["cooccurrence"] == 0
    assert scheduler.correlation_boost("B", ["A"])[0] == 1.0


@chapter_claim(
    'handbook/01-fixed-procedure.md',
    'Alternate which tool goes first and both edges fill in evenly and the mechanism works as advertised.',
)
def test_alternating_which_tool_goes_first_fills_both_edges():
    events = [
        (t, u)
        for i, u in enumerate(URLS)
        for t in (("A", "B") if i % 2 == 0 else ("B", "A"))
    ]
    scheduler = _run_order(events)
    assert scheduler.correlation_boost("A", ["B"])[0] > 1.0
    assert scheduler.correlation_boost("B", ["A"])[0] > 1.0, (
        "chapter 01 says the mechanism works as advertised under an "
        "alternating order; if this fails the defect is worse than described"
    )


# ---------------------------------------------------------------------------
# Claim 9b -- WHY the edge points backwards.
#
# The observable defect above was already pinned. Its published cause was
# not, and was wrong: the first draft blamed the order of two statements in
# record(). A reader who acted on that diagnosis would have swapped the lines
# and fixed nothing. In a chapter about verification a wrong root cause is
# worse than none, so the real mechanism gets its own test and the wrong one
# gets falsified rather than quietly dropped.
# ---------------------------------------------------------------------------


class _SwappedRecordScheduler(SmartScheduler):
    """SmartScheduler with the two statements the wrong diagnosis blamed
    swapped: the current tool's target joins its own success set BEFORE the
    correlation update rather than after."""

    def record(self, tool, result, profile_hash, found=0, target=""):
        stats = self._tool_stats[tool]
        stats.total_executions += 1
        success = result == ExecutionResult.SUCCESS
        if success:
            stats.successes += 1
            stats.consecutive_failures = 0
            stats.total_findings += found
        ctx = self._contextual[tool][profile_hash]
        ctx.total += 1
        if success:
            ctx.successes += 1
            ctx.findings += found
        self._tools_tried.add(tool)
        if success:
            self._tool_success_count[tool] += 1
            if tool not in self._recently_successful:
                self._recently_successful.append(tool)
        if success and target:
            self._successful_targets[tool].add(target)   # <-- moved earlier
            self._update_correlations(tool, target)


def _counters(scheduler):
    return {k: dict(v) for k, v in scheduler._correlations.items()}


@chapter_claim(
    'handbook/01-fixed-procedure.md',
    'Every key it can write carries the tool that just succeeded on the left, and it iterates only over _successful_targets, which holds tools that have already succeeded at least once.',
    'So the first success of a run creates no edge at all, there being nothing to iterate over; and when a second tool lands on a URL the first one already hit, the only edge available to carry that co-occurrence is the one pointing from the second tool back to the first.',
)
def test_the_edge_direction_comes_from_who_succeeded_first_not_statement_order():
    # 1. Nothing to iterate over on the first success, so no edge exists.
    scheduler = SmartScheduler()
    scheduler.record("A", ExecutionResult.SUCCESS, PROFILE_HASH, found=1, target=URLS[0])
    assert _counters(scheduler) == {}, (
        "chapter 01 says the first success of a run creates no edge at all"
    )

    # 2. The second tool on the same URL can only record second-to-first.
    scheduler.record("B", ExecutionResult.SUCCESS, PROFILE_HASH, found=1, target=URLS[0])
    assert _counters(scheduler) == {"B→A": {"cooccurrence": 1, "tool1_successes": 1}}

    # 3. Every key ever written carries the just-succeeded tool on the left,
    #    so no forward edge can be created at the moment it would be true.
    sweep = SmartScheduler()
    seen_left = set()
    for tool, url in [("A", URLS[0]), ("B", URLS[0]), ("C", URLS[0]),
                      ("A", URLS[1]), ("B", URLS[1])]:
        before = set(sweep._correlations)
        sweep.record(tool, ExecutionResult.SUCCESS, PROFILE_HASH, found=1, target=url)
        for key in set(sweep._correlations) - before:
            seen_left.add(key.split("→")[0])
            assert key.split("→")[0] == tool, (
                f"{key!r} was created while {tool} succeeded, so the left-hand "
                "side is not always the tool that just succeeded"
            )
    assert seen_left == {"B", "C", "A"}, "the sweep did not exercise all three"

    # 4. The falsification: swapping the two statements the wrong diagnosis
    #    blamed changes nothing, because _update_correlations skips the
    #    current tool's own entry and never reads its set.
    events = [("A", u) for u in URLS] + [("B", u) for u in URLS]

    def run(cls):
        s = cls()
        for tool, url in events:
            s.record(tool, ExecutionResult.SUCCESS, PROFILE_HASH, found=1, target=url)
        return _counters(s), s.correlation_boost("A", ["B"]), s.correlation_boost("B", ["A"])

    assert run(SmartScheduler) == run(_SwappedRecordScheduler), (
        "the statement order DOES matter after all, which would make the "
        "diagnosis chapter 01 now publishes wrong in the other direction"
    )


# ---------------------------------------------------------------------------
# Claim 9c -- the adjustment explains itself in the reason string.
#
# The chapter quotes a reason verbatim. A quoted output is exactly the kind of
# sentence that rots without anyone noticing, so it is reproduced here from
# the same inputs rather than trusted.
# ---------------------------------------------------------------------------


@chapter_claim(
    'handbook/01-fixed-procedure.md',
    'Every multiplier it applies is appended to that tool\'s reason as it goes, so an adjusted list comes back reading fatigue×0.80; sr_exact×1.15; productive×1.15, and the question of why a given tool ranked where it did is answered by reading a line instead of reconstructing a decision.',
)
def test_adjust_appends_every_multiplier_it_applied_to_the_reason():
    profile_hash = "php:mysql:waf:cloudflare:rest:laravel"
    scheduler = SmartScheduler()
    for i in range(3):
        scheduler.record("test_sqli", ExecutionResult.SUCCESS, profile_hash,
                         found=1, target=f"http://target.invalid/{i}")
    scheduler.record("test_sqli", ExecutionResult.FAIL, profile_hash)
    scheduler.set_profile(profile_hash)

    reason = scheduler.adjust([("test_sqli", 20.0, "HIGH PRIORITY")])[0][2]
    assert reason == "HIGH PRIORITY [fatigue×0.80; sr_exact×1.15; productive×1.15]", (
        "chapter 01 quotes this reason string verbatim; adjust() now returns "
        f"{reason!r}"
    )


# ---------------------------------------------------------------------------
# Claim 10 -- the persistence round-trip loses "already tried".
#
# handbook/01-fixed-procedure.md:118  "Inside a live session those two facts
#   cannot disagree [...] Round-trip the identical state through the
#   persistence schema and it is both: the restored scheduler applies the
#   fatigue penalty and the first-time coverage bonus to the same tool in the
#   same call, and ranks it above where the live scheduler had it."
# ---------------------------------------------------------------------------


@chapter_claim(
    'handbook/01-fixed-procedure.md',
    'Round-trip the identical state through the persistence schema and it is both: the restored scheduler applies the fatigue penalty and the first-time coverage bonus to the same tool in the same call, and ranks it above where the live scheduler had it.',
)
def test_reload_grants_fatigue_and_the_new_tool_bonus_at_once():
    base = [("test_sqli", 20.0, "reason")]
    live = SmartScheduler()
    live.record("test_sqli", ExecutionResult.FAIL, "php:mysql:nowaf:none:rest:laravel")

    live_score, live_summary = live.adjust(base)[0][1], live.adjust(base)[0][2]
    assert "fatigue" in live_summary and "new_tool" not in live_summary, (
        "in a live session recording the failure is also what marks the tool "
        "tried, so the two must be mutually exclusive"
    )

    restored = SmartScheduler.from_dict(live.to_dict())
    restored_score, restored_summary = restored.adjust(base)[0][1], restored.adjust(base)[0][2]
    assert "fatigue" in restored_summary and "new_tool" in restored_summary, (
        "chapter 01 claims the round-trip grants both; it did not"
    )
    assert restored_score > live_score

    assert "tools_tried" not in live.to_dict(), (
        "the persistence schema now carries the tried set, which would fix "
        "the defect and make chapter 01's paragraph stale"
    )


# ===========================================================================
# Chapter 02 -- the narrow waist.
#
# Only one of chapter 02's three mechanisms has code in this repository. The
# unified write path and the grounding critic ship in a later release and the
# chapter says so on the page; the validator is here, so every claim the
# chapter makes about it gets an assertion.
#
# Note what these do NOT cover: nothing below says anything about the write
# path, the store's finding method, the severity governor, or the grounding
# gate. Those sentences in chapter 02 are prose about a system, not claims
# about core/, and pretending otherwise with a test that asserts something
# adjacent would be worse than leaving the gap visible.
# ===========================================================================

import json
import math

from core.llm_control import ToolCall, ToolCallValidator, ValidationError

# The schema chapter 02's worked examples are written against.
FETCH_SCHEMA = {
    "fetch_url": {
        "properties": {
            "url": {"type": "string"},
            "timeout": {"type": "integer", "default": 10},
            "follow_redirects": {"type": "boolean"},
        },
        "required": ["url"],
    },
}


def _call(**arguments):
    return json.dumps({"name": "fetch_url", "arguments": arguments})


class _CountingLLM:
    """Stand-in for the injected provider that records how often it was asked."""

    def __init__(self, replies=()):
        self.prompts = []
        self._replies = list(replies)

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if self._replies:
            return self._replies.pop(0)
        return '{"name": "fetch_url", "arguments": {}}'  # still invalid


@chapter_claim(
    'handbook/02-narrow-waist.md',
    'Hand it a call with a stowaway and the stowaway is gone.',
)
def test_unknown_argument_keys_never_reach_the_executor():
    tc = ToolCallValidator(FETCH_SCHEMA).validate(
        _call(url="https://h/", payload="'; DROP TABLE--", timeout=5)
    )
    assert tc == ToolCall(name="fetch_url", arguments={"url": "https://h/", "timeout": 5})
    assert "payload" not in tc.arguments


@chapter_claim(
    'handbook/02-narrow-waist.md',
    'Dictionary membership has no opinion about how plausible `test_auth_bypass` sounds next to `test_auth`.',
)
def test_a_plausible_invented_tool_name_is_rejected_by_membership_alone():
    validator = ToolCallValidator({"test_auth": {"properties": {}, "required": []}})
    validator.validate('{"name": "test_auth", "arguments": {}}')  # the real one passes
    with pytest.raises(ValidationError) as exc:
        validator.validate('{"name": "test_auth_bypass", "arguments": {}}')
    assert "[stage:tool_registry]" in str(exc.value)
    assert "test_auth_bypass" in str(exc.value)


@chapter_claim(
    'handbook/02-narrow-waist.md',
    "`[[code:llm_control.py:_validate_type]]` turns a quoted integer into an integer, a bare number in a string field into a string, and the strings `true` and `false` into booleans. It refuses to treat a boolean as either an integer or a string, which is the one coercion that would be silently destructive.",
)
def test_the_type_check_bends_the_sloppy_cases_and_refuses_booleans():
    v = ToolCallValidator(FETCH_SCHEMA)

    assert v.validate(_call(url="https://h/", timeout="30")).arguments["timeout"] == 30
    assert v.validate(_call(url=8080)).arguments["url"] == "8080"
    for text, expected in (("true", True), ("TRUE", True), ("false", False)):
        got = v.validate(_call(url="https://h/", follow_redirects=text))
        assert got.arguments["follow_redirects"] is expected

    for bad, field in ((_call(url=True), "url"), (_call(url="https://h/", timeout=True), "timeout")):
        with pytest.raises(ValidationError) as exc:
            v.validate(bad)
        assert field in str(exc.value)


# ---------------------------------------------------------------------------
# Chapter 02's causal claim, and its falsification.
#
# The chapter blames a specific mechanism -- the unknown-key branch being a
# `continue` rather than a failure -- for the silence. Chapter 01 published a
# cause that a two-line swap disproved, so a "because" now costs a test that
# breaks the accused mechanism and confirms the behaviour actually changes.
# ---------------------------------------------------------------------------


class _StrictArgsValidator(ToolCallValidator):
    """The validator with the accused branch flipped: an unrecognised key is
    an error instead of something silently skipped. Everything else is the
    inherited implementation."""

    def _validate_args(self, args, schema):
        props = schema.get("properties", {}) if isinstance(schema, dict) else {}
        if isinstance(args, dict):
            for key in args:
                if key not in props:
                    return False, {}, f"unknown argument '{key}'"
        return super()._validate_args(args, schema)


@chapter_claim(
    'handbook/02-narrow-waist.md',
    "The model asked for a longer timeout. It got the default. It was not told, the executor cannot tell, and the repair loop never runs because from the validator's point of view nothing failed.",
    'That one is caused by the drop being a `continue` rather than an error, and I checked rather than assumed: subclass the validator so an unknown key returns a failure instead of skipping, feed it the same call, and the repair loop fires and re-prompts.',
)
def test_a_misspelled_optional_key_is_swapped_for_the_default_in_silence():
    typo = _call(url="https://h/", timeoutt=30)

    llm = _CountingLLM()
    tc = ToolCallValidator(FETCH_SCHEMA).repair_loop(typo, ask_llm=llm, max_retries=3)
    assert tc.arguments == {"url": "https://h/", "timeout": 10}, (
        "the value the model asked for should be gone, replaced by the default"
    )
    assert llm.prompts == [], "nothing failed, so nothing was re-prompted"

    # Falsification: break the mechanism the chapter blames and the silence ends.
    strict_llm = _CountingLLM()
    with pytest.raises(ValidationError):
        _StrictArgsValidator(FETCH_SCHEMA).repair_loop(
            typo, ask_llm=strict_llm, max_retries=3
        )
    assert len(strict_llm.prompts) == 3, (
        "with the drop turned into a failure the repair loop must fire; if it "
        "does not, chapter 02 is blaming the wrong line"
    )
    assert "unknown argument 'timeoutt'" in strict_llm.prompts[0]


@chapter_claim(
    'handbook/02-narrow-waist.md',
    'A required parameter that also carries a default is not required.',
    'Defaults are applied before the missing-argument check runs, so the check never sees a gap.',
)
def test_a_default_satisfies_a_required_parameter():
    v = ToolCallValidator(
        {"scan": {"properties": {"depth": {"type": "integer", "default": 3}},
                  "required": ["depth"]}}
    )
    assert v.validate('{"name": "scan", "arguments": {}}').arguments == {"depth": 3}

    # Same schema without the default: now the requirement bites.
    bare = ToolCallValidator(
        {"scan": {"properties": {"depth": {"type": "integer"}}, "required": ["depth"]}}
    )
    with pytest.raises(ValidationError) as exc:
        bare.validate('{"name": "scan", "arguments": {}}')
    assert "missing required argument(s): depth" in str(exc.value)


@chapter_claim(
    'handbook/02-narrow-waist.md',
    'An unrecognised `type` keyword disables checking for that property.',
    'it means a schema with `"strng"` in it validates a nested object as a string and nobody hears about it',
)
def test_a_typo_in_a_type_keyword_turns_the_check_off():
    typo = ToolCallValidator({"t": {"properties": {"url": {"type": "strng"}}, "required": ["url"]}})
    nested = {"a": [1, 2]}
    assert typo.validate(json.dumps({"name": "t", "arguments": {"url": nested}})).arguments == {
        "url": nested
    }

    spelled = ToolCallValidator({"t": {"properties": {"url": {"type": "string"}}, "required": ["url"]}})
    with pytest.raises(ValidationError):
        spelled.validate(json.dumps({"name": "t", "arguments": {"url": nested}}))


@chapter_claim(
    'handbook/02-narrow-waist.md',
    "And the number branch accepts any string Python's `float()` accepts, which includes `nan` and `Infinity`.",
)
def test_the_number_branch_accepts_nan_and_infinity_as_strings():
    v = ToolCallValidator({"t": {"properties": {"rate": {"type": "number"}}, "required": []}})
    assert math.isnan(v.validate('{"name": "t", "arguments": {"rate": "nan"}}').arguments["rate"])
    assert math.isinf(v.validate('{"name": "t", "arguments": {"rate": "Infinity"}}').arguments["rate"])


@chapter_claim(
    'handbook/02-narrow-waist.md',
    'Read that as three re-prompts and four validation attempts, since the first attempt happens before any repair.',
    'Set it to zero and you get validation with no second chance and no model call.',
    'If the last attempt still fails, the final `[[code:llm_control.py:ValidationError]]` is raised rather than swallowed, which matters: a call that cannot be repaired is an error the orchestrator has to handle, not a silently dropped turn.',
)
def test_the_repair_budget_is_three_reprompts_and_four_validations():
    v = ToolCallValidator(FETCH_SCHEMA)

    llm = _CountingLLM()
    with pytest.raises(ValidationError):
        v.repair_loop("not json at all", ask_llm=llm, max_retries=3)
    assert len(llm.prompts) == 3

    zero = _CountingLLM()
    with pytest.raises(ValidationError) as exc:
        v.repair_loop("not json at all", ask_llm=zero, max_retries=0)
    assert zero.prompts == []
    assert "[stage:json_parse]" in str(exc.value)

    # The default is three, so calling without the argument spends three prompts.
    default_llm = _CountingLLM()
    with pytest.raises(ValidationError):
        v.repair_loop("not json at all", ask_llm=default_llm)
    assert len(default_llm.prompts) == 3


@chapter_claim(
    'handbook/02-narrow-waist.md',
    'The prompt carries the original response verbatim, the exact error with its stage tag, the list of known tools, and, when the error message named a tool the registry recognises, that tool\'s full schema.',
)
def test_the_repair_prompt_carries_the_error_the_tools_and_the_schema():
    v = ToolCallValidator(FETCH_SCHEMA)
    bad = '{"name": "fetch_url", "arguments": {}}'

    replies = ['{"name": "fetch_url", "arguments": {"url": "https://h/"}}']
    llm = _CountingLLM(replies)
    assert v.repair_loop(bad, ask_llm=llm, max_retries=3).arguments["url"] == "https://h/"

    prompt = llm.prompts[0]
    assert bad in prompt                       # original response, verbatim
    assert "[stage:type_match]" in prompt      # the error, with its stage tag
    assert "Known tools: ['fetch_url']" in prompt
    assert '"required": [\n    "url"\n  ]' in prompt  # the schema itself


# ---------------------------------------------------------------------------
# Chapter 03 -- the governance corpus.
#
# The governor, the rules file and the verifier are NOT in this repository's
# core/, so there is nothing here to import and nothing to assert against.
# What chapter 03 does put on the page is a set of published figures, and
# those ARE checkable: data/stats.json carries the pre/post band counts, the
# per-band deltas and the transition table, and the chapter makes arithmetic
# claims about how they fit together. A figure that no longer reconciles is
# either a re-measured corpus or a chapter sentence that has gone stale, and
# both need a human.
#
# Read the scope honestly. These tests pin the published NUMBERS and the
# relationships the chapter asserts between them. They cannot reach the
# mechanism: nothing here proves the governor is incapable of escalating,
# only that in the corpus it never did. That gap is stated in the chapter
# and is not papered over with an approximate test.
# ---------------------------------------------------------------------------

SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _stats():
    root = pathlib.Path(__file__).resolve().parents[1]
    return json.loads((root / "data" / "stats.json").read_text(encoding="utf-8"))


def _transitions():
    """(from, to, count) for every entry in the audited transition table."""
    table = _stats()["governance"]["summary"]["by_transition"]
    out = []
    for key, count in table.items():
        frm, _, to = key.partition("->")
        out.append((frm, to, count))
    assert out, "the transition table is empty; nothing below means anything"
    return out


@chapter_claim(
    'handbook/03-asymmetric-trust.md',
    'Every transition in it goes down.',
)
def test_every_audited_transition_lowers_severity():
    for frm, to, count in _transitions():
        assert frm in SEVERITY_RANK and to in SEVERITY_RANK, (frm, to)
        assert SEVERITY_RANK[to] < SEVERITY_RANK[frm], (frm, to, count)


@chapter_claim(
    'handbook/03-asymmetric-trust.md',
    'No transition in that table ends at informational.',
)
def test_no_audited_transition_ends_at_informational():
    assert [t for t in _transitions() if t[1] == "info"] == []


@chapter_claim(
    'handbook/03-asymmetric-trust.md',
    "The critical band's loss is the two rows that leave it; the high band's loss is what it shipped to medium less what it received from critical; and the movement out of the combined band is the two rows that land on medium, which is exactly the combined delta above.",
)
def test_the_band_deltas_reconcile_with_the_transition_table():
    gov = _stats()["governance"]
    tr = gov["summary"]["by_transition"]
    delta = gov["impact"]["delta"]

    crit_to_high = tr["critical->high"]
    crit_to_medium = tr["critical->medium"]
    high_to_medium = tr["high->medium"]

    assert delta["critical"] == -(crit_to_high + crit_to_medium)
    assert delta["high"] == crit_to_high - high_to_medium
    assert delta["critical_plus_high"] == -(crit_to_medium + high_to_medium)


@chapter_claim(
    'handbook/03-asymmetric-trust.md',
    'When the governance layer described in this chapter was finally run over the whole corpus, the critical-and-high band moved by [[stats:governance.impact.delta.critical_plus_high]]. From [[stats:governance.impact.pre_governance.critical_plus_high]] down to [[stats:governance.impact.post_governance.critical_plus_high]], split [[stats:governance.impact.delta.critical]] in the critical band and [[stats:governance.impact.delta.high]] in the high band.',
)
def test_the_published_deltas_are_post_minus_pre():
    impact = _stats()["governance"]["impact"]
    for band in ("critical", "high", "critical_plus_high"):
        assert impact["delta"][band] == (
            impact["post_governance"][band] - impact["pre_governance"][band]
        ), band
    # The combined band is the sum of its parts on both sides of the pass.
    for side in ("pre_governance", "post_governance"):
        assert impact[side]["critical_plus_high"] == (
            impact[side]["critical"] + impact[side]["high"]
        ), side
    # Every movement is downward, so the deltas can only be negative or zero.
    assert all(v <= 0 for v in impact["delta"].values())


@chapter_claim(
    'handbook/03-asymmetric-trust.md',
    'The audit of that pass split the changes into [[stats:governance.summary.expected]] it recognised as intended behaviour and [[stats:governance.summary.flagged]] it refused to bless, and the flagged ones went to a human.',
)
def test_the_audit_split_accounts_for_every_change():
    summary = _stats()["governance"]["summary"]
    assert summary["expected"] + summary["flagged"] == summary["total"]
    assert sum(summary["by_transition"].values()) == summary["total"]
    assert sum(summary["by_type"].values()) == summary["total"]


@chapter_claim(
    'handbook/03-asymmetric-trust.md',
    'Coverage is established by a different pair, [[stats:governance.summary.scans_governed]] scans governed of [[stats:governance.summary.scans_total]].',
)
def test_governance_covered_every_scan_in_the_corpus():
    stats = _stats()
    summary = stats["governance"]["summary"]
    assert summary["scans_governed"] == summary["scans_total"]
    # And that total is the corpus itself, not some subset of it.
    assert summary["scans_total"] == stats["corpus"]["scans"]["total"]
    # A record-writing count is not a coverage count: the pair the chapter
    # warns about must stay well below the scans it was governed across.
    written = stats["corpus"]["governance_record_written"]
    assert written["with_record"] + written["without_record"] == (
        stats["corpus"]["findings"]["stored"]
    )


@chapter_claim(
    'handbook/03-asymmetric-trust.md',
    'Those are the chains that became findings, and there are [[stats:corpus.chains.governed]] of them. The same corpus holds [[stats:corpus.chains.ungoverned]] chain objects that were written into the analysis store instead, never became findings, and were therefore never evaluated by anything. Out of [[stats:corpus.chains.total]] chains altogether, that is better than nine in ten which the governor never saw.',
)
def test_the_chain_populations_partition_the_total():
    chains = _stats()["corpus"]["chains"]
    # The two populations are exhaustive and disjoint: every chain is either
    # one the governor saw (a finding) or one it never saw (analysis store).
    assert chains["governed"] + chains["ungoverned"] == chains["total"]
    assert chains["ungoverned_share"] == pytest.approx(
        chains["ungoverned"] / chains["total"]
    )
    # The chapter's whole point: the ungoverned population is the large one.
    assert chains["ungoverned"] > chains["governed"]
    # "better than nine in ten" is a worded quantifier the number gate cannot
    # read, and it is the only form the share appears in now that the raw
    # num-ok: 16 counts the decimal places in corpus.chains.ungoverned_share as data/stats.json stores it, a property of the recorded value rather than a measurement of anything
    # 16-decimal value is no longer rendered into prose. Pin it.
    assert chains["ungoverned"] / chains["total"] > 0.9
    # And the governed count is the same population the audit table counts.
    assert chains["governed"] == (
        _stats()["governance"]["summary"]["by_type"]["attack_chain"]
    )


@chapter_claim(
    'handbook/03-asymmetric-trust.md',
    'Chain data of some kind turns up in [[stats:corpus.chains.scans_with_chain_objects]] of the [[stats:corpus.scans.total]] scans in the corpus, which is a little under half of them.',
)
def test_scans_with_chain_data_are_a_little_under_half_the_corpus():
    stats = _stats()
    with_chains = stats["corpus"]["chains"]["scans_with_chain_objects"]
    total = stats["corpus"]["scans"]["total"]
    # "a little under half" is a worded quantifier, which the number gate does
    # not read. Pin it: strictly below half, and not so far below that "a
    # little" stops being honest.
    assert 0.45 <= with_chains / total < 0.50


# ---------------------------------------------------------------------------
# Chapter 04 -- the scoping gap the benchmark surfaced.
#
# The scope guard, the bundle miner and the endpoint confirmer are NOT in this
# repository's core/, exactly as chapter 03's subject was not, so nothing here
# imports them and nothing here asserts how they behave. The chapter says so on
# the page. What it also does is quote the one benchmark run's per-finding
# counts and then say, in words, what fraction of them were third-party hosts.
# The counts are checkable; the fraction is only half checkable, and the tests
# below are deliberate about which is which.
#
# What these pin:
#   - the published run's counts reconcile (true positives plus false
#     positives equal the reported findings, and precision is that ratio), so
#     the sentence quoting them cannot go stale silently;
#   - the false-positive count is literally six, because the chapter goes on
#     to write "those six" in prose and a worded restatement of a cited number
#     is invisible to the number gate.
#
# What they cannot pin: that three of those six carried a third-party
# hostname. That breakdown lives in the run's own per-finding record, which is
# not published in data/stats.json -- only the aggregate is. The chapter says
# where the breakdown comes from rather than pretending the public block
# carries it, and no approximate test is written here to paper over the gap.
# ---------------------------------------------------------------------------


def _benchmark_run():
    """The single included benchmark run, with its per-run counts."""
    juice = _stats()["benchmark"]["juice_shop"]
    included = juice["included"]
    assert len(included) == juice["n"], (len(included), juice["n"])
    return included[0]


@chapter_claim(
    'handbook/04-scope-as-code.md',
    "In the selected public-target aggregate, [[stats:benchmark.juice_shop.n]] author-recorded run, [[stats:benchmark.juice_shop.included.0.false_positives]] of the run's [[stats:benchmark.juice_shop.included.0.findings_count]] findings were labelled false positives.",
)
def test_the_selected_runs_recorded_findings_are_its_labelled_hits_plus_misses():
    run = _benchmark_run()
    assert run["true_positives"] + run["false_positives"] == run["findings_count"]
    assert run["precision"] == pytest.approx(
        run["true_positives"] / run["findings_count"]
    )
    # The chapter reports the author's label, so the count has to be the
    # labelled-false-positive count and not the finding count beside it. This
    # arithmetic does not validate the missing ground truth or matcher.
    assert run["false_positives"] < run["findings_count"]


# The split the chapter reports inside that false-positive count, taken from the
# run's own per-finding record. data/stats.json publishes the aggregate only, so
# these three are pinned here as constants and NOT as a measurement this test can
# take: what the test can do is stop them drifting apart from each other or
# outgrowing the published total they are a subset of.
FP_ROWS_NAMING_A_THIRD_PARTY = 3
FP_ROWS_THAT_WERE_THIRD_PARTY_HOSTS = 2
FP_ROWS_THAT_WERE_AN_ORDINARY_PATH = 1


@chapter_claim(
    'handbook/04-scope-as-code.md',
    'Three of the six carry the name of a third-party service in the title, all three from the bundle miner, all three reported as missing-authentication leads.',
    'Two of those three are third-party hosts, both IP-geolocation providers, that the miner lifted out of the target\'s own JavaScript.',
)
def test_the_third_party_rows_are_a_strict_subset_of_the_published_false_positives():
    # "the six" is a worded restatement of a cited number, and the number gate
    # reads digits only: if the corpus is re-measured and this count moves,
    # nothing but this assertion fails the word on the page.
    run = _benchmark_run()
    assert run["false_positives"] == 6
    assert (
        FP_ROWS_THAT_WERE_THIRD_PARTY_HOSTS + FP_ROWS_THAT_WERE_AN_ORDINARY_PATH
        == FP_ROWS_NAMING_A_THIRD_PARTY
    )
    assert FP_ROWS_NAMING_A_THIRD_PARTY < run["false_positives"]


# ---------------------------------------------------------------------------
# Chapter 04 -- the causal account of which guard keeps a mined candidate on
# the target host.
#
# This chapter published a causal claim that was wrong: that the leading-slash
# strip was the only reason the benchmark's probes stayed on the target. Replay
# showed the rows carried an /api base, so the strip never came into it. That is
# the exact sentence class a citation gate cannot touch -- no number in it, no
# symbol in it -- and it shipped.
#
# The probe URL the endpoint confirmer builds is, verbatim, the expression
# reproduced in _probe_url below. The confirmer is NOT in this repository, and
# the chapter says so on the page, so read the scope of these tests honestly:
# they pin the join arithmetic the causal account rests on -- given a candidate
# of each shape, does the probe stay on the target host -- and they cannot prove
# the private confirmer uses that expression. That much is read from source and
# asserted in prose.
#
# What they do bind is the prose. Each @chapter_claim anchor carries the
# sentence verbatim, so flipping "lands on the target" to "leaves the target"
# fails the gate instead of passing it silently, which is what happened when a
# reviewer tried exactly that mutation against the unanchored version.
# ---------------------------------------------------------------------------

from urllib.parse import urljoin

TARGET_ROOT = "http://app.shop.example"


def _probe_url(candidate, strip=True):
    """Transcribe the endpoint confirmer's probe expression, urljoin(root + "/", path.lstrip("/")).

    The confirmer lives in the SPA miner, which this repository does not ship and
    may never, so nothing here proves the transcription matches it; unlike the
    consolidation signature and the gate check, there is no shipped function to
    import in its place.
    """
    return urljoin(TARGET_ROOT + "/", candidate.lstrip("/") if strip else candidate)


def _on_target(url):
    return url.startswith(TARGET_ROOT + "/")


@chapter_claim(
    'handbook/04-scope-as-code.md',
    'Replay the shape the rows actually carry, a protocol-relative host sitting under the `/api` base, and it lands on the target either way: `/api//geo.vendor.example/v1/city` resolves to the target with the strip and to the target without it, because the base in front means the string no longer opens with two slashes and the join has nothing to read as a network-path reference.',
)
def test_a_based_candidate_lands_on_the_target_with_or_without_the_strip():
    candidate = "/api//geo.vendor.example/v1/city"
    assert _on_target(_probe_url(candidate, strip=True))
    assert _on_target(_probe_url(candidate, strip=False))
    # And the base is why: it is the leading "/api" that stops the string
    # opening with two slashes, so removing it flips the unstripped case.
    assert not _on_target(_probe_url(candidate[len("/api"):], strip=False))


@chapter_claim(
    'handbook/04-scope-as-code.md',
    'When the run has observed a request whose path matches one the miner recovered, the resolved base comes out empty, the candidate stays `//geo.vendor.example/v1/city`, and with the strip removed the probe resolves to that host instead of the target.',
)
def test_a_bare_candidate_is_held_on_the_target_only_by_the_strip():
    candidate = "//geo.vendor.example/v1/city"
    assert _on_target(_probe_url(candidate, strip=True))
    off = _probe_url(candidate, strip=False)
    assert not _on_target(off)
    assert off == "http://geo.vendor.example/v1/city"


@chapter_claim(
    'handbook/04-scope-as-code.md',
    'Then the candidate is itself an absolute URL, stripping leading slashes does nothing to a string that opens with a scheme, and the join hands it back unchanged.',
    'The probe leaves the target host.',
)
def test_an_absolute_declared_base_leaves_the_target_host_either_way():
    candidate = "https://api.vendor.example/orders"
    for strip in (True, False):
        assert _probe_url(candidate, strip=strip) == candidate
        assert not _on_target(_probe_url(candidate, strip=strip))


@chapter_claim(
    'handbook/04-scope-as-code.md',
    'Which of the two shapes the miner picked it up in, the plain path or a protocol-relative form of the same name, the row cannot settle: the join collapses `/api//engine.io` and `/api/engine.io` onto the same URL.',
)
def test_the_stored_url_cannot_distinguish_the_two_harvest_shapes():
    assert _probe_url("/api//engine.io") == _probe_url("/api/engine.io")
    assert _on_target(_probe_url("/api//engine.io"))


# ---------------------------------------------------------------------------
# Chapter 05 -- honest reporting.
#
# Three of this chapter's subjects (the gate-check decision tree, the coverage
# matrix, the consolidation pass) are NOT in this repository's core/, and the
# chapter says so on the page. Nothing below imports them. Where a test needs
# their arithmetic it TRANSCRIBES the expression, exactly as chapter 04's tests
# transcribe the endpoint confirmer's probe join, and the comment above each one
# says what it can and cannot prove: it pins the arithmetic the chapter's prose
# rests on, and it cannot prove the private code still contains that expression.
# That much was read from source and is asserted in prose only.
#
# The rest are properties of published data (data/stats.json) or of the
# reference implementation that IS here (core/scheduler.py's ablation flag).
#
# The chapter's worded quantifiers get assertions here for the reason chapter
# 04 learned twice: the number gate reads digits, so "three times", "a fifth"
# and "three in ten" are invisible to it, and a re-measured corpus would leave
# them standing on the page saying something false.
# ---------------------------------------------------------------------------


def _juice():
    return _stats()["benchmark"]["juice_shop"]


@chapter_claim(
    'handbook/05-honest-reporting.md',
    'Three runs exist.',
    'Two were excluded, both published in full under benchmark.juice_shop.excluded in data/stats.json with their real metrics and their real reasons, and both scored zero.',
    'The published headline is therefore exactly three times the mean over every attempt that was made, which is arithmetic and not a coincidence: two of the three scored zero, so the multiple is just the count.',
)
def test_the_headline_is_one_of_three_attempts_and_triple_their_mean():
    juice = _juice()
    included, excluded = juice["included"], juice["excluded"]
    assert len(included) == 1 and len(excluded) == 2
    assert len(included) + len(excluded) == 3
    assert juice["n"] == len(included)
    # Both excluded runs scored zero on every published metric, so the
    # exclusion is what the headline rests on, not a rounding difference.
    for run in excluded:
        assert run["f1"] == 0.0 and run["precision"] == 0.0 and run["recall"] == 0.0
        assert run["true_positives"] == 0
    all_attempts = [r["f1"] for r in included] + [r["f1"] for r in excluded]
    mean_all = sum(all_attempts) / len(all_attempts)
    assert juice["f1"]["mean"] == pytest.approx(3 * mean_all)


@chapter_claim(
    'handbook/05-honest-reporting.md',
    '`n` is [[stats:benchmark.juice_shop.n]]. One run. The standard deviation published beside the mean is null, and it is null because a spread over one sample is not a thing that exists; the file says so in its own words under benchmark.juice_shop._unmeasured_reason.',
)
def test_one_run_publishes_no_spread():
    juice = _juice()
    assert juice["n"] == 1
    for metric in ("f1", "precision", "recall"):
        assert juice[metric]["stdev"] is None, metric
        assert len(juice[metric]["values"]) == 1, metric
    assert juice["_unmeasured_reason"]


@chapter_claim(
    'handbook/05-honest-reporting.md',
    'The system\'s author-recorded F1 on a public deliberately-vulnerable application is [[stats:benchmark.juice_shop.f1.mean]]. An OWASP ZAP passive-scan score in the same snapshot is [[stats:benchmark.zap_baseline.f1]]. The repository proves the aggregate arithmetic, not a controlled head-to-head: it does not publish the raw findings, ground-truth entries, matcher, target identifiers or run identifiers needed to establish that both rows were scored on identical inputs.',
    'The baseline row reports [[stats:benchmark.zap_baseline.findings_count]] findings and zero true positives against a ground_truth_count of [[stats:benchmark.zap_baseline.ground_truth_count]].',
)
def test_the_comparison_is_published_with_its_evidence_limit():
    juice, zap = _juice(), _stats()["benchmark"]["zap_baseline"]
    # Equal counts are arithmetic, not proof of object identity. The published
    # files contain no raw findings, ground-truth rows, matcher, target id or run
    # id, so the note must keep that evidence limit beside the number.
    note = zap["note"].lower()
    assert "author-recorded" in note
    assert "does not publish" in note
    for missing in ("raw findings", "ground-truth entries", "matcher",
                    "target identifiers", "run identifiers"):
        assert missing in note, missing
    assert "controlled head-to-head" in note
    assert zap["label"] == "ZAP"
    # The baseline's zero is a zero on the matching, not an empty report.
    assert zap["true_positives"] == 0
    assert zap["findings_count"] > 0
    assert zap["false_negatives"] == zap["ground_truth_count"]
    assert zap["f1"] == 0.0
    assert juice["f1"]["mean"] > zap["f1"]


@chapter_claim(
    'handbook/05-honest-reporting.md',
    'Precision was [[stats:benchmark.juice_shop.included.0.precision]] and recall [[stats:benchmark.juice_shop.included.0.recall]]. Half the reported findings were wrong, and three in ten of the known bugs were found: [[stats:benchmark.juice_shop.included.0.true_positives]] of [[stats:benchmark.juice_shop.included.0.ground_truth_count]].',
)
def test_half_wrong_and_three_in_ten_found():
    run = _juice()["included"][0]
    # "Half the reported findings were wrong": precision is the hit rate over
    # num-ok: the other half of the same count is the complement of the precision the assertion below pins, the same rhetorical use of the word the chapter annotates at its own line, not a second measurement
    # what was reported, and the misses are the other half of the same count.
    assert run["precision"] == pytest.approx(run["true_positives"] / run["findings_count"])
    assert run["precision"] == pytest.approx(0.5)
    assert run["false_positives"] == run["findings_count"] - run["true_positives"]
    # "three in ten of the known bugs": recall against the ground-truth size.
    assert run["recall"] == pytest.approx(run["true_positives"] / run["ground_truth_count"])
    assert run["recall"] == pytest.approx(0.3)
    p, r = run["precision"], run["recall"]
    assert run["f1"] == pytest.approx(2 * p * r / (p + r))


@chapter_claim(
    'handbook/05-honest-reporting.md',
    'Of [[stats:corpus.scans.total]] scans between [[stats:corpus.window.first_scan]] and [[stats:corpus.window.last_scan]], none is sitting in a non-terminal state: the statuses are complete, a second spelling of complete that two writers produced, failed, and killed. The split between the two spellings is [[stats:corpus.scans.by_status.complete]] rows against [[stats:corpus.scans.by_status.completed]], and corpus.scans.note in data/stats.json records both verbatim rather than merging them away. The failed and killed rows together are about a fifth of the corpus, [[stats:corpus.scans.by_status.failed]] and [[stats:corpus.scans.by_status.killed]], and every one of them is a scan that reached a terminal state saying so.',
)
def test_every_scan_in_the_corpus_reached_a_terminal_state():
    scans = _stats()["corpus"]["scans"]
    by_status = scans["by_status"]
    # The four terminal spellings are the whole distribution: a scan left
    # running would show up here as a fifth key, and the chapter's claim that
    # none is sitting in a non-terminal state would be false.
    assert set(by_status) == {"complete", "completed", "failed", "killed"}
    assert sum(by_status.values()) == scans["total"]
    # "about a fifth" is a worded quantifier the number gate cannot read.
    unfinished = by_status["failed"] + by_status["killed"]
    assert 0.19 <= unfinished / scans["total"] <= 0.21


# The previous published snapshot of data/stats.json, read out of this
# repository's own git history (the Phase 0 import commit) and pinned here as
# constants: the file holds one snapshot at a time, so the earlier figures
# cannot be re-read from it. These are NOT a measurement this test takes. What
# it can do is fail the moment the current snapshot moves, which is the whole
# point of the drift section: a re-measure invalidates the prose about it.
PRIOR_SNAPSHOT_RATIO = 1.2874493927125505
PRIOR_SNAPSHOT_SCANS_MEASURED = 18
PRIOR_SNAPSHOT_SCANS_TOTAL = 205
PRIOR_SNAPSHOT_FINDINGS_STORED = 2975
PRIOR_SNAPSHOT_TOOL_EXECUTIONS = 7253


@chapter_claim(
    'handbook/05-honest-reporting.md',
    'Between the two measurement passes recorded in this repository\'s history the corpus gained one scan, thirteen findings and six tool executions, the measured subset went from eighteen scans to [[stats:llm_ratio.coverage.scans_measured]], and [[stats:llm_ratio.llm_turns_per_tool_execution]] came out 18 per cent higher on the second pass.',
)
def test_the_published_ratio_moved_eighteen_per_cent_between_snapshots():
    stats = _stats()
    corpus, ratio_block = stats["corpus"], stats["llm_ratio"]
    assert corpus["scans"]["total"] - PRIOR_SNAPSHOT_SCANS_TOTAL == 1
    assert corpus["findings"]["stored"] - PRIOR_SNAPSHOT_FINDINGS_STORED == 13
    assert corpus["tool_executions"] - PRIOR_SNAPSHOT_TOOL_EXECUTIONS == 6
    assert PRIOR_SNAPSHOT_SCANS_MEASURED == 18
    assert ratio_block["coverage"]["scans_measured"] == 20
    now = ratio_block["llm_turns_per_tool_execution"]
    rise = (now - PRIOR_SNAPSHOT_RATIO) / PRIOR_SNAPSHOT_RATIO * 100
    assert round(rise) == 18


# The drift claim itself -- "re-run it today and the transcript count differs" --
# is NOT pinnable from this repository. It is a statement about a directory on the
# author's machine that no public artifact records, and the honest move is to say
# so here rather than assert a neighbouring property and let the anchor imply
# coverage it does not have. An earlier version of this test anchored the drift
# sentence and then asserted subset-ness, which is a different claim. What follows
# is anchored to the sentence it does pin.
@chapter_claim(
    'handbook/05-honest-reporting.md',
    'The published pair says plainly how little of the corpus this is: [[stats:llm_ratio.coverage.scans_measured]] scans measured of [[stats:llm_ratio.coverage.scans_total]], split between the two transcript sources and extrapolated to nothing.',
)
def test_the_published_coverage_is_a_measured_subset_of_the_corpus():
    """The note is read as a whole clause, because a hedge fits inside it.

    "extrapolated to nothing" rests on what the published note says, and
    ``"NOT extrapolated" in note`` cannot tell the claim from its opposite: a
    word between the negation and its object -- "NOT extrapolated NAIVELY to the
    full corpus" -- leaves the containment test true while the note now admits
    the extrapolation it denied. The whole clause is read instead, so any
    insertion inside it fails. An insertion AFTER the clause is caught by
    nothing here: a note retracting itself one clause later -- "... to the full
    corpus, except that it is extrapolated to the full corpus" -- was run and
    passed. The totals assertion below pins the underlying fact, that the
    published totals are the measured subset's rather than the corpus's, by
    comparing two numbers; no wording can move it.
    """
    stats = _stats()
    cov = stats["llm_ratio"]["coverage"]
    # "how little of the corpus this is": a strict subset, and the total is the
    # corpus itself rather than some other population.
    assert cov["scans_measured"] < cov["scans_total"]
    assert cov["scans_total"] == stats["corpus"]["scans"]["total"]
    # "split between the two transcript sources": exhaustively, with both
    # contributing, so the word split is true in both directions.
    assert cov["scans_measured"] == (
        cov["scans_from_stream_feed"] + cov["scans_from_cc_transcript"]
    )
    assert cov["scans_from_stream_feed"] > 0 and cov["scans_from_cc_transcript"] > 0
    # "extrapolated to nothing": the published note says exactly that, and the
    # ratio's totals are the measured subset's, not the corpus's.
    assert "is NOT extrapolated to the full corpus" in cov["note"], cov["note"]
    assert stats["llm_ratio"]["totals"]["tool_executions"] < (
        stats["corpus"]["tool_executions"]
    )


# Anchored to CHAPTER 01, not 05, and kept here beside the test above because
# both read the same two coverage keys: an edit to either belongs in front of
# both claims at once. Chapter 01 uses the same split for a different purpose --
# not "how little of the corpus" but WHICH orchestration path the measured part
# of it came from, which is the pairing that makes the turn-ratio section and
# num-ok: different halves of the system is a figure of speech for the two orchestration paths, a count of nothing
# its own rebuttal describe different halves of the system.
#
# What this CAN pin: that the two named sources exhaust the measured set, which
# is what "every scan the ratio could be measured over" rests on -- if a third
# source appeared, or if the two stopped summing, the word "every" would be
# doing unearned work.
#
# What it CANNOT pin, stated rather than approximated: WHICH orchestration path
# each source belongs to. That is a property of the private measurement script
# and of what writes each transcript, and no key in data/stats.json records it.
# An earlier version of this chapter asserted the two sources were opposite
# paths, which was false in both halves, and no assertion here could have
# caught it. Naming the gap is worth more than a neighbouring assertion that
# implies coverage it does not have.
@chapter_claim(
    'handbook/01-fixed-procedure.md',
    "Every scan the ratio could be measured over is on the path where the ranking is not called.",
    "Its two transcript sources exhaust the measured set, [[stats:llm_ratio.coverage.scans_from_cc_transcript]] read out of coding-agent sessions and [[stats:llm_ratio.coverage.scans_from_stream_feed]] out of the unattended runner's own feed, and that runner drives the same skill headless, so both sources are the same orchestrator.",
)
def test_the_two_transcript_sources_exhaust_the_measured_subset():
    cov = _stats()["llm_ratio"]["coverage"]
    cc, feed = cov["scans_from_cc_transcript"], cov["scans_from_stream_feed"]
    assert cc + feed == cov["scans_measured"]
    assert cc > 0 and feed > 0, "both sources have to contribute for 'two' to be true"
    # No third source hides in the coverage block: any other scans_from_* key
    # would break the sum above, and this pins that the two named are the two.
    assert sorted(k for k in cov if k.startswith("scans_from_")) == [
        "scans_from_cc_transcript",
        "scans_from_stream_feed",
    ]


# The two coverage percentages, transcribed from the store methods the chapter
# describes. The store is not in this repository, so these pin the arithmetic the
# prose rests on and cannot prove the private methods still compute it this way.
#
# _matrix_pct takes the discovered-URL universe as a SECOND argument and ignores
# it, because that is exactly the claim under test: the matrix denominator is
# len(urls) * len(tools) over the URLs and tools appearing in the EXECUTION rows,
# and no set of discovered-but-untouched URLs can move it. An earlier version of
# this test wrote `_matrix_pct(ran) == _matrix_pct(ran + [])`, which compares the
# function against itself on an identical argument and cannot fail for any
# implementation -- a vacuous assertion under a true claim, which is worse than no
# assertion because it reads as covered. _baseline_pct is the contrast the chapter
# draws: the same executions counted against a denominator fixed before testing,
# which does see the untouched URLs.
def _matrix_pct(rows, discovered=()):
    """Transcribe the coverage-matrix percentage a store computes in get_coverage.

    The store that computes it is not in this repository -- only the get_coverage
    signature ships, as a stub on the FindingStore protocol in core/store_protocol.py
    -- so nothing here proves the transcription matches the withheld implementation;
    the check closes when a real store ships and this helper can import it in place
    of the transcription. `discovered` is accepted and ignored on purpose: it is the
    untouched-URL set, and the property under test is that the matrix denominator
    never sees it.
    """
    del discovered  # deliberately unused: that is the property under test
    matrix, urls, tools = {}, set(), set()
    for url, tool in rows:
        urls.add(url)
        tools.add(tool)
        matrix.setdefault(url, {})[tool] = True
    total = len(urls) * len(tools)
    tested = sum(len(t) for t in matrix.values())
    return round((tested / total * 100.0) if total else 0.0, 1)


def _baseline_pct(tested, baseline):
    """Baseline URLs with at least one successful execution, over the baseline."""
    if not baseline:
        return 0.0
    return round(len(set(tested) & set(baseline)) / len(set(baseline)) * 100.0, 1)


@chapter_claim(
    'handbook/05-honest-reporting.md',
    'Both sets come out of the executions. A URL nothing ever ran against contributes no row, so it is absent from the denominator; a tool nobody ran is absent as well.',
    'Half is exactly what that expression returns for two URLs and two tools with one tool run against each.',
)
def test_untested_urls_never_enter_the_coverage_denominator():
    ran = [("/a", "t1"), ("/b", "t2")]
    assert _matrix_pct(ran) == 50.0
    # The chapter's own code block: 198 discovered endpoints nothing ran
    # against, and the percentage does not move.
    untouched = [f"/x{i}" for i in range(198)]
    assert _matrix_pct(ran, discovered=untouched) == 50.0
    # Discriminating rather than vacuous: a real execution row DOES move it.
    # (Not any row: adding /a with a THIRD tool happens to land on 50.0 again,
    # 3 filled of 2 urls x 3 tools, which is its own small lesson about what
    # this percentage is measuring. Filling a cell in the existing grid moves
    # it, and that is the comparison the assertion above needs to be worth
    # anything.)
    assert _matrix_pct(ran + [("/a", "t2")]) == 75.0
    assert _matrix_pct(ran + [("/a", "t3")]) == 50.0
    # And the degenerate case the chapter opens on: one tool, one URL, done.
    assert _matrix_pct([("/a", "t1")]) == 100.0


@chapter_claim(
    'handbook/05-honest-reporting.md',
    'Coverage then means baseline URLs with at least one successful execution, over the baseline count.',
)
def test_the_baseline_denominator_does_see_the_untested_urls():
    baseline = {"/a", "/b"} | {f"/x{i}" for i in range(198)}
    # The same two executions the matrix scored at 50.0 score at 1.0 here.
    # That gap between the two definitions is the chapter's whole point.
    assert _baseline_pct(tested={"/a", "/b"}, baseline=baseline) == 1.0
    assert _matrix_pct([("/a", "t1"), ("/b", "t2")], discovered=baseline) == 50.0
    # Fixed before testing, so URLs discovered later cannot dilute it: they are
    # not in the snapshot at all.
    assert _baseline_pct(tested={"/a", "/b"}, baseline={"/a", "/b"}) == 100.0


# The consolidation signature now comes from the shipped pass rather than a
# transcription: consolidation_signature is imported from core.consolidator at
# the top of this file. The `import re` below stays, used further down.

import re


@chapter_claim(
    'handbook/05-honest-reporting.md',
    'The signature has no URL component.',
    'A pair of findings reading `TLS 1.0 supported` and `TLS 1.2 supported` share a signature, because the version is exactly the digits that got removed.',
)
def test_the_consolidation_signature_drops_the_url_and_the_version():
    leak_a = consolidation_signature(
        {"type": "unauth_data_leak", "title": "Unauthenticated GET returns 3389-byte response."}
    )
    leak_b = consolidation_signature(
        {"type": "unauth_data_leak", "title": "Unauthenticated GET returns 1602-byte response."}
    )
    # Same class on two different endpoints of two different hosts: the
    # signature takes no URL, so nothing in it can tell them apart.
    assert leak_a == leak_b
    assert consolidation_signature({"type": "weak_tls", "title": "TLS 1.0 supported"}) == (
        consolidation_signature({"type": "weak_tls", "title": "TLS 1.2 supported"})
    )
    # A genuinely different class or title still separates.
    assert consolidation_signature({"type": "idor", "title": "TLS 1.0 supported"}) != (
        consolidation_signature({"type": "weak_tls", "title": "TLS 1.0 supported"})
    )


# The gate check now comes from the shipped tree rather than a transcription:
# decide_gate_status is imported from core.gate_check at the top of this file.
# _gate_status shapes the four inputs this test varies into the dict the function
# reads and returns the status, other signals left at their defaults.
def _gate_status(pages, forms, params, scripts):
    return decide_gate_status({
        "pages_crawled": pages,
        "forms_found": forms,
        "parameters_found": params,
        "scripts_found": scripts,
    })["status"]


@chapter_claim(
    'handbook/05-honest-reporting.md',
    'In practice it means few parameters were recorded, with the forms and scripts conditions structurally true in advance.',
)
def test_pinned_inputs_reduce_the_no_surface_verdict_to_a_parameter_count():
    # With forms and scripts pinned at zero by the caller, the four-condition
    # branch is decided entirely by the other two.
    for pages in (1, 9, 400):
        for params in (0, 1, 2):
            assert _gate_status(pages, 0, params, 0) == "limited"
        assert _gate_status(pages, 0, 3, 0) != "limited"
    # Supply either pinned field for real and the same target stops matching.
    assert _gate_status(9, 3, 1, 0) != "limited"
    assert _gate_status(9, 0, 1, 12) != "limited"


@chapter_claim(
    'handbook/05-honest-reporting.md',
    'That branch has never fired.',
    'The record holds the count, not the reason, and the honest thing is to publish the count and say I cannot choose between those readings.',
)
def test_the_gated_branch_never_fired_across_the_corpus():
    """The paragraph reports the gate-outcome distribution and states that the
    strictest outcome did not occur anywhere in the corpus. This test reads the
    published figures: the strictest outcome sits at the distribution's floor as
    a value rather than a bare present key, the named outcomes sum to the
    recorded total, and their order runs from that floor up to the plurality the
    prose calls lopsided.
    """
    gd = _stats()["corpus"]["gate_decisions"]
    # The strictest outcome as a value, not a bare present key: a key carrying a
    # different count would still satisfy the citation gate and still be wrong.
    assert gd["gated"] == 0
    # A statement about the whole corpus, so the named outcomes account for
    # every decision on record -- nothing parked in an unnamed bucket.
    assert gd["proceed"] + gd["limited"] + gd["gated_soft"] + gd["gated"] == gd["total"]
    # Lopsided: the strictest outcome the floor, proceed the plurality, ordered.
    assert gd["gated"] < gd["gated_soft"] < gd["limited"] < gd["proceed"]


@chapter_claim(
    'handbook/05-honest-reporting.md',
    'Off, the adjust pass hands the Layer 1 ranking straight back:',
    'Two recorded failures are enough to move the injection tool from first to last with the flag on, and change nothing at all with it off. So the switch does what it says on the tin.',
)
def test_the_ablation_flag_switches_the_whole_adjustment_off(monkeypatch):
    ranked = [("test_sqli", 20.0, "base"), ("test_cors", 12.0, "base"),
              ("test_xxe", 9.0, "base")]
    profile_hash = "php:mysql:nowaf:none:rest:laravel"

    def run(flag):
        monkeypatch.setenv("HARNESS_SCHEDULER_ENABLED", flag)
        sched = SmartScheduler()
        for url in ("http://app.shop.example/a", "http://app.shop.example/b"):
            sched.record("test_sqli", ExecutionResult.FAIL, profile_hash, target=url)
        return sched.adjust(list(ranked))

    on, off = run("1"), run("0")
    assert [t for t, _, _ in on] == ["test_cors", "test_xxe", "test_sqli"]
    assert [t for t, _, _ in off] == ["test_sqli", "test_cors", "test_xxe"]
    # Off is the Layer 1 ranking untouched: same order, same scores, no
    # adjustment summary appended to any reason.
    assert off == sorted(ranked, key=lambda r: r[1], reverse=True)
    assert on[-1][1] < off[0][1]


# ---------------------------------------------------------------------------
# README -- the front door copies two things out of the chapters, and a copy is
# where drift hides. verify_claims.sh reads this file's anchors against whatever
# target it was invoked with, so the anchor below is checked when the gate sweep
# runs it over README.md (tests/test_gates.sh does, explicitly).
#
# What these pin: that the five laws in the README are the CURRENT text of the
# five laws in chapter 00, character for character, and not a remembered
# version; that the attribution line is the same string every chapter ends on;
# and that every chapter file is actually linked. Two of the five laws have
# already been corrected once each, in place, in chapter 00 -- a README that
# quietly kept the superseded wording would contradict the book it fronts.
# ---------------------------------------------------------------------------


def _repo_root():
    return pathlib.Path(__file__).resolve().parents[1]


def _five_laws():
    """The five law lines, read out of chapter 00's own five-laws section."""
    thesis = (_repo_root() / "handbook" / "00-thesis.md").read_text(encoding="utf-8")
    section = thesis.split("## The five laws", 1)[1].split("## How to read", 1)[0]
    laws = [l for l in section.splitlines() if re.match(r"^\d\. \*\*", l)]
    assert len(laws) == 5, laws
    return laws


CHAPTER_FILES = [
    "handbook/00-thesis.md",
    "handbook/01-fixed-procedure.md",
    "handbook/02-narrow-waist.md",
    "handbook/03-asymmetric-trust.md",
    "handbook/04-scope-as-code.md",
    "handbook/05-honest-reporting.md",
]


@chapter_claim(
    'README.md',
    "Canonical in chapter 00, copied here. Each is design intent, and the chapter named at the end of a law is where this system is held against it: which parts hold by construction, which hold on only one of the two orchestration paths, which hold on the orchestrator's good behaviour, and which do not hold yet.",
)
def test_the_readme_laws_are_chapter_00s_current_laws():
    """Both parts of the anchored sentence, because it makes two claims.

    "Canonical in chapter 00, copied here" is the first: every law line in
    chapter 00 is present in the README as a whole line, character for
    character. A containment test would also accept a README line that carried
    the law and then a clause of its own, which is not a copy.

    "the chapter named at the end of a law is where this system is held against
    it" is the second, and an earlier version of this test did not read it at
    all -- the anchor was updated to match the reworded sentence while the
    assertion still tested only the copy. So: every law ends by naming at least
    one chapter, and every chapter it names is a file this repository ships.
    Whether that chapter really holds the system against that law is a reading
    judgement no assertion can make; that the pointer resolves is not.
    """
    readme = (_repo_root() / "README.md").read_text(encoding="utf-8")
    readme_lines = readme.splitlines()
    laws = _five_laws()
    for law in laws:
        # A whole line, not a substring of the page: "character for character"
        # is false of a README line that carries the law and then a clause of
        # its own, and a containment test cannot tell the two apart.
        assert law in readme_lines, law[:60]

    named = []
    for law in laws:
        m = re.search(r"Chapters?((?:\s+\d\d(?:\s+and)?)+)\.\s*$", law)
        assert m, f"law does not end by naming a chapter: {law[-60:]!r}"
        numbers = re.findall(r"\d\d", m.group(1))
        assert numbers, law[-60:]
        named.append(numbers)
    for numbers in named:
        for num in numbers:
            matches = [c for c in CHAPTER_FILES if c.startswith(f"handbook/{num}-")]
            assert len(matches) == 1, f"law names chapter {num}, which is not a chapter file"
            assert (_repo_root() / matches[0]).exists(), matches[0]
    # Every chapter after the thesis is named by at least one law, which is what
    # makes "the chapter named at the end of a law" a complete account.
    all_named = {n for numbers in named for n in numbers}
    assert all_named == {c[len("handbook/"):][:2] for c in CHAPTER_FILES[1:]}, sorted(all_named)


COST_HEADING = "## What it costs to build this"
# The claim's locator and its scoping phrase, kept apart on purpose: the first
# finds the README sentence whatever else is edited around it, the second is the
# quantifier that has to survive.
ADMISSION_CLAIM = "a section on the control's costs and remaining gaps"
ADMISSION_SCOPE = "after the first"
# The subject the scope phrase modifies, which bounds it on the left.
ADMISSION_SUBJECT = "Every chapter"
# Subject, scope and predicate joined, which is what the README assertion reads.
# `ADMISSION_SCOPE in sentence` was that assertion before this commit, and a
# narrowing run against it walked straight through -- not a defect that shipped,
# a mutation that was executed and parked: "after the first two" contains "after
# the first", so the README sentence and its anchor were edited together and the
# suite and every gate stayed green. Joining the scope to the predicate closed
# that, and left the mirror image open: an insertion on the LEFT leaves the scope
# phrase intact too, so "Every other chapter after the first ends by ..." passed
# the right-bounded clause. Both sides are bounded here, and both insertions are
# demonstrated on the published sentence in the test below. What the pair does
# not reach is text OUTSIDE the clause, at either end, and that is more than one
# shape: text before the subject that leaves its capital intact ("Almost Every
# chapter ..."), a trailing exception inside the same sentence ("... gets wrong,
# except chapter 03, and the honesty sections ..."), and an appended sentence
# taking the claim back ("... show it. Chapter 03 does not."). All three were run
# against this clause and all three passed. The anchored sentence's second half
# is pinned by no content assertion at all -- only by the anchor, which a
# coordinated edit defeats. A re-scoping written before the subject normally
# lowercases it ("Almost every chapter"), which the clause does catch. This is
# left open deliberately, not overlooked: closing it means pinning the whole
# sentence here, and that only adds a third copy for a coordinated edit to
# update.
ADMISSION_CLAUSE = f"{ADMISSION_SUBJECT} {ADMISSION_SCOPE} ends with {ADMISSION_CLAIM}"


@chapter_claim(
    'README.md',
    "Every chapter after the first ends with a section on the control's costs and remaining gaps.",
)
def test_every_chapter_after_the_first_ends_on_the_cost_admission():
    """The quantifier is the claim: "after the first", not "each".

    Operationalised as the chapter's last section heading, which is where each of
    01-05 puts its admission of what the control still gets wrong. Chapter 00 ends
    on "How to read the rest of this" and scopes the same sentence the same way in
    its own words.

    Which guard catches which mutation, measured rather than reasoned, because
    the version this replaces got it wrong and that is the error the chapter it
    backs is about. A chapter that drops its cost section fails the first
    assertion here. A chapter 00 that grows one fails the first assertion when
    the new section is its last and the second when it sits anywhere else,
    because the first reads only each file's final heading -- the placement
    decides which one fires, so naming one of them alone is not an answer. A
    chapter 00 that ends on a cost section worded differently from COST_HEADING
    passes both of those, and the third assertion exists for that case alone: it
    reads the word "cost" in chapter 00's last heading, and nothing else in the
    file.

    Loosening the README's quantifier back to "each chapter" was once caught
    only by verify_claims.sh Check C, via the anchor above, and by nothing in
    this function, which did not read the README at all before the README block
    below existed. That block read the scoping phrase as a bare containment
    test, which caught the loosening and let the narrowing through: "after the
    first two" contains "after the first", so that edit, made in the README and
    the anchor together, passed this function, the suite and every gate. The
    assertion now reads ADMISSION_CLAUSE -- the phrase joined to the predicate
    it scopes and to the subject it modifies -- and an insertion on either side
    of the phrase fails it. Rewriting the predicate instead is caught, but by
    the block's first assertion rather than this one: the locator stops finding
    a sentence at all and "the README no longer makes the admission claim"
    fires. The comment above ADMISSION_CLAUSE records what the pair still does
    not reach.
    """
    root = _repo_root()
    ends_on_cost = set()
    last_heading = {}
    # The population is DERIVED from the tree, not read off CHAPTER_FILES, and
    # that is the whole guarantee. Against the hard-coded list this check ran over
    # chapters 00-05 while chapter 06 shipped, was linked from the README's own
    # index, and ended on a step heading -- so the sentence it backs was false and
    # this function could only agree with it. A numbered chapter added tomorrow
    # now enters here by existing, and fails until somebody decides about it.
    numbered = sorted(
        f"handbook/{q.name}" for q in (root / "handbook").glob("[0-9]*.md")
    )
    assert numbered[0] == CHAPTER_FILES[0], numbered
    assert set(CHAPTER_FILES).issubset(numbered), sorted(set(CHAPTER_FILES) - set(numbered))
    for rel in numbered:
        headings = [
            l for l in (root / rel).read_text(encoding="utf-8").splitlines()
            if l.startswith("## ")
        ]
        last_heading[rel] = headings[-1] if headings else ""
        if headings and headings[-1] == COST_HEADING:
            ends_on_cost.add(rel)
    assert ends_on_cost == set(numbered[1:]), sorted(set(numbered[1:]) ^ ends_on_cost)
    assert COST_HEADING not in (root / numbered[0]).read_text(encoding="utf-8")
    # Both assertions above compare against COST_HEADING exactly, so a chapter 00
    # that ends on a cost section worded differently -- "## What it costs to
    # really build this" -- satisfies both: the set because the string differs,
    # the absence check for the same reason. Read the word instead. Scoped to the
    # last heading rather than the whole file on purpose: chapter 00 already
    # carries "## What this costs" mid-file, and the sentence is about what a
    # chapter ENDS on.
    assert "cost" not in last_heading[numbered[0]].lower(), (
        f"chapter 00 now ends on {last_heading[numbered[0]]!r}, so "
        '"every chapter after the first" no longer describes the tree'
    )

    readme = (root / "README.md").read_text(encoding="utf-8")
    sentences = [
        s for s in re.split(r"(?<=[.!?])\s+", readme.replace("\n", " "))
        if ADMISSION_CLAIM in s
    ]
    assert sentences, "the README no longer makes the admission claim at all"
    for s in sentences:
        # Chapter 00 is outside the computed set, so a universal quantifier here
        # would be false. The scoping phrase is what makes it true, and it is
        # read bounded by the subject on its left and the predicate on its
        # right, because the phrase on its own survives an insertion on either
        # side.
        assert ADMISSION_CLAUSE in s, s
        # Both insertions, applied to this sentence rather than to a synthetic
        # copy of it so neither demonstration can go stale. The bare containment
        # test stays true of both mutants; the bounded clause survives neither.
        narrowed = s.replace(ADMISSION_SCOPE, ADMISSION_SCOPE + " two", 1)
        widened = s.replace(ADMISSION_SUBJECT, "Every other chapter", 1)
        assert ADMISSION_SCOPE in narrowed and ADMISSION_SCOPE in widened
        assert ADMISSION_CLAUSE not in narrowed
        assert ADMISSION_CLAUSE not in widened


# The README also describes the POPULATION of num-ok annotations, and nothing in
# the gate stack reads a num-ok reason for truth or counts the reasons -- which is
# how a false census of them shipped through five green gates once already. The
# annotations were each individually sound; the sentence about them said "most
# name a constant in the code" where the real figure is a plurality. Every count
# in the replacement sentence is derived here instead of transcribed, and the
# category test is a string in the reason itself, so an annotation added without
# updating the sentence fails this rather than passing quietly.
#
# The fourth category, "spelled quantity", arrived with the extension of Check A
# to quantities written as words. Its members are mixed by kind: most of them
# count a code artifact -- a line, a method, a row -- and the rest are worded
# ratios over figures the chapter already cites, counts from a corpus query with
# no published key behind it, quantity words doing rhetorical work, and two that
# count something in this handbook itself rather than in the system. What they
# share is why they are split out rather than folded into the residual
# category: every annotation in that residual category is about a digit
# read out of the source, and a count written as a word is a different object
# even when the thing it counts is in the code.
NUM_OK_RE = re.compile(r"<!--\s*num-ok\s*:?\s*(.*?)\s*-->")
ANNOTATED_FILES = CHAPTER_FILES + ["README.md"]


def _num_ok_reasons():
    root = _repo_root()
    out = []
    for rel in ANNOTATED_FILES:
        for reason in NUM_OK_RE.findall((root / rel).read_text(encoding="utf-8")):
            out.append((rel, reason))
    return out


@chapter_claim(
    'README.md',
    "Across chapters 00 through 05 and this README, fourteen annotations name a constant or a property of the code, thirty-five cover a spelled quantity the digit check cannot read, five name an HTTP status code, and one names a comparison between two of this repository's own published snapshots.",
)
def test_the_readme_census_of_its_own_annotations_is_the_real_one():
    reasons = _num_ok_reasons()
    http = [r for r in reasons if "HTTP status code" in r[1]]
    snapshot = [r for r in reasons if "between the two measurement passes" in r[1]]
    spelled = [r for r in reasons if "spelled quantity" in r[1]]
    categorised = http + snapshot + spelled
    code = [r for r in reasons if r not in categorised]

    # The three named categories partition cleanly, so "the rest" is a real
    # category and not an overlap artifact.
    assert len(set(map(id, categorised))) == len(categorised)
    assert len(code) + len(categorised) == len(reasons)

    assert len(code) == 14, [r[0] for r in code]
    assert len(spelled) == 35, [r[0] for r in spelled]
    assert len(http) == 5, [r[0] for r in http]
    assert len(snapshot) == 1, [r[0] for r in snapshot]
    assert len(reasons) == 55


@chapter_claim(
    'README.md',
    'It holds assertions against the reference implementation and the published statistics, and each is anchored to the verbatim sentence it backs, so an edit that changes a fact fails a test instead of quietly shipping.',
)
def test_every_chapter_is_linked_at_source_and_rendered():
    """A chapter counts as linked when a markdown link points at it.

    A chapter is now linked TWICE and both links are asserted, because the
    two targets do different jobs and losing either is a silent regression. The
    source under handbook/ carries the `[[stats:]]` and `[[code:]]` macros
    unresolved, which is what the citation gates read; the copy under rendered/
    is where a figure is a digit. A reader sent to the source alone meets
    placeholders where every number should be -- measured on a first-time
    reader, who could not check a single figure without leaving the files the
    front door had pointed them at.

    "Linked from the front door" was read as ``rel in readme``, which a bare
    mention of the path in prose satisfies, and which a link to a longer path
    beginning with the same characters satisfies too: retarget one link at
    ``handbook/00-thesis.md.bak`` and the containment test never notices, while
    the chapter it names is no longer reachable from the README. The link target
    is read whole instead. A reference-style link would fail this, and the
    assertion is what to change if the README ever adopts one.
    """
    root = _repo_root()
    readme = (root / "README.md").read_text(encoding="utf-8")
    for rel in CHAPTER_FILES:
        path = root / rel
        assert path.exists(), rel
        # Linked from the front door, so a renamed chapter breaks the sweep.
        assert f"]({rel})" in readme, rel
        # And linked at its resolved twin, so a reader meets digits rather than
        # macros. Derived from the source name, never typed.
        rendered = rel.replace("handbook/", "rendered/", 1)
        assert (root / rendered).exists(), rendered
        assert f"]({rendered})" in readme, rendered
@chapter_claim(
    'README.md',
    "Chapter 05 reports the system's F1 against a public deliberately-vulnerable application and places it beside an OWASP ZAP passive-scan score. This repository proves the arithmetic and keeps the four aggregate score files synchronized with data/stats.json; it does not contain the raw findings, ground-truth entries, matcher, target identifiers or run identifiers needed to prove that the two tools were evaluated in a controlled head-to-head. Treat the pair as historical, author-recorded data points, not a fair benchmark.",
)
def test_the_readme_names_the_baseline_and_its_evidence_limit():
    """The front door must not turn aggregate rows into a fair benchmark."""
    root = _repo_root()
    bench = _stats()["benchmark"]
    baseline = bench["zap_baseline"]

    note = baseline["note"].lower()
    assert "author-recorded" in note
    assert "controlled head-to-head" in note

    scores = sorted((root / "data" / "benchmark").glob("*.score.json"))
    assert scores, "the README names committed scorer output that is not there"
    assert (root / "tests" / "test_benchmark_score_files.py").exists()

    ch05 = (root / "handbook" / "05-honest-reporting.md").read_text(encoding="utf-8")
    pair = next(
        l for l in ch05.splitlines()
        if "benchmark.juice_shop.f1.mean" in l and "benchmark.zap_baseline.f1" in l
    )
    reading = ch05.split(pair, 1)[1].split("\n## ", 1)[0]
    assert len(reading) > len(pair), (len(reading), len(pair))
    assert "proof of anything" in reading, "chapter 05 no longer disowns the baseline zero"
