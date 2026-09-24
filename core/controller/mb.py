"""The sparse mushroom-body-inspired controller: static scoring plus habituation.

The design borrows three ideas from the insect mushroom body and names each one
once, beside its code equivalent: a wide sparse expansion of the input (Kenyon
cells; `SparseEncoder`), a fixed random readout over the few active units
(`FixedReadout`), and a decaying penalty on work that keeps producing the same
unrewarding outcome (habituation; `Habituation`). It is an engineering analogy,
not a brain simulation. Selection combines five per-family terms:

    activation = PRIOR_WEIGHT * prior
               + NOVELTY_WEIGHT * novelty
               + w_dot
               - HABITUATION_WEIGHT * habituation
               - COST_WEIGHT * cost

followed by soft lateral inhibition across families and a seeded epsilon-greedy
exploration draw. Everything is deterministic under a fixed seed, which is what
makes a selection replayable and a comparison against the baselines fair.

Teaching scale: the expansion here is deliberately small (see N_KC, K_FRAC,
CLAWS) and the random draws use the standard library generator; the originating
implementation runs the same construction at a much larger scale. The lesson
states both parameter sets side by side.
"""

import copy
import math
import random
from urllib.parse import urlsplit

from .contract import Controller, stable_best


# Encoder scale (teaching defaults; the lesson quotes the originating scale).
N_KC = 512        # expansion units ("Kenyon cells")
K_FRAC = 0.02     # fraction of units kept active
CLAWS = 3         # input dimensions each unit samples ("claws")
W_SIGMA = 0.05    # fixed readout weight scale

# Activation term weights.
PRIOR_WEIGHT = 1.0
NOVELTY_WEIGHT = 0.5
HABITUATION_WEIGHT = 1.0
COST_WEIGHT = 0.1
COVERAGE_BOOST = 0.5

# Competition and exploration.
KAPPA = 0.25
EPSILON = 0.05

# Habituation dynamics.
RHO = 0.9           # per-select decay
HAB_ALPHA = 0.7     # penalty saturation rate
CLEAN_WEIGHT = 0.5  # clean outcomes habituate at half the error rate
PRUNE_BELOW = 0.01

# Which outcome statuses habituate. Only a target response can habituate a
# surface: an error and a clean result are the target answering unrewardingly.
# Verified evidence is positive signal, a skip or an unavailable tool means the
# target was not touched, and an unresolved execution has no observed response.
SIGNATURE_BY_STATUS = {
    "clean": "clean",
    "tool_error": "error",
    "verified_evidence": "hit",
    "skipped": "skipped",
    "tool_unavailable": "unavailable",
    "unresolved": "unresolved",
}
NON_HABITUATING = frozenset({"hit", "skipped", "unavailable", "unresolved"})


def surface_class(url):
    """A structural bucket for a destination: kind, path depth, query flag.

    Habituation keys on this class rather than on exact URLs, so a family that
    keeps erroring on one shape of surface is suppressed there without touching
    its standing on unrelated surfaces.
    """
    parts = urlsplit(url or "")
    path = parts.path or ""
    segments = [s for s in path.split("/") if s]
    ext = segments[-1].rsplit(".", 1)[-1].lower() if segments and "." in segments[-1] else ""
    if "/api" in path or "graphql" in path or ext in ("json", "xml"):
        kind = "api"
    elif ext in ("js", "css", "png", "jpg", "jpeg", "gif", "svg", "ico",
                 "woff", "woff2", "ttf", "map"):
        kind = "asset"
    else:
        kind = "page"
    depth = min(len(segments), 4)
    query = "q" if parts.query else "nq"
    return f"{kind}:d{depth}:{query}"


class SparseEncoder:
    """Seeded sparse expansion: each unit reads a few input dims with random signs."""

    def __init__(self, *, seed, n_inputs, n_kc=N_KC, k_frac=K_FRAC, claws=CLAWS):
        self.n_inputs = n_inputs
        self.n_kc = n_kc
        self.k = max(1, round(n_kc * k_frac))
        rng = random.Random(seed)
        self._rows = []
        for _ in range(n_kc):
            cols = rng.sample(range(n_inputs), k=min(claws, n_inputs))
            signs = [rng.choice((-1.0, 1.0)) for _ in cols]
            self._rows.append(tuple(zip(cols, signs)))

    def encode(self, x):
        """The sorted indices of the top-k units, among strictly positive ones."""
        activations = []
        for i, row in enumerate(self._rows):
            a = sum(sign * x[col] for col, sign in row)
            if a > 0.0:
                activations.append((-a, i))
        if not activations:
            return ()
        activations.sort()
        keep = activations[:min(self.k, len(activations))]
        return tuple(sorted(i for _, i in keep))


class FixedReadout:
    """Per-family Gaussian weights over the expansion units, left untrained.

    Seeded with `seed + 1` so the readout is decorrelated from the projection
    without introducing a second configuration knob. Rows are generated per
    family name on first use, so a family's weights are the same whatever order
    families first appear in.
    """

    def __init__(self, *, seed, n_kc=N_KC, scale=W_SIGMA):
        self.seed = seed
        self.n_kc = n_kc
        self.scale = scale
        self._rows = {}

    def _row(self, family):
        row = self._rows.get(family)
        if row is None:
            rng = random.Random(f"{self.seed + 1}|{family}")
            row = [rng.gauss(0.0, self.scale) for _ in range(self.n_kc)]
            self._rows[family] = row
        return row

    def w_dot(self, z, family):
        """The mean readout weight over the active units; 0.0 for an empty code."""
        if not z:
            return 0.0
        row = self._row(family)
        return sum(row[u] for u in z) / len(z)


class Habituation:
    """Decaying counts of unrewarding outcomes, keyed by what kept happening.

    Keys are (surface class, family, outcome signature): tried-and-errored and
    tried-and-clean are different keys with different weights, and an untried
    pairing has no key at all.
    """

    def __init__(self, *, rho=RHO, alpha=HAB_ALPHA, clean_weight=CLEAN_WEIGHT):
        self.rho = rho
        self.alpha = alpha
        self.clean_weight = clean_weight
        self._h = {}

    def observe(self, surface, family, signature):
        if signature in NON_HABITUATING:
            return
        key = (surface, family, signature)
        self._h[key] = self._h.get(key, 0.0) + 1.0

    def decay_step(self):
        decayed = {}
        for key, value in self._h.items():
            value *= self.rho
            if value >= PRUNE_BELOW:
                decayed[key] = value
        self._h = decayed

    def penalty(self, surface, family):
        h = (self._h.get((surface, family, "error"), 0.0)
             + self.clean_weight * self._h.get((surface, family, "clean"), 0.0))
        return 1.0 - math.exp(-self.alpha * h)

    def to_dict(self):
        for key in self._h:
            if any("||" in part for part in key):
                raise ValueError(f"habituation key {key!r} contains the "
                                 "snapshot separator and would not round-trip")
        return {"||".join(key): value for key, value in self._h.items()}

    @classmethod
    def from_dict(cls, data, **kwargs):
        hab = cls(**kwargs)
        for key, value in data.items():
            parts = key.split("||")
            if len(parts) != 3:
                raise ValueError(f"unparseable habituation key {key!r}; "
                                 "refusing a snapshot that would silently "
                                 "lose state")
            hab._h[tuple(parts)] = float(value)
        return hab


class MushroomBodyController(Controller):
    """The static sparse controller; see the module docstring for the terms."""

    name = "mb"

    def __init__(self, *, seed=0):
        super().__init__()
        self.seed = seed
        self._n_inputs = None
        self._encoder = None
        self._readout = FixedReadout(seed=seed)
        self._hab = Habituation()
        self._tried = set()
        self._surfaces = {}
        self._step = 0
        self._last_z = ()

    # Scoring -----------------------------------------------------------------

    def _ensure_encoder(self, n_inputs):
        if self._encoder is None:
            self._n_inputs = n_inputs
            self._encoder = SparseEncoder(seed=self.seed, n_inputs=n_inputs)
        elif self._n_inputs != n_inputs:
            raise ValueError(
                f"encoder was built for dimension {self._n_inputs}, "
                f"got a vector of dimension {n_inputs}")
        return self._encoder

    def _w_dot(self, z, family):
        return self._readout.w_dot(z, family)

    def _family_signal(self, family, pool, z):
        prior = max(min(max(c.priority, 0.0) / 10.0, 1.0) for c in pool)
        if any(c.features.get("coverage_obligation") for c in pool):
            prior += COVERAGE_BOOST
        untried = sum(1 for c in pool if c.candidate_id not in self._tried)
        novelty = untried / len(pool)
        surfaces = sorted({surface_class(c.features.get("url", "")) for c in pool})
        habituation = (sum(self._hab.penalty(s, family) for s in surfaces)
                       / len(surfaces)) if surfaces else 0.0
        cost = min(1.0, sum(max(0.0, c.cost) for c in pool) / len(pool) / 10.0)
        w_dot = self._w_dot(z, family)
        raw = (PRIOR_WEIGHT * prior + NOVELTY_WEIGHT * novelty + w_dot
               - HABITUATION_WEIGHT * habituation - COST_WEIGHT * cost)
        return {"prior": round(prior, 6), "novelty": round(novelty, 6),
                "habituation": round(habituation, 6), "cost": round(cost, 6),
                "w_dot": round(w_dot, 6),
                "activation_before_inhibition": round(raw, 6),
                "size": len(pool)}

    def _choose(self, state, candidates):
        x = state.vector()
        z = self._ensure_encoder(len(x)).encode(x)
        self._last_z = z
        self._hab.decay_step()
        self._step += 1

        by_family = {}
        for candidate in candidates:
            by_family.setdefault(candidate.family, []).append(candidate)
            self._surfaces[candidate.candidate_id] = surface_class(
                candidate.features.get("url", ""))
        signals = {family: self._family_signal(family, pool, z)
                   for family, pool in sorted(by_family.items())}

        # Soft lateral inhibition: each family is pushed down by the others'
        # positive activation, so a crowded field suppresses more than a lone
        # family does, and the runner-up survives into the record.
        raw = {f: s["activation_before_inhibition"] for f, s in signals.items()}
        total_positive = sum(max(0.0, a) for a in raw.values())
        for family, signal in signals.items():
            others = total_positive - max(0.0, raw[family])
            signal["activation"] = round(raw[family] - KAPPA * others, 6)

        ranking = sorted(signals, key=lambda f: (-signals[f]["activation"], f))
        rng = random.Random(f"{self.seed}|{state.run_id}|{state.step}")
        exploration = rng.random() < EPSILON
        winner = rng.choice(sorted(by_family)) if exploration else ranking[0]

        chosen = stable_best(by_family[winner],
                             score_of=lambda c: c.priority,
                             tiebreak_of=lambda c: c.candidate_id)
        runner_up = next((f for f in ranking if f != winner), None)
        margin = (round(signals[winner]["activation"]
                        - signals[runner_up]["activation"], 6)
                  if runner_up else None)
        scores = {
            "rule": "mb activation with lateral inhibition, then priority "
                    "within the family",
            "kc_active": len(z),
            "by_family": signals,
            "winner": winner,
            "runner_up": runner_up,
            "margin": margin,
            "exploration": exploration,
        }
        return chosen, scores

    # Feedback ----------------------------------------------------------------

    def _learn(self, pending, outcome):
        signature = SIGNATURE_BY_STATUS[outcome.status]
        surface = self._surfaces.get(outcome.candidate_id, surface_class(""))
        self._tried.add(outcome.candidate_id)
        self._hab.observe(surface, pending["family"], signature)
        return {
            "applied": False,
            "reason": "this controller has no learned weights",
            "habituation": {
                "surface": surface,
                "family": pending["family"],
                "signature": signature,
                "penalty_after": round(self._hab.penalty(surface, pending["family"]), 6),
            },
        }

    # Episode reconstruction ---------------------------------------------------

    def hydrate(self, events):
        """Rebuild habituation and the step counter from an ordered event list.

        One decay per event mirrors the live ordering (decay at select), and an
        event carrying a signature replays its observe. Decisions still in
        flight (signature None) contribute their decay step and nothing else.
        """
        hab = Habituation()
        steps = 0
        for event in events:
            if not isinstance(event, dict) or "family" not in event:
                continue
            steps += 1
            hab.decay_step()
            if event.get("signature"):
                hab.observe(event.get("surface", surface_class("")),
                            event["family"], event["signature"])
        self._hab = hab
        self._step = steps

    # State -------------------------------------------------------------------

    def reset(self):
        super().reset()
        self._hab = Habituation()
        self._tried = set()
        self._surfaces = {}
        self._step = 0
        self._last_z = ()

    def select(self, state, candidates, shadow=False):
        """A shadow consultation reads this controller without advancing it.

        Selection here has episode side effects on purpose -- habituation
        decays, the step counts, surfaces are remembered -- but those belong
        to decisions the run acts on. A shadow recommendation is advice the
        host does not execute, so it must not tick the episode clock either:
        the episode state is saved around the consultation and restored after
        it, and a run that asked for shadow advice selects exactly as one
        that never did.
        """
        if not shadow:
            return super().select(state, candidates, shadow=False)
        saved_hab = self._hab.to_dict()
        saved_step = self._step
        saved_surfaces = copy.deepcopy(self._surfaces)
        try:
            return super().select(state, candidates, shadow=True)
        finally:
            self._hab = Habituation.from_dict(saved_hab)
            self._step = saved_step
            self._surfaces = saved_surfaces

    def snapshot(self):
        base = super().snapshot()
        base.update({
            "seed": self.seed,
            "n_inputs": self._n_inputs,
            "step": self._step,
            "habituation": self._hab.to_dict(),
            "tried": sorted(self._tried),
            "surfaces": copy.deepcopy(self._surfaces),
        })
        return base

    def restore(self, snapshot):
        super().restore(snapshot)
        self.seed = snapshot["seed"]
        self._n_inputs = snapshot["n_inputs"]
        self._encoder = None
        if self._n_inputs is not None:
            self._encoder = SparseEncoder(seed=self.seed, n_inputs=self._n_inputs)
        self._readout = FixedReadout(seed=self.seed)
        self._step = snapshot["step"]
        self._hab = Habituation.from_dict(snapshot["habituation"])
        self._tried = set(snapshot["tried"])
        self._surfaces = copy.deepcopy(snapshot["surfaces"])
        self._last_z = ()
