"""LinUCB over hypothesis families: a linear model per family, picked by
predicted reward plus an uncertainty bonus, then a shared within-family choice.

The variant implemented is disjoint LinUCB with one model per family rather
than per candidate: each family keeps a square matrix `A` (started at the
identity) and a reward vector `b` over the state feature vector `x`, and scores

    theta = solve(A, b)
    score = dot(theta, x) + alpha * sqrt(dot(x, solve(A, x)))

The family with the best score wins, ties going to the lexicographically
smaller family name, and the candidate inside the family is chosen by the same
priority rule the baselines use, so the bandit's contribution is family choice
and nothing else. After an executed outcome:

    A <- A + outer(x, x)
    b <- b + reward * x

applied only when the controller was built with `learn=True` and only to the
family of the decision the outcome names. A frozen controller performs the
identical selection arithmetic and leaves `A` and `b` untouched.
"""

import copy
import math

from .contract import Controller, stable_best


DEFAULT_ALPHA = 0.5


def solve(matrix, vector):
    """Solve `matrix @ x = vector` by Gaussian elimination with pivoting.

    The matrices here are identity plus a sum of outer products, so they are
    symmetric positive definite and the solve is always well posed; the pivot
    step is still present so a hand-edited snapshot produces a loud error
    instead of a quiet wrong answer.
    """
    n = len(vector)
    a = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            raise ValueError("singular matrix in LinUCB solve")
        a[col], a[pivot] = a[pivot], a[col]
        for row in range(col + 1, n):
            factor = a[row][col] / a[col][col]
            for k in range(col, n + 1):
                a[row][k] -= factor * a[col][k]
    x = [0.0] * n
    for row in range(n - 1, -1, -1):
        x[row] = (a[row][n] - sum(a[row][k] * x[k] for k in range(row + 1, n))) / a[row][row]
    return x


def identity(n):
    return [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]


class LinUcbController(Controller):
    """The contextual bandit; see the module docstring for the arithmetic."""

    name = "linucb"

    def __init__(self, *, alpha=DEFAULT_ALPHA, learn=False, seed=0):
        super().__init__()
        self.alpha = float(alpha)
        self.learn = bool(learn)
        self.seed = seed  # recorded for provenance; this policy draws nothing
        self._families = {}
        self._observed = 0

    # Selection ---------------------------------------------------------------

    def _family_state(self, family, dimension):
        state = self._families.get(family)
        if state is None:
            state = {"A": identity(dimension), "b": [0.0] * dimension}
            self._families[family] = state
        if len(state["b"]) != dimension:
            raise ValueError(
                f"family {family!r} was learned on dimension {len(state['b'])}, "
                f"got a vector of dimension {dimension}")
        return state

    def family_score(self, family, x):
        """Predicted reward plus uncertainty bonus for one family at `x`."""
        state = self._family_state(family, len(x))
        theta = solve(state["A"], state["b"])
        predicted = sum(t * xi for t, xi in zip(theta, x))
        spread = sum(xi * si for xi, si in zip(x, solve(state["A"], x)))
        bonus = self.alpha * math.sqrt(max(spread, 0.0))
        return {"predicted": predicted, "bonus": bonus,
                "score": predicted + bonus, "theta": theta}

    def _choose(self, state, candidates):
        x = state.vector()
        families = sorted({c.family for c in candidates})
        per_family = {f: self.family_score(f, x) for f in families}
        best_family = stable_best(families,
                                  score_of=lambda f: per_family[f]["score"],
                                  tiebreak_of=lambda f: f)
        within = [c for c in candidates if c.family == best_family]
        chosen = stable_best(within,
                             score_of=lambda c: c.priority,
                             tiebreak_of=lambda c: c.candidate_id)
        scores = {
            "rule": "linucb family, then priority within the family",
            "alpha": self.alpha,
            "by_family": {f: {k: per_family[f][k] for k in ("predicted", "bonus", "score")}
                          for f in families},
            "chosen_family": best_family,
        }
        return chosen, scores

    # Learning ----------------------------------------------------------------

    def _learn(self, pending, outcome):
        if not self.learn:
            return {"applied": False, "reason": "learning is frozen"}
        x = pending["vector"]
        state = self._family_state(pending["family"], len(x))
        for i in range(len(x)):
            for j in range(len(x)):
                state["A"][i][j] += x[i] * x[j]
            state["b"][i] += outcome.feedback * x[i]
        self._observed += 1
        return {"applied": True, "family": pending["family"],
                "reward": outcome.feedback}

    # State -------------------------------------------------------------------

    def reset(self):
        super().reset()
        self._families = {}
        self._observed = 0

    def snapshot(self):
        base = super().snapshot()
        base.update({
            "alpha": self.alpha,
            "learn": self.learn,
            "observed": self._observed,
            "families": copy.deepcopy(self._families),
        })
        return base

    def restore(self, snapshot):
        super().restore(snapshot)
        self.alpha = snapshot["alpha"]
        self.learn = snapshot["learn"]
        self._observed = snapshot["observed"]
        self._families = copy.deepcopy(snapshot["families"])
