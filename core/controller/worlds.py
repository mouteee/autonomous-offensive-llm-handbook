"""Named synthetic worlds for controller comparisons.

A world is a deterministic generator: given a seed it produces, per step, the
state features, the eligible candidates and the reward each candidate would
earn if executed. Every controller in a comparison sees the same candidates and
the same reward table at every step, so the only degree of freedom is the
choice. Rewards here are abstract numbers for exercising selection policies;
none of them measures anything about security testing.

Worlds are looked up by name, and the name travels into every trace and plot
generated from them, which is what "a named synthetic world" means in the
course chapters.
"""

import random

from .contract import Candidate


class World:
    """One synthetic world: fixed families, seeded rewards, optional drift."""

    def __init__(self, name, *, families, steps, seed, drift_at=None,
                 drifted_means=None, noise=0.1, priorities=None, costs=None,
                 delay=0, broken_families=()):
        self.name = name
        self.families = dict(families)
        self.steps = int(steps)
        self.seed = int(seed)
        self.drift_at = drift_at
        self.drifted_means = dict(drifted_means or {})
        self.noise = float(noise)
        # The host's static opinion of each family, handed identically to every
        # controller. The deterministic baselines rank by these; whether the
        # opinion happens to be right for the world is the comparison's point.
        self.priorities = dict(priorities or {f: 1.0 for f in self.families})
        self.costs = dict(costs or {f: 1.0 for f in self.families})
        # How many steps after an action its feedback is delivered. The world
        # itself only declares the delay; honoring it is the runner's job, and
        # reward totals are unaffected because only delivery timing moves.
        self.delay = int(delay)
        # Families whose tool is broken: executing them yields a tool_error
        # outcome and the shared error feedback instead of the table's reward.
        # The table still records what the family WOULD pay -- that is the
        # point of the error-pit exercise: the value is real and unreachable
        # until the tool is repaired.
        self.broken_families = frozenset(broken_families)

    def _means_at(self, step):
        if self.drift_at is not None and step >= self.drift_at:
            return {**self.families, **self.drifted_means}
        return dict(self.families)

    def episode(self):
        """Yield (step, features, candidates, rewards_by_candidate_id)."""
        rng = random.Random(self.seed)
        for step in range(self.steps):
            means = self._means_at(step)
            progress = step / max(self.steps - 1, 1)
            features = {
                "bias": 1.0,
                "stage_progress": round(progress, 6),
                "surface_known": 1.0,
                "recent_error_rate": 0.0,
                "budget_remaining": round(1.0 - progress, 6),
            }
            candidates = []
            rewards = {}
            for family in sorted(means):
                candidate_id = f"{family}:step{step}"
                candidates.append(Candidate(candidate_id=candidate_id,
                                            family=family,
                                            priority=self.priorities[family],
                                            cost=self.costs[family]))
                rewards[candidate_id] = round(
                    means[family] + rng.uniform(-self.noise, self.noise), 6)
            yield step, features, candidates, rewards

    def effective_outcome(self, candidate, table_reward):
        """What executing this candidate actually yields: (status, feedback).

        A working family pays the table; a broken family yields a tool_error
        and the shared feedback definition's answer for one -- no evidence,
        and the action's cost still spent.
        """
        from .feedback import assemble_signal, scalarize
        if candidate.family in self.broken_families:
            signal = assemble_signal(status="tool_error",
                                     novelty=candidate.novelty,
                                     cost=candidate.cost)
            return "tool_error", round(scalarize(signal), 6)
        return "clean", table_reward

    def best_fixed_family(self):
        """The best single family in hindsight, with its per-step cumulative.

        The regret baseline: replay every step, sum each family's EFFECTIVE
        rewards, and take the best total. Effective is the load-bearing word
        for the error-pit worlds: a broken family's table value is
        unreachable, so hindsight is computed over what execution actually
        yields. Returns (family, cumulative_rewards).
        """
        per_family = {}
        for _, _, candidates, rewards in self.episode():
            by_id = {c.candidate_id: c for c in candidates}
            for candidate_id, reward in rewards.items():
                family = candidate_id.split(":", 1)[0]
                _, effective = self.effective_outcome(by_id[candidate_id], reward)
                per_family.setdefault(family, []).append(effective)
        best = max(per_family, key=lambda f: (sum(per_family[f]), f))
        cumulative, total = [], 0.0
        for reward in per_family[best]:
            total += reward
            cumulative.append(round(total, 6))
        return best, cumulative


# The host's static opinion, shared by both worlds below: injection work is
# rated highest but is also the most expensive, so the priority baseline and
# the cost-aware legacy baseline disagree about it.
_STATIC_PRIORITIES = {"fam-recon": 2.0, "fam-inject": 3.0, "fam-authz": 1.0}
_STATIC_COSTS = {"fam-recon": 1.0, "fam-inject": 3.0, "fam-authz": 1.0}

WORLDS = {
    # Three families with fixed mean rewards. The steady world answers "does
    # the policy find and keep the best family", nothing subtler. The host's
    # static priorities happen to agree with this world.
    "steady-families": lambda seed=7: World(
        "steady-families",
        families={"fam-recon": 0.2, "fam-inject": 0.7, "fam-authz": 0.4},
        steps=120, seed=seed,
        priorities=_STATIC_PRIORITIES, costs=_STATIC_COSTS),
    # The best family changes partway through the episode: what was worth 0.7
    # collapses and a previously mediocre family takes over. A policy that
    # stopped exploring, or a static rank that was right yesterday, rides the
    # dead family down.
    "drifting-signal": lambda seed=7: World(
        "drifting-signal",
        families={"fam-recon": 0.2, "fam-inject": 0.7, "fam-authz": 0.4},
        steps=120, seed=seed, drift_at=60,
        drifted_means={"fam-inject": 0.1, "fam-recon": 0.8},
        priorities=_STATIC_PRIORITIES, costs=_STATIC_COSTS),
}


# A family the host rates highest that never pays, beside a paying family
# whose feedback arrives late: the pair separates policies that credit the
# action that earned the reward from policies that credit whatever ran when
# the reward happened to arrive.
_DECOY_PRIORITIES = {"fam-decoy": 9.0, "fam-pay": 2.0, "fam-side": 4.0}

WORLDS["delayed-credit"] = lambda seed=7: World(
    "delayed-credit",
    families={"fam-recon": 0.2, "fam-inject": 0.7, "fam-authz": 0.4},
    steps=60, seed=seed, delay=3,
    priorities=_STATIC_PRIORITIES, costs=_STATIC_COSTS)

WORLDS["decoy-delay"] = lambda seed=7: World(
    "decoy-delay",
    families={"fam-decoy": -0.2, "fam-pay": 0.7, "fam-side": 0.3},
    steps=60, seed=seed, delay=3,
    priorities=_DECOY_PRIORITIES)


# The error-pit pair: the same world twice, differing only in whether the
# best-paying family's tool works. Comparing controllers inside the broken
# world, then again after the repair, is the exercise the originating
# project's corrected campaign record demands: report how much of a
# controller difference is tool health rather than controller quality.
WORLDS["error-pit-broken"] = lambda seed=7: World(
    "error-pit-broken",
    families={"fam-recon": 0.2, "fam-inject": 0.7, "fam-authz": 0.4},
    steps=120, seed=seed,
    priorities=_STATIC_PRIORITIES, costs=_STATIC_COSTS,
    broken_families=("fam-inject",))

WORLDS["error-pit-repaired"] = lambda seed=7: World(
    "error-pit-repaired",
    families={"fam-recon": 0.2, "fam-inject": 0.7, "fam-authz": 0.4},
    steps=120, seed=seed,
    priorities=_STATIC_PRIORITIES, costs=_STATIC_COSTS)


def make_world(name, seed=7):
    try:
        factory = WORLDS[name]
    except KeyError:
        raise ValueError(f"unknown world {name!r}; known: {', '.join(sorted(WORLDS))}") from None
    return factory(seed)
