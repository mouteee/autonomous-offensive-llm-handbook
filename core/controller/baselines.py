"""The two deterministic baselines every adaptive controller is compared to.

Both are stateless: `observe` records nothing and `snapshot` round-trips only
the shared pending table. That is what makes them baselines -- identical
candidates in, identical choice out, on any day, which is the floor an adaptive
policy has to beat before its extra machinery earns anything.
"""

from .contract import Controller, stable_best


class PriorityController(Controller):
    """Highest host-assigned priority wins; ties go to the smaller identifier."""

    name = "priority"

    def _choose(self, state, candidates):
        chosen = stable_best(candidates,
                             score_of=lambda c: c.priority,
                             tiebreak_of=lambda c: c.candidate_id)
        scores = {c.candidate_id: c.priority for c in candidates}
        return chosen, {"rule": "priority", "by_candidate": scores}


class LegacyRankingController(Controller):
    """Priority per unit cost, the ranking the fixture lab's planner uses.

    Same shape as the lab's `weight / cost` policy: value scaled by what the
    action costs, ties again on the identifier. A zero or negative cost is
    read as the minimum positive cost rather than as free work.
    """

    name = "legacy"

    MINIMUM_COST = 1e-6

    def _choose(self, state, candidates):
        def score(candidate):
            return candidate.priority / max(candidate.cost, self.MINIMUM_COST)

        chosen = stable_best(candidates, score_of=score,
                             tiebreak_of=lambda c: c.candidate_id)
        scores = {c.candidate_id: score(c) for c in candidates}
        return chosen, {"rule": "priority / cost", "by_candidate": scores}
