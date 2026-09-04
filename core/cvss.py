# num-ok: 3.1 names the CVSS specification revision this module scores against, a revision identifier and not a measurement
"""CVSS 3.1 base scoring: the metric-weight tables, the exploitability and
impact sub-formulas, and the official round-up rule, so a score is
reproducible by a reader holding nothing but this file and a copy of the
specification.

Two severity vocabularies live here, and neither stands in for the other.
``severity_from_score`` returns the Title-case rating a report shows a
person -- "None", "Low", "Medium", "High", "Critical". ``band_from_score``
returns the lowercase word a store can hold and a governor can rank --
"info", "low", "medium", "high", "critical". A governor built to compare
severities reads only the second vocabulary; handing it the first leaves it
holding a string it has no ordering for.

A vector missing a required metric, or carrying no recognizable metric at
all, scores to ``None`` rather than a guessed number -- ``cvss_base_score``
and ``parse_cvss_vector`` never raise on malformed input, they refuse it.

Round-up is CVSS's own rule, not Python's ``round()``: the base score is
the smallest value, at one decimal place, that is not lower than the raw
result -- a ceiling, never a round to the nearest tenth. ``round()`` rounds
to nearest instead, so the two routinely disagree, and every disagreement
lands ``round()``'s answer exactly one tick below what CVSS requires.
"""
from typing import Optional

# The eight CVSS base metrics, in the order both the vector string and the
# breakdown table below use.
_METRIC_ORDER = ("AV", "AC", "PR", "UI", "S", "C", "I", "A")

_AV_WEIGHTS = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.20}
_AC_WEIGHTS = {"L": 0.77, "H": 0.44}
_UI_WEIGHTS = {"N": 0.85, "R": 0.62}

# Privileges Required is the one exploitability metric Scope also shapes: a
# Changed-scope PR:L or PR:H carries a higher weight than the identical
# letter under Unchanged scope, because Scope:Changed already means the
# exploit's effect reaches past the boundary those privileges were meant to
# hold it inside.
_PR_WEIGHTS = {
    "U": {"N": 0.85, "L": 0.62, "H": 0.27},
    "C": {"N": 0.85, "L": 0.68, "H": 0.50},
}

# Confidentiality, Integrity and Availability share one weight table --
# CVSS scores all three impact metrics on the same scale.
_CIA_WEIGHTS = {"H": 0.56, "L": 0.22, "N": 0.0}

# Metric name and per-value human label, for cvss_breakdown's report rows.
_METRIC_LABELS = {
    "AV": ("Attack Vector", {"N": "Network", "A": "Adjacent", "L": "Local", "P": "Physical"}),
    "AC": ("Attack Complexity", {"L": "Low", "H": "High"}),
    "PR": ("Privileges Required", {"N": "None", "L": "Low", "H": "High"}),
    "UI": ("User Interaction", {"N": "None", "R": "Required"}),
    "S":  ("Scope", {"U": "Unchanged", "C": "Changed"}),
    "C":  ("Confidentiality", {"H": "High", "L": "Low", "N": "None"}),
    "I":  ("Integrity", {"H": "High", "L": "Low", "N": "None"}),
    "A":  ("Availability", {"H": "High", "L": "Low", "N": "None"}),
}


def parse_cvss_vector(vector: str) -> dict:
    """Split a ``Metric:Value/Metric:Value/...`` string into {metric: value}.

    Only the eight recognized base-metric keys are kept; an unrecognized
    segment -- the leading version marker, a temporal or environmental
    metric, stray text -- is silently skipped rather than rejected, so a
    caller never has to strip anything before parsing. Returns ``{}`` for
    input with no recognizable segment at all, including a non-string or an
    empty argument.
    """
    metrics = {}
    for segment in str(vector or "").strip().split("/"):
        key, _, value = segment.partition(":")
        key, value = key.strip().upper(), value.strip().upper()
        if value and key in _METRIC_ORDER:
            metrics[key] = value
    return metrics


def _cvss_roundup(value: float) -> float:
    """CVSS's own round-up rule: the smallest value, at one decimal place,
    that is not lower than the raw input -- a ceiling, not a round to the
    nearest tenth.

    Working in scaled integers keeps the comparison exact regardless of
    binary floating-point representation. Python's round() rounds to
    nearest instead, so it never matches this rule's answer except where
    the input already happens to round up on its own -- everywhere else it
    lands exactly one tick low.
    """
    scaled = int(round(value * 100000))
    if scaled % 10000 == 0:
        return scaled / 100000.0
    return (scaled // 10000 + 1) / 10.0


def cvss_base_score(vector: str) -> Optional[float]:
    """Compute the CVSS base score for a vector string.

    Returns ``None`` -- never raises, never guesses -- when the vector is
    missing any of the eight required metrics, or carries an unrecognized
    value for one of them.
    """
    metrics = parse_cvss_vector(vector)
    if not all(key in metrics for key in _METRIC_ORDER):
        return None
    try:
        scope = metrics["S"]
        impact_subscore = 1 - (
            (1 - _CIA_WEIGHTS[metrics["C"]])
            * (1 - _CIA_WEIGHTS[metrics["I"]])
            * (1 - _CIA_WEIGHTS[metrics["A"]])
        )
        if scope == "U":
            impact = 6.42 * impact_subscore
        else:
            impact = (7.52 * (impact_subscore - 0.029)
                      - 3.25 * (impact_subscore - 0.02) ** 15)
        exploitability = (8.22 * _AV_WEIGHTS[metrics["AV"]] * _AC_WEIGHTS[metrics["AC"]]
                           * _PR_WEIGHTS[scope][metrics["PR"]] * _UI_WEIGHTS[metrics["UI"]])
        if impact <= 0:
            return 0.0
        combined = impact + exploitability
        raw_score = combined if scope == "U" else 1.08 * combined
        return _cvss_roundup(min(raw_score, 10.0))
    except (KeyError, ValueError):
        return None


def severity_from_score(score) -> str:
    """The Title-case CVSS rating for display: None, Low, Medium, High or Critical.

    CVSS defines "None" as the rating at exactly 0.0 -- that is the correct
    label there, not a sloppy placeholder. Input that will not convert to a
    float returns the em-dash "—" instead, so a report can print a rating
    column with no separate branch for the unscored case.
    """
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "—"
    if value == 0:
        return "None"
    if value < 4.0:
        return "Low"
    if value < 7.0:
        return "Medium"
    if value < 9.0:
        return "High"
    return "Critical"


def band_from_score(score):
    """The lowercase severity band a store holds and a governor ranks:
    info, low, medium, high or critical.

    The boundaries match severity_from_score's exactly, but the vocabulary
    is the other one -- the word a database column stores and a governor
    orders, never the word a report displays. Unscorable input returns
    None, an absence rather than a label, because a governor must be able
    to tell "cannot rank this" apart from a real band.
    """
    try:
        value = float(score)
    except (TypeError, ValueError):
        return None
    if value == 0:
        return "info"
    if value < 4.0:
        return "low"
    if value < 7.0:
        return "medium"
    if value < 9.0:
        return "high"
    return "critical"


def cvss_risk_label(score) -> str:
    """A score paired with a plain-language risk word, for prose display.

    Uses severity_from_score's own thresholds but writes the number into
    the sentence itself rather than returning the tier name alone --
    "<score> — <Tier> Risk". Below the lowest tier's floor, or on input
    that will not parse as a float at all, this falls back to echoing the
    original value back as text, or to "Not scored" when that value is
    itself empty, zero, or otherwise falsy.
    """
    try:
        value = float(score)
        if value >= 9.0:
            return f"{score} — Critical Risk"
        if value >= 7.0:
            return f"{score} — High Risk"
        if value >= 4.0:
            return f"{score} — Medium Risk"
        if value >= 0.1:
            return f"{score} — Low Risk"
    except (TypeError, ValueError):
        pass
    return str(score) if score and score != "—" else "Not scored"


def cvss_breakdown(vector: str):
    """[(metric name, human-readable value), ...] for a vector's report display.

    Only the metrics present in the parsed vector are returned, in the
    fixed AV/AC/PR/UI/S/C/I/A order; a recognized metric whose value has no
    human label on record is passed through as the raw letter instead.
    """
    metrics = parse_cvss_vector(vector)
    rows = []
    for key in _METRIC_ORDER:
        if key in metrics:
            label, values = _METRIC_LABELS[key]
            rows.append((label, values.get(metrics[key], metrics[key])))
    return rows
