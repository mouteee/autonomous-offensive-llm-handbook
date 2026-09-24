"""The operational stage machine, and its mapping onto the teaching harness.

An operational run moves through seven stages -- discovery, detection,
crawling, mining, scanning, active_testing, reporting -- while the fixture lab
teaches five: observe, plan, execute, review, report. The two vocabularies
describe the same run at different resolutions, and `HARNESS_MAPPING` writes
the correspondence down as data so the lessons can show it instead of waving at
it. Advancement is positional and prerequisite-gated in host code; the machine
answers refusals as recorded decisions, so an out-of-order transition leaves
evidence rather than an exception trace.
"""

OPERATIONAL_STAGES = (
    "discovery",
    "detection",
    "crawling",
    "mining",
    "scanning",
    "active_testing",
    "reporting",
)

# Which teaching-harness stage(s) each operational stage corresponds to. The
# first three all sit inside "observe": they gather what is true before any
# selection happens. Reporting covers both "review" and "report" -- in the
# operational vocabulary, findings review happens while the report is being
# assembled, which is a simplification the lesson labels.
HARNESS_MAPPING = {
    "discovery": ("observe",),
    "detection": ("observe",),
    "crawling": ("observe",),
    "mining": ("plan",),
    "scanning": ("execute",),
    "active_testing": ("execute",),
    "reporting": ("review", "report"),
}

# The stages in which dispatch may run an action at all: the two that map onto
# the teaching harness's "execute". Everything earlier is looking and planning;
# everything later is writing the report about what already ran.
EXECUTABLE_STAGES = ("scanning", "active_testing")


def dispatch_admission(recorder, policy, tool_id):
    """Why the run's recorded gate and stage refuse this dispatch, or None.

    This is the door's own reading of shared state, deliberately independent
    of whoever sequenced the run: a recorded stop gate refuses every tool, a
    passive gate refuses active tools, a staged run outside its executable
    stages dispatches nothing, and a staged run that never recorded a gate
    decision dispatches nothing either -- the same rules the fixture harness
    enforces inside its execute step. A bare component run with no stage
    machine and no gate has no gate state to enforce; composing one in is the
    host's assembly step, and budgets still apply either way.
    """
    stage = recorder.stage
    if stage is not None and stage not in EXECUTABLE_STAGES:
        return (f"stage {stage!r} does not execute actions; dispatch is "
                f"admitted only in {' or '.join(EXECUTABLE_STAGES)}")
    gate = recorder.gate
    if stage is not None and gate is None:
        return ("a staged run has no recorded gate decision; testing "
                "callbacks are not admitted without one")
    if gate is not None:
        if gate["mode"] == "stop":
            return "gate mode stop admits no testing callbacks"
        tool = policy.tools.get(tool_id)
        if gate["mode"] == "passive" and tool is not None and \
                tool.activity == "active":
            return "gate mode passive excludes active callbacks"
    return None


def measured(field, value, source):
    """An observation with a value and the source it was measured from."""
    return {"field": field, "value": value, "state": "measured",
            "source": source}


def unknown(field):
    """An observation whose value is honestly absent. Unknown is not false."""
    return {"field": field, "value": None, "state": "unknown", "source": ""}


def observations_from_response(name, response):
    """Toy extractors from one fixture response into observation records.

    The same deliberate shape as the fixture lab's extractors: derived,
    labeled, and not claims that a crawler or browser ran. A port replaces
    these with defined observation semantics and tests.
    """
    body = response.get("body", "")
    status = response.get("status")
    rows = [
        measured(f"{name}_status", status, f"fixture:{name}"),
        measured(f"{name}_has_form", "<form" in body, f"fixture:{name}"),
        measured(f"{name}_has_script", "<script" in body, f"fixture:{name}"),
    ]
    return rows


def requirements_met(requires, observations):
    """Whether every required observed field is measured with the wanted value.

    Answers a decision record with the unmet requirements listed. An unknown
    observation does not satisfy a requirement -- that is the whole difference
    between unknown and false -- and a field nobody observed at all is its own
    reason, distinct from a measured mismatch.
    """
    unmet = []
    for field, wanted in sorted(requires.items()):
        row = observations.get(field)
        if row is None:
            unmet.append(f"{field}: not observed")
        elif row["state"] != "measured":
            unmet.append(f"{field}: unknown")
        elif row["value"] != wanted:
            unmet.append(f"{field}: measured {row['value']!r}, requires {wanted!r}")
    return {"allowed": not unmet, "reason": "requirements met" if not unmet
            else "; ".join(unmet)}


class StageMachine:
    """Positional, prerequisite-gated advancement through the seven stages."""

    def __init__(self, recorder):
        self.recorder = recorder
        self._index = 0
        recorder.record("stage", {"run_id": recorder.run.run_id,
                                  "stage": OPERATIONAL_STAGES[0]})

    @property
    def current(self):
        return OPERATIONAL_STAGES[self._index]

    def _prerequisite(self, stage):
        """The declared entry condition for a stage, as a decision record."""
        if stage == "detection" and not self.recorder.observations:
            return {"allowed": False,
                    "reason": "detection requires at least one recorded "
                              "observation"}
        if stage in ("scanning", "active_testing"):
            gate = self.recorder.gate
            if gate is None:
                return {"allowed": False,
                        "reason": f"{stage} requires a recorded gate decision"}
            if stage == "active_testing" and gate["status"] not in ("proceed",
                                                                    "limited"):
                return {"allowed": False,
                        "reason": "active_testing requires a gate status of "
                                  "proceed or limited"}
        return {"allowed": True, "reason": "prerequisites satisfied"}

    def advance(self, stage):
        """Move to `stage` if it is next in order and its prerequisites hold.

        The answer is a decision record either way, and a refusal is recorded
        through the write boundary: the run's story carries the transition it
        declined, with the reason, next to the ones it made.
        """
        expected = (OPERATIONAL_STAGES[self._index + 1]
                    if self._index + 1 < len(OPERATIONAL_STAGES) else None)
        if stage != expected:
            reason = (f"stage {stage!r} is not the next declared stage "
                      f"(expected {expected!r})")
            self.recorder.refuse("stage", reason, {"run_id": None, "stage": stage})
            return {"allowed": False, "reason": reason}
        gate = self._prerequisite(stage)
        if not gate["allowed"]:
            self.recorder.refuse("stage", gate["reason"],
                                 {"run_id": None, "stage": stage})
            return gate
        self._index += 1
        self.recorder.record("stage", {"run_id": self.recorder.run.run_id,
                                       "stage": stage})
        return {"allowed": True, "reason": "advanced",
                "harness_stages": list(HARNESS_MAPPING[stage])}
