# Build the deterministic harness

The model remains probabilistic. Make the application around it accountable: authorization, permitted actions, captured evidence, severity policy, completion and acceptance belong to code. A repeated control decision is reproducible only when its inputs, policy and implementation are fixed. A changing target or a new model answer is a new input.

This chapter is the recommended offline teaching path. Earlier chapters and `core/` retain the historical case study, including its defects. The lab in `harness/` is separate: no model call, no network client, no shell tool, and no production exploit predicate. It teaches a boundary an application can enforce without claiming to be an operating-system sandbox.

## The path to remember

| Development phase | Decisions to implement | What leaves the phase |
|---|---|---|
| Bound | Single write path; fixed stage machine | An explicit authority boundary and ordered event ledger |
| Describe | Measured profile; relevance catalogue | A frozen, reviewable plan with reasons |
| Prove | Evidence schema; governor; verdict acceptance | Captures bound to findings and recorded severity changes |
| Control and account | Scope; gate; orchestrator contract; measurement | An honest terminal report, including errors and skips |

These are the decisions from [chapter 06](06-build-your-own.md), grouped for recall. They are a development checklist, not the order in which a request runs. At runtime, the authorization and gate checks happen before the adapter callback. Evidence and review follow execution.

## Run it

From the repository root:

```bash
python3 -m harness.demo --out /tmp/harness-report.json
diff -u harness/report.json /tmp/harness-report.json
python3 -m pytest tests/test_harness.py
```

The command reads `harness/port.json` and `harness/fixtures.json`, invokes local fixture adapters and writes a complete report. No credential, API key or target connection is needed. Use a different output path when comparing; do not overwrite the committed report before checking the difference.

The demo proposes a high-severity interpretation of a header and a synthetic lab marker. The governing write path applies declared ceilings before persistence. A genuine quotation from the header does not satisfy the independent lab-marker predicate, so that raise is rejected. The marker satisfies the synthetic predicate, allowing a bounded raise. Both findings still say `human_review_required`.

That is a demonstration of the mechanism, not a vulnerability benchmark. The marker was authored to exercise the acceptance path. It is not an exploit detector and must not be presented as one.

## What code owns

`harness/runtime.py` contains the dispatcher and its state. The host registers trusted adapters at construction. A model-facing integration should expose proposals to this API, never the adapter registry, raw storage or arbitrary Python execution.

| Boundary | Enforcing operation | Falsifier to try |
|---|---|---|
| Exact origin authorization | `origin`, then `Harness.execute` | A sibling hostname, different scheme or port reaches a callback |
| Missing measurements | `strict_gate` | Delete a consulted input and active work still runs |
| Runtime order | `Harness.advance` and stage checks | Skip a stage or invoke a tool during review |
| Frozen selection | `Harness.plan` | Unknown profile vocabulary is silently accepted |
| Action budget | `Harness.execute` | An extra callback runs after budget exhaustion |
| Capture provenance | `Harness._quote` | Empty, paraphrased or foreign-record text authorizes a write |
| Governed persistence | `Harness.propose_finding` | A rule raises a severity or a caller mutates stored state through a returned object |
| Bounded raising | `Harness.verify_raise` | A quotation without the independent predicate changes severity |
| Completion accounting | `Harness.finish`, `Harness.abort`, `Harness.snapshot` | A planned action disappears without an outcome |

The adversarial tests live in `tests/test_harness.py`. Their expected order, expected scores and coverage recounts are independently stated, not copied from a runtime constant. Run them after changing policy as well as code.

## The stage machine

The runtime stages are `observe`, `plan`, `execute`, `review`, `report`. Advancement is positional. During observation, recorded measurements determine the gate. During planning, profile requirements select tools and the explicit `weight / cost` policy orders them, with tool name as a stable tie-breaker. Execution consumes only pending tool-and-URL pairs from that frozen plan. Review accepts evidence-bound findings. Reporting terminates the run.

Unknown is different from false. A profile field carries `state`, `value` and `source`; an unknown field has a null value and does not satisfy a tool requirement. The catalogue references declared fields, so a misspelled field is a configuration error rather than a tool quietly disappearing from the plan.

The sample scoring weights and gate threshold are authored teaching policy. They have no empirical optimality claim. A port owner must justify them for that port and preserve a fixture for each relevant policy case.

## Scope before effects

Authorization is an explicit list of origins: scheme, canonical host and port. No parent-domain expansion or inferred subdomain authorization occurs. Empty authorization, credentials in URLs, relative URLs, unsupported schemes and malformed ports are rejected. The source of authorization is recorded as an operator reference; the library does not authenticate that reference.

The host and adapters are trusted. A Python callback can itself make an unrecorded request, follow a redirect or write a file. This dispatcher cannot prevent that. A live integration needs a transport wrapper that validates every destination, including redirects and secondary requests, plus process isolation, credential restrictions and an egress policy. Do not advertise this tutorial as network containment.

## Missing input is a state

The strict gate distinguishes measured zeroes from absent inputs. Missing fields or no observed responses produce `indeterminate`, with no dispatch permitted. A high observed error rate permits only passive catalogue entries. Consulted values are retained without post-decision rounding, so replay uses the same values the branch evaluated.

The demo's `observations` function reads the named `headers` and `marker` fixtures. Its values are derived, but the historical field names are not claims that a crawler, browser or WAF detector ran:

| Recorded input | Exact synthetic derivation |
|---|---|
| `total_responses` | Count of the selected fixture records |
| `error_rate` | Fraction whose status is an HTTP client or server error |
| `waf_detected` | Whether a selected body contains the authored `WAF_BLOCKED` marker |
| `parameters_found` | Count of double-quoted `name` attributes matched by the sample regular expression; not validated request parameters |
| `forms_found`, `scripts_found` | Case-sensitive opening-tag matches in the fixture text; not browser-parsed elements |
| `pages_crawled` | Count of selected responses below the HTTP error-status range; not distinct pages or a crawl |

The successful fixtures both represent the same URL. Their response count must not be presented as distinct-page coverage. The `has_http` profile field records whether the selected statuses are in the supported HTTP response range, with those fixtures named as its source; it is not a live connectivity probe. A real port must replace these toy extractors with defined observation semantics and corresponding tests.

The simplified gate requires and validates every declared input, but only `total_responses` and `error_rate` affect its classification once the inputs are complete. The remaining fields are recorded context, not additional decision branches. Their presence does not imply that this tutorial implements the historical gate's full policy.

These are conservative tutorial choices, not universal production thresholds. Stopping on missing evidence can delay legitimate work. That cost should be visible as a gate result, not hidden by inventing a clean measurement.

## A quote is not proof

A finding names a captured evidence digest and an exact, nonempty quotation from that capture. The capture is produced by an adapter, not by a model proposal. The run identifier binds the capture to the manifest and fixtures used here. Defensive copies prevent a caller from modifying stored records through ordinary API returns.

Matching the quotation establishes citation integrity. It does not establish that the quotation is relevant, that the target is exploitable, or that the chosen severity is justified. An attacker-controlled page can contain any sentence. The raising path therefore also requires an independently authored predicate over the captured status and marker, plus a severity ceiling. The shipped predicate is deliberately synthetic and belongs only to the offline lab.

The governor and raising path both need tests. Downward errors can hide important vulnerabilities; under-reporting is not inherently safe. The benefit of separate paths is a smaller set of permissions and clearer audit evidence, not freedom from trust or review.

## The report is part of the control

Read `coverage.denominator` before its counts. The unit here is a planned tool-and-URL action, not a unique tool, endpoint, finding or percentage of the target. Outcomes are `executed`, `error` or `skipped`; pending actions prevent normal completion. An explicit abort records remaining work as skipped and names the reason.

The report includes the plan, action outcomes, evidence, findings, gate inputs and event ledger. Coverage is computed from outcomes and tested against action events. A run with no findings is therefore distinguishable from a run whose plan was entirely refused.

Every finding is marked as requiring human review. The tutorial does not implement acceptance: it enforces neither a real user's identity nor an organization's report-signing process. A production host must keep that acceptance channel separate from model proposals.

## Port the inputs, keep the constraints

| Port surface | What the owner supplies | Validation obligation |
|---|---|---|
| Observation adapter and profile | Fields, measured/unknown state, source | No default masquerades as an observation |
| Catalogue and rules | Tool requirements, weights, costs, ceilings | Known field names, unique identifiers, fixtures |
| Authorization and scope | Exact origins and authorization reference | Explicit permission before dispatch |
| Evidence extraction and proof policy | Trusted adapters, capture shape, predicates | Finding-bound records and independent rule tests |

The manifest is a reviewable declaration, not a universal implementation. A cloud, infrastructure or other target port also needs appropriate adapters, evidence semantics and evaluation ground truth. Changing a catalogue alone does not demonstrate an end-to-end port.

## Limits of the fixture lab

- It does not make model text or live findings repeatable.
- It does not establish savings in tokens, elapsed time, money or analyst effort.
- It does not establish improved recall or precision on a target corpus.
- It does not prove security against a hostile adapter or host process.
- It does not replace legal authorization, network isolation or human report acceptance.

Repeated fixture bytes test replay and drift. Separate adversarial tests examine control correctness. A controlled comparison with repeated target runs is needed for claims about savings or detection quality. The proposed measurement protocol is in `harness/EVALUATION.md`.

## Build checklist

Before adding a model, run the negative cases: wrong stage, unknown tool, unauthorized origin, missing signal, exhausted budget, absent evidence, fabricated quote and unresolved work. Inspect the resulting records as well as exceptions. A blocked action without an auditable reason is unfinished work.

Then integrate a model only as a proposal producer. Keep the trusted adapter registry and report acceptance outside its tool surface. Finally evaluate useful coverage, false positives, false negatives, model cost, elapsed time and reviewer effort together. A cheaper run that silently misses important findings is not a successful optimization.

## What it costs to build this

Every new adapter needs transport-boundary tests; every rule needs positive and negative fixtures; every target port needs reviewable authorization and evidence semantics. Those costs do not disappear when the model becomes more capable. The sample proof predicate is not a production verifier, the library is not a sandbox, and the controlled study remains unrun as of the register date in [the evidence register](appendix-f-evidence-register.md). These are remaining implementation and measurement obligations, not claims that the tutorial has paid them.
