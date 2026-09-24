"""The shared controller contract: records in, one decision out, feedback back.

Four records travel between the host and a controller, and their field names
are the interface. `State` is what the run knows right now. `Candidate` is one
eligible piece of work the host already authorized; the controller ranks
candidates and invents none. `Decision` is the controller's answer, carrying
the scores it used so the choice is inspectable afterwards. `Outcome` is the
host's report of what actually happened to a decision, carrying the shared
feedback value defined in `feedback.py`.

Learning credit is keyed by decision identifier: a controller keeps its own
pending record per decision it issued and applies feedback only to the decision
the outcome names. The originating system's bandit used a sequential
pending-selection contract instead, where a second selection replaced the
pending one before its outcome arrived; the decision-keyed design here is a
deliberate teaching correction for interleaved feedback, not a transcription of
the original. The lesson that builds this package says so as well.
"""

import copy
import hashlib
import json
from dataclasses import dataclass, field


SCHEMA_VERSION = "features-v1"

# The feature names a versioned state vector carries, in order. Controllers
# read the vector positionally, so the order is part of the schema version and
# reordering it is a new version, not an edit.
FEATURE_SCHEMA = {
    "features-v1": (
        "bias",
        "stage_progress",
        "surface_known",
        "recent_error_rate",
        "budget_remaining",
    ),
    # The two-dimensional schema the LinUCB lesson's worked arithmetic uses.
    "toy-v1": ("bias", "signal"),
}

# One vocabulary for what happened to an executed decision. These are distinct
# on purpose: an errored tool, a tool the host does not have, a clean result,
# work the host skipped, an execution whose record was lost, and a result that
# later produced verified evidence are different facts and collapse badly.
OUTCOME_STATUSES = (
    "clean",
    "tool_error",
    "tool_unavailable",
    "skipped",
    "unresolved",
    "verified_evidence",
)


class ContractError(ValueError):
    """A record that does not satisfy the contract."""


def _finite_number(value, name):
    if type(value) is bool or not isinstance(value, (int, float)):
        raise ContractError(f"{name} needs a number, got {type(value).__name__}")
    if value != value or value in (float("inf"), float("-inf")):
        raise ContractError(f"{name} needs a finite number")
    return float(value)


@dataclass(frozen=True)
class State:
    """What the run knows at the moment of selection."""

    run_id: str
    step: int
    features: dict
    schema_version: str = SCHEMA_VERSION

    def vector(self):
        """The features as an ordered list under this record's schema."""
        try:
            names = FEATURE_SCHEMA[self.schema_version]
        except KeyError:
            raise ContractError(
                f"unknown feature schema {self.schema_version!r}") from None
        missing = [n for n in names if n not in self.features]
        if missing:
            raise ContractError(f"state features missing {missing}")
        return [_finite_number(self.features[n], n) for n in names]


@dataclass(frozen=True)
class Candidate:
    """One eligible action, already authorized by the host.

    `candidate_id` is the normalized action identity the whole pipeline shares:
    proposal, selection, execution, recording and feedback all use this one
    string, so an outcome is attributed to the action that ran and to nothing
    else; how far a learning controller spreads that credit across its own
    live traces is that controller's stated mechanism. `family` groups
    candidates that test the same hypothesis kind.
    """

    candidate_id: str
    family: str
    features: dict = field(default_factory=dict)
    priority: float = 0.0
    novelty: float = 0.0
    cost: float = 1.0


@dataclass(frozen=True)
class Decision:
    """A controller's answer, with the arithmetic it used left visible."""

    decision_id: str
    candidate_id: str
    family: str
    scores: dict
    selected_features: list
    shadow: bool = False
    controller: str = ""
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class Outcome:
    """The host's report of what happened to one decision."""

    decision_id: str
    candidate_id: str
    run_id: str
    status: str
    feedback: float = 0.0
    executed: bool = True

    def __post_init__(self):
        if self.status not in OUTCOME_STATUSES:
            raise ContractError(
                f"unknown outcome status {self.status!r}; "
                f"known: {', '.join(OUTCOME_STATUSES)}")


def decision_id(run_id, step, candidate_id, controller=""):
    """A stable decision identifier: run, step, chosen candidate, controller.

    The controller's name is part of the identity because two controllers can
    legitimately select the same candidate at the same step (the laboratory's
    comparison shape), and an outcome for one of them landing on the other is
    exactly the misdelivery decision keying exists to stop.
    """
    text = json.dumps([run_id, step, candidate_id, controller],
                      separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def stable_best(items, score_of, tiebreak_of):
    """The highest-scoring item, ties broken by the smallest tiebreak key.

    Selection has to replay: given the same items and the same scores, the
    same item comes back regardless of input order, which is why the tie rule
    is an explicit sort key rather than whatever order the list arrived in.
    """
    best = None
    best_key = None
    for item in items:
        key = (-score_of(item), tiebreak_of(item))
        if best_key is None or key < best_key:
            best, best_key = item, key
    return best


class Controller:
    """Base class: the four operations every selection policy offers.

    `select` answers with a `Decision` over the offered candidates, or `None`
    when no candidate is offered. A shadow selection is a recommendation the
    host does not execute; it is recorded for comparison and receives no
    learning credit, because credit for an action that did not run is exactly
    the off-policy mistake the outcome record's `executed` flag exists to name.
    `observe` consumes an `Outcome` for a decision this controller issued.
    `snapshot` and `restore` round-trip the controller's whole mutable state.
    """

    name = "base"

    def __init__(self):
        self._pending = {}

    def select(self, state, candidates, shadow=False):
        if not candidates:
            return None
        chosen, scores = self._choose(state, candidates)
        decision = Decision(
            decision_id=decision_id(state.run_id, state.step,
                                    chosen.candidate_id, self.name),
            candidate_id=chosen.candidate_id,
            family=chosen.family,
            scores=scores,
            selected_features=state.vector(),
            shadow=shadow,
            controller=self.name,
            schema_version=state.schema_version,
        )
        if not shadow:
            self._pending[decision.decision_id] = {
                "candidate_id": chosen.candidate_id,
                "family": chosen.family,
                "vector": decision.selected_features,
            }
        return decision

    def observe(self, outcome):
        pending = self._pending.get(outcome.decision_id)
        if pending is None:
            return {"applied": False, "reason": "unknown or shadow decision"}
        if pending["candidate_id"] != outcome.candidate_id:
            # The pending record stays: a mis-addressed outcome is the host's
            # mistake, and consuming the record here would also discard the
            # correctly addressed outcome that may still arrive.
            return {"applied": False, "reason": "outcome names a different candidate"}
        del self._pending[outcome.decision_id]
        if not outcome.executed:
            return {"applied": False, "reason": "decision was not executed"}
        return self._learn(pending, outcome)

    def reset(self):
        self._pending = {}

    def snapshot(self):
        return {"name": self.name, "pending": copy.deepcopy(self._pending)}

    def restore(self, snapshot):
        if snapshot.get("name") != self.name:
            raise ContractError(
                f"snapshot belongs to {snapshot.get('name')!r}, not {self.name!r}")
        self._pending = copy.deepcopy(snapshot["pending"])

    # Policy hooks -----------------------------------------------------------

    def _choose(self, state, candidates):
        raise NotImplementedError

    def _learn(self, pending, outcome):
        return {"applied": False, "reason": "this controller does not learn"}
