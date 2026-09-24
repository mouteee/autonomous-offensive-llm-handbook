"""The provider-neutral transport template, held to the connection guide.

The guide's promise is that `send(prompt) -> str` is the entire integration
surface: the packet reaches the model as one JSON prompt with nothing
host-owned inside it, the reply text goes back to the strict parser
unchanged, and the offline stand-in runs the same assembled path a real
client would. These tests hold each piece, plus the documented command in a
separate process.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.run.app import Application
from core.run.demo_app import WORLD
from examples.app_agent import agent_config, fake_transport
from examples.custom_transport import make_transport, offline_send, run

ROOT = Path(__file__).resolve().parents[1]

PACKET_KEYS = {"instruction", "output_schema", "tools", "observations",
               "evidence", "advisory_memory", "validation_error"}
VERIFIER_KEYS = {"instruction", "output_schema", "finding", "capture",
                 "verdict_schema"}


def test_the_prompt_is_the_packet_and_the_reply_passes_through_unchanged():
    seen = []

    def send(prompt):
        seen.append(prompt)
        return '{"marker": "verbatim-reply"}'

    transport = make_transport(send)
    packet = {"instruction": "x", "output_schema": {}, "observations": []}
    reply = transport(packet)
    assert reply == '{"marker": "verbatim-reply"}'
    assert json.loads(seen[0]) == packet, \
        "the prompt must be the packet, serialized and nothing else"


def test_a_non_text_reply_is_refused_at_the_transport():
    transport = make_transport(lambda prompt: {"sdk": "object"})
    with pytest.raises(TypeError):
        transport({"instruction": "x"})


def test_the_model_sees_no_adapters_credentials_or_policy():
    prompts = []

    def send(prompt):
        prompts.append(json.loads(prompt))
        return offline_send(prompt)

    report = Application(agent_config(make_transport(send))).run(WORLD)
    assert report["finish"]["completed"]
    assert prompts, "the provider path never reached the model"
    for packet in prompts:
        allowed = PACKET_KEYS if "observations" in packet else VERIFIER_KEYS
        assert set(packet) <= allowed, \
            f"the packet leaked undocumented keys: {sorted(set(packet) - allowed)}"
        text = json.dumps(packet)
        for forbidden in ("adapters", "authorization", "budgets",
                          "api_key", "token"):
            assert f'"{forbidden}"' not in text, \
                f"host-owned {forbidden!r} reached the model prompt"


def test_the_custom_path_matches_the_fake_transports_run(tmp_path):
    through_custom = run(make_transport(offline_send),
                         out=str(tmp_path / "custom.json"))
    direct = Application(agent_config(fake_transport)).run(WORLD)
    assert [p["phase"] for p in through_custom["proposals"]] == \
        [p["phase"] for p in direct["proposals"]] == ["observation",
                                                      "evidence"]
    custom_findings = through_custom["finish"]["report"]["run_report"]["findings"]
    direct_findings = direct["finish"]["report"]["run_report"]["findings"]
    assert [f["finding_id"] for f in custom_findings] == \
        [f["finding_id"] for f in direct_findings], \
        "the custom path changed what the run found"


def test_the_documented_command_runs_in_its_own_process(tmp_path):
    out = tmp_path / "custom-report.json"
    done = subprocess.run(
        [sys.executable, "-m", "examples.custom_transport",
         "--out", str(out)],
        cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["finish"]["completed"] is True
    assert "completed: True" in done.stdout
