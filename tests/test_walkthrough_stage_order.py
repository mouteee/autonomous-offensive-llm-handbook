"""The stage ledger as an ordered sequence, not a set: position is what nothing else checks.

tests/test_walkthrough_stages_1_4.py, _5_7 and _8_9 each confirm their own slice of the nine
stages is present in `_stages`, via a subset test over sets (`set(_STAGES) <= set(out["_stages"])`
in _1_4, a two-member set literal in _8_9), a loop of `out.stage_ran(stage)` (_1_4 and _5_7), or
both, which is what _1_4 does. `stage_ran` is `return name in self.get("_stages", ())` in
`walkthrough/run.py` -- membership, and structurally unable to say anything about position.
`test_the_stage_ledger_is_the_store_s_own_list`, beside the first of those, checks identity of
the list object against the store's own `stages_run`, which is a different property again and
still not order.

Transpose any two of the calls inside `run_all` and every one of those assertions stays green:
a transposed list is still the same set, still contains every name exactly once, and is still
the same object it always was. Here, instead, `_stages` is read as the ordered sequence it
actually is, positionally, against the nine-stage order `walkthrough/run.py` documents in its
own module docstring and step 1 of `handbook/06-build-your-own.md` names in prose.
"""
import asyncio
import pathlib

from walkthrough import run as runner

ROOT = pathlib.Path(__file__).resolve().parents[1]

DECLARED_ORDER = (
    "fingerprint", "scope", "recommend", "schedule",
    "evidence", "critic", "write", "consolidate", "gate",
)


def test_the_stage_ledger_equals_the_declared_order_positionally():
    """`==` against a list, not `<=` against a set: a transposed pair fails here and nowhere else.

    Every existing stage-ledger assertion in this suite survives a transposition of two calls
    inside `run_all` untouched, because a set has no order and `stage_ran` is bare membership.
    This asserts `_stages` against the declared nine-stage sequence positionally, so swapping
    any two stages -- the list otherwise identical, every name still present exactly once --
    fails this test where every other stage test in this suite stays green.
    """
    out = asyncio.run(runner.run_all(ROOT))
    assert list(out["_stages"]) == list(DECLARED_ORDER)
