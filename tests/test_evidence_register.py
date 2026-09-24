"""Editorial tripwires for the evidence register in appendix F.

The register's job is keeping execution, analysis, review and public
reproducibility apart, and preserving the corrected readings of the
originating-project studies. These tests hold the register to that job the same
way test_public_guidance.py holds the five laws: fixed review decisions, pinned
verbatim, so a rewrite that softens a correction or drops a status column
reddens a test instead of shipping.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "handbook" / "appendix-f-evidence-register.md"


def chapter_claim(chapter, *sentences):
    """Anchor a test to the verbatim chapter sentence(s) it backs.

    Same declaration shape as tests/test_chapter_claims.py: verify_claims.sh's
    Check C parses these decorators from every tests/**/*.py file and fails
    when a declared sentence is no longer present in its chapter.
    """
    def deco(fn):
        return fn
    return deco


def _cards(text):
    """Split the register into its per-study cards, keyed by heading."""
    cards = {}
    heading = None
    for line in text.splitlines():
        if line.startswith("### "):
            heading = line[4:].strip()
            cards[heading] = []
        elif heading is not None and line.startswith("## "):
            heading = None
        elif heading is not None:
            cards[heading].append(line)
    return {k: "\n".join(v) for k, v in cards.items()}


@chapter_claim(
    "handbook/appendix-f-evidence-register.md",
    "Each card below carries its own execution status, analysis status, review "
    "status and public reproducibility status, and they move independently",
)
def test_every_card_reports_its_statuses_separately():
    cards = _cards(REGISTER.read_text(encoding="utf-8"))
    assert len(cards) >= 4, sorted(cards)
    for heading, body in cards.items():
        for field in ("Execution", "Analysis", "Review"):
            assert f"{field}:" in body, (heading, field)


@chapter_claim(
    "handbook/appendix-f-evidence-register.md",
    "The first confirmatory run's recorded verdict is insufficient_nontied_targets",
    "That verdict means neither \"never run\" nor \"no effect\" nor \"confirmed "
    "benefit\", and each of those three misreadings has to be refused separately.",
)
def test_the_habituation_confirmatory_verdict_is_preserved_verbatim():
    text = REGISTER.read_text(encoding="utf-8")
    assert "`insufficient_nontied_targets`" in text


@chapter_claim(
    "handbook/appendix-f-evidence-register.md",
    "records effective ties between the static sparse controller, its learning "
    "variant and the linear bandit on valid investigation outcomes",
    "no general superiority claim survives the correction",
)
def test_the_controller_campaign_correction_is_preserved():
    body = _cards(REGISTER.read_text(encoding="utf-8"))["Live controller campaigns"]
    assert "tool-error" in body


@chapter_claim(
    "handbook/appendix-f-evidence-register.md",
    "the loop behind it used a random toy graph fixture, correcting an earlier "
    "attribution to measured topology",
    "it does not establish an advantage from measured biological topology",
)
def test_the_graph_mechanism_correction_is_preserved():
    body = _cards(REGISTER.read_text(encoding="utf-8"))[
        "Graph and plasticity mechanism studies"]
    assert "rejected or parked" in body


@chapter_claim(
    "handbook/appendix-f-evidence-register.md",
    "the instrumentation objective passed in both",
    "the detectability gate failed in both",
    "the planned larger sweep was not approved",
)
def test_the_cognition_pilots_gate_outcome_is_preserved():
    body = _cards(REGISTER.read_text(encoding="utf-8"))["Real-model cognition pilots"]
    assert "twice-failed detectability gate" in body


@chapter_claim(
    "handbook/appendix-f-evidence-register.md",
    "not executed as of the register date, on either orchestration path",
    "none of them retroactively answers this card's question",
)
def test_the_unrun_ranking_study_stays_a_dated_claim():
    body = _cards(REGISTER.read_text(encoding="utf-8"))[
        "The scheduler and ranking ablation"]
    assert "not executed" in body


@chapter_claim(
    "handbook/appendix-f-evidence-register.md",
    "It does not convert a recorded model-blinded analysis into human review.",
    "It does not treat access to a research log as a fresh recomputation.",
)
def test_the_register_refusals_stay_in_the_register():
    text = REGISTER.read_text(encoding="utf-8")
    assert "## Claim boundaries" in text
