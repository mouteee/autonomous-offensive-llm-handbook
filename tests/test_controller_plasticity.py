"""Plasticity, delayed credit and the prior bank, held against their lesson."""

import pytest

from core.controller import make_controller
from core.controller.contract import Candidate, Outcome, State
from core.controller.plasticity import (
    Eligibility, LearnedWeights, PlasticMbController)
from core.controller.priors import (
    DIGESTED, HEX_ONLY, PriorBank, descriptor_key)


def chapter_claim(chapter, *sentences):
    """Anchor a test to the verbatim lesson sentence(s) it backs.

    Same declaration shape as tests/test_chapter_claims.py: verify_claims.sh's
    Check C parses these decorators and fails when a declared sentence is no
    longer present in its chapter.
    """
    def deco(fn):
        return fn
    return deco





def full_state(step=0):
    return State(run_id="pl-test", step=step, features={
        "bias": 1.0, "stage_progress": 0.5, "surface_known": 1.0,
        "recent_error_rate": 0.0, "budget_remaining": 0.5})


def candidate(family):
    return Candidate(candidate_id=f"{family}:probe", family=family, priority=1.0,
                     features={"url": f"https://lab.example/{family}"})


def rewarded(controller, decision, feedback=1.0):
    return controller.observe(Outcome(
        decision_id=decision.decision_id, candidate_id=decision.candidate_id,
        run_id="pl-test", status="verified_evidence", feedback=feedback))


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md", "The lesson's toy update produces exactly the lesson's number.")
def test_the_toy_update_produces_the_lessons_number():
    weights = LearnedWeights(eta=0.05, w_max=1.0)
    weights._w[(1, "fam-a")] = 0.1
    weights.update({(1, "fam-a"): 0.8}, 0.6)
    assert weights.weights()[(1, "fam-a")] == pytest.approx(0.124)


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md", "A frozen instance lays no traces and changes no weights, "
                    "while its habituation still updates.")
def test_a_frozen_instance_learns_nothing_but_still_habituates():
    controller = PlasticMbController(seed=3, learn=False)
    for step in range(4):
        decision = controller.select(full_state(step), [candidate("fam-a")])
        controller.observe(Outcome(
            decision_id=decision.decision_id, candidate_id=decision.candidate_id,
            run_id="pl-test", status="tool_error", feedback=1.0))
    assert controller._elig.traces() == {}
    assert controller._weights.total_change() == 0.0
    assert controller.snapshot()["habituation"] != {}


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md", "Only traced pairs move, and every update is clipped to "
                    "the bound.")
def test_only_traced_pairs_move_and_updates_clip():
    weights = LearnedWeights(eta=0.5, w_max=1.0)
    weights._w[(9, "fam-b")] = 0.25
    report = weights.update({(1, "fam-a"): 10.0}, 1.0)
    assert report["updated"] == 1
    assert report["clipped"] == 1
    assert weights.weights()[(1, "fam-a")] == 1.0
    assert weights.weights()[(9, "fam-b")] == 0.25


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md", "Delayed credit lands on the decision the outcome names, "
                    "and also brushes every trace still alive.")
def test_delayed_credit_lands_and_brushes_live_traces():
    controller = PlasticMbController(seed=3, learn=True)
    first = controller.select(full_state(0), [candidate("fam-a")])
    second = controller.select(full_state(1), [candidate("fam-b")])
    rewarded(controller, second)
    z = controller._last_z
    before_a = controller._weights.w_dot(z, "fam-a")
    before_b = controller._weights.w_dot(z, "fam-b")
    report = rewarded(controller, first)
    assert report["applied"] is True
    assert controller._weights.w_dot(z, "fam-a") > before_a
    # The older decision's late reward also moved the newer family's fresh
    # traces: the crosstalk the lesson demonstrates rather than hides.
    assert controller._weights.w_dot(z, "fam-b") > before_b


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md", "Stale traces buy a smaller update, and fresher traces "
                    "capture most of a late reward.")
def test_stale_traces_buy_less_and_fresh_traces_capture_more():
    controller = PlasticMbController(seed=3, learn=True)
    immediate = controller.select(full_state(0), [candidate("fam-a")])
    z = controller._last_z
    rewarded(controller, immediate)
    immediate_gain = controller._weights.w_dot(z, "fam-a")

    stale = PlasticMbController(seed=3, learn=True)
    old = stale.select(full_state(0), [candidate("fam-a")])
    for step in range(1, 5):
        skipped = stale.select(full_state(step), [candidate("fam-b")])
        rewarded(stale, skipped, feedback=0.0)
    before_b = stale._weights.w_dot(z, "fam-b")
    rewarded(stale, old)
    stale_gain = stale._weights.w_dot(z, "fam-a")
    fresh_gain = stale._weights.w_dot(z, "fam-b") - before_b
    assert stale_gain < immediate_gain
    assert fresh_gain > stale_gain


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md", "Saturated weights stop moving, and the ledger records "
                    "the clipping.")
def test_saturated_weights_stop_moving():
    controller = PlasticMbController(seed=3, learn=True)
    last = None
    for step in range(8):
        decision = controller.select(full_state(step), [candidate("fam-b")])
        last = rewarded(controller, decision, feedback=5.0)
    assert last["clipped"] > 0
    assert last["total_abs_delta"] == 0.0


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md", "Exploration credit follows the family that actually ran.")
def test_exploration_credit_follows_the_executed_family():
    controller = PlasticMbController(seed=3, learn=True)
    decision = controller.select(full_state(0), [candidate("fam-b")])
    rewarded(controller, decision)
    z = controller._last_z
    assert controller._weights.w_dot(z, "fam-b") > 0.0
    assert controller._weights.w_dot(z, "fam-a") == 0.0


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md", "Snapshot and restore round-trip traces and weights exactly.")
def test_snapshot_round_trips_traces_and_weights():
    controller = PlasticMbController(seed=3, learn=True)
    decision = controller.select(full_state(0), [candidate("fam-a")])
    rewarded(controller, decision)
    saved = controller.snapshot()
    twin = make_controller("mb-plastic", learn=True)
    twin.restore(saved)
    assert twin.snapshot() == saved
    assert twin._weights.weights() == controller._weights.weights()


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md", "Eligibility decays on every select and prunes to nothing.")
def test_eligibility_decays_and_prunes():
    elig = Eligibility()
    elig.on_select((1, 2), "fam-a")
    first = elig.traces()[(1, "fam-a")]
    for _ in range(40):
        elig.on_select((), "fam-b")
    assert (1, "fam-a") not in elig.traces()
    assert first == 1.0


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md", "The historical fold gate rejected the producer's own key "
                    "format and folded nothing.")
def test_the_historical_fold_gate_folds_nothing():
    bank = PriorBank(key_rule=HEX_ONLY)
    key = descriptor_key({"backend": "php", "database": "mysql", "waf": "none"})
    report = bank.fold_episode(key, {"fam-a": {"mean_modulation": 0.5}})
    assert report["folded"] == 0
    assert report["stored_key"] is None
    assert bank.load(key) == {}


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md", "The corrected rule canonicalizes any nonempty descriptor "
                    "and the fold lands.")
def test_the_corrected_fold_rule_lands():
    bank = PriorBank(key_rule=DIGESTED)
    key = descriptor_key({"backend": "php", "database": "mysql", "waf": "none"})
    report = bank.fold_episode(key, {
        "fam-a": {"episodes": 1, "mean_modulation": 0.5,
                  "signatures": {"hit": 2}}})
    assert report["folded"] == 1
    loaded = bank.load(key)
    assert loaded["fam-a"]["episodes"] == 1
    assert loaded["fam-a"]["mean_modulation"] == pytest.approx(0.5)
    # A second episode folds into a running mean, not a replacement.
    bank.fold_episode(key, {"fam-a": {"episodes": 1, "mean_modulation": 0.1,
                                      "signatures": {"error": 1}}})
    again = bank.load(key)
    assert again["fam-a"]["episodes"] == 2
    assert again["fam-a"]["mean_modulation"] == pytest.approx(0.3)
    assert again["fam-a"]["signatures"] == {"hit": 2, "error": 1}


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md", "Episode weights and cross-run priors are separate stores "
                    "with separate versions.")
def test_episode_weights_and_priors_are_separate_stores():
    controller = PlasticMbController(seed=3, learn=True)
    decision = controller.select(full_state(0), [candidate("fam-a")])
    rewarded(controller, decision)
    bank = PriorBank()
    key = descriptor_key({"backend": "php"})
    bank.fold_episode(key, {"fam-a": {"mean_modulation": 0.4}})
    # The bank stores aggregates under its own version; the controller's
    # snapshot carries per-synapse weights and no bank content.
    assert bank._bank[bank._storage_key(key)]["version"] == "priors-v1"
    snapshot = controller.snapshot()
    assert "weights" in snapshot and "eligibility" in snapshot
    assert "priors" not in snapshot
    bonus = bank.prior_bonus(key, "fam-a")
    assert 0.0 < bonus <= 0.1


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md",
    "A shadow selection lays no eligibility trace: a later legitimate outcome "
    "cannot credit units only the shadow activated.",
)
def test_a_shadow_selection_lays_no_trace_and_earns_no_later_credit():
    controller = make_controller("mb-plastic", learn=True)
    shadow = controller.select(full_state(0), [candidate("shadow-only")],
                               shadow=True)
    assert shadow is not None and shadow.shadow is True
    assert not controller._elig.traces(), "a shadow selection laid a trace"

    real = controller.select(full_state(1), [candidate("executed")])
    report = rewarded(controller, real, feedback=1.0)
    assert report["applied"] is True

    snapshot = controller.snapshot()
    shadow_weights = {key: value for key, value in snapshot["weights"].items()
                      if key.endswith("|shadow-only") and value != 0}
    assert shadow_weights == {}, \
        "a later legitimate outcome credited shadow-only units"
    assert not any(key.endswith("|shadow-only")
                   for key in snapshot["eligibility"])
    assert any(key.endswith("|executed") and value != 0
               for key, value in snapshot["weights"].items()), \
        "the executed selection itself failed to learn"
    assert shadow.decision_id not in snapshot["pending"]


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md",
    "A shadow selection lays no eligibility trace: a later legitimate outcome "
    "cannot credit units only the shadow activated.",
)
def test_a_shadow_selection_does_not_decay_the_live_traces():
    controller = make_controller("mb-plastic", learn=True)
    controller.select(full_state(0), [candidate("executed")])
    before = controller._elig.traces()
    assert before, "the real selection laid no trace"
    controller.select(full_state(1), [candidate("shadow-only")], shadow=True)
    assert controller._elig.traces() == before, \
        "a shadow selection aged or changed the live traces"


def refused(controller, decision):
    # Deliver the host's not-executed outcome for this decision.
    return controller.observe(Outcome(
        decision_id=decision.decision_id, candidate_id=decision.candidate_id,
        run_id="pl-test", status="skipped", feedback=0.0, executed=False))


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md",
    "A real selection the host then refuses is unwound exactly: the deposit's "
    "keys and its decay-pass date ride the contract's pending record, and "
    "when the refusal arrives the controller subtracts what remains of that "
    "deposit, so a later outcome cannot credit units only a refused selection "
    "activated.",
)
def test_a_refused_selection_earns_no_later_credit():
    controller = make_controller("mb-plastic", learn=True)
    refused_pick = controller.select(full_state(0), [candidate("refused-fam")])
    report = refused(controller, refused_pick)
    assert report == {"applied": False, "reason": "decision was not executed"}
    assert not any(f == "refused-fam" for _, f in controller._elig.traces()), \
        "the refusal left the refused selection's trace alive"

    executed = controller.select(full_state(1), [candidate("executed-fam")])
    paid = rewarded(controller, executed, feedback=1.0)
    assert paid["applied"] is True
    leaked = {key: w for key, w in controller._weights.weights().items()
              if key[1] == "refused-fam" and w != 0}
    assert leaked == {}, \
        f"a later outcome credited the refused selection's units: {leaked}"
    assert any(f == "executed-fam" and w != 0
               for (_, f), w in controller._weights.weights().items())


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md",
    "A real selection the host then refuses is unwound exactly: the deposit's "
    "keys and its decay-pass date ride the contract's pending record, and "
    "when the refusal arrives the controller subtracts what remains of that "
    "deposit, so a later outcome cannot credit units only a refused selection "
    "activated.",
)
def test_a_prompt_refusal_from_empty_traces_matches_a_never_selected_twin():
    # The twin equality below needs its stated precondition: the refused
    # selection is the FIRST (no other live traces to decay). With traces
    # already live, the refused selection's decay pass on them stands --
    # that boundary is pinned by its own test further down.
    lived = make_controller("mb-plastic", learn=True)
    doomed = lived.select(full_state(0), [candidate("refused-fam")])
    refused(lived, doomed)
    lived.select(full_state(1), [candidate("kept-fam")])

    twin = make_controller("mb-plastic", learn=True)
    twin.select(full_state(1), [candidate("kept-fam")])

    ours, theirs = lived._elig.traces(), twin._elig.traces()
    assert set(ours) == set(theirs)
    assert all(abs(ours[key] - theirs[key]) < 1e-12 for key in ours), \
        "the unwind is not exact"


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md",
    "A real selection the host then refuses is unwound exactly: the deposit's "
    "keys and its decay-pass date ride the contract's pending record, and "
    "when the refusal arrives the controller subtracts what remains of that "
    "deposit, so a later outcome cannot credit units only a refused selection "
    "activated.",
)
def test_a_late_refusal_unwinds_the_decayed_residual():
    controller = make_controller("mb-plastic", learn=True)
    doomed = controller.select(full_state(0), [candidate("refused-fam")])
    controller.select(full_state(1), [candidate("kept-fam")])
    refused(controller, doomed)
    families = {f for _, f in controller._elig.traces()}
    assert "refused-fam" not in families, \
        "the decayed residual of the refused deposit survived the unwind"
    assert "kept-fam" in families


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md",
    "Report a refusal when it happens: credit an interleaved outcome already "
    "granted before a late refusal report is not clawed back.",
)
def test_credit_granted_before_a_late_refusal_stays_granted():
    controller = make_controller("mb-plastic", learn=True)
    doomed = controller.select(full_state(0), [candidate("refused-fam")])
    executed = controller.select(full_state(1), [candidate("kept-fam")])
    rewarded(controller, executed, feedback=1.0)
    brushed = {key: w for key, w in controller._weights.weights().items()
               if key[1] == "refused-fam" and w != 0}
    assert brushed, "the interleaved outcome never brushed the live trace"
    refused(controller, doomed)
    assert {key: w for key, w in controller._weights.weights().items()
            if key[1] == "refused-fam" and w != 0} == brushed, \
        "the late refusal clawed back granted credit"
    assert not any(f == "refused-fam" for _, f in controller._elig.traces())


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md",
    "A real selection the host then refuses is unwound exactly: the deposit's "
    "keys and its decay-pass date ride the contract's pending record, and "
    "when the refusal arrives the controller subtracts what remains of that "
    "deposit, so a later outcome cannot credit units only a refused selection "
    "activated.",
)
def test_the_unwind_survives_a_json_checkpoint_roundtrip():
    import json as _json
    controller = make_controller("mb-plastic", learn=True)
    doomed = controller.select(full_state(0), [candidate("refused-fam")])
    snapshot = _json.loads(_json.dumps(controller.snapshot()))

    resumed = make_controller("mb-plastic", learn=True)
    resumed.restore(snapshot)
    refused(resumed, doomed)
    assert not any(f == "refused-fam" for _, f in resumed._elig.traces()), \
        "the deposit annotation did not survive the checkpoint"


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md",
    "The rollback restores the refused deposit's share, not the world as it "
    "was, and its two edges are stated rather than hidden: the decay pass "
    "the refused selection applied to the other live traces is history and "
    "stays applied, and a remainder the subtraction leaves below the prune "
    "threshold is pruned exactly as decay would have pruned it.",
)
def test_the_refused_selections_decay_tick_on_other_traces_stands():
    # The private-main review's boundary case, pinned as behavior: a refusal
    # restores the refused deposit's share only; pre-existing traces keep the
    # decay tick the refused selection applied to them.
    controller = make_controller("mb-plastic", learn=True)
    controller.select(full_state(0), [candidate("kept-fam")])
    kept_before = {k: v for k, v in controller._elig.traces().items()
                   if k[1] == "kept-fam"}
    assert set(kept_before.values()) == {1.0}

    doomed = controller.select(full_state(1), [candidate("refused-fam")])
    refused(controller, doomed)

    kept_after = {k: v for k, v in controller._elig.traces().items()
                  if k[1] == "kept-fam"}
    assert set(kept_after) == set(kept_before)
    assert all(value == 0.8 for value in kept_after.values()), \
        "the refused selection's decay tick was rewound; only the deposit " \
        "may come back"
    assert not any(f == "refused-fam" for _, f in controller._elig.traces())


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md",
    "The rollback restores the refused deposit's share, not the world as it "
    "was, and its two edges are stated rather than hidden: the decay pass "
    "the refused selection applied to the other live traces is history and "
    "stays applied, and a remainder the subtraction leaves below the prune "
    "threshold is pruned exactly as decay would have pruned it.",
)
def test_the_unwind_remainder_follows_the_prune_rule():
    # Directly on the trace store. An old deposit rides the same key as a
    # later refused deposit. When the unwind's subtraction leaves the old
    # residual above the prune threshold, it survives to within float error
    # of its true decayed value; when it leaves it below, the key is pruned
    # exactly as the next decay pass would have pruned it.
    surviving = Eligibility()
    surviving.on_select((1,), "f")
    for _ in range(27):
        surviving.on_select((), "")
    surviving.on_select((1,), "f")           # the deposit later refused
    marker = surviving.marker()
    for _ in range(2):
        surviving.on_select((), "")
    surviving.unwind([(1, "f")], marker)
    remainder = surviving.traces()[(1, "f")]
    true_residual = 1.0
    for _ in range(30):
        true_residual *= 0.8
    assert abs(remainder - true_residual) < 1e-12

    pruned = Eligibility()
    pruned.on_select((1,), "f")
    for _ in range(29):
        pruned.on_select((), "")
    pruned.on_select((1,), "f")
    marker = pruned.marker()
    for _ in range(3):
        pruned.on_select((), "")
    pruned.unwind([(1, "f")], marker)
    assert (1, "f") not in pruned.traces(), \
        "a sub-threshold remainder must prune as decay would"


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md",
    "A deposit whose share was already pruned away subtracts nothing later: "
    "each key remembers the decay pass that created it, so a late refusal of "
    "a dead deposit leaves a successor deposit's fresh value untouched.",
)
def test_a_dead_deposits_late_refusal_takes_nothing_from_a_successor():
    # The ae1c999 review's tracked limitation, first at the trace store: on
    # that commit this sequence left the fresh deposit at 1.0 minus the dead
    # deposit's computed residual instead of exactly 1.0.
    elig = Eligibility()
    elig.on_select((1,), "f")
    dead_marker = elig.marker()
    while (1, "f") in elig.traces():
        elig.on_select((), "")          # decay until the share prunes away
    elig.on_select((1,), "f")           # a successor recreates the key
    elig.unwind([(1, "f")], dead_marker)
    assert elig.traces()[(1, "f")] == 1.0, \
        "a dead deposit's late refusal was subtracted from its successor"


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md",
    "A deposit whose share was already pruned away subtracts nothing later: "
    "each key remembers the decay pass that created it, so a late refusal of "
    "a dead deposit leaves a successor deposit's fresh value untouched.",
)
def test_the_dead_deposit_rule_holds_at_the_controller():
    # The same sequence through the controller contract: select, let the
    # trace decay to pruning under other work, reselect the same family
    # (same state features, so the same expansion units and keys), then
    # deliver the FIRST decision's refusal late.
    controller = make_controller("mb-plastic", learn=True)
    doomed = controller.select(full_state(0), [candidate("fam-a")])
    step = 1
    while any(f == "fam-a" for _, f in controller._elig.traces()):
        controller.select(full_state(step), [candidate("fam-b")])
        step += 1
    fresh = controller.select(full_state(step), [candidate("fam-a")])
    fresh_traces = {k: v for k, v in controller._elig.traces().items()
                    if k[1] == "fam-a"}
    assert set(fresh_traces.values()) == {1.0}
    refused(controller, doomed)
    after = {k: v for k, v in controller._elig.traces().items()
             if k[1] == "fam-a"}
    assert after == fresh_traces, \
        "the dead first selection's refusal changed the fresh deposit"
    # And the fresh selection can still be unwound exactly if IT is refused.
    refused(controller, fresh)
    assert not any(f == "fam-a" for _, f in controller._elig.traces())


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md",
    "A deposit whose share was already pruned away subtracts nothing later: "
    "each key remembers the decay pass that created it, so a late refusal of "
    "a dead deposit leaves a successor deposit's fresh value untouched.",
)
def test_key_births_survive_a_json_checkpoint_roundtrip():
    import json as _json
    controller = make_controller("mb-plastic", learn=True)
    doomed = controller.select(full_state(0), [candidate("fam-a")])
    step = 1
    while any(f == "fam-a" for _, f in controller._elig.traces()):
        controller.select(full_state(step), [candidate("fam-b")])
        step += 1
    controller.select(full_state(step), [candidate("fam-a")])

    snapshot = _json.loads(_json.dumps(controller.snapshot()))
    resumed = make_controller("mb-plastic", learn=True)
    resumed.restore(snapshot)
    fresh = {k: v for k, v in resumed._elig.traces().items()
             if k[1] == "fam-a"}
    refused(resumed, doomed)
    assert {k: v for k, v in resumed._elig.traces().items()
            if k[1] == "fam-a"} == fresh, \
        "the key births did not survive the checkpoint"


def _dead_deposit_snapshot():
    """A learn-on controller holding a fresh deposit over a dead one."""
    controller = make_controller("mb-plastic", learn=True)
    doomed = controller.select(full_state(0), [candidate("fam-a")])
    step = 1
    while any(f == "fam-a" for _, f in controller._elig.traces()):
        controller.select(full_state(step), [candidate("fam-b")])
        step += 1
    controller.select(full_state(step), [candidate("fam-a")])
    return controller, doomed


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md",
    "A snapshot from before the key-birth bookkeeping degrades boundedly "
    "instead: births restore unknown, and what a dead deposit can then "
    "wrongly subtract again stays below the prune threshold.",
)
def test_an_old_snapshot_without_births_degrades_boundedly():
    # The adversarial review's finding: a snapshot from before the birth
    # bookkeeping restores with unknown births, and a dead deposit's late
    # refusal then subtracts its residual from the successor again. Pinned:
    # the reintroduced residue is exactly the dead deposit's decayed value,
    # and that value sits below the prune threshold by construction (a
    # residual at or above it would mean the key was never pruned).
    import json as _json
    controller, doomed = _dead_deposit_snapshot()
    snapshot = _json.loads(_json.dumps(controller.snapshot()))
    del snapshot["eligibility_born"]

    resumed = make_controller("mb-plastic", learn=True)
    resumed.restore(snapshot)
    refused(resumed, doomed)
    values = [v for (u, f), v in resumed._elig.traces().items()
              if f == "fam-a"]
    assert values, "the fallback must not erase the successor deposit"
    residue = 1.0 - values[0]
    assert 0.0 < residue < Eligibility().prune_below, \
        "the old-snapshot fallback residue must stay below the prune " \
        f"threshold; got {residue}"


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md",
    "A restore refuses an internally inconsistent snapshot: a dated "
    "deposit note with no decay counter to date it against, or a note "
    "dated after the restored counter.",
)
def test_a_snapshot_with_deposit_notes_but_no_counter_is_refused():
    import json as _json
    from core.controller.contract import ContractError
    controller, _ = _dead_deposit_snapshot()
    snapshot = _json.loads(_json.dumps(controller.snapshot()))
    assert any(p.get("elig") for p in snapshot["pending"].values())
    del snapshot["eligibility_gen"]
    resumed = make_controller("mb-plastic", learn=True)
    with pytest.raises(ContractError):
        resumed.restore(snapshot)


@chapter_claim(
    "handbook/course/13-plasticity-and-credit.md",
    "A restore refuses an internally inconsistent snapshot: a dated "
    "deposit note with no decay counter to date it against, or a note "
    "dated after the restored counter.",
)
def test_a_deposit_dated_after_the_restored_counter_is_refused():
    import json as _json
    from core.controller.contract import ContractError
    controller, _ = _dead_deposit_snapshot()
    snapshot = _json.loads(_json.dumps(controller.snapshot()))
    snapshot["eligibility_gen"] = 0  # every stored note now postdates it
    resumed = make_controller("mb-plastic", learn=True)
    with pytest.raises(ContractError):
        resumed.restore(snapshot)
