"""The capstone's connections, held to what the reader review found missing.

The assembled application claimed to compose the taught parts; the reader
review showed the memory lessons never fed it, both proposal calls preceded
every capture, and the recalled rows never changed the provider context.
These tests hold the corrected connections: the evidence phase sees new
captures, recalled memory flows through the taught store, search and
assembler into the context with an omissions record, and a completed run's
surviving findings become tactics a later run retrieves -- unless refuted.
"""

import json

from core.memory.store import MemoryStore
from core.run.app import Application
from core.run.demo_app import (
    LAB, PROPOSAL_ADMITTED, PROPOSAL_REFUSED, WORLD, build_config,
    demo_verifier)
from core.run.demo_lifecycle import FakeClock


def chapter_claim(chapter, *sentences):
    """Anchor a test to the verbatim lesson sentence(s) it backs.

    Same declaration shape as tests/test_chapter_claims.py: verify_claims.sh's
    Check C parses these decorators and goes red when a declared sentence is
    no longer present in its chapter.
    """
    def deco(fn):
        return fn
    return deco


class RecordingProvider:
    """A provider that keeps every context it was shown, then replays replies."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.contexts = []

    def __call__(self, context):
        self.contexts.append(json.loads(json.dumps(context)))
        return self.replies.pop(0)


# The host's own boundary, matching what _remember stamps for this world:
# scoped retrieval and the write-back speak the same identity.
SCOPE = {"engagement": "assembly-lesson-fixtures",
         "profile_hash": "fixture:assembly-lesson-fixtures"}

SEED_TACTIC = {
    "record_id": "tac-shared-banner", "tier": "longterm",
    "record_type": "tactic",
    "content": "inspect_headers on the lab landing disclosed the shared "
               "banner marker",
    "source": "memory", "created_at": 1.0, **SCOPE,
}


def retrieval_config(store, query="shared banner inspect_headers",
                     records=(SEED_TACTIC,), budget=400, scope=SCOPE,
                     **kwargs):
    config = build_config(**kwargs)
    config["retrieval"] = {"enabled": True, "store": store,
                           "records": list(records), "query": query,
                           "budget": budget, "scope": dict(scope)}
    return config


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "The second proposal phase sees the evidence the first phase's actions "
    "captured, and its admitted work runs through the same door.",
)
def test_the_evidence_phase_sees_what_the_first_phase_captured():
    provider = RecordingProvider([PROPOSAL_REFUSED, PROPOSAL_ADMITTED])
    config = build_config(provider=provider)
    report = Application(config, clock=FakeClock()).run(WORLD)

    assert len(provider.contexts) == 2
    first, second = provider.contexts
    assert "evidence" not in first, \
        "the observation phase claimed evidence before anything ran"
    assert second["evidence"], "the evidence phase saw no captures"
    assert any("LAB_SHARED_BANNER" in row["excerpt"]
               for row in second["evidence"]), \
        "the evidence summaries lack the captured banner"
    phases = [p["phase"] for p in report["proposals"]]
    assert phases == ["observation", "evidence"]
    # The evidence-phase admission executed through the same door: the health
    # action it proposed has an outcome in the terminal report.
    outcomes = report["finish"]["report"]["run_report"]["outcomes"]
    health = [aid for aid in outcomes if aid.endswith("/health")]
    assert health and outcomes[health[0]]["status"] == "clean"
    assert report["followup_plan"] and \
        report["followup_plan"][0]["destination"].endswith("/health")


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "Recalled memory reaches the model through the taught store, search and "
    "context assembler, and the report records what was included and what "
    "was omitted.",
)
def test_recalled_content_reaches_the_provider_context():
    provider = RecordingProvider([PROPOSAL_REFUSED, PROPOSAL_ADMITTED])
    config = retrieval_config(MemoryStore(":memory:"), provider=provider)
    report = Application(config, clock=FakeClock()).run(WORLD)

    advisory = provider.contexts[0].get("advisory_memory", "")
    assert SEED_TACTIC["content"] in advisory, \
        "the stored record's content never reached the provider"
    assert "tac-shared-banner" in advisory, "the block lost its provenance id"
    assert report["retrieval"]["observation"]["included"] == \
        ["tac-shared-banner"]
    assert report["retrieval"]["observation"]["query"] == \
        "shared banner inspect_headers"

    # Changing the stored content changes the context: memory is wired, not
    # a static label.
    other = dict(SEED_TACTIC,
                 content="form_probe on the login form found nothing new")
    provider2 = RecordingProvider([PROPOSAL_REFUSED, PROPOSAL_ADMITTED])
    config2 = retrieval_config(MemoryStore(":memory:"), provider=provider2,
                               query="login form probe", records=(other,))
    Application(config2, clock=FakeClock()).run(WORLD)
    advisory2 = provider2.contexts[0].get("advisory_memory", "")
    assert other["content"] in advisory2
    assert advisory2 != advisory


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "Recalled memory reaches the model through the taught store, search and "
    "context assembler, and the report records what was included and what "
    "was omitted.",
)
def test_the_context_budget_produces_an_omissions_record():
    big = dict(SEED_TACTIC, record_id="tac-big",
               content=("banner " * 400).strip())
    provider = RecordingProvider([PROPOSAL_REFUSED, PROPOSAL_ADMITTED])
    config = retrieval_config(MemoryStore(":memory:"), provider=provider,
                              query="banner", records=(SEED_TACTIC, big),
                              budget=60)
    report = Application(config, clock=FakeClock()).run(WORLD)
    trace = report["retrieval"]["observation"]
    assert "tac-big" not in trace["included"]
    assert any(o["block_id"] == "tac-big" for o in trace["omissions"]), \
        "the too-large block vanished instead of being recorded as omitted"


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "A completed run teaches the next one: surviving findings become stored "
    "tactics, and a refuted tactic declines the write loudly.",
)
def test_a_completed_run_teaches_the_next_and_refutation_is_honored():
    store = MemoryStore(":memory:")

    # Run one: verified findings become tactics in the shared store.
    provider1 = RecordingProvider([PROPOSAL_REFUSED, PROPOSAL_ADMITTED])
    config1 = retrieval_config(store, provider=provider1, records=())
    config1["verifier"] = demo_verifier
    report1 = Application(config1, clock=FakeClock()).run(WORLD)
    written = [w for w in report1["memory_written"] if w["record_id"]]
    assert written, "no surviving finding was written back to memory"

    # Run two, same store: the tactic run one learned is in the context.
    provider2 = RecordingProvider([PROPOSAL_REFUSED, PROPOSAL_ADMITTED])
    config2 = retrieval_config(store, provider=provider2, records=(),
                               query="shared lab banner")
    report2 = Application(config2, clock=FakeClock()).run(WORLD)
    advisory = provider2.contexts[0].get("advisory_memory", "")
    assert "Shared lab banner disclosed" in advisory, \
        "run two's context lacks the tactic run one stored"

    # Refute every learned tactic through the taught API, using the stored
    # identity fields; run three's context must exclude them, and the
    # write-back must decline to rehabilitate them.
    tactics = store.fetch(record_type="tactic")
    assert tactics
    for row in tactics:
        meta = json.loads(row["metadata"])
        assert store.record_refuted(
            profile_hash=row["profile_hash"], tool=row["tool_name"],
            endpoint=row["url_pattern"], param=meta.get("param_name"),
            technique=meta.get("bypass_technique")) is True

    provider3 = RecordingProvider([PROPOSAL_REFUSED, PROPOSAL_ADMITTED])
    config3 = retrieval_config(store, provider=provider3, records=(),
                               query="shared lab banner")
    config3["verifier"] = demo_verifier
    report3 = Application(config3, clock=FakeClock()).run(WORLD)
    advisory3 = provider3.contexts[0].get("advisory_memory", "")
    assert "Shared lab banner disclosed" not in advisory3, \
        "a refuted tactic still reached the provider context"
    refuted_ids = {r["record_id"]
                   for r in store.fetch(include_refuted=True,
                                        record_type="tactic")
                   if r["refuted"]}
    assert refuted_ids, "nothing was actually refuted; fixture defect"
    included3 = report3["retrieval"]["observation"]["included"]
    assert not refuted_ids & set(included3), \
        "a refuted tactic still reached the assembled context"
    declined = [w for w in report3["memory_written"] if w.get("declined")]
    assert declined, "re-recording a refuted tactic did not decline loudly"
    assert "refuted" in declined[0]["declined"]


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "A completed run teaches the next one: surviving findings become stored "
    "tactics, and a refuted tactic declines the write loudly.",
)
def test_unreviewed_survivors_store_as_hypotheses_never_proven():
    # The adversarial recheck's F-A: a wall that expires after the captures
    # refuses every verifier call; the surviving findings must not convert
    # into proven memory on the strength of nobody having reviewed them.
    store = MemoryStore(":memory:")
    clock = FakeClock()
    config = retrieval_config(store, records=())
    config["verifier"] = demo_verifier
    config["budgets"]["wall_seconds"] = 15

    slow = {}
    from core.run.demo_app import adapters as demo_adapters
    for name, fn in demo_adapters().items():
        def slowed(url, _fn=fn):
            clock.now += 10.0
            return _fn(url)
        slow[name] = slowed
    config["adapters"] = slow
    config["provider"] = None

    report = Application(config, clock=clock).run(WORLD)
    events = report["finish"]["report"]["run_report"]["events"]
    assert any(e["event"] == "refused" and e["kind"] == "verdict"
               and "wall_seconds" in e["reason"] for e in events), \
        "the fixture never actually refused a verifier call"
    written = [w for w in report["memory_written"] if w["record_id"]]
    assert written, "nothing was written; the fixture proves nothing"
    assert all(w["grade"] == "hypothesis" for w in written), written
    for row in store.fetch(record_type="tactic"):
        meta = json.loads(row["metadata"])
        assert meta["evidence_grade"] == "hypothesis", meta
        assert "proof" not in meta

    # The contrast: an accepted verdict stores its proof and grades proven.
    store2 = MemoryStore(":memory:")
    config2 = retrieval_config(store2, records=())
    config2["verifier"] = demo_verifier
    report2 = Application(config2, clock=FakeClock()).run(WORLD)
    accepted = [w for w in report2["memory_written"] if w["record_id"]]
    assert accepted and all(w["grade"] == "proven" for w in accepted)
    assert any(json.loads(r["metadata"]).get("proof")
               for r in store2.fetch(record_type="tactic"))


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "Recalled memory reaches the model through the taught store, search and "
    "context assembler, and the report records what was included and what "
    "was omitted.",
)
def test_a_failing_store_degrades_to_a_recorded_refusal():
    # The adversarial recheck's F-B: memory is advisory, so a store that dies
    # mid-run costs the run its recall, never its terminal report.
    store = MemoryStore(":memory:")
    store.close()
    provider = RecordingProvider([PROPOSAL_REFUSED, PROPOSAL_ADMITTED])
    config = retrieval_config(store, provider=provider, records=())
    config["verifier"] = demo_verifier
    report = Application(config, clock=FakeClock()).run(WORLD)
    assert report["finish"]["completed"] is True, \
        "a dead memory store cost the run its terminal report"
    assert "error" in report["retrieval"]["observation"]
    events = report["finish"]["report"]["run_report"]["events"]
    assert any(e["event"] == "refused" and e["kind"] in ("retrieval", "memory")
               for e in events)
    declined = [w for w in report["memory_written"] if w.get("declined")]
    assert declined and all(w["record_id"] is None for w in declined)


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "Retrieval records are validated at configuration time, not discovered "
    "broken mid-run.",
)
def test_malformed_seed_records_and_coverage_urls_refuse_at_config_time():
    # The adversarial recheck's F-C and the K2 nit: both promises belong to
    # the configuration boundary, not to a crash mid-run.
    import pytest
    from core.run.app import AppConfigError, validate_config
    config = retrieval_config(":memory:",
                              records=({"content": "x", "tool": "sqlmap"},))
    with pytest.raises(AppConfigError) as caught:
        validate_config(config)
    assert "MemoryRecord" in str(caught.value)

    config = build_config()
    config["coverage"] = [["inspect_headers", "::not a url::"]]
    with pytest.raises(AppConfigError) as caught:
        validate_config(config)
    assert "not a usable destination" in str(caught.value)


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "A stop gate executes zero testing callbacks: the run halts, every "
    "planned row becomes a recorded skip, and the terminal report says it "
    "stopped and why.",
)
def test_a_halted_run_never_touches_a_durable_store(tmp_path):
    # The adversarial recheck's F-D: the store opens lazily, so a run the
    # gate halts does not even seed it.
    path = tmp_path / "halted-memory.db"
    world = {"name": WORLD["name"],
             "surfaces": [{**s, "response": {**s["response"], "status": 503}}
                          for s in WORLD["surfaces"]]}
    config = retrieval_config(str(path), records=(SEED_TACTIC,))
    config["provider"] = RecordingProvider([PROPOSAL_ADMITTED,
                                            PROPOSAL_ADMITTED])
    report = Application(config, clock=FakeClock()).run(world)
    assert report["halted"] is not None
    assert report["memory_written"] == []
    assert not path.exists(), \
        "a gate-halted run created and seeded the durable store"


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "Every search filters both the keyword and vector lanes by that engagement, so another engagement's record cannot enter the provider context.",
)
def test_retrieval_never_crosses_the_engagement_boundary(tmp_path):
    # The release review's P1: a durable store holding another engagement's
    # records, and the current engagement's provider context. Both proposal
    # phases, and a reopened store, must stay inside the host's scope.
    path = str(tmp_path / "memory.sqlite")
    foreign = {"record_id": "tac-foreign", "tier": "longterm",
               "record_type": "tactic",
               "content": "FOREIGN-ENGAGEMENT banner note: inspect_headers "
                          "found the other client's shared banner",
               "source": "memory", "created_at": 1.0,
               "engagement": "someone-elses-engagement",
               "profile_hash": "ph-foreign"}

    provider = RecordingProvider([PROPOSAL_REFUSED, PROPOSAL_ADMITTED])
    config = retrieval_config(path, records=(SEED_TACTIC, foreign),
                              provider=provider)
    report = Application(config, clock=FakeClock()).run(WORLD)

    assert len(provider.contexts) == 2, "both proposal phases must run"
    for phase, context in zip(("observation", "evidence"), provider.contexts):
        advisory = context.get("advisory_memory", "")
        assert "FOREIGN-ENGAGEMENT" not in advisory, \
            f"the {phase} phase leaked another engagement's record"
        assert SEED_TACTIC["content"] in advisory, \
            f"the {phase} phase lost the in-scope record"
        trace = report["retrieval"][phase]
        assert trace["scope"] == SCOPE
        assert "tac-foreign" not in trace["included"]

    # Reopened durable storage: a second application over the same file, no
    # seeds, stays scoped -- the boundary is the read, not the ingest.
    provider2 = RecordingProvider([PROPOSAL_REFUSED, PROPOSAL_ADMITTED])
    config2 = retrieval_config(path, records=(), provider=provider2)
    Application(config2, clock=FakeClock()).run(WORLD)
    for context in provider2.contexts:
        assert "FOREIGN-ENGAGEMENT" not in context.get("advisory_memory", "")


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    'A recalled block keeps its stored creation time and expiry. The assembler omits expired blocks and names them in the omissions list.',
)
def test_an_expired_record_is_omitted_not_renewed(tmp_path):
    # The release review's P2: the block used to be rebuilt with the current
    # time and no expiry, so nothing could ever expire. One consistent time
    # base, one record already past its expiry, one still inside it.
    path = str(tmp_path / "memory.sqlite")
    stale = dict(SEED_TACTIC, record_id="tac-stale",
                 content="EXPIRED-TACTIC inspect_headers shared banner note "
                         "that aged out",
                 created_at=1.0, expires_at=2.0)
    fresh = dict(SEED_TACTIC, record_id="tac-fresh",
                 created_at=1.0, expires_at=10_000.0)

    wall = FakeClock()
    wall.now = 50.0  # far past tac-stale's expiry, inside tac-fresh's
    provider = RecordingProvider([PROPOSAL_REFUSED, PROPOSAL_ADMITTED])
    config = retrieval_config(path, records=(stale, fresh), provider=provider)
    report = Application(config, clock=FakeClock(), wall_clock=wall).run(WORLD)

    trace = report["retrieval"]["observation"]
    assert "tac-stale" not in trace["included"], \
        "retrieval renewed an expired record"
    assert {"block_id": "tac-stale", "reason": "expired"} in trace["omissions"]
    assert "tac-fresh" in trace["included"]
    for context in provider.contexts:
        assert "EXPIRED-TACTIC" not in context.get("advisory_memory", "")

    # Reopened durable storage on the same persistent time base: still
    # expired, still visible as an omission.
    provider2 = RecordingProvider([PROPOSAL_REFUSED, PROPOSAL_ADMITTED])
    wall2 = FakeClock()
    wall2.now = 60.0
    config2 = retrieval_config(path, records=(), provider=provider2)
    report2 = Application(config2, clock=FakeClock(), wall_clock=wall2).run(WORLD)
    trace2 = report2["retrieval"]["observation"]
    assert "tac-stale" not in trace2["included"]
    assert {"block_id": "tac-stale", "reason": "expired"} in trace2["omissions"]


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    'Enabled retrieval requires the host to name an engagement.',
)
def test_enabled_retrieval_refuses_a_missing_or_malformed_scope():
    import pytest
    from core.run.app import AppConfigError

    def build(scope):
        config = retrieval_config(MemoryStore(":memory:"))
        config["retrieval"]["scope"] = scope
        return Application(config)

    for bad, why in ((None, "missing"), ({}, "empty"),
                     ({"tier": "longterm"}, "key not in the allowlist"),
                     ({"engagement": "  "}, "blank value")):
        with pytest.raises(AppConfigError):
            build(bad)


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    'New tactics receive the same engagement scope, and each `memory_written` row identifies the finding and record involved or the reason a write was refused.',
)
def test_write_backs_carry_the_hosts_scope(tmp_path):
    path = str(tmp_path / "memory.sqlite")
    provider = RecordingProvider([PROPOSAL_REFUSED, PROPOSAL_ADMITTED])
    config = retrieval_config(path, records=(), provider=provider)
    config["verifier"] = demo_verifier
    report = Application(config, clock=FakeClock()).run(WORLD)
    assert [w for w in report["memory_written"] if w["record_id"]]

    rows = MemoryStore(path).fetch(record_type="tactic")
    assert rows
    for row in rows:
        assert row["engagement"] == SCOPE["engagement"]
        assert row["profile_hash"] == SCOPE["profile_hash"]


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "The engagement key is mandatory in that scope: a tool-only or profile-only read would let another engagement's record ride a shared tool or stack fingerprint into the context, so cross-engagement tactic sharing is a separate lane a host builds deliberately, never a wider read scope.",
)
def test_a_scope_without_the_engagement_key_is_refused():
    # The private-main review's P1: on the reviewed commit these scopes were
    # accepted, and a foreign engagement's record sharing the tool or the
    # profile reached the provider context in both phases.
    import pytest
    from core.run.app import AppConfigError

    for scope in ({"tool_name": "inspect_headers"},
                  {"profile_hash": "fixture:assembly-lesson-fixtures"},
                  {"tool_name": "inspect_headers",
                   "profile_hash": "fixture:assembly-lesson-fixtures"}):
        config = retrieval_config(MemoryStore(":memory:"), scope=scope)
        with pytest.raises(AppConfigError) as caught:
            Application(config)
        assert "engagement" in str(caught.value)


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "Every search filters both the keyword and vector lanes by that engagement, so another engagement's record cannot enter the provider context.",
)
def test_every_accepted_scope_shape_excludes_foreign_engagements():
    # The review's acceptance rule: test all accepted scope shapes against
    # the provider context, not only the recommended full scope. A foreign
    # record deliberately shares the tool AND the profile; only the
    # engagement boundary keeps it out.
    foreign = {"record_id": "f-ride", "tier": "longterm",
               "record_type": "tactic",
               "content": "FOREIGN_RIDER shared banner inspect_headers note",
               "source": "memory", "created_at": 1.0,
               "engagement": "someone-else",
               "profile_hash": SCOPE["profile_hash"],
               "tool_name": "inspect_headers"}
    shapes = (
        {"engagement": SCOPE["engagement"]},
        {"engagement": SCOPE["engagement"],
         "profile_hash": SCOPE["profile_hash"]},
        {"engagement": SCOPE["engagement"], "tool_name": "inspect_headers"},
    )
    for scope in shapes:
        provider = RecordingProvider([PROPOSAL_REFUSED, PROPOSAL_ADMITTED])
        config = retrieval_config(MemoryStore(":memory:"),
                                  records=(SEED_TACTIC, foreign),
                                  provider=provider, scope=scope)
        Application(config, clock=FakeClock()).run(WORLD)
        assert len(provider.contexts) == 2
        for phase, context in zip(("observation", "evidence"),
                                  provider.contexts):
            assert "FOREIGN_RIDER" not in context.get("advisory_memory", ""), \
                f"scope {scope} leaked a foreign record in the {phase} phase"


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    'Persistent memory uses a separate epoch clock for expiry checks and write-backs; comparing an epoch timestamp with monotonic time would leave old records available.',
)
def test_epoch_expiry_holds_under_fully_default_clocks(tmp_path):
    # The private-main review's P2: on the reviewed commit, an ordinary
    # default-clock application compared monotonic now against epoch
    # timestamps, included the expired row in both provider contexts, and
    # recorded no omission.
    import time as _time
    path = str(tmp_path / "memory.sqlite")
    now_epoch = _time.time()
    expired = dict(SEED_TACTIC, record_id="e-epoch",
                   content="EXPIRED_EPOCH inspect_headers shared banner stale",
                   created_at=now_epoch - 120, expires_at=now_epoch - 60)

    provider = RecordingProvider([PROPOSAL_REFUSED, PROPOSAL_ADMITTED])
    config = retrieval_config(path, records=(expired,), provider=provider)
    report = Application(config).run(WORLD)  # both clocks left at defaults
    trace = report["retrieval"]["observation"]
    assert {"block_id": "e-epoch", "reason": "expired"} in trace["omissions"]
    for phase, context in zip(("observation", "evidence"), provider.contexts):
        assert "EXPIRED_EPOCH" not in context.get("advisory_memory", ""), \
            f"the {phase} phase renewed an epoch-expired record"

    # Reopened SQLite file, second default-clock application instance.
    provider2 = RecordingProvider([PROPOSAL_REFUSED, PROPOSAL_ADMITTED])
    config2 = retrieval_config(path, records=(), provider=provider2)
    report2 = Application(config2).run(WORLD)
    trace2 = report2["retrieval"]["observation"]
    assert {"block_id": "e-epoch", "reason": "expired"} in trace2["omissions"]
    for context in provider2.contexts:
        assert "EXPIRED_EPOCH" not in context.get("advisory_memory", "")


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    'Persistent memory uses a separate epoch clock for expiry checks and write-backs; comparing an epoch timestamp with monotonic time would leave old records available.',
)
def test_write_backs_are_stamped_on_the_wall_clock(tmp_path):
    path = str(tmp_path / "memory.sqlite")
    wall = FakeClock()
    wall.now = 1_700_000_000.0
    provider = RecordingProvider([PROPOSAL_REFUSED, PROPOSAL_ADMITTED])
    config = retrieval_config(path, records=(), provider=provider)
    config["verifier"] = demo_verifier
    report = Application(config, clock=FakeClock(),
                         wall_clock=wall).run(WORLD)
    assert [w for w in report["memory_written"] if w["record_id"]]
    for row in MemoryStore(path).fetch(record_type="tactic"):
        assert row["created_at"] == wall.now, \
            "a persistent record carries a non-wall timestamp"
