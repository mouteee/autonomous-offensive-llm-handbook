"""The grounding gate, split by claim type — containment decides, the caller advises."""
import asyncio
import pytest
from core.critic import (
    GROUNDED_PHASES, score_grounded, critic_enabled, critic_threshold, Critic,
)

CONTEXT = "GET /api/v1/orders returned 200 with a JSON array of order objects."

# Distinctive absent tokens. A short ref like "/a" is a SUBSTRING of the context
# and grounds by accident -- that trap cost an earlier draft of this task.
ABSENT_REF, ABSENT_SNIP = "/zzz-nope", "qqq-absent"


def _ins(ref, snippet, **kw):
    d = {"evidence": {"source": "traffic", "ref": ref, "snippet": snippet}}
    d.update(kw)
    return d


def _only(res):
    """The single insight in a one-item result, whichever list it landed in."""
    items = res["kept"] + res["dropped"]
    assert len(items) == 1
    return items[0]


def test_the_result_is_a_dict_of_kept_dropped_and_scores():
    res = score_grounded([_ins("/api/v1/orders", "JSON array of order objects")], CONTEXT)
    assert set(res) == {"kept", "dropped", "scores"}
    assert res["scores"] == {0: 0.85}            # int index, not "0"
    assert all(isinstance(k, int) for k in res["scores"])


def test_containment_is_a_four_step_ladder():
    """Four steps, and either field alone reaches the middle one."""
    both = score_grounded([_ins("/api/v1/orders", "JSON array of order objects")], CONTEXT)
    ref_only = score_grounded([_ins("/api/v1/orders", ABSENT_SNIP)], CONTEXT)
    snip_only = score_grounded([_ins(ABSENT_REF, "JSON array of order objects")], CONTEXT)
    neither_hits = score_grounded([_ins(ABSENT_REF, ABSENT_SNIP)], CONTEXT)
    no_evidence = score_grounded([{}], CONTEXT)
    empty_fields = score_grounded([_ins("", "")], CONTEXT)
    assert both["scores"][0] == 0.85
    assert ref_only["scores"][0] == 0.6
    assert snip_only["scores"][0] == 0.6         # snippet alone reaches 0.6 too
    assert neither_hits["scores"][0] == 0.35     # present, absent from context
    assert no_evidence["scores"][0] == 0.15      # nothing offered at all
    assert empty_fields["scores"][0] == 0.15


def test_a_snippet_grounds_on_its_first_sixty_characters_only():
    """A loosening nothing documented: only `snippet[:60]` is looked for."""
    ctx = CONTEXT + " " + "X" * 70
    long_snippet = "X" * 70 + "JSON array"       # tail absent from ctx
    res = score_grounded([_ins(ABSENT_REF, long_snippet)], ctx)
    assert res["scores"][0] == 0.6


def test_phase_decides_whether_anything_is_dropped():
    assert "surface" in GROUNDED_PHASES and "plan" not in GROUNDED_PHASES
    pair = [_ins(ABSENT_REF, ABSENT_SNIP), _ins("/api/v1/orders", "returned 200")]
    surface = score_grounded(list(pair), CONTEXT, phase="surface")
    plan = score_grounded(list(pair), CONTEXT, phase="plan")
    assert [i["evidence"]["ref"] for i in surface["dropped"]] == [ABSENT_REF]
    assert plan["dropped"] == []


def test_a_self_scored_invented_item_is_no_longer_smuggled_through():
    """The fix, smuggling direction: `0.99` on an invented item does not raise it."""
    res = score_grounded([_ins(ABSENT_REF, ABSENT_SNIP, confidence=0.99)], CONTEXT)
    item = _only(res)
    assert item["confidence"] == 0.35            # containment, not the caller's number
    assert item["critic_containment_score"] == 0.35
    assert item["critic_self_score"] == 0.99     # kept for audit
    assert item["critic_notes"] == (
        "grounded:ref=False,snippet=False,self_score=0.99(ignored:cannot-raise)")


def test_a_self_scored_zero_no_longer_suppresses_a_grounded_item():
    """The fix, suppression direction -- the damaging one. Two items, so the
    forced-keep floor is not what is doing the rescuing."""
    res = score_grounded([
        _ins("/api/v1/orders", "JSON array of order objects", confidence=0.0),
        _ins("/api/v1/orders", "returned 200"),
    ], CONTEXT)
    assert res["dropped"] == []
    zeroed = [i for i in res["kept"] if i.get("critic_self_score") == 0.0]
    assert len(zeroed) == 1
    assert zeroed[0]["confidence"] == 0.0        # reported low, as the caller asked
    assert zeroed[0]["critic_containment_score"] == 0.85   # measured high, recorded
    assert zeroed[0]["critic_notes"] == (
        "grounded:ref=True,snippet=True,self_score=0(applied:lowered-priority)")


def test_a_bool_confidence_is_not_a_score():
    res = score_grounded(
        [_ins("/api/v1/orders", "JSON array of order objects", confidence=True)], CONTEXT)
    item = _only(res)
    assert item["confidence"] == 0.85
    assert "critic_self_score" not in item
    assert item["critic_notes"].endswith("self_score=True(ignored:not-a-score)")


def test_caller_notes_move_aside_and_do_not_erase_the_gates_record():
    res = score_grounded([_ins(ABSENT_REF, ABSENT_SNIP, critic_notes="mine")], CONTEXT)
    item = _only(res)
    assert item["critic_notes"] == "grounded:ref=False,snippet=False"
    assert item["critic_notes_caller"] == "mine"


def test_the_forced_keep_floor_keeps_exactly_one():
    res = score_grounded(
        [_ins(ABSENT_REF, ABSENT_SNIP), _ins("/yyy-nope", "www-absent")], CONTEXT)
    assert len(res["kept"]) == 1 and len(res["dropped"]) == 1
    assert res["kept"][0]["critic_forced_keep"] is True


def test_the_floor_masks_the_verdict_when_the_item_is_alone():
    """Documented so nobody 'fixes' a drop test by shrinking its batch."""
    res = score_grounded([_ins(ABSENT_REF, ABSENT_SNIP)], CONTEXT)
    assert res["dropped"] == []
    assert res["kept"][0]["critic_forced_keep"] is True


def test_the_caller_still_picks_the_survivor_of_an_all_dropped_batch():
    """The residual channel the fix does not close: the floor sorts by the
    LOWERED confidence, so self-scoring one item zero promotes the other."""
    res = score_grounded([
        _ins(ABSENT_REF, ABSENT_SNIP, confidence=0.0),
        _ins("/yyy-nope", "www-absent"),
    ], CONTEXT)
    assert len(res["kept"]) == 1
    assert res["kept"][0]["evidence"]["ref"] == "/yyy-nope"
    assert res["kept"][0]["critic_forced_keep"] is True


def test_the_model_calling_paths_are_withheld():
    """`score_batch` is a coroutine: it must be awaited or it raises nothing."""
    critic = Critic(llm=object())
    with pytest.raises(NotImplementedError):
        asyncio.run(critic.score_batch([], "", "surface"))
    with pytest.raises(NotImplementedError):
        asyncio.run(critic._raw_call("prompt"))


def test_the_switches_report_their_defaults():
    assert critic_enabled() is True
    assert critic_threshold() == 0.55


def test_the_caller_dict_is_not_mutated_by_scoring():
    """The per-item copy leaves the caller's own dict as it was."""
    src = _ins(ABSENT_REF, ABSENT_SNIP)
    score_grounded([src], CONTEXT)
    assert src == {"evidence": {"source": "traffic",
                                "ref": ABSENT_REF, "snippet": ABSENT_SNIP}}


def test_a_long_caller_note_comes_back_cut_to_the_caller_notes_length():
    """A caller note longer than the cut length is stored only up to it."""
    res = score_grounded(
        [_ins(ABSENT_REF, ABSENT_SNIP, critic_notes="z" * 500)], CONTEXT)
    item = _only(res)
    assert len(item["critic_notes_caller"]) == 200
    assert item["critic_notes_caller"] == "z" * 200


def test_an_out_of_range_self_score_is_clamped_into_the_unit_interval():
    """A self-score below zero or above one is pulled back to the interval."""
    low = _only(score_grounded(
        [_ins("/api/v1/orders", "returned 200", confidence=-3.0)], CONTEXT))
    high = _only(score_grounded(
        [_ins(ABSENT_REF, ABSENT_SNIP, confidence=99.0)], CONTEXT))
    assert low["critic_self_score"] == 0.0
    assert high["critic_self_score"] == 1.0


def test_scores_is_unrounded_while_the_insight_confidence_and_self_score_are_rounded():
    """`scores` carries the raw number; the returned insight carries a rounded one."""
    res = score_grounded(
        [_ins("/api/v1/orders", "JSON array of order objects",
              confidence=0.123456789)], CONTEXT)
    item = _only(res)
    assert res["scores"][0] == 0.123456789        # raw
    assert item["confidence"] == 0.123            # round(_, 3)
    assert item["critic_self_score"] == 0.123     # round(_, 3)


def test_parse_scores_keeps_well_formed_and_excludes_by_two_separate_mechanisms():
    """A well-formed entry is kept; missing, non-numeric and out-of-range i are left out."""
    payload = (
        '{"scores": ['
        '{"i": 0, "confidence": 0.9},'       # well-formed -> kept
        '{"confidence": 0.5},'               # i missing -> int(None) raises, out via try/except
        '{"i": "x", "confidence": 0.5},'     # i non-numeric -> int("x") raises, out via try/except
        '{"i": 99, "confidence": 0.5}'       # i in range? no -> out via the 0<=index<expected_n line
        "]}"
    )
    out = Critic._parse_scores(payload, 3)
    assert set(out) == {0}                        # only the well-formed, in-range entry
    assert out[0]["confidence"] == 0.9
