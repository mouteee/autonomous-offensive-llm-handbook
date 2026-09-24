import copy
import json

import pytest

from examples.model_bridge import MAX_REPLY_BYTES, fake_propose, run
from examples import ollama_client
from harness.runtime import canonical_bytes


def test_default_bridge_is_repeatable_and_executes_fixtures():
    report = run()
    assert canonical_bytes(report) == canonical_bytes(run())
    assert report["model_calls"] == 2
    assert report["harness"]["coverage"] == {
        "denominator": "planned tool-and-URL actions", "planned": 2,
        "executed": 2, "error": 0, "skipped": 0, "pending": 0,
    }
    assert report["harness"]["findings"] == []
    assert report["harness"]["acceptance"] == "human_review_required"


@pytest.mark.parametrize("reply", [
    "not json", "[]", "null", '{"action":"execute"}',
    '{"action":"execute","tool":"shell","url":"https://lab.example/"}',
    '{"action":"execute","tool":"inspect_headers","url":"https://outside.invalid/"}',
    '{"action":"execute","tool":"check_lab_marker","url":"https://lab.example/"}',
    '{"action":"execute","tool":"inspect_headers","url":"https://lab.example/","shell":"id"}',
    '{"action":"stop","reason":"stop","action":"execute"}',
    '{"action":"stop","reason":null}', '{"action":"stop","reason":" "}',
    '{"action":"stop","reason":NaN}', "x" * (MAX_REPLY_BYTES + 1),
    "\ud800", "[" * 1500, {"action": "stop", "reason": "wrong return type"},
])
def test_invalid_proposals_exhaust_repair_without_evidence(reply):
    report = run(lambda context: reply)
    assert report["model_calls"] == 2
    assert [e["status"] for e in report["proposal_log"]] == ["rejected", "rejected"]
    assert report["harness"]["evidence"] == {}
    assert report["harness"]["coverage"]["skipped"] == 2
    assert report["harness"]["events"][-1] == {"event": "aborted", "reason": "proposal repair exhausted"}


def test_repair_gets_reason_and_success_is_not_duplicated():
    contexts = []
    def propose(context):
        contexts.append(copy.deepcopy(context))
        return "bad json" if len(contexts) == 1 else fake_propose(context)
    report = run(propose)
    assert report["model_calls"] == 3
    assert contexts[1]["validation_error"]
    assert contexts[2]["validation_error"] is None
    assert report["harness"]["coverage"]["executed"] == 2


def test_context_mutation_does_not_change_the_expected_action():
    def propose(context):
        context["next_action"]["url"] = "https://outside.invalid/"
        return fake_propose(context)
    report = run(propose)
    assert report["harness"]["evidence"] == {}


def test_provider_exception_after_progress_records_partial_run():
    calls = []
    def propose(context):
        calls.append(context)
        if len(calls) == 2:
            raise TimeoutError("private provider detail")
        return fake_propose(context)
    report = run(propose)
    assert report["harness"]["coverage"]["executed"] == 1
    assert report["harness"]["coverage"]["skipped"] == 1
    assert report["proposal_log"][-1] == {"status": "provider_error", "error_type": "TimeoutError"}
    assert "private provider detail" not in json.dumps(report)


def test_model_stop_is_separate_from_success():
    report = run(lambda context: '{"action":"stop","reason":"insufficient context"}')
    assert report["model_calls"] == 1
    assert report["proposal_log"][-1]["status"] == "model_stop"
    assert report["harness"]["events"][-1]["event"] == "aborted"
    assert report["harness"]["coverage"]["pending"] == 0


@pytest.mark.parametrize("attempts", [0, -1, 5, True, 1.5])
def test_invalid_attempt_limit(attempts):
    with pytest.raises(ValueError):
        run(max_attempts=attempts)


def test_ollama_request_and_response_mapping_without_network(monkeypatch):
    captured = []
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, size):
            assert size == ollama_client.MAX_RESPONSE_BYTES + 1
            return json.dumps({"done": True, "done_reason": "stop", "message": {
                "content": '{"action":"stop","reason":"transport fixture"}'}}).encode()
    class Opener:
        def open(self, request, timeout):
            captured.append((request, timeout))
            return Response()
    def build(*handlers):
        assert handlers[0].proxies == {}
        assert isinstance(handlers[1], ollama_client.NoRedirect)
        return Opener()
    monkeypatch.setattr(ollama_client, "build_opener", build)
    report = run(ollama_client.make_proposer("fixture-model"))
    request, timeout = captured[0]
    payload = json.loads(request.data)
    assert request.full_url == "http://127.0.0.1:11434/api/chat"
    assert request.method == "POST"
    assert payload["model"] == "fixture-model" and payload["stream"] is False
    assert payload["format"]["oneOf"]
    assert payload["options"]["num_predict"] == 256
    assert timeout == 60
    assert report["proposal_log"][0]["status"] == "model_stop"
    assert ollama_client.NoRedirect().redirect_request(None, None, 302, None, None, "https://outside.invalid") is None
