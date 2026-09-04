"""The gate-check tree: 'found nothing' and 'could not reach anything' differ."""
import pytest
from core.gate_check import decide_gate_status

FULLY_BLOCKED = {"total_responses": 1, "error_rate": 1.0, "waf_detected": True,
                 "parameters_found": 0, "forms_found": 0}
HIGH_ERROR = {"error_rate": 0.9, "parameters_found": 0, "forms_found": 0}
STATIC_ONLY = {"pages_crawled": 9, "forms_found": 0, "parameters_found": 1, "scripts_found": 0}
RICH = {"pages_crawled": 40, "forms_found": 3, "parameters_found": 12, "scripts_found": 8}


@pytest.mark.parametrize("inputs,status,stages", [
    (FULLY_BLOCKED, "gated", ["baseline_passive"]),
    (HIGH_ERROR, "gated_soft", ["baseline_passive"]),
    (STATIC_ONLY, "limited", ["baseline_passive", "cache_cors_csp"]),
    (RICH, "proceed", ["full"]),
])
def test_the_four_outcomes(inputs, status, stages):
    out = decide_gate_status(inputs)
    assert out["status"] == status
    assert out["allowed_stages"] == stages


def test_an_empty_input_proceeds_and_that_is_the_fail_open():
    out = decide_gate_status({})
    assert out["status"] == "proceed"
    assert out["allowed_stages"] == ["full"]


def test_branch_order_is_load_bearing():
    """A fully-blocked target also satisfies the high-error branch. It must
    return `gated`, the more specific outcome, not `gated_soft`."""
    assert decide_gate_status(FULLY_BLOCKED)["status"] == "gated"


GATED_SOFT_LIMITED_OVERLAP = {"error_rate": 0.9, "parameters_found": 0,
                              "forms_found": 0, "scripts_found": 0,
                              "pages_crawled": 5}


def test_gated_soft_outranks_limited_on_their_overlap():
    """`gated_soft` and `limited` overlap: a high error rate with no surface
    (`error_rate > 0.8`, no params or forms) that still crawled a few pages
    satisfies both branch conditions at once. `gated_soft` is the stricter
    outcome -- `baseline_passive` only -- so it must be checked first; swapping
    them would report this target as `limited` and grant it `cache_cors_csp`."""
    out = decide_gate_status(GATED_SOFT_LIMITED_OVERLAP)
    assert out["status"] == "gated_soft"
    assert out["allowed_stages"] == ["baseline_passive"]


def test_the_decision_is_pure_and_replayable():
    a = decide_gate_status(dict(STATIC_ONLY))
    b = decide_gate_status(dict(STATIC_ONLY))
    assert a == b


def test_evidence_echoes_every_input_consulted():
    out = decide_gate_status(STATIC_ONLY)
    for key in ("waf_detected", "total_responses", "error_rate", "parameters_found",
                "forms_found", "pages_crawled", "scripts_found"):
        assert key in out["evidence"]
