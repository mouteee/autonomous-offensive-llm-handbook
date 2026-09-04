# num-ok: 3.1 names the CVSS specification revision these vectors are written against, a revision identifier and not a measurement
"""CVSS 3.1 base scoring — published vectors, so a reader can check them."""
import pytest
from core.cvss import (
    parse_cvss_vector, cvss_base_score, severity_from_score, band_from_score,
)

# num-ok: 3.1 names the CVSS specification revision, the same identifier and the same reason as the module docstring above
# Published CVSS 3.1 examples. A reader can verify each against the NVD calculator.
# Third column is the DISPLAY label, fourth is the internal band — two vocabularies.
PUBLISHED = [
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", 9.8, "Critical", "critical"),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N", 7.5, "High", "high"),
    ("CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:L/I:N/A:N", 4.3, "Medium", "medium"),
    ("CVSS:3.1/AV:L/AC:H/PR:H/UI:R/S:U/C:L/I:N/A:N", 1.8, "Low", "low"),
]


@pytest.mark.parametrize("vector,score,label,band", PUBLISHED)
def test_published_vectors_score_and_land_in_both_vocabularies(vector, score, label, band):
    got = cvss_base_score(vector)
    assert got == pytest.approx(score, abs=0.05)
    assert severity_from_score(got) == label     # Title-case display label
    assert band_from_score(got) == band          # lowercase internal band


def test_roundup_is_a_ceiling_and_not_round_to_nearest():
    """CVSS round-up is a ceiling to one decimal place; Python's round() is
    round-to-nearest. An earlier draft of this test used a value where the two
    AGREE, so it passed for a round()-based implementation and did not test the
    thing its own name promised -- see the note above this test."""
    from core.cvss import _cvss_roundup
    assert _cvss_roundup(8.51) == 8.6      # round(8.51, 1) is 8.5
    assert _cvss_roundup(4.01) == 4.1      # round(4.01, 1) is 4.0
    assert _cvss_roundup(6.0) == 6.0       # already on a tick: unchanged either way


def test_a_malformed_vector_returns_none_rather_than_guessing():
    assert cvss_base_score("not-a-vector") is None
    assert cvss_base_score("CVSS:3.1/AV:N") is None          # partial
    assert cvss_base_score("") is None
    assert parse_cvss_vector("garbage") == {}


def test_the_two_vocabularies_stay_distinct_at_every_boundary():
    """severity_from_score is the CVSS display rating; band_from_score is the
    storable severity. Conflating them hands the governor an unrankable value."""
    assert severity_from_score(0.0) == "None"      # CVSS 3.1 defines a None rating
    assert band_from_score(0.0) == "info"          # the DB has no 'None' severity
    for score, label, band in [(3.9, "Low", "low"), (4.0, "Medium", "medium"),
                               (6.9, "Medium", "medium"), (7.0, "High", "high"),
                               (8.9, "High", "high"), (9.0, "Critical", "critical")]:
        assert severity_from_score(score) == label
        assert band_from_score(score) == band


def test_unscorable_input_differs_between_the_two_on_purpose():
    assert severity_from_score("garbage") == "—"   # a display placeholder
    assert band_from_score("garbage") is None      # absence, not a label
