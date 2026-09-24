# Connect your own model

You build a host application around the model. The handbook is not a model checkpoint, a fine-tuning dataset or a prompt that makes an existing chatbot autonomous. Your model supplies proposals; the host owns policy, execution and records.

The course's assembled application runs through [`examples/app_agent.py`](../examples/app_agent.py). It wraps one transport with the proposal and verifier contracts, using a fake transport by default. Add `--model NAME` to use an installed local model. The older [model bridge](../examples/model_bridge.py) is an optional smaller exercise with a different action format. Its proposer cannot be pasted into the assembled application.

The field-by-field migration between the two contracts:

| | Bridge (smoke test) | Application (`app_agent.py`) |
|---|---|---|
| Input packet | `instruction`, `output_schema`, observation profile | proposal context: `instruction`, `observations`, optional `evidence` and `advisory_memory`, `validation_error` on repair: the wrapper adds `output_schema` and the tool descriptions itself |
| Reply object | `{"action": "execute", "tool": ..., "url": ...}` or `{"action": "stop", "reason": ...}` | a hypothesis: `{"kind": ..., "surface": ..., "evidence": [...], "action": {"tool": ..., "destination": ..., "arguments": {...}}}` |
| Second model role | none | the verifier: an isolated `{finding, capture, verdict_schema}` packet answered with `{"verdict": ..., "reason": ...}` |
| Failure surface | bridge report statuses | proposal `status` per phase and the process exit code; `--broken-transport` demonstrates it honestly |

## Run the assembled application

From the repository root, run the application with its fake transport:

```bash
python3 -m examples.app_agent --out /tmp/agent-report.json --store /tmp/agent-memory.db
python3 -m pytest tests/test_app_agent_example.py -q
```

Read `proposals` and `verification` in `/tmp/agent-report.json`. The fake transport proves that the wrappers, checks and fixture actions connect; it does not measure the quality of a real model. To try an installed local model, run the same command with `--model NAME`. The model replies may differ, while policy and fixture actions stay in the host application. The wrapper and its output schemas are in `examples/app_agent.py`.

## Plug in your own client

Any provider whose SDK can take a text prompt and return the assistant's text plugs into the assembled application through the `send` function you supply, and nothing else. [`examples/custom_transport.py`](../examples/custom_transport.py) is the runnable template: it turns each packet the application builds (instruction, output schema, tool vocabulary, observations, evidence, advisory memory, and the validation error on a repair round) into a single JSON prompt, hands it to your `send`, and returns the reply text to the host's strict parser unchanged. The same transport serves both model roles, proposals and verification, because both packets carry their own `output_schema`.

Run it first with no provider at all, then read the report it writes:

```bash
python3 -m examples.custom_transport --out /tmp/custom-agent-report.json
python3 -m pytest tests/test_custom_transport_example.py -q
```

Then replace the stand-in `send` with your client:

```python
from examples.custom_transport import make_transport, run

def send(prompt: str) -> str:
    # One call to your model client, whatever its SDK looks like.
    # Credentials come from your environment HERE, in host code; ask for
    # the JSON object the prompt's output_schema describes, and return
    # the assistant's text, never the SDK's response object.
    ...

report = run(make_transport(send), out="/tmp/custom-agent-report.json")
```

What stays host-owned, by construction and by test: the packet reaching your model carries no adapters, credentials, budgets or policy, a reply that is not text is refused at the transport, and an invalid or hostile reply becomes a recorded refusal, never an action. Your production `send` still owes what the local-model section below owes: a total deadline, cancellation, and token and cost accounting.

## Optional bridge smoke test

The bridge exercises one scheduled action at a time. It is useful when you want to implement a proposal function before working with the assembled application. Its adapters read local fixtures.

### Follow the bridge connection

```text
Owner supplies policy + fixtures
            |
     host observes and plans
            |
   propose(context) -> JSON text       <- your model client plugs in here
            |
   parse + validate + bounded repair
            |
   Harness.execute(tool, url)
            |
   fixture capture + action ledger
            |
   report, or an explicit aborted run
```

The model sees the next planned action, synthetic observations, the output schema and the last validation error, if any. It receives no harness object, callback registry, credentials or policy-editing interface. The host rechecks the response before calling `Harness.execute`, which applies the existing stage, plan order, scope, gate and action-budget rules.

This first exercise gives the model a narrow choice: propose the next scheduled action or request a stop. It does not demonstrate useful autonomous reasoning, finding generation or a model verifier. Those need separate interfaces and evaluation; [asymmetric trust](../rendered/03-asymmetric-trust.md) explains the finding boundary.

### Run the bridge without a provider

From the repository root, in the Python environment used for the lab:

```bash
python -m examples.model_bridge --out /tmp/model-bridge-report.json
python -m pytest tests/test_model_bridge.py -q
```

The default `fake_propose` returns fixed, valid proposals without making a network request. Inspect `proposal_log`, `model_calls`, `harness.outcomes`, `harness.evidence` and `harness.coverage`. The bridge adds no findings; empty findings in this exercise are not a clean security assessment.

The tests include malformed JSON, duplicate keys, extra fields, unknown tools, changed destinations, wrong ordering, provider errors and a model-requested stop. Repair exhaustion records remaining actions as skipped. An aborted CLI run writes its report and exits unsuccessfully so automation can distinguish it from normal completion.

### Replace the bridge's proposal function

Your integration has this contract:

```python
def propose(context: dict) -> str:
    # Call your chosen model using its documented client.
    # Serialize context as data, request context["output_schema"],
    # and return the assistant's JSON text, not the whole API response.
    ...
```

Pass that function to `run`; do not hand your SDK the harness methods as automatic tools. The SDK call belongs inside your trusted wrapper. Keep provider-specific credentials and settings there, outside model-generated arguments.

```python
from examples.model_bridge import run
from harness.runtime import canonical_bytes
from pathlib import Path

# After defining propose using your model's client:
report = run(propose)
Path("/tmp/my-model-report.json").write_bytes(canonical_bytes(report))
```

For an SDK that returns native tool calls, your wrapper should accept the intended proposal call, serialize its arguments to this contract and reject unexpected or multiple calls. It should not execute the provider's tool calls itself.

The current proposal forms are:

```json
{"action": "execute", "tool": "inspect_headers", "url": "https://lab.example/"}
```

```json
{"action": "stop", "reason": "The available context is insufficient."}
```

The execute form must name the exact pending tool and URL. The schema helps the model format its answer; application checks decide whether that answer is admissible. A model that ignores the prompt still passes through those checks.

### Try an installed local model in the bridge

The included [Ollama wrapper](../examples/ollama_client.py) is a concrete transport example using the [chat endpoint](https://docs.ollama.com/api/chat) and [structured output format](https://docs.ollama.com/capabilities/structured-outputs). Start your local Ollama server and choose a locally installed model that supports structured output:

```bash
ollama list
python -m examples.model_bridge \
  --ollama-model YOUR_INSTALLED_LOCAL_MODEL \
  --out /tmp/local-model-report.json
```

Replace `YOUR_INSTALLED_LOCAL_MODEL` with its installed name. This optional mode sends the synthetic context to the local model server. The target-looking URL in a proposal remains a fixture identifier; the tool adapters do not contact it. The wrapper does not download a model or configure a provider account.

The local connection is fixed in the wrapper:

```text
endpoint:       http://127.0.0.1:11434/api/chat
streaming:      disabled
socket timeout: 60 seconds
response cap:   65536 bytes
proposal cap:   4096 bytes
output budget:  num_predict = 256
attempts:       at most 2 per planned action by default
```

The socket timeout is not a total run deadline, and the provider's generation setting is not a cost guarantee. Your production wrapper needs a total deadline, cancellation, token and cost accounting, and controlled SDK retries. A synchronous callback that never returns can stall this teaching example. The generic callback and the Python host remain trusted code.

The committed tests exercise the wrapper's request and response mapping with a fake transport. They do not establish compatibility or output quality for every installed model. Run your selected model, inspect its report and test its failure responses before relying on it.

### What changes for another bridge provider?

| Surface | Change for your model | Keep under host control |
|---|---|---|
| Provider wrapper | Client, model identifier, response extraction | Credentials, timeout and retry settings |
| Formatting | Provider's structured-output or tool-call request | Local JSON and proposal validation |
| Context | Deliberately selected observations | Policy, state and budgets outside the prompt |
| Tool execution | Nothing during this fixture exercise | Trusted registry and `Harness.execute` |
| Findings and review | The bridge has no verifier; use the assembled application for that contract | Captured evidence, severity policy and human acceptance |

Attaching a model and adding live security tools are separate changes. A live adapter needs destination checks for every request and redirect, credential restrictions, process isolation and explicit authorization. Copying the fixture adapter and adding an HTTP call does not supply those controls. The course carries the working lessons this bridge points toward: [hostile content refused by policy](../rendered/course/04-model-proposals.md), [memory and retrieval](../rendered/course/06-retrieval-and-memory.md), [context assembly](../rendered/course/07-context-assembly.md) and [recovery](../rendered/course/09-stop-recover-finish.md); [the build sequence](BUILD_ROADMAP.md) is the map.

You have completed the bridge exercise when valid proposals create fixture evidence, invalid proposals create no evidence, exhausted repair produces an aborted report, and replacing the provider wrapper leaves the host's decision rules intact. The assembled application's proposal and verifier statuses are recorded in its own report.
