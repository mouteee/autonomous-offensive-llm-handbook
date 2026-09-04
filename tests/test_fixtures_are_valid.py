import pathlib
import re

from walkthrough.fixture_schema import load_fixture, validate_fixture

FIXTURES = sorted((pathlib.Path(__file__).resolve().parents[1] / "walkthrough" / "fixtures").glob("*.json"))


def test_the_fixture_set_is_not_empty_and_every_fixture_validates():
    assert FIXTURES, "no fixtures committed"
    for p in FIXTURES:
        assert validate_fixture(load_fixture(p)) == [], f"{p.name}: {validate_fixture(load_fixture(p))}"


def test_exactly_one_insights_fixture_and_it_has_three_or_more():
    kinds = [load_fixture(p)["kind"] for p in FIXTURES]
    assert kinds.count("insights") == 1
    ins = [load_fixture(p) for p in FIXTURES if load_fixture(p)["kind"] == "insights"][0]
    assert len(ins["insights"]) >= 3


def test_at_least_six_exchange_fixtures_are_committed():
    kinds = [load_fixture(p)["kind"] for p in FIXTURES]
    assert kinds.count("exchange") >= 6, kinds


# The identifier sweep, kept here rather than imported, because the tool that
# regenerated these files lives in a private repository and a public clone has
# no access to it. The shapes are the ones the regeneration is held to: an
# email address, a run of six or more digits, a JWT, and any hostname outside
# the reserved suffixes. Filenames are excluded by extension, or every SPA
# shell carrying `main.js` reads as a host.
_RESERVED_HOST_SUFFIXES = (".example.com", ".example", ".invalid")
_FILE_EXTENSIONS = frozenset((
    "js", "json", "css", "html", "htm", "map", "png", "jpg", "jpeg", "gif",
    "svg", "ico", "txt", "xml", "md", "py", "sh", "log", "csv", "pdf", "yml",
    "yaml", "ts", "php", "asp", "aspx", "jsp", "do",
))
_SHAPES = (
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("six-or-more digits", re.compile(r"\d{6,}")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}")),
)
_HOSTISH = re.compile(r"\b(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}\b")


def _foreign_hostnames(text):
    out = []
    for match in _HOSTISH.finditer(text):
        token = match.group(0).lower()
        if token.endswith(_RESERVED_HOST_SUFFIXES) or token == "example.com":
            continue
        if token.rsplit(".", 1)[-1] in _FILE_EXTENSIONS:
            continue
        out.append(match.group(0))
    return out


def test_no_committed_fixture_carries_an_identifier_shape():
    """A positive sweep over the bytes, not a denylist over known strings.

    A denylist cannot catch an identifier nobody enumerated, which is why these files are
    regenerated rather than redacted. This is the same property from the other side: whatever
    a regeneration missed still has to look like nothing -- no email address, no long run of
    digits, no JWT, and no hostname outside the reserved example and invalid suffixes.
    """
    problems = []
    for path in FIXTURES:
        text = path.read_text(encoding="utf-8")
        for name, pattern in _SHAPES:
            problems += [f"{path.name}: {name}: {m}" for m in pattern.findall(text)]
        problems += [f"{path.name}: hostname: {h}" for h in _foreign_hostnames(text)]
    assert problems == [], "identifier shapes in committed fixtures:\n" + "\n".join(problems)


def test_the_evidence_ceiling_fixture_carries_no_capture_to_attach():
    """The one fixture whose point is a THIN grade must ship nothing a driver can attach.

    `expected.attach_exchange_evidence: false` was a note in a dictionary that nothing
    read: a driver that attached the exchange anyway graded the finding `strong`, no
    ceiling fired, and the fixture demonstrated the opposite of its purpose on a green
    run. The contract asks only that `method` and `url` be truthy on the request and that
    `status` and `url` be present on the response, so this fixture carries exactly those
    -- no body, no headers, no cookies. A comment cannot fail; this assertion can.
    """
    ceiling = [load_fixture(p) for p in FIXTURES
               if load_fixture(p).get("provenance", {}).get("rule_id") == "evidence-ceiling"]
    assert len(ceiling) == 1, "expected exactly one evidence-ceiling fixture"
    fixture = ceiling[0]
    assert set(fixture["request"]) == {"method", "url"}, fixture["request"]
    assert set(fixture["response"]) == {"status", "url"}, fixture["response"]
    assert fixture["expected"]["attach_exchange_evidence"] is False
