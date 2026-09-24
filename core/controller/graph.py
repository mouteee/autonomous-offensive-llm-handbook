"""The experimental graph controller: activation over a toy graph, plastic edges.

This arm is deliberately separate from the mushroom-body controller, and the
separation is the point. Both expand the state vector into a sparse active set
and read family scores off it; what differs is where learning lives. The
mushroom-body lessons' plastic site is the unit-to-family readout weights. This
arm's plastic site is the association edges of a graph: the one weighted hop
that turns the step-zero active set into the final active set is where learned
weights are added, so learning changes which units end up active, and the
readout itself stays fixed random noise. The two mechanisms are never the same
thing, and any comparison between them is a comparison of learning sites.

Topology here is a small authored toy graph committed with the course. The
originating experiments ran this mechanism over a measured connectome whose
artifact and license are not distributable in this repository; the lesson
records that boundary and the register records what those experiments did and
did not show. Nothing in this module fetches or ships connectome data.
"""

import json
import math
import pathlib
import random

from .contract import Controller, stable_best
from .plasticity import Eligibility, LearnedWeights


# Teaching-scale parameters, named so the lesson can cite them. The originating
# arm ran the same construction at connectome scale; the lesson quotes that
# scale in a fenced block rather than here.
CLAWS = 3          # input dimensions each graph node samples
K_FRAC = 0.15      # fraction of nodes kept active (toy graphs are small)
W_SIGMA = 0.05     # fixed readout weight scale
SWAPS_PER_EDGE = 10  # rewiring attempts per edge for the shuffled control
W95_FLOOR = 1e-9   # normalization guard for degenerate weight sets


class ToyGraph:
    """A frozen directed weighted graph loaded from a committed fixture."""

    def __init__(self, *, name, n, edges):
        self.name = name
        self.n = int(n)
        self.edges = [(int(pre), int(post), float(w)) for pre, post, w in edges]
        for pre, post, _ in self.edges:
            if not (0 <= pre < self.n and 0 <= post < self.n):
                raise ValueError(f"edge ({pre}, {post}) outside node range")

    @classmethod
    def load(cls, path):
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        if data.get("schema") != "course-toy-graph/v1":
            raise ValueError("not a course toy-graph fixture")
        return cls(name=data["name"], n=data["nodes"], edges=data["edges"])

    def w95(self):
        """The 95th-percentile edge weight, the hop's normalization anchor.

        Computed once from the arm-A graph and reused for its controls, the
        anchor keeps the three arms' hop magnitudes comparable: a control gets
        arm A's scale, not its own.
        """
        weights = sorted(w for _, _, w in self.edges)
        index = min(len(weights) - 1, int(0.95 * (len(weights) - 1)))
        return max(weights[index], W95_FLOOR)

    def degree_sequences(self):
        out_deg, in_deg = {}, {}
        for pre, post, _ in self.edges:
            out_deg[pre] = out_deg.get(pre, 0) + 1
            in_deg[post] = in_deg.get(post, 0) + 1
        return sorted(out_deg.values()), sorted(in_deg.values())


def shuffled_variant(graph, seed, swaps_per_edge=SWAPS_PER_EDGE):
    """A degree-preserving control: double-edge swaps, weights travel along.

    Swap (a -> b, c -> d) into (a -> d, c -> b), refusing self-loops and
    duplicate directed pairs, so every node keeps its in and out degree while
    the wiring pattern is destroyed. The weight multiset is preserved because
    weights stay attached to their (rewired) edge rows.
    """
    rng = random.Random(seed)
    edges = [list(e) for e in graph.edges]
    existing = {(pre, post) for pre, post, _ in graph.edges}
    attempts = swaps_per_edge * len(edges)
    for _ in range(attempts):
        i, j = rng.randrange(len(edges)), rng.randrange(len(edges))
        if i == j:
            continue
        a, b, wa = edges[i]
        c, d, wc = edges[j]
        if a == d or c == b:
            continue
        if (a, d) in existing or (c, b) in existing:
            continue
        existing.discard((a, b))
        existing.discard((c, d))
        edges[i] = [a, d, wa]
        edges[j] = [c, b, wc]
        existing.add((a, d))
        existing.add((c, b))
    return ToyGraph(name=f"{graph.name}-shuffled", n=graph.n, edges=edges)


def random_variant(graph, seed):
    """A density-matched control: same node and edge counts, same weight
    multiset, wiring drawn fresh with no degree preservation."""
    rng = random.Random(seed)
    pairs = set()
    while len(pairs) < len(graph.edges):
        pre = rng.randrange(graph.n)
        post = rng.randrange(graph.n)
        if pre != post and (pre, post) not in pairs:
            pairs.add((pre, post))
    weights = [w for _, _, w in graph.edges]
    rng.shuffle(weights)
    edges = [(pre, post, w) for (pre, post), w in zip(sorted(pairs), weights)]
    return ToyGraph(name=f"{graph.name}-random", n=graph.n, edges=edges)


class EdgeEligibility(Eligibility):
    """The shared decaying-trace mechanism, keyed by association edge.

    Reuses the lesson 13 class unchanged for decay, pruning and storage; the
    only difference is what a key is: an (pre, post) node pair instead of a
    (unit, family) pair. Depositing on the co-activation keys is what makes the
    later three-factor update land on edges.
    """

    def on_coactivation(self, keys):
        self.on_select((), "")  # decay and prune every trace; deposit nothing
        for key in keys:
            # Same birth bookkeeping as the base deposit: a recreated edge
            # remembers the pass that recreated it, so a dead deposit's late
            # refusal cannot be subtracted from a successor's fresh value.
            if key not in self._e:
                self._born[key] = self._gen
            self._e[key] = self._e.get(key, 0.0) + 1.0


class GraphController(Controller):
    """Family selection by one weighted hop over a graph, learning on edges.

    This research arm defines no snapshot of its own: the inherited contract
    snapshot round-trips the pending records (deposit notes included) and
    nothing else, so edge traces, learned weights and the readout do not
    survive a restore. The arm is outside the controller factory and the
    assembled application's checkpoints; a research harness that needs its
    learning state to persist must carry that state itself.
    """

    name = "graph"

    def __init__(self, *, graph, seed=0, learn=False, hop=True, w95_anchor=None):
        super().__init__()
        self.graph = graph
        self.seed = int(seed)
        self.learn = bool(learn)
        self.hop = bool(hop)
        self.w95_anchor = float(w95_anchor if w95_anchor is not None else graph.w95())
        self.k = max(1, round(graph.n * K_FRAC))
        rng = random.Random(seed)
        self._rows = []
        self._dim = None
        self._rng_state_rows = rng.getstate()
        self._readout = {}
        self._elig = EdgeEligibility()
        self._weights = LearnedWeights()
        self._out_edges = {}
        for index, (pre, post, w) in enumerate(graph.edges):
            self._out_edges.setdefault(pre, []).append((post, w))
        self._last_co_keys = ()

    # Projection and readout ---------------------------------------------------

    def _pin_dimension(self, dim):
        if self._dim is None:
            rng = random.Random(self.seed)
            self._rows = []
            for _ in range(self.graph.n):
                cols = rng.sample(range(dim), k=min(CLAWS, dim))
                signs = [rng.choice((-1.0, 1.0)) for _ in cols]
                self._rows.append(tuple(zip(cols, signs)))
            self._dim = dim
        elif self._dim != dim:
            raise ValueError(
                f"graph arm was pinned to dimension {self._dim}, got {dim}")

    def _family_readout(self, family):
        row = self._readout.get(family)
        if row is None:
            rng = random.Random(f"{self.seed + 1}|{family}")
            row = [rng.gauss(0.0, W_SIGMA) for _ in range(self.graph.n)]
            self._readout[family] = row
        return row

    def _topk_positive(self, values):
        active = [(-v, i) for i, v in enumerate(values) if v > 0.0]
        if not active:
            return ()
        active.sort()
        return tuple(sorted(i for _, i in active[:min(self.k, len(active))]))

    def forward(self, x):
        """One pass: project, hop once, and answer the active set and co-keys.

        The hop adds `w_norm + learned` for every edge out of a step-zero
        active node; with `hop=False` (the no-hop control) the final active set
        is the step-zero set and no co-activation keys exist, which is exactly
        why that control isolates the hop's contribution.
        """
        self._pin_dimension(len(x))
        u0 = [sum(sign * x[col] for col, sign in row) for row in self._rows]
        active0 = self._topk_positive(u0)
        if not self.hop:
            return {"active": active0, "active0": active0, "co_keys": ()}
        u1 = [0.0] * self.graph.n
        for pre in active0:
            for post, w in self._out_edges.get(pre, ()):
                u1[post] += (w / self.w95_anchor
                             + self._weights._w.get((pre, post), 0.0))
        combined = [a + b for a, b in zip(u0, u1)]
        active = self._topk_positive(combined)
        active_set = set(active)
        co_keys = tuple((pre, post) for pre in active0
                        for post, _ in self._out_edges.get(pre, ())
                        if post in active_set)
        return {"active": active, "active0": active0, "co_keys": co_keys}

    # Selection and learning ---------------------------------------------------

    def _choose(self, state, candidates):
        x = state.vector()
        pass_result = self.forward(x)
        active = pass_result["active"]
        families = sorted({c.family for c in candidates})
        by_family = {}
        for family in families:
            row = self._family_readout(family)
            score = (sum(row[i] for i in active) / len(active)) if active else 0.0
            by_family[family] = round(score, 9)
        winner = stable_best(families, score_of=lambda f: by_family[f],
                             tiebreak_of=lambda f: f)
        within = [c for c in candidates if c.family == winner]
        chosen = stable_best(within, score_of=lambda c: c.priority,
                             tiebreak_of=lambda c: c.candidate_id)
        self._last_co_keys = pass_result["co_keys"]
        scores = {
            "rule": "fixed readout over the graph's active set, then priority",
            "variant": self.graph.name,
            "hop": self.hop,
            "by_family": by_family,
            "chosen_family": winner,
            "active0_n": len(pass_result["active0"]),
            "active_n": len(active),
            "co_keys_n": len(pass_result["co_keys"]),
        }
        return chosen, scores

    def select(self, state, candidates, shadow=False):
        """Deposit edge eligibility only for selections that can earn credit.

        The deposit's keys and decay-pass date ride the pending record, the
        same arrangement the plastic mushroom-body controller uses: a shadow
        selection deposits nothing, and a selection the host later refuses is
        unwound exactly in `observe`.
        """
        decision = super().select(state, candidates, shadow=shadow)
        if decision is not None and not shadow and self.learn:
            self._elig.on_coactivation(self._last_co_keys)
            self._pending[decision.decision_id]["elig"] = {
                "keys": [list(key) for key in self._last_co_keys],
                "gen": self._elig.marker()}
        return decision

    def observe(self, outcome):
        """The contract's routing, plus exact unwind of refused deposits.

        When the base class consumes a pending record for a non-executed
        outcome, what remains of that selection's own edge deposit is
        subtracted, so a later outcome cannot credit edges only a refused
        selection co-activated. The deposit's share is all that comes back:
        the decay pass the refused selection applied to other live traces
        stands, and credit already granted before a late refusal report is
        not clawed back -- report a refusal when it happens.
        """
        pending = self._pending.get(outcome.decision_id)
        report = super().observe(outcome)
        if (self.learn and pending is not None and not outcome.executed
                and outcome.decision_id not in self._pending):
            note = pending.get("elig")
            if note:
                self._elig.unwind([tuple(key) for key in note["keys"]],
                                  note["gen"])
        return report

    def _learn(self, pending, outcome):
        if not self.learn:
            return {"applied": False, "reason": "learning is frozen"}
        update = self._weights.update(self._elig.traces(), outcome.feedback)
        return {"applied": True, "modulation": outcome.feedback,
                "plastic_site": "association_edges", **update}

    # Accounting ----------------------------------------------------------------

    def parity(self):
        """The per-arm disclosure record: scale and how much learning moved."""
        learned = self._weights.weights()
        magnitudes = sorted(abs(w) for w in learned.values())
        median = magnitudes[len(magnitudes) // 2] if magnitudes else 0.0
        clipped = sum(1 for w in learned.values()
                      if abs(w) >= self._weights.w_max - 1e-9)
        return {
            "graph": self.graph.name,
            "nodes": self.graph.n,
            "edges": len(self.graph.edges),
            "hop": self.hop,
            "learn": self.learn,
            "plastic_site": "association_edges",
            "learned_edges_n": len(learned),
            "clipped_fraction": round(clipped / len(learned), 6) if learned else 0.0,
            "median_abs_learned": round(median, 9),
        }

    def reset(self):
        super().reset()
        self._elig.reset()
        self._weights.reset()
        self._readout = {}
        self._last_co_keys = ()
