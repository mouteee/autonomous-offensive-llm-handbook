"""The shared feedback signal every controller learns from.

One definition, used by every controller in every comparison. A signal is
assembled from an executed action's recorded facts, component by component, and
then scalarized under a named weight version. Publishing the components beside
the scalar is the point: a reader can see which term moved a reward, and a
comparison between controllers cannot quietly use two different reward
definitions.

An evidence grade here measures what the record supports, not ground-truth
security value; the evidence lessons carry that distinction.
"""

from dataclasses import dataclass


WEIGHTS_VERSION = "feedback-v1"

# Component weights, versioned. Changing a weight is a new version: recorded
# feedback values name the version they were computed under, so an old trace
# stays interpretable after a retune.
WEIGHTS = {
    "feedback-v1": {
        "evidence_value": 1.0,
        "information_gain": 0.5,
        "novelty": 0.25,
        "falsification": 0.25,
        "duplicate_work": -0.5,
        "resource_cost": -0.25,
        "policy_pressure": -1.0,
    },
}

# How much evidence each outcome status is worth on its own. Statuses that
# report the host's bookkeeping rather than the target's behavior are worth
# nothing, deliberately: an unavailable tool is not a discovery about the
# target, and an unresolved execution is not a success.
EVIDENCE_VALUE_BY_STATUS = {
    "verified_evidence": 1.0,
    "clean": 0.2,
    "tool_error": 0.0,
    "tool_unavailable": 0.0,
    "skipped": 0.0,
    "unresolved": 0.0,
}


@dataclass(frozen=True)
class FeedbackSignal:
    """The named components behind one scalar feedback value."""

    evidence_value: float
    information_gain: float
    novelty: float
    falsification: float
    duplicate_work: float
    resource_cost: float
    policy_pressure: float
    weights_version: str = WEIGHTS_VERSION

    def components(self):
        return {
            "evidence_value": self.evidence_value,
            "information_gain": self.information_gain,
            "novelty": self.novelty,
            "falsification": self.falsification,
            "duplicate_work": self.duplicate_work,
            "resource_cost": self.resource_cost,
            "policy_pressure": self.policy_pressure,
        }


def assemble_signal(*, status, new_observations=0, novelty=0.0,
                    refuted_hypothesis=False, repeats_prior_work=False,
                    cost=0.0, policy_pressure=0.0):
    """Build the signal for one executed action from its recorded facts."""
    if status not in EVIDENCE_VALUE_BY_STATUS:
        raise ValueError(f"unknown outcome status {status!r}")
    return FeedbackSignal(
        evidence_value=EVIDENCE_VALUE_BY_STATUS[status],
        information_gain=min(1.0, 0.25 * max(0, int(new_observations))),
        novelty=max(0.0, min(1.0, float(novelty))),
        falsification=1.0 if refuted_hypothesis else 0.0,
        duplicate_work=1.0 if repeats_prior_work else 0.0,
        resource_cost=max(0.0, float(cost)),
        policy_pressure=max(0.0, min(1.0, float(policy_pressure))),
    )


def scalarize(signal):
    """One number from the components, under the signal's weight version."""
    weights = WEIGHTS[signal.weights_version]
    return sum(weights[name] * value
               for name, value in signal.components().items())
