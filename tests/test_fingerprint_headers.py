"""Header lookups in core/fingerprint.py read any legal casing.

num-ok: 7230 is the number of the RFC that specifies HTTP header fields, a document identifier and not a measurement
Header field names are case-insensitive per RFC 7230, so a response is free to
send any casing.

This file exists because the fingerprinter answered "nginx" for a canonically
spelled Server header and "unknown" for the same header spelled ``sErVeR``,
which is a wrong answer on legal input rather than a documented narrowness:
the module's direct header lookups tried two exact spellings each.

The docstring on ``analyze`` had claimed case-insensitivity all along, which is
the one shape where narrowing the prose is the wrong fix -- the claim was
right and the code was what was out of step. These tests pin the code so the
claim can stay broad, and they assert the DETECTED VALUE rather than merely
that the three casings agree: three spellings that all resolve to "unknown"
agree too, and an equality-only test would pass on the very bug it was written
for.
"""
from core.fingerprint import Fingerprinter

SERVER_CASINGS = ("Server", "server", "sErVeR")
AUTH_CASINGS = ("Authorization", "authorization", "AUTHORIZATION")
CHALLENGE_CASINGS = ("WWW-Authenticate", "www-authenticate", "WwW-AuThEnTiCaTe")


def _profile(headers, body="", url="https://probe.test/"):
    return Fingerprinter().analyze(headers, body, url)


def test_the_server_header_is_read_in_any_casing():
    """Every casing must resolve to the vendor, and no header must not.

    The absent-header case is what keeps this from passing vacuously: it fixes
    what "not detected" looks like, so the three positive assertions cannot be
    satisfied by a default.
    """
    detected = {c: _profile({c: "nginx-probe"}).server_software for c in SERVER_CASINGS}
    assert set(detected.values()) == {"nginx"}, detected
    assert _profile({}).server_software == "unknown"


def test_a_blank_spelling_cannot_mask_a_real_server_header():
    """A duplicate name with an empty value is skipped, in either order.

    Normalising the keys collapses two spellings of one name into a single
    entry, so without the empty-value skip the answer would depend on dict
    insertion order. Both orders are asserted because only one of them
    regresses.
    """
    assert _profile({"Server": "", "server": "nginx-probe"}).server_software == "nginx"
    assert _profile({"server": "nginx-probe", "Server": ""}).server_software == "nginx"


def test_the_authorization_and_challenge_headers_are_read_in_any_casing():
    """The other two direct lookups, and the negative for each.

    Both used the same two-spelling shape as the Server lookup, so both are
    pinned here rather than left to be found again. The negatives matter for
    the same reason as above: a bearer challenge must not be read as basic,
    and no Authorization header at all must leave jwt undetected.
    """
    for casing in AUTH_CASINGS:
        profile = _profile({casing: "Bearer eyJhbGciOiJIUzI1NiJ9.e30.x"})
        assert profile.jwt_detected is True, casing
        assert "jwt" in profile.auth_mechanisms, casing
    assert _profile({}).jwt_detected is False

    for casing in CHALLENGE_CASINGS:
        profile = _profile({casing: 'Basic realm="probe"'})
        assert "basic" in profile.auth_mechanisms, casing
    assert "basic" not in _profile({"WWW-Authenticate": 'Bearer realm="probe"'}).auth_mechanisms


def test_the_regex_and_security_header_paths_were_already_case_blind():
    """The paths that were never broken, asserted so the claim covers them.

    ``analyze``'s docstring now claims case-insensitivity on every path. Two of
    those paths reach the headers a different way -- a re.I regex over the
    serialised dict, and a lowercased copy of the keys -- and neither is
    exercised by the lookups above, so a regression in either would leave the
    restored claim false with every test still green.
    """
    assert _profile({"x-POWERED-by": "PHP/8.1"}).backend_language == "php"
    assert _profile({"X-Powered-By": "PHP/8.1"}).backend_language == "php"
    upper = _profile({"CONTENT-SECURITY-POLICY": "default-src 'self'"})
    lower = _profile({"content-security-policy": "default-src 'self'"})
    assert upper.security_headers == lower.security_headers
    assert upper.security_headers.get("Content-Security-Policy") is True
