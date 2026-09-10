# The fixed procedure

Chapter 00 argued that the opening of an engagement is procedure rather than judgement. This chapter is what taking that seriously looks like in code, with one exception it names in the first section: a stage machine the model gets no vote on, which is the one layer `core/` does not ship, a scoring table that ranks tools from a fingerprint without a model call, and a set of priors that live as counters in a file instead of intuitions in a context window.

It is also where I hand you a measurement that looks, on first reading, like it sinks the argument. It gets its own heading, with two more sections of argument after it. Putting it last would have been the exact dishonesty this handbook is about.

## Layer 0: eight stages, seven boundaries

Eight names, in this order: INIT, OBSERVE, GATE, PLAN, TEST, VERIFY, SYNTHESIZE, FINALIZE.

The contract in the working system counts seven stages and files verification as a half-step inside testing. This chapter counts it as a stage of its own, because the boundaries on either side of it carry two of the checks below. Nothing about the system changes with the count, and a reader holding this list against that contract should expect the two totals to differ by one.

Nobody needs a handbook to arrive at that list. What earns it a place in the architecture is the seven boundaries between the names, because a boundary is the only place a deterministic check has to stand.

Three of the seven are about not getting ahead of yourself. The scope function does not run until observation has finished handing it things to rule on, nothing is planned until it has ruled, which is chapter 04's whole subject, and nothing is tested until the plan is a ranked list instead of a paragraph of intent, with the ranking coming from the two layers below on one orchestration path and from chapter 02's grounding critic on the other. Two more are about not believing yourself. A finding is re-examined against the artifact that produced it before anyone may write about it, and the report is then composed out of that verified set, never out of the model's recollection of the run. The model is badly placed to police that last distinction on its own, which is exactly why it is a boundary and not an instruction. The last two are housekeeping and matter anyway: a scan record has to exist before a packet leaves the box, or there is nowhere for artifacts to land, and FINALIZE has to run even after a run that collapsed, or chapter 05's coverage ledger has nothing to report.

Without stages you would be deciding where each of those checks goes on every run, which is the improvisation problem again, one level up.

Two honest limits. First, the sequence in the eight names above is a contract the orchestrator follows rather than a state machine that refuses out-of-stage tool calls: the orchestrator advances the stage and the model cannot, but the model can still ask for a testing tool during observation and be told no by convention, not by construction. Gating the available tool namespace on the current stage is strictly better, and it is what I would build here. The server-side orchestrator already does it: it keeps its own phase list, offers the model only the tool schemas that phase allows, and refuses a call for anything else. So this limit belongs to the path these eight names describe rather than to the system, and I had written it as though it belonged to both. Second, and worth saying plainly because the rest of this chapter leans on runnable code: Layer 0 is the one layer here with nothing runnable behind it. The reference implementation in `core/` contains no stage machine, and no test in this repository backs a sentence in this section.

## The profile everything downstream reads from

[num-ok 1]
Fingerprinting produces one object, [`fingerprint.py:TargetProfile`](../core/fingerprint.py), and it is 30 fields wide: identity, technology stack, API characteristics, security posture, authentication mechanisms, database hints, attack surface, and a dictionary of the evidence that produced each conclusion. Four of those fields are confidences, held separately from the values they qualify, so `backend_language` and `backend_confidence` travel together but are consumed differently by the layer above. That separation turns out to matter more than it looks like it should, and I come back to it in the next section.

Contextual learning does not key on the profile. It keys on [`fingerprint.py:profile_hash`](../core/fingerprint.py), which projects those fields down to six components:

```
backend : database : waf_status : waf_vendor : api_type : framework

php:mysql:waf:cloudflare:rest:laravel
nodejs:mongodb:nowaf:none:rest:express
```

Everything else is discarded. All four confidence scores go. So does the entire attack-surface block, so a target with a file upload, verbose errors, a JWT and permissive CORS produces the same hash as an otherwise identical target with none of them, and the two pool their statistics. The API list is truncated to its first element, and there is no `unknown` in that slot: `api_types[0] if api_types else "rest"` means a target where nothing was detected is filed under REST, indistinguishable from one where REST was positively identified.

[num-ok 2]
The projection is defensible and I would make the same call. Statistics keyed on a hash this coarse actually accumulate; statistics keyed on the full profile would give you a bucket of one per target and nothing to learn from. What I would insist on is that the discarded list be written down somewhere, because six components is a decision about what the system is allowed to learn from. Nothing in the code records that decision: the hash is built in one method, the fields it drops are simply the ones it does not mention.

## Scoring is arithmetic over that profile

Every tool in the catalogue carries a small record of scoring parameters, [`tool_recommender.py:ToolRelevance`](../core/tool_recommender.py), and the score is `Score = (Base x Relevance x Impact) / Cost`, with Relevance the product of the multipliers the profile earned.

[num-ok 3]
Chapter 00 gave the tiers, [`tool_recommender.py:TIER_HIGH`](../core/tool_recommender.py) at 15 and its two siblings at 8 and 3, and made the point that they label the ranked list without filtering it. Worth adding what the labels do inside the recommender, which is nothing. [`tool_recommender.py:tier`](../core/tool_recommender.py) is called once per tool and its answer goes straight into the human-readable reason string. Force it to return SKIP for every tool and the ranked list comes back in the same order with the same scores and different prose. The tiers are advice to whatever runs the list, not a decision the scorer takes.

What chapter 00 did not give is the part that decides whether a tool is in the ranked list at all, and there are two mechanisms for that rather than one.

The first is the hard gate. `requires` conditions must all hold and `requires_any` needs at least one, checked by [`tool_recommender.py:_requirements_met`](../core/tool_recommender.py), and a tool that fails is dropped before a score is ever computed. The second is quieter. A `penalizes` entry with a multiplier of zero drives the relevance product to zero, and [`tool_recommender.py:recommend`](../core/tool_recommender.py) discards anything whose score lands at or below zero. Same outcome, different route, and the catalogue uses both.

[num-ok 4]
The pattern, trimmed to the parts that matter, with its 0.0 penalty:

```python
"test_graphql": ToolRelevance(
    tool_name="test_graphql",
    base_priority=8.0,
    impact_potential=4.0,
    cost_estimate=3.0,
    requires=[
        "has_graphql == True",
    ],
    boosts={
        "has_graphql == True": 2.0,
    },
    penalizes={
        "has_graphql == False": 0.0,            # do not run
    },
),
```

Read the gate and the penalty together and the penalty has nothing to do. When `has_graphql` is false the gate closes and the penalizes map is never walked; when it is true the condition is asked and comes back false. The comment says `do not run`, and it is true that the tool does not run, but the line saying so is not what stops it.

[num-ok 5]
That is one entry. I swept the whole catalogue for it, enumerating every value the condition language can distinguish for each field a tool's own conditions reference, and asking whether any profile satisfies both the requirement gate and the penalty.

[num-ok 6]
8 of the 21 penalty conditions in a catalogue of 26 tools can never fire. Every one is already excluded by a gate on the same field in the same entry. Chapter 00 found one of them by hand and called it dead configuration. The sweep found seven more, spread across six tools. Five of those repeat a single idiom, a 0.0 penalty behind a gate on the field it names, which is the shape the GraphQL entry above comments `do not run` and the other four leave uncommented; the remaining two are 0.1 penalties on the NoSQL entry, shut out by that entry's own `requires`. I went looking to confirm one and came back with eight, which was not the afternoon I had planned.

I find those entries more interesting than the live ones. A relevance table is hand-maintained, hand-maintained things rot, and this rot is invisible in the ordinary way: nothing breaks and nothing logs, and the tool behaves correctly throughout. What makes it findable is that the table is data. You can enumerate the conditions, ask which are reachable, and get an answer in a loop. Try the equivalent against a paragraph of methodology in a system prompt.

None of which is an argument against keeping the table. Point the scorer at a Python, Django, PostgreSQL profile and the prototype-pollution and NoSQL-injection tools are gone before scoring begins, because that stack cannot host either bug, and the run spends its budget somewhere it might pay. That is a dictionary lookup standing in for an hour of a tester's attention, and it hands you a ranked list with a reason on every row.

The confidence weighting has a related asymmetry, and this one is live. [`tool_recommender.py:_field_confidence`](../core/tool_recommender.py) attenuates every multiplier by the fingerprinter's confidence in the field the condition names:

```python
weighted = 1.0 + (mult - 1.0) * confidence
```

The gate does no such thing. `_requirements_met` calls [`tool_recommender.py:_evaluate_condition`](../core/tool_recommender.py) raw, with no confidence anywhere in the path. So a database guess the fingerprinter holds weakly still opens or closes the gate absolutely, while every boost and penalty keyed on that same guess barely moves the score. Sweep any profile across the confidence range and the membership of the ranked list never changes. Only the numbers move, and which way they move depends on whether that profile's tracked conditions are mostly boosts or mostly penalties, so I will not claim a direction. On a Ruby and Oracle target behind a WAF, where the WAF penalty is the only tracked condition left, the SQL injection tool drops out of the medium tier and into the low one as the fingerprinter gets more sure of itself.

I think the gate is right to be binary. Softening it would mean scoring MongoDB tools against MySQL targets at a discount, which is worse than not scoring them. But the asymmetry is worth knowing, because it tells you exactly where a fingerprinting error costs the most. A wrong `backend_language` at high confidence is embarrassing. A wrong `likely_database` at any confidence at all silently rewrites which injection tools exist for that target.

[num-ok 7]
The dataclass documents 0.0 as meaning skip, and it does, though only because every zero penalty in the catalogue happens to sit on a field `_field_confidence` does not track and therefore scores at 1.0. Put one on a tracked field and at partial confidence the multiplier comes out at one minus that confidence, which is not zero, and the tool runs. The same helper has a wrinkle at the other end of the scale, which caught me. A confidence of exactly 0.0 is read as never set and returned as 1.0, on the reasonable argument that a profile which does not track confidence should not have its boosts silently zeroed. The side effect is a discontinuity at the bottom: a field the fingerprinter is barely sure of scores lower than the same field with no confidence recorded at all.

## Priors the code looks up

[`scheduler.py:adjust`](../core/scheduler.py) takes the ranked list and multiplies it along six independent axes. Chapter 00 named three. The other three are a first-time coverage bonus, [`scheduler.py:COVERAGE_BONUS`](../core/scheduler.py), a productivity boost for tools that historically return findings per execution, and a penalty when the tool's category has burned through its budget from [`scheduler.py:CATEGORY_BUDGETS`](../core/scheduler.py).

[num-ok 8]
Fatigue is [`scheduler.py:FATIGUE_DECAY`](../core/scheduler.py) raised to the consecutive-failure count, clamped by [`scheduler.py:FATIGUE_FLOOR`](../core/scheduler.py). At 0.8 and a floor of 0.3, the floor binds from the sixth consecutive failure onward, and every failure after that changes nothing. Whether six is the right number I genuinely do not know, and nobody tuned it. It sits in a file, so anyone who disagrees can change it and re-run the ranking against their own history.

[num-ok 9]
Contextual rates are the axis with the most hidden structure. [`scheduler.py:_contextual_rate_for_hash`](../core/scheduler.py) wants an exact profile-hash match with enough observations behind it. Failing that, it pools every stored hash whose [`fingerprint.py:hash_similarity`](../core/fingerprint.py) clears 0.6, and uses the pool only when at least three observations have accumulated across it. Backend and database carry 0.35 each, WAF status 0.15, framework 0.10, and the remaining two components round out the rest. Two consequences follow from those weights, and neither is obvious from reading the scheduler.

The first is a hard invariant. Two profiles that agree on neither backend nor database cannot reach the cutoff no matter what else they share, even with the partial credit that unknown components earn. The other four are worth less between them than the gap those two leave, and an unknown on either side buys back only a fraction of it. So the fuzzy match will never carry MySQL-on-PHP experience to MongoDB-on-Node, which is correct and reassuring.

[num-ok 10]
The second is tighter than it looks. The scheduler's own documented example is carrying `php:mysql` experience to a fresh `php:postgresql` target. That pair scores 0.65 against a cutoff of 0.6, so it clears by 0.05, which is half the framework component's weight of 0.10 and not the whole of it. Change `laravel` to `symfony` at the same time and the pair falls to 0.55 and carries nothing. In practice the fuzzy match means same backend and near-identical everything else. That is a much narrower promise than the phrase "fuzzy profile matching" suggests, and I would sooner state the narrow version than have a reader discover it in production.

Correlations record the wrong tool, and the reason is not the one I first wrote down. [`scheduler.py:_update_correlations`](../core/scheduler.py) is the whole mechanism, and this is all of it:

```python
src_successes = self._tool_success_count[successful_tool]
for other_tool, targets in self._successful_targets.items():
    if other_tool == successful_tool:
        continue
    key = f"{successful_tool}→{other_tool}"
    if target in targets:
        self._correlations[key]["cooccurrence"] += 1
    self._correlations[key]["tool1_successes"] = src_successes
```

Every key it can write carries the tool that just succeeded on the left, and it iterates only over `_successful_targets`, which holds tools that have already succeeded at least once. A tool that has not succeeded yet is in neither position. So the first success of a run creates no edge at all, there being nothing to iterate over; and when a second tool lands on a URL the first one already hit, the only edge available to carry that co-occurrence is the one pointing from the second tool back to the first. The forward edge was not writable at the moment it would have been true. [`scheduler.py:correlation_boost`](../core/scheduler.py) then looks up recently-successful-to-candidate, so the boost goes to whichever tool got there first.

The tempting explanation is the wrong one, and I published it before I checked. [`scheduler.py:record`](../core/scheduler.py) calls this function before adding the current tool's target to its own success set, which looks like the cause. It is not: the loop skips the current tool's own entry outright, so its set is never read here, and swapping those two statements produces byte-identical counters and boosts. Direction is fixed by which tool reached the URL first. Statement order has nothing to do with it, and a reader who took my first diagnosis to their own scheduler would have moved a line and fixed nothing.

Whether the boost landing on the earlier tool is actually backwards depends on execution order, so I measured all three cases. Sweep one tool across every URL and then the other, and every edge points one way and the reverse edge sits at zero. Interleave them in a stable per-URL order and you get the same lopsided result, and since ranking is deterministic and the top-ranked tool tends to go first, a stable order is the case to expect. Alternate which tool goes first and both edges fill in evenly and the mechanism works as advertised.

None of which argues against the layer. Every multiplier it applies is appended to that tool's reason as it goes, so an adjusted list comes back reading `fatigue×0.80; sr_exact×1.15; productive×1.15`, and the question of why a given tool ranked where it did is answered by reading a line instead of reconstructing a decision. The three defects here were findable for the same reason.

The last of them ranks a failing tool higher on a resumed scan than on the scan it resumed. Inside a live session that cannot happen, because recording a failure is also what marks a tool as tried, so a fatigued tool can never also be a new one. Round-trip the identical state through the persistence schema and it is both: the restored scheduler applies the fatigue penalty and the first-time coverage bonus to the same tool in the same call, and ranks it above where the live scheduler had it. [`scheduler.py:from_dict`](../core/scheduler.py) restores tool statistics, contextual statistics, correlations and success counts, and the set of tools already tried is not in the schema at all.

Three defects, none of them catastrophic, all found the same way: I read a file and wrote a loop. That is what I mean when I say these decisions belong outside the model. There was no transcript to interpret and no run to reproduce, because there is no run to reproduce: `recommend()` and `adjust()` are functions of a profile and a JSON file, and they answer the same on the tenth call as on the first.

## Half again as many turns as executions

Now the number, and it does not say what a reader sympathetic to this design would want it to say.

Across every scan in the corpus with a usable transcript, the measured ratio of model turns to security-tool executions is `1.520446096654275`. Restricted to scans that actually executed at least one tool, it is `1.2936802973977695`. That is about half again as many model turns as tool executions, and still comfortably more than one apiece once the scans that executed nothing are dropped.

That is not, on its face, evidence of a determinism win. If you arrived expecting a system where the model barely runs, the measurement does not support that and I am not going to dress it up. The model is in the loop constantly, at better than one turn per tool execution. Anyone selling a design like this on the promise of fewer model calls is selling something these numbers do not back.

The caveat, published verbatim at `llm_turns is a PROXY for assistant turns, not a transcript-accurate count: it is defined as tool results + 1 (one model turn per tool result, plus the turn that precedes the first tool use), because both transcript formats record tool results reliably and neither marks an assistant-turn boundary. Two known biases, pulling in opposite directions: a turn that emits only text and calls no tool is not counted at all (UNDERCOUNT), and a single turn issuing several tool calls in parallel is counted once per result (OVERCOUNT). Which one dominates is not measured. Note which way the flattery runs: fewer model turns per deterministic tool execution is the result this project would like to see, and the undercount is the bias that produces it -- so read every ratio here as an approximation of shape, not a precise figure. llm_turns_per_agent_tool_call in particular is near-1 BY CONSTRUCTION -- turns are defined as results + 1 and results track calls -- so it restates the definition above and carries no information about the system. It is not a finding; it is published only so the definition can be checked against the totals.`, matters as much as the figure. `llm_turns` is not a transcript-accurate count. It is a proxy, defined as tool results plus one, because both transcript formats record tool results reliably and neither marks an assistant-turn boundary. Two known biases pull in opposite directions: a turn that emits only text and calls no tool is never counted at all, and a turn that issues several tool calls in parallel is counted once per result. Which one dominates has not been measured. Note which way that flatters me. Fewer model turns per deterministic tool execution is the result this project would like to report, and the undercount is the bias that produces it. Read the ratio as an approximation of shape, not a figure to quote to three decimal places. That caveat has since earned itself, which is why it is still standing here rather than quietly softened: between two corpus snapshots the ratio moved by close to a fifth, and every gloss of it in this section, the heading included, had to be rewritten. The companion statistic in the same block, `1.0380710659898478`, is near one by construction and carries no information about the system at all; it is published only so the definition can be checked against the totals.

Coverage is thin and is not extrapolated. `20` scans of `206` carried a transcript this measurement could read, and the active figure drops a further `5` that executed no tools. In absolute terms that is `269` tool executions measured against `7259` in the corpus as a whole.

The argument the number does support lives one level below turn counting.

On the path that calls the ranking, the model is not choosing which tools run. It is not choosing their order, and it is not choosing what they run against. Those decisions belong to a scoring pass over a fingerprint and a lookup over stored counters, both auditable and both replayable: hand `recommend()` the same profile and `adjust()` the same statistics file and the ranked list comes back identical, today and next year, with no model in the path and nothing to reproduce. What the turns are doing in between is carrying results forward, reading what a response body means, and proposing where to look next inside an order they did not set. A system can be noisy and still be deterministic about the things that matter. Turn count measures orchestration chatter. Decision authority is a different quantity, and this ratio cannot tell a talkative system with none of it apart from a quiet system with all of it.

Which path that is, is the qualification this section owes you, and it is not a small one. Chapter 00 flags the split and chapter 02 develops it: there are two orchestrators, and the scoring pass and the counter lookup are live on the server-driven one. On the agent-driven path, which is the default, the executor builds a recommender and a scheduler on every tool execution and the entry point that ranks them is never called. The tool, the URL, the arguments and the priority come out of the plan the orchestrating model wrote, and what stands in for relevance scoring there is chapter 02's grounding gate, which asks whether a proposal quotes something real and has no opinion about whether a tool suits the profile. Chapter 05 gives the consequence for the ablation. The consequence for this section is that the reproducibility claimed in the paragraph above is a property of the layers rather than of every scan this system has run.

The measurement makes that pairing worse rather than better, and it belongs in the same breath as the claim. Every scan the ratio could be measured over is on the path where the ranking is not called. Its two transcript sources exhaust the measured set, `12` read out of coding-agent sessions and `8` out of the unattended runner's own feed, and that runner drives the same skill headless, so both sources are the same orchestrator. The ratio is measured entirely on the path whose tool selection the model makes, and the argument standing beside it describes the other one.

One modest thing the ratio does establish, and it is about cost, not determinism. If turns track executions at a roughly fixed rate, the token bill scales with how many tools you run, not with how large the space of things you might have run happens to be. That is a useful budgeting property. It is not the thesis of this handbook, and I would rather name it small than let it stand in for the claim it does not prove.

None of this shows determinism helped. The scheduler-and-ranking ablation has not been run -- the scheduler carries the flags for it, [`scheduler.py:HARNESS_SCHEDULER_ENABLED`](../core/scheduler.py) among them, and that study remains owed; the verification-stage studies in appendices D and E measured a different layer, and what they attribute to determinism is governance, not detection. What the layers in this chapter give you is a system where the question is answerable at all, because the deterministic half can be switched off and replayed. Ask the same question of an agent that improvises its methodology each run and there is nothing to switch off.

## What is actually left for the model

In recon specifically, the model's job is reading rather than selecting.

The signature tables in the fingerprinter will tell you the server, the framework, the session cookie and the database from an error string, and they will do it faster and more consistently than a model. They will not tell you that a particular chunk of a minified bundle builds a request carrying somebody's customer identifier, or that an endpoint named like an internal admin route answers differently to a trailing slash. Turning prose, markup and JavaScript into candidate structure is genuinely not derivable, and it is where model capacity earns its cost.

The output of that reading is an input to Layer 1, never an override of it. A discovered endpoint becomes a target the scoring pass ranks tools against. A guessed technology becomes a profile field with a confidence, and the gate treats it exactly as it treats a regex-derived one, which is precisely why the confidence asymmetry above is worth watching. On the server-driven path nothing the model produces reaches the target without passing [`llm_control.py:ToolCallValidator`](../core/llm_control.py) first; on the agent-driven path that is the convention the orchestrator follows rather than a wall it cannot get past. Either way the gate is chapter 02's subject and not this one's.

## What it costs to build this

The relevance table is a permanent obligation. Every new tool needs an entry, every entry needs conditions someone thought about, and this chapter is partly a record of what happens when that maintenance slips: eight penalties that do nothing, seven of which nobody had noticed, because a no-op does not announce itself.

The profile hash is a decision you can only get wrong slowly. Choose too few components and unlike targets pool their statistics; choose too many and every bucket holds one target and the priors never leave their neutral defaults. You find out which mistake you made after you have accumulated enough history to care about losing it.

And the stage machine binds you, on purpose. The first time a run would obviously have gone better with a stage skipped, you will find yourself arguing with your own design, and you should expect to lose that argument. That is the whole reason it is written down as a sequence rather than left as advice. What binds is the contract rather than the code, as the first section of this chapter admits, and the argument you lose is with yourself.

The last cost is the one I did not anticipate. Every defect in this chapter sat in a repository I have read many times, and I found all of them in writing sweeps for a book chapter, not in operating the system. Deterministic layers are auditable. That is not the same as audited, and the gap between those two words is where I would point anyone building this next.

Two of this chapter's own sentences were wrong when it was first written, and both are worth naming because they are failure modes you will hit too. One stated a margin as a whole quantity when the arithmetic makes it a half, and it got that way because I had a number the citation gate would not take and paraphrased it into a mechanism instead of annotating it. Paraphrase is where facts go to die; if a number resists your process, fix the process. The other named a cause that a two-line swap disproves. A wrong root cause is worse than none, because it is actionable, and someone acting on it changes a line and fixes nothing. Both were caught by tests that assert against `core/` rather than against my recollection of it, which is the argument for writing them.

---

## Number annotations

These notes were written inline in the handbook source beside the numbers they explain; the renderer collects them here and leaves a `[num-ok N]` marker at each point of use above.

**[num-ok 1]** 30 is the field count of the TargetProfile dataclass in core/fingerprint.py, pinned by tests/test_chapter_claims.py; it is a property of the checked-in code, not a measurement taken from any target

**[num-ok 2]** one method is a spelled quantity counting a code artifact: profile_hash in core/fingerprint.py is the single method that builds the hash, and the fields it drops are the ones it does not mention

**[num-ok 3]** 15, 8 and 3 are TIER_HIGH, TIER_MEDIUM and TIER_LOW, module-level literals in core/tool_recommender.py that this sentence quotes directly; they are cutoffs written into the code, not counts of anything observed

**[num-ok 4]** 0.0 is the penalize multiplier literal in the catalogue entry quoted immediately below, copied verbatim from core/tool_recommender.py

**[num-ok 5]** one entry is a spelled quantity counting a code artifact: the single catalogue entry quoted in the block immediately above

**[num-ok 6]** 8, 21 and 26 count entries in core/tool_recommender.py's RELEVANCE catalogue: the penalty conditions no profile can satisfy, the total penalty conditions defined, and the tools defined; 0.0 and 0.1 are the two penalize multipliers those dead entries carry, copied from that same table. All five are pinned by the sweep in tests/test_chapter_claims.py and are properties of the checked-in table, not measurements of any target

**[num-ok 7]** 0.0 is both the penalize-multiplier literal from the catalogue entry above and the confidence value _field_confidence's fallback branch tests for; 1.0 is the neutral multiplier that branch returns. Both are literals in core/tool_recommender.py, neither is a measurement

**[num-ok 8]** 0.8 is FATIGUE_DECAY and 0.3 is FATIGUE_FLOOR, class attributes of SmartScheduler in core/scheduler.py that this sentence quotes directly; they are tuning constants written into the class, not counts of anything observed

**[num-ok 9]** 0.6 is the similarity cutoff literal in _contextual_rate_for_hash in core/scheduler.py; 0.35, 0.15 and 0.10 are the backend, WAF-status and framework component weights in hash_similarity's weights list in core/fingerprint.py. Both files, all literals, none of them a measurement

**[num-ok 10]** 0.6 is the same similarity cutoff literal in _contextual_rate_for_hash in core/scheduler.py, and 0.10 is the framework component weight in hash_similarity's weights list in core/fingerprint.py; 0.65 and 0.55 are what hash_similarity's whole weights vector produces for the two exact hash pairs this sentence names, and 0.05 is the first of them less that cutoff; all three are computed and pinned in tests/test_chapter_claims.py. All five are arithmetic over checked-in constants, not measurements of any target, and "half the" is that same 0.05 against that same 0.10, the arithmetic restated in words
