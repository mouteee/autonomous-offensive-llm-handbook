"""Candidate construction: observed surfaces times declared tools, with every
exclusion carrying its reason and its scope.

A candidate is eligible work, not permitted work -- authorization is re-asked
at dispatch regardless of what this module produced. Two exclusion scopes stay
apart on purpose: a tool the host does not have at all (host scope) and a tool
whose declared requirements this particular surface does not satisfy
(destination scope). Collapsing them turns "install the tool" and "this page
has no form" into the same row, and later lessons build habituation on the
difference.

The candidate feature vocabulary is a contract with the controllers, written
once here: `tool`, `destination`, `url`, `surface_id` and
`coverage_obligation`. `url` carries the same normalized destination string
under the name the controller lessons use for surface classing, and
`coverage_obligation` is true exactly when the host declared this identity a
coverage obligation -- the field the sparse controller's prior boost reads. A
producer that omits fields a consumer documents is a contract violation, not
a smaller candidate.
"""

from ..controller.contract import Candidate
from .policy import normalize_destination
from .records import action_identity


def _surface_decision(requires, facts):
    unmet = []
    for field, wanted in sorted(requires.items()):
        if field not in facts:
            unmet.append(f"{field}: not observed at this surface")
        elif facts[field] != wanted:
            unmet.append(f"{field}: observed {facts[field]!r}, requires {wanted!r}")
    return unmet


def build_candidates(*, policy, surfaces, unavailable_tools=(),
                     coverage=()):
    """Eligible candidates plus the excluded table, from surfaces and tools.

    `surfaces` rows carry `surface_id`, `url` and `facts` (observed fields for
    that surface). `unavailable_tools` names tools missing host-wide.
    `coverage` is a list of (tool_id, url) obligations; an obligation that
    produced no eligible candidate is reported in the excluded table rather
    than vanishing.
    """
    eligible = []
    excluded = []
    unavailable = set(unavailable_tools)
    obligations = {action_identity(tool_id, normalize_destination(url))
                   for tool_id, url in coverage}
    for surface in surfaces:
        destination = normalize_destination(surface["url"])
        for tool_id, tool in sorted(policy.tools.items()):
            identity = action_identity(tool_id, destination)
            if tool_id in unavailable:
                excluded.append({"action_id": identity, "scope": "host",
                                 "reasons": [f"tool {tool_id!r} is unavailable "
                                             "on this host"]})
                continue
            unmet = _surface_decision(tool.requires, surface.get("facts", {}))
            if unmet:
                excluded.append({"action_id": identity, "scope": "destination",
                                 "reasons": unmet})
                continue
            eligible.append(Candidate(
                candidate_id=identity, family=tool.family,
                features={"tool": tool_id, "destination": destination,
                          "url": destination,
                          "surface_id": surface["surface_id"],
                          "coverage_obligation": identity in obligations},
                priority=tool.weight, novelty=0.0, cost=tool.cost))
    satisfied = {c.candidate_id for c in eligible}
    for identity in sorted(obligations - satisfied):
        excluded.append({"action_id": identity, "scope": "coverage",
                         "reasons": ["coverage obligation without an "
                                     "eligible candidate"]})
    return {"eligible": eligible, "excluded": excluded}


def rank(candidates):
    """The documented deterministic baseline: weight per unit cost, then id.

    Same ordering rule as the fixture lab's planner and the legacy baseline
    controller, written once as a sort key so the ranking replays exactly.
    """
    return sorted(candidates,
                  key=lambda c: (-(c.priority / max(c.cost, 1e-6)),
                                 c.candidate_id))
