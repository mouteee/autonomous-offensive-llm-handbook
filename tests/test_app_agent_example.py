"""The executable capstone, driven exactly as the lesson drives it.

Every test here shells out to `python -m examples.app_agent` the way a reader
would, in separate processes, so what passes is the documented operator
procedure itself: the fake-transport connection, the honest failure, the
cross-process checkpoint restart, the durable memory reopened by a second
run, and the review decision recorded beside a closed run.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def chapter_claim(chapter, *sentences):
    """Anchor a test to the verbatim lesson sentence(s) it backs.

    Same declaration shape as tests/test_chapter_claims.py: verify_claims.sh's
    Check C parses these decorators and goes red when a declared sentence is
    no longer present in its chapter.
    """
    def deco(fn):
        return fn
    return deco


def agent(*args):
    return subprocess.run([sys.executable, "-m", "examples.app_agent", *args],
                          cwd=ROOT, capture_output=True, text=True, timeout=120)


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "The executable capstone wraps one transport behind the exact proposal "
    "and verdict schemas, and the fake transport proves the whole connection "
    "before any model is installed.",
)
def test_the_fake_transport_proves_the_whole_connection(tmp_path):
    out = tmp_path / "report.json"
    store = tmp_path / "memory.db"
    first = agent("--out", str(out), "--store", str(store))
    assert first.returncode == 0, first.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    assert [p["phase"] for p in report["proposals"]] == \
        ["observation", "evidence"]
    assert all(p["admitted"] for p in report["proposals"])
    assert report["verification"]["verdict_ledger"], "no verdicts were applied"
    assert report["finish"]["completed"] is True
    assert [w for w in report["memory_written"] if w["record_id"]]

    # The durable store reopened by a second process: the tactics the first
    # run learned are in the second run's assembled context.
    second = agent("--out", str(tmp_path / "report2.json"),
                   "--store", str(store))
    assert second.returncode == 0, second.stderr
    report2 = json.loads((tmp_path / "report2.json").read_text(encoding="utf-8"))
    assert report2["retrieval"]["observation"]["included"], \
        "the second process retrieved nothing from the durable store"


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "A failed transport is visible in the proposal statuses and the exit "
    "code, not hidden behind a completed fixture run.",
)
def test_a_broken_transport_fails_visibly(tmp_path):
    out = tmp_path / "broken.json"
    result = agent("--out", str(out), "--broken-transport")
    assert result.returncode == 1
    assert "model connection NOT established" in result.stdout
    report = json.loads(out.read_text(encoding="utf-8"))
    assert all(p["status"] == "provider_error" for p in report["proposals"])
    # The fixture run still completes -- which is exactly why the statuses
    # and the exit code, not completion, are the connection evidence.
    assert report["finish"]["completed"] is True


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "A checkpoint saved to disk restarts in a second process, and the "
    "unresolved action stays unresolved there.",
)
def test_the_checkpoint_restarts_in_a_second_process(tmp_path):
    checkpoint = tmp_path / "checkpoint.json"
    interrupted = agent("--out", str(tmp_path / "interrupted.json"),
                        "--checkpoint", str(checkpoint),
                        "--interrupt-after", "1")
    assert interrupted.returncode == 0, interrupted.stderr
    assert checkpoint.exists()

    resumed = agent("--resume", str(checkpoint),
                    "--out", str(tmp_path / "resumed.json"))
    assert resumed.returncode == 0, resumed.stderr
    result = json.loads((tmp_path / "resumed.json").read_text(encoding="utf-8"))
    assert result["finish_completed"] is True
    assert result["coverage"]["unresolved"], \
        "the interrupted action was not kept explicitly unresolved"
    assert any(row["settled"] == "unresolved"
               for row in result["reconciliation"])
    # The budgets already spent came back with the checkpoint.
    assert result["resource_use"]["used"]["actions"] >= 1


@chapter_claim(
    "handbook/course/16-package-your-agent.md",
    "An operator's review decision becomes its own artifact beside the closed "
    "run, and a decision about a finding the report does not hold is refused.",
)
def test_a_review_decision_is_its_own_artifact(tmp_path):
    out = tmp_path / "report.json"
    assert agent("--out", str(out)).returncode == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    finding_id = report["finish"]["report"]["run_report"]["findings"][0][
        "finding_id"]

    artifact_path = tmp_path / "review-0001.json"
    reviewed = agent("--review", str(out), "--finding", finding_id,
                     "--decision", "accepted",
                     "--reason", "quote verified against the capture",
                     "--actor", "reader", "--out", str(artifact_path))
    assert reviewed.returncode == 0, reviewed.stderr
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["schema"] == "course-review-decision/v1"
    assert artifact["finding_id"] == finding_id
    assert artifact["decision"] == "accepted"
    assert artifact["actor"] == "reader"
    assert artifact["run_id"] == \
        report["finish"]["report"]["run_report"]["run_id"]
    # The reviewed report is untouched on disk, and the artifact binds to it.
    assert json.loads(out.read_text(encoding="utf-8")) == report

    refused = agent("--review", str(out), "--finding", "not-a-finding",
                    "--decision", "accepted", "--reason", "x",
                    "--actor", "reader",
                    "--out", str(tmp_path / "review-bad.json"))
    assert refused.returncode == 2
    assert "not in the reviewed report" in refused.stderr
