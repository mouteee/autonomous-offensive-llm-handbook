"""The starter exercises' contract, held by the reference suite.

The reader review's acceptance rule for the build-it-yourself path: a fresh
clone must NOT already satisfy a lesson's learner-owned completion check, and
the worked solution must. These tests run each pilot's check in a separate
process both ways, so the reference suite guarantees the exercises stay real
exercises -- failing before the learner's edit, passing after it -- without
ever collecting them into itself.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PILOTS = ("lesson02", "lesson04", "lesson05")


@pytest.fixture(scope="module")
def committed_starter(tmp_path_factory):
    """The starter files as COMMITTED, extracted fresh from git.

    The learner owns the working copies, and a completed exercise there must
    not redden this suite: the pristine check reads HEAD's bytes, never the
    working tree.
    """
    base = tmp_path_factory.mktemp("committed-starter")
    (base / "solutions").mkdir()
    for name in PILOTS:
        for rel in (f"{name}.py", f"solutions/{name}.py"):
            shown = subprocess.run(
                ["git", "show", f"HEAD:starter/{rel}"], cwd=ROOT,
                capture_output=True, text=True, timeout=60)
            assert shown.returncode == 0, shown.stderr
            (base / rel).write_text(shown.stdout, encoding="utf-8")
    return base


def chapter_claim(chapter, *sentences):
    """Anchor a test to the verbatim lesson sentence(s) it backs.

    Same declaration shape as tests/test_chapter_claims.py: verify_claims.sh's
    Check C parses these decorators and goes red when a declared sentence is
    no longer present in its chapter.
    """
    def deco(fn):
        return fn
    return deco


def run_check(name, starter_dir, solutions=False):
    env = {"PATH": "/usr/bin:/bin", "STARTER_DIR": str(starter_dir)}
    if solutions:
        env["STARTER_SOLUTIONS"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "pytest", f"starter/{name}_test.py", "-q"],
        cwd=ROOT, capture_output=True, text=True, timeout=120, env=env)


@chapter_claim(
    "handbook/course/02-policy-and-records.md",
    "The starter's completion test fails on a fresh clone and passes only "
    "after your edit.",
)
@pytest.mark.parametrize("name", PILOTS)
def test_a_fresh_clone_does_not_satisfy_the_learner_owned_check(
        name, committed_starter):
    pristine = run_check(name, committed_starter)
    assert pristine.returncode != 0, (
        f"{name}'s learner-owned check passes without the learner's edit; "
        "the exercise is not an exercise")
    assert "NotImplementedError" in pristine.stdout, pristine.stdout


@chapter_claim(
    "handbook/course/02-policy-and-records.md",
    "The starter's completion test fails on a fresh clone and passes only "
    "after your edit.",
)
@pytest.mark.parametrize("name", PILOTS)
def test_the_worked_solution_satisfies_the_learner_owned_check(
        name, committed_starter):
    solved = run_check(name, committed_starter, solutions=True)
    assert solved.returncode == 0, solved.stdout + solved.stderr
