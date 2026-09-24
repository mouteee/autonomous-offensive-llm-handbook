"""Plasticity for the sparse controller: eligibility traces and a local rule.

Learning has exactly one home: the weights from active expansion units to
the winning family's readout. The projection and the fixed random readout are
untouched, and no language model is involved anywhere in this file -- local
controller plasticity adjusts this package's own small weight table and is not
fine-tuning of any model.

Two pieces:

    eligibility <- LAMBDA_E * eligibility        (every select, all traces)
    eligibility[(unit, winner)] += 1.0           (the winning family's units)

    weight <- clip(weight + ETA * modulation * eligibility, -W_MAX, +W_MAX)

The modulation value is the same scalarized feedback every controller in the
laboratory learns from. Decay is select-driven only: a trace ages when new
decisions are made, not when old outcomes arrive, which is what lets a delayed
outcome still find a (smaller) trace to credit.
"""

from .contract import Outcome  # noqa: F401  (re-exported for the lesson's demo)
from .mb import MushroomBodyController


LAMBDA_E = 0.8      # eligibility decay per select
TRACE_PRUNE = 1e-3  # traces below this are dropped
ETA = 0.05          # learning rate
W_MAX = 1.0         # symmetric clipping bound


class Eligibility:
    """Sparse decaying traces keyed by (expansion unit, family).

    Every deposit is one unit of eligibility laid after that select's decay
    pass, so a deposit's remaining value after any number of later selects is
    `lambda_e` raised to the number of decay passes since -- which is what
    lets `unwind` subtract a refused selection's deposit exactly instead of
    waiting for it to decay away. Two pieces of bookkeeping make the
    subtraction exact: the decay-pass counter (`marker`) dates each deposit,
    and each live key remembers the pass that created it, so a deposit whose
    share was pruned away cannot be subtracted from a successor deposit that
    later recreated the key.
    """

    def __init__(self, *, lambda_e=LAMBDA_E, prune_below=TRACE_PRUNE):
        self.lambda_e = lambda_e
        self.prune_below = prune_below
        self._e = {}
        self._born = {}
        self._gen = 0

    def on_select(self, z, family):
        decayed = {}
        for key, value in self._e.items():
            value *= self.lambda_e
            if value >= self.prune_below:
                decayed[key] = value
        self._e = decayed
        self._born = {key: gen for key, gen in self._born.items()
                      if key in decayed}
        self._gen += 1
        for unit in z:
            key = (unit, family)
            if key not in self._e:
                self._born[key] = self._gen
            self._e[key] = self._e.get(key, 0.0) + 1.0

    def marker(self):
        """The decay-pass count; taken right after a deposit, it dates it."""
        return self._gen

    def unwind(self, keys, gen):
        """Subtract what remains of one dated deposit, key by key.

        The residual is one unit decayed once per pass since the deposit --
        computed by the same repeated multiplication decay itself performs,
        so a key holding only this deposit lands on exactly zero. That is
        the whole promise: the refused deposit's own share is removed. What
        is deliberately NOT rewound, because the pass counter is shared
        history: the decay this selection's pass applied to every other
        live trace stands, and a remainder the subtraction leaves below the
        prune threshold is pruned the same way decay would prune it. A key
        already pruned is left alone -- its residual went with it -- and a
        key recreated by a later deposit after this one was pruned is left
        alone too: the key's recorded birth pass postdates this deposit, so
        this deposit's share is not in it, and a dead deposit subtracts
        nothing from a successor's fresh value.
        """
        residual = 1.0
        for _ in range(self._gen - gen):
            residual *= self.lambda_e
        for key in keys:
            value = self._e.get(key)
            if value is None:
                continue
            if self._born.get(key, 0) > gen:
                continue
            value -= residual
            if value >= self.prune_below:
                self._e[key] = value
            else:
                self._e.pop(key, None)
                self._born.pop(key, None)

    def traces(self):
        return dict(self._e)

    def reset(self):
        self._e = {}
        self._born = {}
        self._gen = 0


class LearnedWeights:
    """The learned part of the readout: clipped, local, traced-pairs-only."""

    def __init__(self, *, eta=ETA, w_max=W_MAX):
        self.eta = eta
        self.w_max = w_max
        self._w = {}

    def update(self, traces, modulation):
        """Apply the three-factor rule; report what moved and what clipped."""
        if not traces or modulation == 0.0:
            return {"updated": 0, "clipped": 0, "total_abs_delta": 0.0}
        updated = clipped = 0
        total = 0.0
        for key, eligibility in traces.items():
            before = self._w.get(key, 0.0)
            after = before + self.eta * modulation * eligibility
            if after > self.w_max:
                after, clipped = self.w_max, clipped + 1
            elif after < -self.w_max:
                after, clipped = -self.w_max, clipped + 1
            self._w[key] = after
            total += abs(after - before)
            updated += 1
        return {"updated": updated, "clipped": clipped,
                "total_abs_delta": round(total, 9)}

    def w_dot(self, z, family):
        """Mean learned weight over the active units, the fixed readout's own
        normalization, so the two halves add on the same scale."""
        if not z:
            return 0.0
        return sum(self._w.get((u, family), 0.0) for u in z) / len(z)

    def total_change(self):
        return sum(abs(w) for w in self._w.values())

    def weights(self):
        return dict(self._w)

    def reset(self):
        self._w = {}


class PlasticMbController(MushroomBodyController):
    """The sparse controller with the learning site switched on by research code.

    Frozen (the ordinary construction) it behaves as the static controller with
    the identical selection arithmetic: habituation still updates, because that
    is episode dynamics rather than learning, while no trace is laid and every
    weight stays at zero.
    """

    name = "mb-plastic"

    def __init__(self, *, seed=0, learn=False):
        super().__init__(seed=seed)
        self.learn = bool(learn)
        self._elig = Eligibility()
        self._weights = LearnedWeights()

    def _w_dot(self, z, family):
        fixed = super()._w_dot(z, family)
        if not self.learn:
            return fixed
        return fixed + self._weights.w_dot(z, family)

    def select(self, state, candidates, shadow=False):
        """Deposit eligibility only for selections that can earn credit.

        A shadow recommendation is advice the host does not execute, and the
        contract refuses its outcome -- so it must not lay a trace either,
        or a later legitimate outcome would quietly credit units the shadow
        alone activated. The deposit therefore happens here, after the shadow
        flag is known, exactly as the graph controller does; `_choose` stays
        selection arithmetic only. A shadow selection neither deposits nor
        decays the traces: it is bookkeeping-free.

        A real selection can still be refused by the host after this deposit,
        so the deposit's keys and its decay-pass date ride the contract's own
        pending record: when the host reports the decision not executed,
        `observe` unwinds exactly what remains of this deposit, and a later
        outcome cannot credit units only a refused selection activated. The
        annotation lives inside the pending record on purpose -- it is
        consumed, kept or checkpointed on exactly the pending record's own
        lifecycle.
        """
        decision = super().select(state, candidates, shadow=shadow)
        if decision is not None and not shadow and self.learn:
            self._elig.on_select(self._last_z, decision.family)
            self._pending[decision.decision_id]["elig"] = {
                "keys": [[unit, decision.family] for unit in self._last_z],
                "gen": self._elig.marker()}
        return decision

    def observe(self, outcome):
        """Route the outcome as the contract does, unwinding refused deposits.

        The base class consumes the pending record and refuses to learn from
        a non-executed outcome; this override additionally subtracts what
        remains of that selection's own eligibility deposit. That removes
        the refused deposit's share and nothing more: the decay pass the
        refused selection applied to the other live traces stands, a
        remainder below the prune threshold is pruned as decay would prune
        it, and credit an interleaved outcome already granted before a late
        refusal report is not clawed back -- report a refusal when it
        happens. A mis-addressed outcome keeps the pending record and
        therefore keeps the deposit.
        """
        pending = self._pending.get(outcome.decision_id)
        report = super().observe(outcome)
        if (self.learn and pending is not None and not outcome.executed
                and outcome.decision_id not in self._pending):
            note = pending.get("elig")
            if note:
                self._elig.unwind([tuple(k) for k in note["keys"]],
                                  note["gen"])
        return report

    def _learn(self, pending, outcome):
        report = super()._learn(pending, outcome)
        if not self.learn:
            return {**report, "reason": "learning is frozen"}
        update = self._weights.update(self._elig.traces(), outcome.feedback)
        return {
            "applied": True,
            "modulation": outcome.feedback,
            "habituation": report["habituation"],
            **update,
        }

    def reset(self):
        super().reset()
        self._elig.reset()
        self._weights.reset()

    def snapshot(self):
        base = super().snapshot()
        base.update({
            "learn": self.learn,
            "eligibility": {f"{u}|{f}": v for (u, f), v in self._elig.traces().items()},
            "eligibility_gen": self._elig.marker(),
            "eligibility_born": {f"{u}|{f}": g
                                 for (u, f), g in self._elig._born.items()},
            "weights": {f"{u}|{f}": v for (u, f), v in self._weights.weights().items()},
        })
        return base

    def restore(self, snapshot):
        """Rebuild the learning state, refusing inconsistent snapshots.

        A pending deposit note is dated against the decay-pass counter, so a
        snapshot carrying such a note without `eligibility_gen`, or a note
        dated after the restored counter, is internally inconsistent and is
        refused loudly: restoring it would let one late refusal subtract a
        full unit from successor traces. A snapshot from before the birth
        bookkeeping restores with every birth unknown, and the unwind then
        falls back to the old always-subtract behavior; the residue a dead
        deposit can reintroduce that way is below the prune threshold,
        because a residual at or above it would mean the key was never
        pruned and the subtraction is simply correct.
        """
        from .contract import ContractError

        super().restore(snapshot)
        notes = [note for pending in snapshot.get("pending", {}).values()
                 for note in [pending.get("elig")] if note]
        gen = snapshot.get("eligibility_gen")
        if notes and gen is None:
            raise ContractError(
                "snapshot carries dated eligibility deposits but no "
                "eligibility_gen to date them against")
        if notes and any(note["gen"] > int(gen) for note in notes):
            raise ContractError(
                "snapshot carries an eligibility deposit dated after its "
                "own decay-pass counter")
        self.learn = snapshot["learn"]
        self._elig = Eligibility()
        self._elig._gen = int(gen or 0)
        for key, value in snapshot["eligibility"].items():
            unit, family = key.split("|", 1)
            self._elig._e[(int(unit), family)] = float(value)
        for key, born in snapshot.get("eligibility_born", {}).items():
            unit, family = key.split("|", 1)
            self._elig._born[(int(unit), family)] = int(born)
        self._weights = LearnedWeights()
        for key, value in snapshot["weights"].items():
            unit, family = key.split("|", 1)
            self._weights._w[(int(unit), family)] = float(value)
