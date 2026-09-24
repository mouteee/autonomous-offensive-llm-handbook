# The determinism gradient

If you came to build, start with [the build sequence](../docs/BUILD_ROADMAP.md): a course of executable lessons, each ending in a working component and a saved artifact. This chapter is the design argument behind those lessons, kept for the reader who wants to know why the controls exist before typing them in.

For the recommended runnable teaching path, see [the harness lab](07-harness-lab.md). This chapter records the historical system and its design argument. The laws below retain that argument while distinguishing the controls to build from the defects the case study actually contains.

Point a capable model at a host, hand it a toolbox, and tell it to run a penetration test. It will do something sensible. Run it again tomorrow against the same host and it will do something else sensible. Both runs find real things. Neither can be replayed, and neither can tell you why it skipped what the other one caught.

Read enough of those transcripts and the diagnosis stops being about hacking ability. The model spends the start of every run rediscovering that you read the response headers before you fuzz the parameters, arrives at a slightly different conclusion each time, and every one of those small differences compounds into a different set of findings. Then it writes the run up as though the order had been chosen on purpose.

The obvious fix is to make the model better. Bigger model, longer prompt, a worked methodology in the system message, a planning scaffold to think it through first. That path moves the average up a little and leaves the variance where it was, because the variance was never a capability problem. It came from handing a stochastic component work that a deterministic one could have done identically every time.

> You don't make an LLM a good pentester by making it smarter. You make it a good pentester by giving it less to decide.

Everything after this chapter is a consequence of that sentence.

## Recon is already a procedure

The uncomfortable part, for anyone who enjoys the craft, is that penetration testing methodology is close to fixed, and reconnaissance is the most fixed part of it. Watch five competent testers open the same unfamiliar web application and the opening is substantially the same opening. Resolve the host. Read the certificate and the response headers. Fetch the well-known paths. Fingerprint the server, the framework, the front end. Pull the JavaScript bundles and read what they call. Enumerate what answers, what redirects, what refuses. Note the WAF and how it behaves when you poke it.

Nobody is improvising in there. The judgement, the part that is actually hard and worth paying a human for, starts later: which of the endpoints you just enumerated deserves an hour of a human's attention, and why. The opening is procedure, and procedure belongs in code.

So asking a model to re-derive that procedure on every run buys nothing. It costs tokens on the least interesting work in the engagement, and it costs reproducibility, since the derivation lands differently each time. The third cost is the one that actually matters. A model narrating a methodology it improvised is already practised at describing its own behaviour as more deliberate than it was, and that habit does not stay politely confined to the methodology section of the report. Hallucinated findings rarely begin at the finding. They begin here, several stages earlier, in an agent that was asked to invent an account of itself.

The design principle that falls out: assign every step to the cheapest layer that can perform it correctly, and spend model capacity only where the answer genuinely is not derivable.

That principle is portable; a particular web-testing implementation is not. Keep the
decision sequence and its constraints stable, then write down the target-bound inputs:
what observes the target, which tools and rules are available, what authorization and
scope mean, and which evidence can support a conclusion. A catalogue is one of those
inputs, not a magic table that makes every other assumption disappear. The useful
promise is that a reviewer can find, diff, and challenge each change before a run does.

## The gradient

Four layers, ordered by how much freedom each one has.

| Layer | Who decides | Example | Property |
|---|---|---|---|
| Layer 0, fixed procedure | The stage machine | INIT, OBSERVE, GATE, PLAN, TEST, VERIFY, SYNTHESIZE, FINALIZE | The model cannot skip a stage, reorder them, or invent one; whether the tool namespace is gated on the stage as well depends on which orchestrator is running |
| Layer 1, deterministic scoring | Code, from a fingerprint | `Score = (Base x Relevance x Impact) / Cost`, plus a `requires` gate that drops tools the profile rules out | Auditable, replayable, no model call, on the path that calls it |
| Layer 2, learned priors | Code, from history | Fatigue at `0.8 ** consecutive_failures`; per-profile success rates; tool correlations | Deterministic given the same history: a lookup, not a judgement, on the path that calls it |
| Layer 3, model judgement | The model, evidence-bound | Which endpoints in this bundle matter; whether two findings chain; whether a finding is real | Every output passes a mechanical gate before it can change state |

Those two middle rows carry a qualification, and it is not a footnote. There are two orchestrators. When a model on the far side of an API drives the run, it asks for the ranked list and works through what comes back, and Layer 1 and Layer 2 are what chose it. When a coding agent drives the run, which is the default, the executor still constructs a recommender and a scheduler on every tool execution, and the entry point that ranks them is never called: the tool, the URL, the arguments and the priority come out of the plan the agent wrote, and what stands in for relevance scoring is the grounding gate in chapter 02, which asks whether a proposal quotes something real rather than whether a tool fits the profile. Chapter 02 introduces the split and names the two paths server-driven and agent-driven, which are the names this book uses for it; chapter 03 and chapter 05 each report a consequence of it.

So the honest form of the argument in this chapter is that the deterministic layers exist, are auditable, are replayable, and are live on one of the two paths, while the other substitutes a check of a different kind. That is a weaker claim than the table on its own reads as, and it is the one the evidence in this book supports. Chapter 01 makes the same claim about tool selection at more length, and scopes it the same way at the point it makes it.

Gradient is the load-bearing word. Nothing here is a stack with a top that calls a bottom. The layers rank decisions by how derivable each one is, and the rule that comes with the ranking is that a decision may rise to a higher layer only when the layer below provably cannot make it.

One numbering collision to flag before you go reading the code. The modules count from the pipeline's point of view, so `core/fingerprint.py` heads itself Layer 1, `core/tool_recommender.py` Layer 2, and `core/scheduler.py` Layer 3. This chapter counts by who decides, which reserves the top slot for the model: the recommender's Layer 2 is this chapter's Layer 1, and the scheduler's Layer 3 is this chapter's Layer 2. Fingerprinting gets no layer of its own here, because it decides nothing. It is the input Layer 1 reads. The two `fingerprint.py` symbols cited further down sit in the Layer 2 section because the profile hash is what Layer 2 keys its statistics on, not because the module carries that number.

## Layer 0: the stage machine

The cheapest control in the whole system is an ordered list of stages the orchestrator moves through and the model gets no vote on. Observe before you plan, plan before you test, verify before you synthesize, and finalize even when the scan went badly. Especially then. What the model gets no vote on is the order, which the orchestrator advances and the model cannot. Whether it can still ask for a tool belonging to another stage depends on which orchestrator is running, and chapter 01 takes that up.

There is no clever code here. Mine is a markdown contract the orchestrator reads at the start of every run, and it looks faintly unserious sitting next to the rest of the codebase. What makes it work is that the sequence is the orchestrator's to advance and not the model's to negotiate. A model under context pressure will quietly drop a step from a prompt and then report that it did it. That is less dishonesty than compression. Skipping has to be impossible, not discouraged, and it is the highest return on effort in this handbook as well as the step people skip, because writing down eight stage names does not feel like engineering.

## Layer 1: scoring, not deciding

<!-- num-ok: one line is a spelled quantity counting a code artifact: the score expression the formula below transcribes is a single statement in core/tool_recommender.py -->
Once the target has been fingerprinted into a profile, which tools are worth running is arithmetic. Every tool in the catalogue carries a small record of scoring parameters and profile-match rules, `[[code:tool_recommender.py:ToolRelevance]]`, and the score is one line:

```
Score = (Base x Relevance x Impact) / Cost
```

<!-- num-ok: 15, 8 and 3 are TIER_HIGH, TIER_MEDIUM and TIER_LOW, module-level literals in core/tool_recommender.py that this sentence quotes directly; they are cutoffs written into the code, not counts of anything observed -->
Base is the tool's inherent priority, Impact is the severity if it finds something, Cost is roughly how long it takes, and Relevance is a product of multipliers earned from conditions that hold on this profile. The tier thresholds are constants, `[[code:tool_recommender.py:TIER_HIGH]]` and its two siblings: 15 and above runs first, 8 and above runs if there is time, 3 and above only on a comprehensive pass, and anything below 3 is labelled SKIP. The tiers label a ranked list rather than filtering it: `recommend()` hands back the SKIP-tier tools too, and drops a tool only when its requirements fail or its score falls to zero.

<!-- num-ok: 0.1 is the mongodb entry in this tool's penalizes map in core/tool_recommender.py, a multiplier written into the catalogue by hand, not a rate measured from anything -->
The interesting fields are the ones that keep tools out, and they come in two kinds. `requires` and `requires_any` are hard gates: fail one and the tool is dropped before it is ever scored. `penalizes` is soft, a multiplier applied to a tool that still runs. The SQL injection entry carries both, and its `mongodb` penalty of 0.1 can never fire: `requires_any` has already excluded MongoDB by the time that multiplier would apply, so the condition gets evaluated on every scoring pass and cannot come back true. A trimmed excerpt:

```python
"test_sqli": ToolRelevance(
    tool_name="test_sqli",
    base_priority=8.0,
    impact_potential=5.0,     # critical: data breach
    cost_estimate=4.0,
    requires_any=[
        "likely_database in ['mysql', 'postgresql', 'mssql', 'oracle', 'sqlite', 'unknown']",
    ],
    boosts={
        "error_verbosity == 'high'": 1.5,
        "backend_language == 'php'": 1.2,
        "waf_detected == False": 1.2,
    },
    penalizes={
        "likely_database == 'mongodb'": 0.1,
    },
)
```

<!-- num-ok: three fields is a spelled quantity counting a code artifact: the profile attributes this sentence changes, PHP/Laravel/MySQL to Node/Express/MongoDB, each of them named in the sentence itself. The membership gates that reverse read only likely_database, in the catalogue entries core/tool_recommender.py holds for these two tools -->
Run the reference implementation in `core/` against a PHP, Laravel, MySQL profile and the NoSQL injection tool never enters the ranked list at all. Its `requires` gate asks for `likely_database == 'mongodb'`, that is false on this profile, and the tool is dropped before scoring. The SQL injection tool is scored and present. Change those three fields to Node, Express, MongoDB and the exclusion reverses exactly: the NoSQL tool is scored, and the SQL injection tool is the one that never appears, because MongoDB is missing from its `requires_any` list. The profile decides which tools are in the conversation at all, before it decides their order.

Say membership rather than order, because order is the weaker claim and I cannot stand behind it. Sweep every profile that satisfies the description I just gave you, varying only the fields that sentence leaves unsaid, and the SQL injection tool refuses to stay put. Sometimes first. Sometimes down in the medium tier behind the CORS and XXE checks, on a target with a WAF and no content-type hints, where the command injection tool costs half as much to run and takes no WAF penalty at all. Membership does not move. It is the property worth putting your name on, and the one a skeptic can falsify.

No model was consulted for any of it. It is a dictionary lookup and a multiplication, it takes microseconds, it gives the same answer every time, and when a client asks why you fuzzed their application for NoSQL injection the answer is a row in a table rather than a paragraph of recalled intent.

Detection confidence is folded in rather than ignored, `[[code:tool_recommender.py:_field_confidence]]`. A boost earned from something the fingerprinter is only half sure about gets attenuated by that confidence before it multiplies, so weak evidence nudges the score and strong evidence moves it. The effect shows up on ambiguous targets, and most targets are ambiguous.

## Layer 2: priors the code can compute

Layer 1 knows what the target looks like. It knows nothing about what has worked before. That is `[[code:scheduler.py:adjust]]`, which takes the ranked list from Layer 1 and multiplies it by history along several independent axes.

<!-- num-ok: 0.3 is FATIGUE_FLOOR in core/scheduler.py, the literal floor the fatigue multiplier is clamped to, quoted from the code path this paragraph describes -->
Fatigue is the simplest. A tool that keeps failing decays at `0.8 ** consecutive_failures`, floored at 0.3 so nothing is ever permanently dead. Aggressive mode switches fatigue off, on the argument that when you have explicitly asked for thoroughness you do not want productive tools soft-capped by a bad streak.

Contextual success rates are the axis I get the most out of in practice. Rather than one global success rate per tool, the scheduler keys its statistics by a compact profile hash, `[[code:fingerprint.py:profile_hash]]`, of the form `php:mysql:waf:cloudflare:rest:laravel`. Tool performance is contextual. An injection tool that lands constantly on PHP and MySQL tells you almost nothing about how it will do on Node and MongoDB, and a single blended average destroys exactly that signal. When the exact hash has no data behind it, similarity matching over the components carries a partial answer across, `[[code:fingerprint.py:hash_similarity]]`, weighted so that backend language and database dominate the comparison.

<!-- num-ok: 0.4 is CORRELATION_THRESHOLD in core/scheduler.py, the literal rate a correlation must reach before the scheduler acts on it -->
Correlations are the third axis. When two tools keep succeeding on the same URL, a hit from one raises the other, at a threshold of 0.4 and only after enough observations that the ratio means something.

Calling any of this learning oversells it. There is no gradient and no model anywhere in it, just counters in a JSON file and arithmetic over them. Same history, same answer, and you can open the file and read why. A prior you cannot inspect is a hunch with better manners.

## Layer 3: what is left for the model

After a fixed sequence and two layers of arithmetic, what remains genuinely is not derivable, and it happens to be the part worth paying for.

<!-- num-ok: 200 is the HTTP status code for OK, a protocol constant naming the response a catch-all SPA route returns; it identifies a response, it does not count one. "one place" on the same line contrasts two locations in a target's surface and counts nothing in the code -->
Which endpoints in a minified bundle look like they touch other people's data. Whether an information leak in one place and a weak identifier in another compose into something worse than either alone. Given a response that reads as an authentication bypass, is it one, or is it the single-page application's catch-all route politely handing back its index shell with a 200? And the judgement the whole report rests on, asked of each finding in the exact shape it took on this target: is it real?

Those are judgements. Pattern matching does them badly and a competent model does them well enough to be worth both the cost and the variance.

<!-- num-ok: 404 is the HTTP status code for Not Found, one possible response to an invented endpoint, not a guaranteed outcome -->
The intended boundary is strict: a proposed tool call passes schema validation and a repair loop before an executor will look at it, `[[code:llm_control.py:ToolCallValidator]]`, and admitted executions are recorded. An invented endpoint may return 404, a login page or a catch-all application shell. None of those responses becomes proof merely because it was captured. A claim about something already observed needs a quote from its own artifact, then a separate check of what that quote supports. The historical severity endpoint checks a quote for a raise; the authored score requested by its contract is not enforced, as chapter 03 shows. The boundary is the design, and the following exceptions are why its enforcement has to be tested.

On the agent-driven path three of those conditions hold by the orchestrator's good behaviour rather than by construction. It has a terminal outside the tool surface, so nothing physically stops it reaching the target off the record. The write path carries a subcommand that stores a finding, so an assertion can become a row without a tool having run. And the quote test has an escape hatch that keeps one item per batch and a channel by which a caller supplies its own score. Chapter 02 takes all three apart. The severity condition is the one that is not path-dependent, and chapter 03 tests it, kill switches and all.

The model proposes and deterministic code disposes. That is the first law below, an interface to enforce rather than an assurance that the historical agent has no way around it.

## What this costs

Honesty about the bill. Layer 1 needs a relevance table, and someone has to write it and keep writing it, tedious work that is never finished, because the tool catalogue never stops moving. Layer 2 needs persisted statistics and a decision about what a profile is, and a badly chosen profile hash gives you contextual learning that learns nothing at all. Layer 0 is nearly free but it binds you: a fixed stage machine is a commitment, and the first time you want a stage skipped you will find yourself arguing with your own design, exactly as intended.

The gradient has an obvious failure mode too. Push too much down and you have rebuilt a conventional scanner with a chat interface bolted to the front, and that is worse than either component on its own. The line I use is derivability. If a competent tester would reach the same answer from the same inputs every time, it is not a judgement and the model should not be asked. If two competent testers would reasonably disagree, keep it in Layer 3 and gate the output.

## What has actually been shown, and what has not

This is one system's argument drawn from one corpus. It is not a controlled study, and I am not claiming that determinism has been proven superior to any alternative.

The corpus, exactly. `[[stats:corpus.scans.total]]` scans against `[[stats:corpus.hosts_distinct]]` distinct hosts, across `[[stats:corpus.tool_executions]]` tool executions, between `[[stats:corpus.window.first_scan]]` and `[[stats:corpus.window.last_scan]]`. Read the first of those figures as scans attempted, not scans that finished: `[[stats:corpus.scans.by_status.failed]]` of them failed outright and `[[stats:corpus.scans.by_status.killed]]` were killed. The scans produced `[[stats:corpus.findings.stored]]` stored findings, `[[stats:corpus.findings.non_fp]]` of which survived false-positive review, and `[[stats:corpus.findings.by_severity_non_fp.info]]` of those survivors are informational severity, so the majority of what cleared review is not a vulnerability anyone will act on. What is left of it went to real targets in real engagements, in reports people did act on.

What that supports is a claim about operation. A system built this way ran at that scale, stayed in scope, and produced findings that survived review. What it could not support, when this chapter was first written, was a comparison, because there was no arm of it where the controls were switched off. Two of those arms have since been run as pre-registered studies on lab targets: appendix D ablates the verifier-and-acceptance stage as a package, and appendix E pulls the package apart and throws each switch independently. What they measured obeys the discount this section asks for, in both directions. The verification stage changes what a run ships (pre-report suppression and blinded precision move with the model verifier, replicated across both studies) and the deterministic acceptance layer behind it marked [[stats:benchmark.factorial.layers.governor_fp_marks]] false positives in [[stats:benchmark.factorial.n_total]] runs, so the cleaner-report effect belongs to the verifier, not to the ruleset this book spends chapters on; the ruleset's measured place is severity governance, duplicate control and auditability. The scheduler and ranking layers still carry their ablation flags unexercised, `[[code:scheduler.py:HARNESS_SCHEDULER_ENABLED]]` among them: the study that would use them has not been run, chapter 05 gives the mundane reason, and for those layers the thesis remains argued, not measured, with the discount applied in full. That "has not been run" is a dated claim, not a standing one: [the evidence register](appendix-f-evidence-register.md) carries it with a register date, beside the execution, analysis and review status of every other study this book leans on.

The selected public-target aggregate has an `n` of `[[stats:benchmark.juice_shop.n]]`. One author-recorded run. Chapter 05 reports its numbers, the two runs excluded from it, and why one of those exclusions is better justified than the other. The repository does not carry the raw findings, ground truth or matcher needed to reproduce its labels, so it is not presented as a benchmark result.

I did not enjoy writing this section and I think it is the most useful one in the chapter. A smaller claim that holds beats a larger one that does not, and what is on offer here is a design argument with operational evidence behind it at a stated scale. Test it rather than adopt it.

## The five laws

These five sentences are the spine of everything that follows. Each is design intent, and the chapter named at the end of a law is where this system is held against it: which parts hold by construction, which hold on only one of the two orchestration paths, which hold on the orchestrator's good behaviour, and which do not hold yet.

<!-- num-ok: 404 is the HTTP status code for Not Found, the same protocol constant used in the Layer 3 section above, restated here in the law it illustrates -->
1. **The model proposes; deterministic code disposes.** Give the model a proposal interface, not direct access to the target, raw storage or the last word on severity. Deterministic code validates, executes and records admitted work. The historical system does not enforce that boundary everywhere: both orchestrators can reach a shell, and its write path carries a subcommand that stores a finding without an execution. An invented endpoint might return 404, a login page or an application shell; record the response and judge the claim separately. A shared writer is not a sandbox. Chapters 01 and 02.

2. **Claims about the past must quote. Proposals about the future must execute.** These are different kinds of statement and they need different gates. A claim about something already observed must cite its own capture; a matching quote establishes citation integrity, not that the conclusion is true. The historical gate leaks: it keeps an item per batch even if none passes, and on one orchestration path a caller-supplied confidence can stand in for the check. A proposed test cannot be validated by quoting an observation it has not made. It may run only after authorization, scope, gate and budget checks permit it, and its outcome still needs interpretation. The law is not permission to execute every proposal. Chapter 02.

3. **Severity falls by default and rises only against proof.** The deterministic governor can lower a severity or mark a finding false-positive, and cannot raise one. That limits its authority; it does not make its conclusions correct. Under-reporting can hide a real vulnerability, so every lowering rule needs matching and counterexample tests and a reviewable reason. The historical raise endpoint checks a verbatim quote but does not enforce the authored score its contract requests. A quote alone is not exploitability proof. Bind the capture to the finding, apply a reviewed domain proof policy, and retain a separate human review and sign-off process. Chapter 03.

4. **Scope is a function, not a sentence.** Authorization written into a prompt competes with every other instruction in the context window. Encode the operator's permission as a reviewable policy and enforce it before every outgoing action, with a record of refusals. The historical guard falls short: it is asked at the tool boundary rather than at every request, broadens some host boundaries, and fails open under a kill switch or when constructed without a target. The lab rejects unlisted origins before its trusted callback, but transport containment still belongs in the adapter. A policy decision is only as correct as the authorization and destination it evaluates. Chapter 04.

5. **Report what you didn't do.** A scan that found nothing and a scan that could not reach anything are different scans, and a report that renders them identically is lying by omission. Coverage, gate status, and a ledger of every host skipped with its reason belong in the deliverable, next to the findings. That is a requirement the historical report did not meet: only coverage arrived, computed against its weakest denominator and under a label naming a different one. The lab accounts for planned tool-and-URL actions, executed work, errors and skips; that denominator does not measure vulnerability coverage. Chapter 05.

## How to read the rest of this

Each remaining chapter opens on a specific way autonomous offensive agents break, shows the control that fixes it, then admits what the control still gets wrong. The reference implementation in `core/` is clean-room and deliberately non-functional: the profiling, the scoring, the scheduling, and the validation are real and runnable, and everything that would put a packet on the wire is withheld. Read it, disagree with parts of it, build your own.

One request, and it is the point of every honesty section in this handbook. If you build this and it works better, measure it against the version with the deterministic layers switched off and publish both numbers, because that is the experiment I owe you and have not run.
