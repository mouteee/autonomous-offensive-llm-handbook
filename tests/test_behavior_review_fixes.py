"""Regressions for the behavior-and-failure review's findings.

Each test reproduces one of the review's probes against the corrected code:
the identity and provenance layer (unauthorized evidence, alias identities,
unverified resume inputs), the provider-input crash, and the smaller boundary
gaps. The attack shapes come from the review record; the tests are fresh.
"""

import copy

import pytest

from core.controller import make_controller
from core.controller.contract import Candidate, Decision, Outcome, State, decision_id
from core.controller.lab import run_episode
from core.controller.mb import Habituation
from core.controller.worlds import make_world
from core.memory.search import HybridSearch, sanitize_query
from core.memory.store import MemoryStore, MemoryStoreError
from core.run.demo_proposals import CONTEXT, OBSERVATIONS, VALID
from core.run.demo_records import build_policy as records_policy
from core.run.dispatch import Dispatcher
from core.run.lifecycle import Budgets, Lifecycle
from core.run.policy import Policy, Tool, normalize_destination
from core.run.proposals import FakeProvider, ProviderSession
from core.run.recorder import Recorder
from core.run.records import Finding, digest, make_run
from core.run.verify import VerificationPipeline


def chapter_claim(chapter, *sentences):
    """Anchor a test to the verbatim lesson sentence(s) it backs.

    Same declaration shape as tests/test_chapter_claims.py: verify_claims.sh's
    Check C parses these decorators and goes red when a declared sentence is
    no longer present in its chapter.
    """
    def deco(fn):
        return fn
    return deco


import json  # noqa: E402  (used by several probes below)


def fresh_recorder():
    policy = records_policy()
    run = make_run(policy.snapshot(), {"world": "behavior-review-fixes"})
    return policy, run, Recorder(run, policy)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def lifecycle_fixture(adapters=None, **kwargs):
    policy = Policy(reference="review-fixes", origins=["https://lab.example/"],
                    tools=[Tool(tool_id="writer", activity="active"),
                           Tool(tool_id="reader", activity="passive")],
                    max_actions=20, max_model_calls=4)
    run = make_run(policy.snapshot(), {"world": "review-fixes"})
    recorder = Recorder(run, policy)
    budgets = kwargs.pop("budgets", None) or Budgets(
        actions=10, model_calls=4, wall_seconds=600, cost=50)
    adapters = adapters or {
        "writer": lambda url: {"status": 200, "body": f"WROTE {url}"},
        "reader": lambda url: {"status": 200, "body": f"READ {url}"},
    }
    lifecycle = Lifecycle(recorder, adapters, budgets, clock=FakeClock(),
                          **kwargs)
    return policy, run, recorder, lifecycle


# --- M1: unauthorized action identities cannot carry evidence -----------------

@chapter_claim(
    "handbook/course/02-policy-and-records.md",
    "A capture or outcome naming an action this run never authorized is "
    "refused at the door.",
)
def test_forged_evidence_for_an_unauthorized_action_is_refused():
    policy, run, recorder = fresh_recorder()
    forged_capture = recorder.record("capture", {
        "run_id": run.run_id,
        "action_id": "shell -> https://evil.example:443/pwn",
        "status": 200, "body": "SECRET marker text for forging"})
    assert forged_capture["recorded"] is False
    assert "never authorized" in forged_capture["reason"]
    ghost_outcome = recorder.record("outcome", {
        "run_id": run.run_id,
        "action_id": "ghost -> https://nowhere.example:443/",
        "status": "clean", "detail": "never authorized"})
    assert ghost_outcome["recorded"] is False
    assert "never authorized" in ghost_outcome["reason"]
    snapshot = recorder.snapshot()
    assert snapshot["captures"] == {} and snapshot["outcomes"] == {}
    refusals = [e for e in snapshot["events"] if e["event"] == "refused"]
    assert len(refusals) == 2


# --- M2: one act, one identity ------------------------------------------------

@chapter_claim(
    "handbook/course/02-policy-and-records.md",
    "One act has one identity: alias spellings of a destination collapse at "
    "the door before anything is recorded.",
)
def test_alias_destinations_collapse_to_one_identity():
    policy, run, recorder = fresh_recorder()
    aliases = ["https://lab.example/login",
               "https://lab.example:443/login",
               "HTTPS://LAB.EXAMPLE./login",
               "https://lab.example/a/../login"]
    ids = set()
    for alias in aliases:
        admitted = recorder.record("action", {
            "run_id": run.run_id, "tool": "inspect_headers",
            "destination": alias})
        assert admitted["recorded"] is True
        ids.add(admitted["action_id"])
    assert len(ids) == 1, sorted(ids)
    action_id = ids.pop()
    first = recorder.record("outcome", {
        "run_id": run.run_id, "action_id": action_id, "status": "clean",
        "detail": "first terminal outcome"})
    assert first["recorded"] is True
    for alias in aliases[1:]:
        second = recorder.record("action", {
            "run_id": run.run_id, "tool": "inspect_headers",
            "destination": alias})
        settled = recorder.record("outcome", {
            "run_id": run.run_id, "action_id": second["action_id"],
            "status": "tool_error", "detail": "settle-once bypass attempt"})
        assert settled["recorded"] is False


@chapter_claim(
    "handbook/course/05-candidates-and-dispatch.md",
    "An alias spelling of a settled destination cannot re-run the side effect.",
)
def test_the_duplicate_guard_holds_across_alias_spellings():
    policy, run, recorder = fresh_recorder()
    calls = {"n": 0}

    def counting_adapter(url):
        calls["n"] += 1
        return {"status": 200, "body": f"counted {url}"}

    dispatcher = Dispatcher(recorder, policy,
                            {"inspect_headers": counting_adapter})
    first = dispatcher.dispatch("inspect_headers", "https://lab.example/x")
    assert first["status"] == "clean"
    for alias in ("https://lab.example:443/x", "HTTPS://LAB.EXAMPLE./x",
                  "https://lab.example/a/../x"):
        again = dispatcher.dispatch("inspect_headers", alias)
        assert again["status"] == "refused", alias
        assert "already has a recorded outcome" in again["reason"]
    assert calls["n"] == 1, "an alias spelling re-ran the adapter"


# --- M3: resume verifies the policy -------------------------------------------

@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "Resume refuses a policy that is not the one the run was authorized under.",
)
def test_resume_refuses_a_swapped_policy():
    policy, run, recorder, lifecycle = lifecycle_fixture()
    lifecycle.execute_with_retries("reader", "https://lab.example/")
    checkpoint = lifecycle.checkpoint()
    wider = Policy(reference="totally-different-authorization",
                   origins=["https://lab.example/", "https://evil.example/"],
                   tools=[Tool(tool_id="writer", activity="active"),
                          Tool(tool_id="reader", activity="passive"),
                          Tool(tool_id="exfil", activity="active")],
                   max_actions=99, max_model_calls=99)
    with pytest.raises(ValueError) as caught:
        Lifecycle.resume(checkpoint, wider, {}, clock=FakeClock())
    assert "misattribute" in str(caught.value)


# --- M4: checkpoints are tamper-evident, and the fold refuses invented success -

@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "Checkpoints carry a tamper-evident digest, verified before any state is "
    "folded.",
)
def test_a_tampered_checkpoint_is_refused_by_its_digest():
    policy, run, recorder, lifecycle = lifecycle_fixture()
    lifecycle.execute_with_retries("reader", "https://lab.example/")
    checkpoint = lifecycle.checkpoint()
    tampered = copy.deepcopy(checkpoint)
    tampered["budgets"]["limits"] = {k: 10 ** 9
                                     for k in tampered["budgets"]["limits"]}
    with pytest.raises(ValueError) as caught:
        Lifecycle.resume(tampered, policy,
                         {"reader": lambda url: {"status": 200, "body": "x"}},
                         clock=FakeClock())
    assert "digest" in str(caught.value)


@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "An evidence-bearing outcome with no capture in the checkpoint resumes as "
    "unresolved, with the refusal recorded.",
)
def test_a_fabricated_clean_outcome_resumes_unresolved():
    policy, run, recorder, lifecycle = lifecycle_fixture()
    ghost = recorder.record("action", {
        "run_id": run.run_id, "tool": "writer",
        "destination": "https://lab.example/ghost"})
    checkpoint = lifecycle.checkpoint()
    body = {k: v for k, v in checkpoint.items() if k != "digest"}
    body["recorder"]["outcomes"][ghost["action_id"]] = {
        "action_id": ghost["action_id"], "status": "clean",
        "detail": "FABRICATED success"}
    # Recompute the digest so the replay guard, not the tamper evidence, is
    # what this test isolates.
    forged = {**body, "digest": digest(body)}
    resumed = Lifecycle.resume(forged, policy,
                               {"writer": lambda url: {"status": 200, "body": "w"},
                                "reader": lambda url: {"status": 200, "body": "r"}},
                               clock=FakeClock())
    snapshot = resumed.recorder.snapshot()
    assert snapshot["outcomes"][ghost["action_id"]]["status"] == "unresolved"
    refusals = [e["reason"] for e in snapshot["events"]
                if e["event"] == "refused"]
    assert any("no capture" in r for r in refusals)
    finished = resumed.finish()
    assert finished["completed"] is True
    assert snapshot["outcomes"][ghost["action_id"]]["status"] != "clean"


# --- M5: provider bytes cannot crash the session -------------------------------

@chapter_claim(
    "handbook/course/04-model-proposals.md",
    "A well-formed reply carrying the wrong types inside is one more malformed "
    "attempt, never a crash.",
)
def test_unhashable_evidence_is_a_malformed_attempt_not_a_crash():
    policy = records_policy()
    bad = dict(json.loads(VALID))
    bad["evidence"] = [{"ref": "x"}]
    session = ProviderSession(FakeProvider([json.dumps(bad), VALID]))
    report = session.propose(CONTEXT, observations=OBSERVATIONS, policy=policy)
    assert report["attempts"][0]["status"] == "malformed"
    assert "observation field names" in report["attempts"][0]["reason"]
    assert report["admitted"] is True  # the repair round got the valid reply


# --- m1: unoffered candidates are refused, not crashed --------------------------

@chapter_claim(
    "handbook/course/05-candidates-and-dispatch.md",
    "A decision naming a candidate that was not offered is refused and "
    "recorded, not dispatched.",
)
def test_an_unoffered_candidate_decision_is_refused():
    policy, run, recorder = fresh_recorder()
    dispatcher = Dispatcher(recorder, policy, {})

    class InventingController:
        name = "inventor"

        def select(self, state, candidates, shadow=False):
            return Decision(
                decision_id=decision_id(state.run_id, state.step, "ghost",
                                        self.name),
                candidate_id="ghost -> https://evil.example:443/",
                family="fam-x", scores={}, selected_features=[],
                controller=self.name)

    offered = [Candidate(candidate_id="inspect_headers -> https://lab.example:443/",
                         family="fam-recon",
                         features={"tool": "inspect_headers",
                                   "destination": "https://lab.example/"})]
    state = State(run_id=run.run_id, step=0, features={
        "bias": 1.0, "stage_progress": 0.0, "surface_known": 1.0,
        "recent_error_rate": 0.0, "budget_remaining": 1.0})
    result = dispatcher.select_and_run(InventingController(), state, offered)
    assert result["status"] == "refused"
    assert "not offered" in result["reason"]
    snapshot = recorder.snapshot()
    assert snapshot["captures"] == {} and snapshot["outcomes"] == {}
    assert any(e["event"] == "refused" and "not offered" in e["reason"]
               for e in snapshot["events"])


@chapter_claim(
    "handbook/course/10-controller-laboratory.md",
    "The laboratory raises loudly, naming the controller, when a decision "
    "names a candidate the world never offered.",
)
def test_a_rogue_lab_controller_raises_naming_itself():
    world = make_world("steady-families")

    class Rogue:
        name = "rogue"

        def select(self, state, candidates, shadow=False):
            return Decision(decision_id="x", candidate_id="not-offered",
                            family="fam-x", scores={}, selected_features=[],
                            controller=self.name)

        def observe(self, outcome):
            return {"applied": False}

    with pytest.raises(ValueError) as caught:
        run_episode(Rogue(), world)
    assert "rogue" in str(caught.value)


# --- m2: sanitizer and lane-error flag ------------------------------------------

@chapter_claim(
    "handbook/course/06-retrieval-and-memory.md",
    "The sanitizer lowercases the query, so FTS5's bare-word operators become "
    "ordinary search words.",
)
def test_bare_word_operators_are_neutralized():
    assert sanitize_query("alpha OR bravo") == "alpha or bravo"
    assert sanitize_query("zzz AND NOT bravo") == "zzz and not bravo"


@chapter_claim(
    "handbook/course/06-retrieval-and-memory.md",
    "A failed keyword lane is flagged in the trace as keyword_lane_error, "
    "distinct from a lane that simply matched nothing.",
)
def test_a_failed_keyword_lane_is_flagged_in_the_trace():
    store = MemoryStore()
    search = HybridSearch(store)
    _, empty_trace = search.search("nothing indexed matches this")
    assert empty_trace["keyword_lane_error"] is None
    store.connection.execute("DROP TABLE memory_fts")
    _, failed_trace = search.search("anything")
    assert failed_trace["keyword_lane_error"] is not None
    assert "OperationalError" in failed_trace["keyword_lane_error"]


# --- m3: refuted tactics decline new successes ----------------------------------

@chapter_claim(
    "handbook/course/06-retrieval-and-memory.md",
    "A refuted tactic declines new successes loudly instead of silently "
    "rehabilitating.",
)
def test_record_success_on_a_refuted_tactic_is_declined():
    store = MemoryStore()
    keys = dict(profile_hash="php:apache:mysql", tool="sqlmap",
                endpoint="https://a.example/api/orders", param="id")
    record_id = store.record_success(**keys, engagement="eng-a", now=1.0)
    assert isinstance(record_id, str)
    assert store.record_refuted(**keys) is True
    from core.memory.records import tactic_signature
    signature = tactic_signature(keys["profile_hash"], keys["tool"],
                                 keys["endpoint"], keys["param"])
    refuted_row = store.get_by_signature(signature)
    before = (refuted_row["metadata"], refuted_row["confidence"])
    with pytest.raises(MemoryStoreError) as caught:
        store.record_success(**keys, engagement="eng-a",
                             proof="PROOF TEXT", now=2.0)
    assert "refuted" in str(caught.value)
    after_row = store.get_by_signature(signature)
    assert (after_row["metadata"], after_row["confidence"]) == before


# --- m4: the wall budget survives resume ----------------------------------------

@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "The wall-clock budget survives a checkpoint and resume; a restart does "
    "not hand time back.",
)
def test_the_wall_budget_survives_resume():
    budgets = Budgets(actions=50, model_calls=4, wall_seconds=100, cost=500)
    budgets.used["wall_seconds"] = 99.5
    policy, run, recorder, lifecycle = lifecycle_fixture(budgets=budgets)
    checkpoint = lifecycle.checkpoint()
    resumed = Lifecycle.resume(checkpoint, policy,
                               {"reader": lambda url: {"status": 200, "body": "r"}},
                               clock=FakeClock())
    resumed.clock.now = 1.0
    assert resumed._blocked() is not None
    assert "wall_seconds" in resumed._blocked()


# --- m5: decision identity includes the controller -------------------------------

@chapter_claim(
    "handbook/course/10-controller-laboratory.md",
    "The decision identity includes the controller, so a comparison cannot "
    "misdeliver credit between controllers.",
)
def test_two_controllers_never_share_a_decision_id():
    offered = [Candidate(candidate_id="probe:a", family="fam-a", priority=1.0)]
    state = State(run_id="run-a", step=0,
                  features={"bias": 1.0, "signal": 0.0},
                  schema_version="toy-v1")
    first = make_controller("priority").select(state, offered)
    second = make_controller("legacy", learn=True)
    second_decision = second.select(state, offered)
    assert first.candidate_id == second_decision.candidate_id
    assert first.decision_id != second_decision.decision_id
    misdelivered = second.observe(Outcome(
        decision_id=first.decision_id, candidate_id=first.candidate_id,
        run_id="run-a", status="clean", feedback=1.0))
    assert misdelivered["applied"] is False
    assert misdelivered["reason"] == "unknown or shadow decision"


# --- m6b: a refused capture surfaces the recorder's reason ------------------------

@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "A refused capture surfaces the recorder's reason.",
)
def test_a_malformed_capture_surfaces_the_recorded_reason():
    policy, run, recorder, lifecycle = lifecycle_fixture(
        adapters={"reader": lambda url: {"status": "200", "body": "text"}})
    result = lifecycle.execute_with_retries("reader", "https://lab.example/")
    assert result["status"] == "tool_error"
    assert result["error_type"] == "ValueError"
    snapshot = recorder.snapshot()
    assert any(e["event"] == "refused" and e["kind"] == "capture"
               for e in snapshot["events"])


# --- m7: habituation snapshots are loud about unroundtrippable keys ---------------

@chapter_claim(
    "handbook/course/12-mushroom-body-controller.md",
    "A habituation key that cannot round-trip the snapshot is refused loudly "
    "instead of silently dropped.",
)
def test_a_separator_bearing_habituation_key_is_loud():
    habituation = Habituation()
    habituation.observe("page:d0:nq", "fam||evil", "error")
    with pytest.raises(ValueError):
        habituation.to_dict()
    with pytest.raises(ValueError):
        Habituation.from_dict({"only||two": 1.0})


# --- m8: the pipeline governs only what the recorder holds ------------------------

@chapter_claim(
    "handbook/course/08-evidence-and-verification.md",
    "The pipeline governs only findings this run's recorder holds.",
)
def test_govern_refuses_a_finding_the_recorder_does_not_hold():
    policy, run, recorder = fresh_recorder()
    pipeline = VerificationPipeline(recorder)
    foreign = Finding(finding_id="f" * 16, run_id=run.run_id,
                      capture_id="c" * 16, kind="idor", title="Foreign",
                      severity="critical",
                      quote="a quote long enough to self-grade moderate, "
                            "were the pipeline to allow it")
    report = pipeline.govern(foreign)
    assert report["applied"] is False
    assert "not held" in report["reason"]
    assert pipeline.governed("f" * 16) is None


# --- n1: resume replays each authorized action once --------------------------------

@chapter_claim(
    "handbook/course/09-stop-recover-finish.md",
    "Resume replays each authorized action once.",
)
def test_resume_does_not_duplicate_authorization_events():
    policy, run, recorder, lifecycle = lifecycle_fixture()
    lifecycle.execute_with_retries("reader", "https://lab.example/a")
    lifecycle.execute_with_retries("reader", "https://lab.example/b")
    checkpoint = lifecycle.checkpoint()
    resumed = Lifecycle.resume(checkpoint, policy,
                               {"reader": lambda url: {"status": 200, "body": "r"}},
                               clock=FakeClock())
    events = resumed.recorder.snapshot()["events"]
    authorized = [e["action_id"] for e in events
                  if e["event"] == "action_authorized"]
    assert len(authorized) == len(set(authorized))


# --- recheck round: R1-R7 -----------------------------------------------------------

@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "A controller decision naming an unoffered candidate is refused and "
    "recorded inside the assembled run too, never crashed on.",
)
def test_the_assembled_run_refuses_an_unoffered_candidate_decision():
    from core.controller.contract import Controller, stable_best
    from core.run.app import Application
    from core.run.demo_app import build_config, WORLD

    class Rogue(Controller):
        name = "priority"

        def _choose(self, state, candidates):
            chosen = stable_best(candidates, score_of=lambda c: c.priority,
                                 tiebreak_of=lambda c: c.candidate_id)
            forged = type(chosen)(candidate_id="ghost -> https://lab.example:443/x",
                                  family=chosen.family, features=chosen.features,
                                  priority=chosen.priority)
            return forged, {"rule": "rogue"}

    app = Application(build_config())
    app.controller = Rogue()
    report = app.run(WORLD)
    events = app.recorder.snapshot()["events"]
    refusals = [e for e in events
                if e["event"] == "refused" and "not offered" in e["reason"]]
    assert refusals, "the rogue decision left no recorded refusal"
    assert report["finish"]["completed"] is True, "the run stalled on bad advice"


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "A finding rule carrying an unknown severity is refused at configuration "
    "time, before any run could silently produce zero findings.",
)
def test_an_unknown_finding_rule_severity_is_refused_at_config_time():
    from core.run.app import AppConfigError, validate_config
    from core.run.demo_app import build_config
    config = build_config()
    config["finding_rules"][0]["severity"] = "apocalyptic"
    try:
        validate_config(config)
    except AppConfigError as exc:
        assert "apocalyptic" in str(exc)
    else:
        raise AssertionError("unknown severity passed config validation")


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "Retrieval records are validated at configuration time, not discovered "
    "broken mid-run.",
)
def test_a_malformed_retrieval_record_is_refused_at_config_time():
    from core.run.app import AppConfigError, validate_config
    from core.run.demo_app import build_config
    config = build_config()
    config["retrieval"] = {"enabled": True, "records": ["not-an-object"],
                           "scope": {"engagement": "lab"}}
    try:
        validate_config(config)
    except AppConfigError as exc:
        assert "content" in str(exc)
    else:
        raise AssertionError("malformed retrieval record passed validation")


@chapter_claim(
    "handbook/course/15-comparisons-and-interpretation.md",
    "Every raw condition file carries a digest over its own body, and "
    "analysis refuses a file edited after the run.",
)
def test_an_edited_raw_result_is_refused_by_its_body_digest(tmp_path):
    import json
    from core.controller.research import analyze, freeze, run_all
    manifest = freeze()
    run_all(manifest, tmp_path)
    victim = sorted(tmp_path.glob("*.json"))[0]
    raw = json.loads(victim.read_text(encoding="utf-8"))
    raw["total_reward"] = 9999.0
    victim.write_text(json.dumps(raw), encoding="utf-8")
    try:
        analyze(manifest, tmp_path)
    except ValueError as exc:
        assert "body digest" in str(exc)
    else:
        raise AssertionError("an edited raw result analyzed silently")


@chapter_claim(
    "handbook/course/04-model-proposals.md",
    "A reply whose text cannot even be encoded is a malformed attempt with a "
    "repair round, not a provider failure.",
)
def test_an_unencodable_reply_is_a_repairable_malformed_attempt():
    from core.run.demo_proposals import CONTEXT, OBSERVATIONS, VALID
    from core.run.demo_records import build_policy
    from core.run.proposals import FakeProvider, ProviderSession
    session = ProviderSession(FakeProvider(["\ud800garbage", VALID]),
                              max_attempts=2)
    report = session.propose(CONTEXT, observations=OBSERVATIONS,
                             policy=build_policy())
    assert report["attempts"][0]["status"] == "malformed"
    assert report["admitted"] is True, report


@chapter_claim(
    "handbook/course/06-retrieval-and-memory.md",
    "A search never inherits an earlier search's lane-error flag.",
)
def test_a_search_does_not_inherit_a_stale_lane_error():
    from core.memory.search import HybridSearch
    from core.memory.store import MemoryStore
    store = MemoryStore()
    search = HybridSearch(store)
    store.connection.execute("ALTER TABLE memory_fts RENAME TO memory_fts_off")
    _, failed = search.search("anything")
    assert failed["keyword_lane_error"] is not None
    store.connection.execute("ALTER TABLE memory_fts_off RENAME TO memory_fts")
    _, healthy = search.search("anything")
    assert healthy["keyword_lane_error"] is None


@chapter_claim(
    "handbook/course/02-policy-and-records.md",
    "One act has one identity: alias spellings of a destination collapse at "
    "the door before anything is recorded.",
)
def test_a_leading_double_slash_is_not_a_second_identity():
    from core.run.policy import normalize_destination
    assert (normalize_destination("https://lab.example//x")
            == normalize_destination("https://lab.example/x"))
