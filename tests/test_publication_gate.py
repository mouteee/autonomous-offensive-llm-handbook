import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PATTERN = "private-release-" + "sentinel"


def staging(tmp_path):
    root = tmp_path / "public"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts/audit.sh", root / "scripts/audit.sh")
    shutil.copy2(ROOT / "scripts/publication_gate.sh", root / "scripts/publication_gate.sh")
    (root / "README.md").write_text("history-free public staging tree\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Approved Author"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "author@noreply.example"], check=True)
    return root


def run_gate(root):
    env = {**os.environ, "PUBLICATION_AUTHOR_NAME": "Approved Author",
           "PUBLICATION_AUTHOR_EMAIL": "author@noreply.example"}
    return subprocess.run(["bash", str(root / "scripts/publication_gate.sh"), str(root)],
                          text=True, capture_output=True, env=env)


def test_publication_gate_requires_and_uses_private_denylist(tmp_path):
    root = staging(tmp_path)
    absent = run_gate(root)
    assert absent.returncode != 0 and "denylist" in absent.stdout
    (root / "scripts/.denylist").write_text("# no patterns\n")
    empty = run_gate(root)
    assert empty.returncode != 0 and "no private pattern" in empty.stdout
    (root / "scripts/.denylist").write_text(PRIVATE_PATTERN + "\n")
    (root / "README.md").write_text("history-free public staging tree\n" + PRIVATE_PATTERN + "\n")
    firing = run_gate(root)
    assert firing.returncode != 0 and "PUBLICATION FAIL [sanitization]" in firing.stdout
    (root / "README.md").write_text("history-free public staging tree\n")
    passed = run_gate(root)
    assert passed.returncode == 0, passed.stdout + passed.stderr
    assert "published patterns and the private denylist" in passed.stdout


def test_publication_gate_refuses_wrong_author_identity(tmp_path):
    root = staging(tmp_path)
    (root / "scripts/.denylist").write_text(PRIVATE_PATTERN + "\n")
    subprocess.run(["git", "-C", str(root), "config", "user.email", "wrong@example.com"], check=True)
    result = run_gate(root)
    assert result.returncode != 0 and "approved value" in result.stdout


@pytest.mark.parametrize("state", ["commit", "tag", "object", "reflog"])
def test_publication_gate_refuses_imported_history_or_refs(tmp_path, state):
    root = staging(tmp_path)
    (root / "scripts/.denylist").write_text(PRIVATE_PATTERN + "\n")
    if state in {"commit", "tag"}:
        subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "unexpected history"], check=True)
        if state == "tag":
            subprocess.run(["git", "-C", str(root), "tag", "unexpected"], check=True)
    elif state == "object":
        subprocess.run(["git", "-C", str(root), "hash-object", "-w", "README.md"],
                       check=True, stdout=subprocess.DEVNULL)
    else:
        logs = root / ".git/logs"
        logs.mkdir()
        (logs / "unexpected").write_text("stale reflog\n")
    result = run_gate(root)
    assert result.returncode != 0 and "history" in result.stdout
