"""Editorial tripwires for reviewed public guidance, not semantic fact checking."""

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def laws(text):
    return {
        int(line[0]): line
        for line in text.splitlines()
        if len(line) > 5 and line[0].isdigit() and line[1:5] == ". **"
    }


def check_reviewed_limits(text):
    # Fixed review decisions, not copies read from the other publication.
    # Rewording requires review; this does not discover arbitrary false prose.
    found = laws(text)
    assert "A shared writer is not a sandbox." in found[1]
    assert "The law is not permission to execute every proposal." in found[2]
    assert "Under-reporting can hide a real vulnerability" in found[3]
    assert "A quote alone is not exploitability proof." in found[3]
    assert "transport containment still belongs in the adapter" in found[4]
    assert "that denominator does not measure vulnerability coverage" in found[5]


@pytest.mark.parametrize("rel", ["README.md", "handbook/00-thesis.md"])
def test_canonical_law_explanations_keep_reviewed_limits(rel):
    check_reviewed_limits((ROOT / rel).read_text())


@pytest.mark.parametrize("limit", [
    "A shared writer is not a sandbox.",
    "The law is not permission to execute every proposal.",
    "Under-reporting can hide a real vulnerability",
    "A quote alone is not exploitability proof.",
    "transport containment still belongs in the adapter",
    "that denominator does not measure vulnerability coverage",
])
def test_removing_a_reviewed_limit_breaks_the_editorial_check(limit):
    text = (ROOT / "README.md").read_text()
    assert text.count(limit) == 1
    with pytest.raises(AssertionError):
        check_reviewed_limits(text.replace(limit, "", 1))


def test_public_prose_uses_author_neutral_attribution():
    # Specific private identities belong in the untracked publication denylist,
    # never in a public test. This checked-in guard instead pins the neutral
    # attribution policy and refuses common reintroductions of a byline.
    byline_markers = ("\n## Author\n", "\nAuthor: ", "\nWritten by ", "\n© ")
    files = [ROOT / "README.md", ROOT / "LICENSE",
             *(ROOT / "handbook").glob("*.md"), *(ROOT / "rendered").glob("*.md")]
    for path in files:
        text = path.read_text()
        for marker in byline_markers:
            assert marker not in text, (path.name, marker)
    assert "Copyright (c) 2026 the handbook author" in (ROOT / "LICENSE").read_text()


def test_recommended_lab_is_linked_as_source_and_rendered_chapter():
    readme = (ROOT / "README.md").read_text()
    for prefix in ("handbook", "rendered"):
        relative = f"{prefix}/07-harness-lab.md"
        assert f"]({relative})" in readme
        assert (ROOT / relative).is_file()


def test_current_raise_reference_names_an_existing_method():
    from harness.runtime import Harness

    chapter = (ROOT / "handbook/06-build-your-own.md").read_text()
    assert "`Harness.verify_raise`" in chapter
    assert callable(Harness.verify_raise)
