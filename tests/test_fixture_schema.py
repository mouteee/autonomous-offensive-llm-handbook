import pytest
from walkthrough.fixture_schema import validate_fixture, load_fixture, FIXTURE_KINDS

def _exchange():
    return {
        "kind": "exchange",
        "provenance": {"rule_id": "cors-wildcard-cap", "finding_type": "cors_misconfiguration"},
        "request": {"method": "GET", "url": "https://shop.example.com/api/orders",
                    "headers": {"Origin": "https://evil.example"}},
        "response": {"status": 200, "url": "https://shop.example.com/api/orders",
                     "headers": {"Access-Control-Allow-Origin": "*"}, "body": "{\"orders\": []}"},
    }

def test_a_well_formed_exchange_validates():
    assert validate_fixture(_exchange()) == []

def test_kinds_are_closed():
    bad = dict(_exchange(), kind="screenshot")
    assert any("kind" in p for p in validate_fixture(bad))
    assert FIXTURE_KINDS == ("exchange", "insights")

@pytest.mark.parametrize("field", ["host", "client", "scan_id", "url"])
def test_provenance_refuses_identifying_fields(field):
    """Provenance names the rule that fired, never who it fired against."""
    bad = _exchange()
    bad["provenance"][field] = "anything"
    problems = validate_fixture(bad)
    assert any(field in p for p in problems), f"provenance accepted {field}"

def test_a_missing_response_status_is_named_not_defaulted():
    bad = _exchange(); del bad["response"]["status"]
    assert any("response.status" in p for p in validate_fixture(bad))

def test_insights_fixture_needs_at_least_three_entries():
    """One insight triggers the critic's forced-keep floor, which masks containment.

    Measured on the shipped module: score_grounded with a single insight returns it with
    critic_forced_keep True and dropped empty, so a one-item fixture would show a reader
    everything kept regardless of scoring. Three insights drop two and keep one.
    """
    two = {"kind": "insights", "provenance": {"rule_id": "critic-containment",
           "finding_type": "insight"}, "intel_context": "ctx",
           "insights": [{"insight": "a", "refs": []}, {"insight": "b", "refs": []}]}
    assert any("three" in p for p in validate_fixture(two))
