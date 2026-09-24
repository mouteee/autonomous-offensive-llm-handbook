# Lesson 16: package an agent around your model

Configure a provider, controller, memory store and tool catalogue. Run them together, inspect the report and check that replacing a component leaves the host's permission checks intact. Configuration selects components; only the policy grants permission.

## Build this

`core/run/app.py`: a configuration validator that refuses what it does not understand, and an `Application` that composes the policy, the write boundary, the stage machine, the proposal session, candidate construction, the taught memory store, search and context assembler, the controller laboratory, the budgeted lifecycle and the verification pipeline into one run you can start, interrupt, resume and finish. Beside it, `core/run/acceptance.py`, the review-decision artifact, and `examples/app_agent.py`, the executable capstone that puts a real transport behind the same configuration. Plus the committed demo artifact carrying a complete run, an interrupted-and-resumed segment, a controller swap, and three runs sharing one memory store.

## Start from here

The core build through [stop, recover, finish](09-stop-recover-finish.md), plus [lesson 10](10-controller-laboratory.md)'s contract and baselines: that is the whole prerequisite, because the ordinary assembly runs the frozen priority baseline. The optional advanced route runs from [LinUCB](11-linucb.md) through [the comparison protocol](15-comparisons-and-interpretation.md); if you took it, everything you built still plugs in through the same contract. Nothing new is implemented below the assembly; if a step here surprises you, its own lesson is the place to look.

## Inputs and outputs

The input is one configuration object:

```json
{"authorization": {"reference": "training-authorization-0016",
                   "origins": ["https://lab.example/", "https://beta.lab.example/"]},
 "tools": [{"tool_id": "inspect_headers", "activity": "passive",
            "family": "fam-recon", "weight": 3.0, "cost": 1.0}],
 "adapters": {"inspect_headers": "a callable, never a transport string"},
 "budgets": {"actions": 12, "model_calls": 6, "wall_seconds": 300, "cost": 60},
 "controller": {"name": "priority", "seed": 0, "learn": false},
 "provider": null,
 "verifier": null,
 "retrieval": {"enabled": false, "store": ":memory:", "records": [],
               "query": null, "budget": 400, "scope": null},
 "coverage": [["inspect_headers", "https://lab.example/"]],
 "finding_rules": [{"kind": "shared-banner", "title": "Shared lab banner disclosed",
                    "severity": "medium", "marker": "LAB_SHARED_BANNER"}]}
```

One caution about that block: it is illustrative notation, not a runnable configuration: the adapter value is a placeholder string standing in for a Python callable, and provider and verifier are callables too. The executable configuration lives in `examples/app_agent.py`, where every one of these values is a real function. The output is one report: the configuration summary with the policy digest, the candidate table with its exclusions, the plan, every proposal session's outcome with its phase, the retrieval trace with its omissions, the memory write-backs, every controller decision with its feedback record, the verification ledger, the consolidation groups, and the gated terminal report from lesson 9.

## Implement it

1. **Validate before building.** [`run/app.py:validate_config`](../../core/run/app.py) normalizes the configuration or refuses it with a named reason. Unknown keys are refused rather than ignored, because a typo that silently disables a control is worse than a loud stop. The controller entry defaults to the priority baseline with learning off, and turning learning on takes the controller key and the separate research flag together: the same posture the controller factory takes: research is opt-in, in writing, never a default anyone drifted into.

2. **Keep live transports out.** The adapters entry accepts callables only: the configuration accepts only callable adapters, and a live transport is a separately reviewed boundary this repository does not ship. The fixture lab's chapter says what that boundary owes (every destination, redirects, credentials, secondary requests) and nothing in this lesson shrinks that bill.

3. **Assemble, do not invent.** [`run/app.py:Application`](../../core/run/app.py) builds the policy, then per run: the recorder and stage machine from lesson 2 and 3, the budgeted lifecycle from lesson 9, the verification pipeline from lesson 8, and the configured controller from the laboratory. The whole class is composition; the one behavior it adds is order.

4. **Observe, gate, plan.** The run walks the operational stages in order, records observations from the fixture world's responses with the same toy extractors lesson 3 labeled, records a gate from what was observed, and builds the candidate table and ranked plan from lesson 5. The gate has three answers, not two: a world answering cleanly proceeds in full mode, a world answering partly in errors proceeds limited and passive-only, and a world answering nothing but errors is indeterminate and stops. Unknown is not safe. Declared `coverage` obligations from the configuration travel into the candidate table, flagging the identities they name for the controllers that read the flag and reporting any obligation nothing satisfies. The exclusion table travels into the report: work that did not qualify is accounted for, not absent.

5. **Check admission and budget before every model call.** Proposal rounds, repairs and verifier calls share one model-call budget. Before each call, the host checks the remaining allowance, wall deadline, cancellation and run closure. A refused call is recorded with its reason. A call already in flight is not interrupted by this teaching runtime, but a late reply cannot authorize another call.

   The observation phase proposes work before execution. The host checks each proposal against policy and records any refusal. After fixture actions produce captures, the evidence phase receives their summaries and may propose follow-up work. The second proposal phase sees the evidence the first phase's actions captured, and its admitted work runs through the same door. If the evidence supports no further action, the run records that outcome without inventing work.

6. **Retrieve memory within the engagement.** Open the configured SQLite store or use an already-open store. Seed records are ingested once. Search results become context blocks carrying their stored identity and timestamps.

   **Scope the search.** Enabled retrieval requires the host to name an engagement. Every search filters both the keyword and vector lanes by that engagement, so another engagement's record cannot enter the provider context. An optional profile or tool filter can narrow it further. The engagement key is mandatory in that scope: a tool-only or profile-only read would let another engagement's record ride a shared tool or stack fingerprint into the context, so cross-engagement tactic sharing is a separate lane a host builds deliberately, never a wider read scope.

   **Preserve expiry.** A recalled block keeps its stored creation time and expiry. The assembler omits expired blocks and names them in the omissions list. The lifecycle measures elapsed time with a monotonic clock. Persistent memory uses a separate epoch clock for expiry checks and write-backs; comparing an epoch timestamp with monotonic time would leave old records available.

   **Assemble and record the context.** The assembler applies each tier's token budget. Recalled memory reaches the model through the taught store, search and context assembler, and the report records what was included and what was omitted. The provider receives this text as prior evidence. A provider cannot widen scope mid-run.

   **Record what the run learned.** A completed run teaches the next one: surviving findings become stored tactics, and a refuted tactic declines the write loudly. New tactics receive the same engagement scope, and each `memory_written` row identifies the finding and record involved or the reason a write was refused.

   Cross-run controller priors are optional and are not wired into this assembly. To add them, load a profile-keyed bank at `_start`, apply a bounded bonus to candidate priorities before ranking, and record the adjustment in the report.

7. **Honor the gate before selecting anything.** Execution starts by reading the gate and advancing the stage machine, and those answers are control flow, not commentary. A stop gate executes zero testing callbacks: the run halts, every planned row becomes a recorded skip, and the terminal report says it stopped and why. A missing gate halts execution exactly like a stop gate. A passive gate excludes active callbacks and runs the passive remainder. A refused stage transition halts the same way. A halted run closes through lesson 9's abort, so its report carries `halted` with the reason, `aborted: true` in the terminal record, and the same reason in `stop_reason`: three spellings of one fact, from the application, the closure and the accounting respectively. And the dispatch door re-checks all of it per attempt on its own authority (lesson 9's admission) so the halt logic here is sequencing, not the only guard.

8. **Let the controller advise.** Per step, the configured controller selects among the remaining eligible candidates; the lifecycle executes the choice through the write boundary, which re-checks policy regardless of who chose; and the outcome's feedback is assembled under the shared definition and handed back through the contract from lesson 10. The decision, the feedback value, the weights version and the learning report all land in the run report. Invalid controller advice earns no credit: the host fallback executes under the host's own ranking, and the ledger entry names the action that actually ran: the controller's decision is settled as not executed, so no learning lands on work it did not choose.

9. **Find, verify, consolidate, finish.** Host-authored marker rules from the configuration propose findings over the captures; the verification pipeline governs them and, with a verifier configured, applies host-validated verdicts: each verifier call admitted against and charged to the shared model-call budget from step five; consolidation groups cross-host repeats; and `finish` gates completion exactly as lesson 9 built it, closing the run against later effects. A verifier is a callable the host validates, never a trusted writer.

10. **Checkpoint and resume.** `Application.resume`, cited as [`run/app.py:resume`](../../core/run/app.py), rebuilds the application around a resumed lifecycle and reconciles unsettled actions. It starts a fresh verification pipeline. A checkpoint does not preserve earlier verifier opinions; the demonstrated interruption happens before final verification.

## Run it

```bash
python3 -m pytest tests/test_run_app.py tests/test_run_capstone.py -q
python3 -m core.run.demo_app --out /tmp/app-demo.json
diff -u data/course/app-demo.json /tmp/app-demo.json
python3 -m examples.app_agent --out /tmp/agent-report.json --store /tmp/agent-memory.db
```

The `diff` prints nothing: the assembled run, the interruption, the controller swap and the shared-memory runs all replay byte for byte from committed inputs. The last command is the executable capstone: the same application under a wrapped transport, offline by default. The executable capstone wraps one transport behind the exact proposal and verdict schemas, and the fake transport proves the whole connection before any model is installed. Add `--model NAME` to swap in the connection guide's local Ollama transport (nothing but the transport changes) and try `--broken-transport` once on purpose: A failed transport is visible in the proposal statuses and the exit code, not hidden behind a completed fixture run.

## Inspect it

[![The assembled application's actual data flow: observe and gate, plan with coverage, the memory store's assembled context, the observation-phase proposal, the dispatch door, captures feeding the evidence-phase proposal, verification on the shared meter, tactics written back to the store, the gated closing finish, and the review artifact beside the closed run.](../../docs/assets/course/assembled-app.svg)](../../docs/assets/course/assembled-app.svg)

Open `/tmp/app-demo.json`. `complete_run` is the whole story in one object: the stage walk in `events`, the gate with its inputs, `halted` reading null because nothing stopped this run, the candidate table with exclusions, one refused proposal (`refused_by_policy`, with the refusal also in the ledger) and one admitted proposal that added a health-path action, the decisions with their feedback records, two findings the scripted verifier accepted and two it rejected. The rejections are deliberately wrong and remain visible with their quotes and captures for human review, as lesson 8 showed. The report also has a cross-host consolidation group for the shared banner, a gated finish, and a resource ledger counting proposal rounds and verifier calls against one model-call budget.

`interrupted_and_resumed` shows lesson 9 running inside the assembly: an action captured but never settled comes back `clean` on reconciliation because its evidence already existed, an action with no capture stays `unresolved` because the side effect may have happened, and the resumed run finishes with both accounted for. A resumed run finishes with the same accounting as an uninterrupted one.

`controller_swap` shows which checks stay unchanged: the priority and legacy runs carry identical `eligible` tables and identical feedback weight versions, and only `execution_order` differs. Changing the controller changes the order of work, and changes neither the eligibility table nor the feedback definition.

`memory_across_runs` is the loop between runs: the first run's surviving findings appear in `first_run_wrote` as tactic record ids, the second run's context `included` exactly those records, and after the operator refutes them the third run's `included` is empty while its write-back rows carry the refusal reason; refuted knowledge stays refuted, visibly.

In `complete_run`, read the two proposal entries against each other: the observation-phase proposal was refused by policy, and the evidence-phase proposal was admitted and its action executed. The context the model actually saw is in the entry itself: the evidence-phase proposal carries `context_evidence`, the capture summaries (action identity, status, an excerpt with the banner marker) that its hypothesis was drawn from. That pair is the difference between a plan written once and an agent: the second decision came from the first result. Each decision row also carries the controller's own `scores`, so "why this candidate" is an arithmetic question the report answers. And to watch the context budget bite, shrink `retrieval.budget` toward the size of one block and rerun: the dropped block lands in `retrieval.*.omissions` with its reason, exactly as lesson 7 taught.

## Operate it

A run you cannot stop, restart and review is a demo, not an operation. The four commands below are the whole procedure, each in its own process:

```bash
python3 -m examples.app_agent --out /tmp/agent-interrupted.json \
    --checkpoint /tmp/agent-checkpoint.json --interrupt-after 1
python3 -m examples.app_agent --resume /tmp/agent-checkpoint.json \
    --out /tmp/agent-resumed.json
python3 -m examples.app_agent --out /tmp/agent-report.json --store /tmp/agent-memory.db
python3 -m examples.app_agent --review /tmp/agent-report.json \
    --finding FINDING_ID --decision needs_review \
    --reason "Synthetic evidence needs independent validation" --actor reader \
    --out /tmp/review-0001.json
```

The first command executes one action, authorizes a second, writes the checkpoint to disk and exits. The second starts a fresh process and reconciles: A checkpoint saved to disk restarts in a second process, and the unresolved action stays unresolved there. The budgets come back spent, exactly as lesson 9 promised. The third command's `--store` is the durable version of the memory loop: run it twice and the second process retrieves what the first one learned from the SQLite file on disk. Verification state is not saved. The resumed application starts with a fresh verifier pipeline, so this example interrupts before final verification; it does not recover a prior model opinion. The checkpoint digest detects accidental changes to saved bytes, not a deliberate replacement of both data and digest.

The fourth command records the operator's decision after the run is closed. The agent prints every verdict with its full finding id and suggests a review command when the verifier rejects a finding. The example uses `needs_review`: even when the scripted verifier is wrong, a matching quote alone does not establish the security claim. (In the saved JSON the ids live at `finish.report.run_report.findings[].finding_id`.) The review decision becomes a separate artifact naming the run, finding, capture, report digest, actor and reason. A decision about an absent finding is refused, and the closed report does not change. Acceptance requires the operator to validate the claim and record that judgment.

## Break it

Three refusals, from the configuration boundary inward:

```bash
python3 - <<'PY'
from core.run.app import Application, AppConfigError, validate_config
from core.run.demo_app import PROPOSAL_REFUSED, WORLD, build_config
from core.run.proposals import FakeProvider

config = build_config()
config["telemetry"] = {"endpoint": "https://collector.example/"}
try:
    validate_config(config)
except AppConfigError as exc:
    print(f"refused: {exc}")

config = build_config()
config["controller"] = {"name": "linucb", "seed": 0, "learn": True}
try:
    validate_config(config)
except AppConfigError as exc:
    print(f"refused: {exc}")

app = Application(build_config(
    provider=FakeProvider([PROPOSAL_REFUSED, PROPOSAL_REFUSED])))
report = app.run(WORLD)
print([p["status"] for p in report["proposals"]])
outcomes = report["finish"]["report"]["run_report"]["outcomes"]
print("actions touching outside.example:",
      sum("outside.example" in a for a in outcomes))
print("completed:", report["finish"]["completed"])
PY
```

Expected output:

```text
refused: unknown configuration keys: ['telemetry']; known keys: ['adapters', 'authorization', 'budgets', 'controller', 'coverage', 'finding_rules', 'provider', 'research', 'retrieval', 'tools', 'verifier']
refused: controller.learn requires the separate research flag; the ordinary configuration keeps learning off
['refused_by_policy', 'refused_by_policy']
actions touching outside.example: 0
completed: True
```

The first refusal is the unknown-key rule catching a plausible-looking addition before it runs. The second is the learning posture: the research flag is a second, separate decision. The third is the mid-run version of lesson 4's boundary: a provider that proposes out-of-scope work every time changes nothing but the refusal count, and the run still completes: an uncooperative model degrades the plan, never the permissions.

## Check completion

- A finding rule carrying an unknown severity is refused at configuration time, before any run could silently produce zero findings.
- Retrieval records are validated at configuration time, not discovered broken mid-run.
- A controller decision naming an unoffered candidate is refused and recorded inside the assembled run too, never crashed on.

- The documented clean-install path exercises the complete lifecycle.
- Changing the provider changes proposals, and changes no permission: the policy digest, the candidate table and the refusal behavior are identical across providers.
- Changing the controller changes the order of work, and changes neither the eligibility table nor the feedback definition.
- The ordinary configuration runs the complete lifecycle with learning off everywhere, read from the decisions' own records.
- An unknown configuration key is refused with a named reason, and turning learning on takes the controller key and the separate research flag together.

- An exhausted action, cost or wall budget executes zero further callbacks, and cancellation stops the run mid-plan.
- Proposal rounds, repair attempts and verifier calls spend one shared model-call budget, admitted before each call.
- A repair that would start after the wall deadline, after closure or after cancellation is a recorded refusal, not a call.
- A stop gate executes zero testing callbacks: the run halts, every planned row becomes a recorded skip, and the terminal report says it stopped and why.
- A missing gate halts execution exactly like a stop gate.
- A passive gate excludes active callbacks and runs the passive remainder.
- Invalid controller advice earns no credit: the host fallback executes under the host's own ranking, and the ledger entry names the action that actually ran.

- The second proposal phase sees the evidence the first phase's actions captured, and its admitted work runs through the same door.
- Recalled memory reaches the model through the taught store, search and context assembler, and the report records what was included and what was omitted.
- A completed run teaches the next one: surviving findings become stored tactics, and a refuted tactic declines the write loudly.
- The executable capstone wraps one transport behind the exact proposal and verdict schemas, and the fake transport proves the whole connection before any model is installed.
- A failed transport is visible in the proposal statuses and the exit code, not hidden behind a completed fixture run.
- A checkpoint saved to disk restarts in a second process, and the unresolved action stays unresolved there.
- An operator's review decision becomes its own artifact beside the closed run, and a decision about a finding the report does not hold is refused.

Each sentence is pinned by a named test in `tests/test_run_app.py`, `tests/test_run_control_enforcement.py`, `tests/test_run_capstone.py` or `tests/test_app_agent_example.py`: the enforcement file counts actual adapter and provider invocations, the capstone file reads the actual provider contexts, and the agent file drives the documented commands in separate processes; completion is those suites green plus the byte-identical `diff` above.

## The deployment and review checklist

Every row names the control that enforces it in this repository; there are no aspirational rows.

| Before a run | Enforced by |
|---|---|
| Authorization is an explicit reference and origin list, validated before anything is built | `core/run/policy.py`, `tests/test_run_records.py` |
| The configuration carries no unknown keys and no non-callable adapter | `core/run/app.py`, `tests/test_run_app.py` |
| Learning is off unless the research flag says otherwise, in writing | `core/run/app.py` and the factory in `core/controller/__init__.py`, `tests/test_run_app.py` |
| Every state change flows through one recorded boundary, refusals included | `core/run/recorder.py`, `tests/test_run_records.py` |
| Budgets have named owners, and remaining budget is enforced before every attempt, retries included | `core/run/lifecycle.py`, `tests/test_run_lifecycle.py`, `tests/test_run_control_enforcement.py` |
| The recorded gate and current stage are enforced at the dispatch door, not only in sequencing | `core/run/stages.py`, `core/run/dispatch.py`, `tests/test_run_control_enforcement.py` |
| Proposal, repair and verifier calls share one enforced model-call budget | `core/run/app.py`, `tests/test_run_control_enforcement.py` |
| Findings bind to captures, verdicts are host-validated, acceptance stays human | `core/run/verify.py`, `tests/test_run_verify.py` |
| An interrupted run resumes without invented successes or repeated side effects | `core/run/lifecycle.py`, `tests/test_run_lifecycle.py` |
| A finished or aborted run is closed: later effects are refused at the write boundary | `core/run/recorder.py`, `core/run/lifecycle.py`, `tests/test_run_control_enforcement.py` |

What this checklist does not cover, on purpose: transport containment, process isolation, credential handling and egress policy for a live adapter. Those belong to the separately reviewed boundary named in step two, and a checked box on this page is not evidence about them.

## Continue

The build sequence is complete: from [the first run](01-first-run.md) to a configured agent running your own provider through `examples/app_agent.py`. If you followed the core route, you can now study the optional advanced controllers: [the controller laboratory](10-controller-laboratory.md), [LinUCB](11-linucb.md), [the sparse controller](12-mushroom-body-controller.md), [plasticity](13-plasticity-and-credit.md), [graph experiments](14-graph-controller-experiments.md) and [the comparison protocol](15-comparisons-and-interpretation.md). The factory-supported controllers plug into this application through the controller key; the graph arm remains a separate experiment. [The evidence register](../appendix-f-evidence-register.md) stays the map of what has and has not been measured. Deliberate simplification to carry forward: this application drives fixture worlds; connecting a live target is not a bigger configuration, it is a smaller trust boundary, built and reviewed on its own terms.
