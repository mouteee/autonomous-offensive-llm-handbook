# What the scan could not reach

Two scans, one report shape. The first ran for an hour against an application with a login form, tested what it found, and came back with nothing worth a client's attention. The second was met by a challenge page on its second request, tested nothing, and came back with nothing worth a client's attention.

Identical finding count. Identical severity table. And on the coverage line the second scan can print the better number, because a run that fired one tool at one URL has tested every pair it knows about.

That is the failure this chapter is about, and it is not a reporting cosmetic. Every control in the four chapters before this one exists to keep false things out of the deliverable. None of them puts true things in. A report that renders an unreachable target and a clean target the same way has passed every check in this handbook and is still lying, by leaving out the one fact that decides how to read everything else on the page.

The fix is not a paragraph in the methodology section. It is making reachability a value the system computes, records, and carries forward, on the same footing as a finding.

## Reachability has to be a recorded value

The obvious place to put it is the scan's status field, and that is the wrong place. Status is set by whoever finalises the run, from a command-line flag that defaults to complete. Nothing derives it from what the scan managed to touch. A run refused at the front door and a run that worked its way through the whole surface both land on the same word, and the caller picks it.

So it needs its own record, written by code, from evidence.

<!-- decide_gate_status in core/gate_check.py is the gate check this section describes; it returns one of four statuses with a reason, detail, allowed_stages and evidence -->
What I run is a gate check, `[[code:gate_check.py:decide_gate_status]]`: a pure function over the artifacts already on disk after observation, no network, no model. It answers with one of four statuses. `proceed` means test normally. `limited` means crawlable but with no interactive surface worth fuzzing. `gated_soft` means high error rate and nothing to work with. `gated` means the target refused everything. Every answer carries four more fields: a short machine-readable reason label and a sentence of detail for a human, both empty on the proceed path since there is nothing to explain, the list of stages the run may spend budget on, and the evidence dictionary the decision was taken from, holding the WAF flag, the response count, the error rate, and counts of parameters, forms, pages and scripts.

<!-- num-ok: One row is a spelled quantity counting a code artifact: the gate check upserts a single row per scan, in the store this repository withholds rather than in core/ -->
That last field is the one that matters for reporting. The decision is reconstructible afterwards because the inputs travel with it. One row per scan, upserted, so a re-run replaces the answer rather than appending a second opinion.

<!-- gated_soft and its reason high_error_no_surface are the status and label decide_gate_status in core/gate_check.py returns for a high-error, no-surface target -->
Two jobs are tangled together there and they are worth separating. The gate is a budget control, deciding what the run may spend effort on. It is also a record, saying what the target let anybody do. Most of the value is in the second job. A tester who reads `gated_soft` with `high_error_no_surface` beside it, and can see the response count and error rate that produced it, knows what to try next. A tester holding a report with three informational findings and no ledger knows nothing at all, and will probably assume the target is fine.

The gate check and the consolidation pass described in this chapter ship in `core/` -- `[[code:gate_check.py:decide_gate_status]]` and `[[code:consolidator.py:consolidate_scan]]` -- and the behaviour below was run against them out of a scratch copy rather than reasoned about. The coverage matrix is the exception: it lives in the store this repository withholds, so the coverage section stays prose. Each of the four chapters before this one made the same admission about its own subject, and this one has now mostly climbed out of it.

## Where the tree gets it wrong

<!-- num-ok: one branch is a spelled quantity used rhetorically: "not any one branch" says the problem is not local to a branch, and counts nothing -->
The interesting part of the tree is not any one branch. It is the gap between what the function accepts and what its only caller bothers to hand it.

The function takes seven inputs. The caller reads five of them, three only if the artifact files happen to exist, and pins the remaining two, forms and scripts, at zero on every single call. Both pinned inputs are read by the branch that decides there is nothing interactive here:

```
caller-shaped inputs      -> limited | static_or_public_surface_only
+ forms=3, scripts=12     -> proceed |
+ forms=3 only            -> proceed
+ scripts=12 only         -> proceed
```

<!-- num-ok: two fields is a spelled quantity counting a code artifact: forms and scripts, the two the caller pins at zero, pinned in test_pinned_inputs_reduce_the_no_surface_verdict_to_a_parameter_count -->
Same target, same everything else. With the two fields the caller never measures, the verdict flips, and either one alone is enough to flip it. So `static_or_public_surface_only` does not mean what its name says. In practice it means few parameters were recorded, with the forms and scripts conditions structurally true in advance. The skill document that drives the call lists forms among the inputs the check considers, which is how a plausible-looking classifier stays wrong for four months without anybody noticing.

Two more, from the same run.

Hand the function nothing at all, artifacts missing and nothing crawled, which is roughly what a target that refused everything leaves behind, and every default fires and it answers `proceed`, allowed stages `full`. The tree fails open, in the direction of testing more. I would keep that default, and it does mean an absent record and a permissive verdict are the same output.

And the top branch is narrower than its name. `gated` requires at most one captured response, along with a near-total error rate, a WAF and zero parameters and forms. One more response and the same target demotes to `gated_soft`:

```
WAF blocking with 200s    -> limited | static_or_public_surface_only
WAF blocking with 403s    -> gated | blocked_total
  ... two responses in    -> gated_soft
```

Read the first line, because it is the one that will happen to you. A WAF that serves its block page with a success status has no error rate to detect. Responses arrive, none of them count as errors, and the tree files the target as a static brochure site. All of that judgement runs on status codes, which an edge in front of the application picks for itself.

Those outcomes have a distribution, and across this corpus it is lopsided. Of the `[[stats:corpus.gate_decisions.total]]` gate decisions on record, the tree returned `proceed` `[[stats:corpus.gate_decisions.proceed]]` times, `limited` `[[stats:corpus.gate_decisions.limited]]` times, `gated_soft` `[[stats:corpus.gate_decisions.gated_soft]]` times, and `gated` -- the top branch just described, the one that says the target refused everything -- `[[stats:corpus.gate_decisions.gated]]` times. That branch has never fired. I cannot say which reading is right. Either the conjunction it demands is not reachable in practice, so the branch is dead in all but name; or nothing this system has scanned was ever refused that completely, and the branch is live and has simply never met its case. The record holds the count, not the reason, and the honest thing is to publish the count and say I cannot choose between those readings.

The list of allowed stages is produced by the function, stored in the row, and read by nothing. The orchestrator branches on the status field and follows a table written into its own markdown contract, which happens to agree with the function today. So the policy exists twice. The copy the function computes is the one nothing consults, and the copy that governs the run is prose in a skill file, which today happens to say the same thing.

## A denominator you chose before you looked

Coverage is where self-flattery gets arithmetic behind it.

The matrix the system builds is URLs against tools, filled in from the executions table, and the percentage is filled cells over the product of the two sets. Both sets come out of the executions. A URL nothing ever ran against contributes no row, so it is absent from the denominator; a tool nobody ran is absent as well.

Transcribe that expression and feed it cases:

```
2 urls x 2 tools, 2 pairs run: 50.0
plus 198 untouched URLs      : 50.0   <- denominator unchanged
1 url x 1 tool               : 100.0
3 urls, 3 tools, 7 of 9 pairs: 77.8
```

<!-- num-ok: half the surface is a spelled quantity used illustratively: it is a hypothetical case showing what the metric does detect, not a share measured anywhere -->
The second line is the whole problem. Discovery can hand you an estate's worth of endpoints and the percentage will not notice, because the untested ones were never allowed into the sum. What the number measures is how ragged the grid is over the URLs you already touched. It is a real quantity and it has a use, which is spotting a tool that got skipped on half the surface. It is not what anybody reading the word "coverage" thinks they have been handed.

The excluded benchmark run in this handbook's own data carries `[[stats:benchmark.juice_shop.excluded.0.reason]]`, and its recorded figure is half coverage on two tested URLs. Half is exactly what that expression returns for two URLs and two tools with one tool run against each. I cannot prove the run's number came out of this code path, and it reproduces to the digit.

The fix already exists in the same codebase, which makes the rest of this section more embarrassing rather than less. At the gate-check transition, after observation and before testing, the URL set known at that moment is snapshotted into a baseline table. Coverage then means baseline URLs with at least one successful execution, over the baseline count. URLs discovered later are tracked in their own bucket instead of retroactively diluting the ratio, which is the right call: work that arrives after the denominator is set should be visible as new work, not as a percentage going backwards.

<!-- num-ok: three columns is a spelled quantity counting a code artifact: the width of the baseline snapshot table the paragraph above introduces, in the store this repository withholds rather than in core/ -->
That snapshot is the whole trick: a count taken at one moment, written down, divided into later. It is a table with three columns and a function that fills it once, at the moment the gate check runs.

## The number that reaches the client

I sat down to write that the system reports coverage honestly, because the baseline mechanism above is exactly right and I built it. Then I went to check which of the two numbers reaches the report.

<!-- num-ok: one line is a spelled quantity counting a code artifact: the single line the report generator renders into the scope table, in the generator this repository withholds rather than in core/ -->
It is the matrix one. The shared write path that runs after every tool execution asks the store for the coverage matrix, takes its percentage, and pushes that into the live status row the dashboard polls. The report generator reads the same row and renders one line in the scope table: coverage, as a percentage of discovered endpoints tested. The baseline function, the honest one, has no caller anywhere in production. Its only callers are its own tests.

So the client-facing sentence names the denominator I would want, and the number beside it was computed against the other one. There is also a third definition, computed inline in the dashboard's own endpoint over URL rows rather than URL and tool pairs, which is a different number again. Three live definitions of coverage in one system, and the one with the weakest denominator is the one that got wired to the deliverable.

The gate decision does not reach the report at all. I expected to find it rendered, since the fifth law says it belongs there and I wrote both the law and the generator. Nothing in the generator reads that row. Neither does anything render the skip ledger from chapter 04. What the PDF carries about what was not done is a single percentage with a misleading label. And there is one thing it does carry that this chapter should not leave to chapter 03 alone: the attack-chain section prints its narrative out of the analysis store, ungraded, on both orchestration paths, so the strongest narrative claim in the deliverable is the part no control in this book has looked at. Chapter 03 left the choice open between grading those chains where they are written and not printing an ungraded narrative beside graded findings. The second of those is a change to the generator, which makes it this chapter's to make, and it is not made.

<!-- num-ok: one call site is a spelled quantity counting a code artifact: the single call this paragraph says the fix is, in process_tool_result in core/result_processor.py, though the baseline method it would call instead lives in the store this repository withholds -->
So a chapter arguing for honest coverage sits on a system that ships the wrong coverage number. Describing the design I meant to build would have been the easier paragraph, and the exact substitution this chapter is against. The fix is one call site: `[[code:result_processor.py:process_tool_result]]`, the shared write path, asks the store for the matrix, and could ask for the baseline instead. Nobody has changed it, including me, and I found out while writing this section.

## Collapsing duplicates without losing them

<!-- num-ok: The other half of is a spelled quantity used rhetorically: it is a section transition and not a share of anything measured. "nine instances" on the same line is a spelled quantity in a hypothetical, the nine sibling hosts the sentence invents to make the point -->
The other half of an honest deliverable is not repeating yourself. A class of misconfiguration that holds on nine sibling hosts is one problem with nine instances, and a report that lists it nine times at high severity inflates its own risk table as surely as a false critical would.

<!-- consolidation_signature in core/consolidator.py builds the grouping key from finding type plus digit-stripped title; consolidate_scan collapses a cross-host group into its primary -->
The consolidation pass is deterministic, which is the only reason I trust it. It groups findings on a signature, built by `[[code:consolidator.py:consolidation_signature]]`, of the finding type plus the title with digits stripped, lowercased and whitespace-collapsed. When a signature spans two or more distinct hosts, the highest-severity member becomes the primary, the affected hosts are written onto it, and every other host-bearing member is marked as absorbed with a pointer back. Findings with no resolvable host are never grouped and never absorbed. One pass is idempotent, because after absorption the signature only spans one host and no longer qualifies.

Three problems, in ascending order of how much they bother me.

<!-- num-ok: dozens is a spelled quantity inside a quoted example finding title, an illustration and not a count of anything measured. "one row" on the same line is a spelled quantity counting a code artifact, the single surviving row consolidate_scan in core/consolidator.py leaves after absorbing a cross-host group -->
The signature has no URL component. So the pass cannot tell "this misconfiguration is on nine hosts" from "this class of unauthenticated leak is on dozens of endpoints across two hosts". Both collapse to one row, and the surviving row records affected hosts, not affected endpoints. Run the signature over real titles and the collision is easy to see:

```python
sig("unauth_data_leak", "Unauthenticated GET returns 3389-byte response...")
sig("unauth_data_leak", "Unauthenticated GET returns 1602-byte response...")
# -> ('unauth_data_leak', 'unauthenticated get returns -byte response...')  identical
```

Digit stripping is what makes those two match, and it is the right instinct applied without a stop condition: response sizes and record identifiers are noise, and version numbers are not. A pair of findings reading `TLS 1.0 supported` and `TLS 1.2 supported` share a signature, because the version is exactly the digits that got removed.

Then the absorbed rows are hidden by setting their false-positive flag. That flag already means something else: not real. After a consolidation pass it also means real, and counted once already, over there. The only thing separating the two populations is a key in the absorbed row's raw data. Chapter 02 leaned on `[[stats:corpus.findings.false_positive]]` as a count that means something because there is one writer; this pass gives that column a second meaning without giving it a second column. In the corpus behind this handbook that has not happened, because the consolidation pass has never run over it, and I went and looked before writing that down: no row in it carries an absorption pointer. The hazard is in the design, not yet in the data.

<!-- num-ok: two places is a spelled quantity counting a code artifact: the function's own docstring and the planning document, both of them named in this same sentence -->
Last, the pass shares the kill switch that turns severity governance off, and I first wrote that this silently loses cross-host deduplication. It does not. Turning governance off flips the write-time dedup rule from same-host to host-blind and activates a cross-subdomain rule that is otherwise dormant, so duplicates still collapse: they collapse earlier, into an affected-URL list on whichever row arrived first, with no host list, no highest-severity primary and no re-levelling. There is a regression test that pins exactly that fallback, which is how I found out I was wrong. One switch, two dedup behaviours. The pairing is written down in the function's own docstring and in a planning document, which is two places an operator setting an environment variable in a compose file will not look.

## Always land somewhere

One rule here is cheaper to implement than anything else in this chapter: reach a finalised state on every run, and especially on the bad ones.

Store whatever findings exist, roll up the counts, record the usage, mark the scan finished, even when coverage is partial and the target was mostly a wall. A scan left sitting in `running` is worse than a scan that admits it got nowhere, because a partial with an honest ledger is a document somebody can act on and an unfinished run is an absence somebody has to remember to chase.

<!-- num-ok: about a fifth of is a spelled quantity, a worded ratio over published statistics: corpus.scans.by_status.failed plus corpus.scans.by_status.killed over corpus.scans.total in data/stats.json, pinned as a bounded fraction in test_every_scan_in_the_corpus_reached_a_terminal_state -->
The published corpus says the rule mostly held. Of `[[stats:corpus.scans.total]]` scans between `[[stats:corpus.window.first_scan]]` and `[[stats:corpus.window.last_scan]]`, none is sitting in a non-terminal state: the statuses are complete, a second spelling of complete that two writers produced, failed, and killed. The split between the two spellings is `[[stats:corpus.scans.by_status.complete]]` rows against `[[stats:corpus.scans.by_status.completed]]`, and `corpus.scans.note` in `data/stats.json` records both verbatim rather than merging them away. The failed and killed rows together are about a fifth of the corpus, `[[stats:corpus.scans.by_status.failed]]` and `[[stats:corpus.scans.by_status.killed]]`, and every one of them is a scan that reached a terminal state saying so.

<!-- num-ok: one row is a spelled quantity counting a code artifact, and it counts zero: corpus.scans.by_status in data/stats.json holds complete, completed, failed and killed and no partial, and that key set is pinned in test_every_scan_in_the_corpus_reached_a_terminal_state -->
On the attended path the rule is a line in a markdown contract rather than a property of the code, and nothing forces finalisation: if the orchestrating agent dies between the last tool and the finalise call, the row stays open. The unattended runner does better. When it kills a job on timeout it governs what is there and closes the scan as `partial`, and its own comment says why, which is that the alternative is a scan left running forever. Not one row in this corpus carries `partial`, so that fallback has never had to fire on anything counted here.

`[[stats:corpus.scans.by_status.killed]]` rows do carry `killed`, and I cannot tell you what set it: nothing in the source as it stands writes that string, in any language, outside the tests. A terminal status with no living writer is its own small reporting problem, and it is sitting in the chapter about not being able to say what you did not do.

The attended path's rule, then, is convention holding, which is the same footing chapter 01 gave the stage machine, chapter 02 gave the write path on the agent-driven path, and chapter 04 gave the skip ledger on the fan-out path. I am consistent about admitting it and I have not fixed any of the four. The unattended runner's fallback is the shape the fix takes: govern what is there, close the row, name the state honestly, in a function short enough to read in one sitting.

## Scoring yourself against a public target

Everything above is internal bookkeeping. At some point you have to point the thing at a target whose bugs somebody else wrote down, and take the score.

The system's author-recorded F1 on a public deliberately-vulnerable application is `[[stats:benchmark.juice_shop.f1.mean]]`. An OWASP ZAP passive-scan score in the same snapshot is `[[stats:benchmark.zap_baseline.f1]]`. The repository proves the aggregate arithmetic, not a controlled head-to-head: it does not publish the raw findings, ground-truth entries, matcher, target identifiers or run identifiers needed to establish that both rows were scored on identical inputs.

Now the reading, which is less flattering than the pair of numbers looks.

<!-- num-ok: Half the and three in ten are each a spelled quantity, a worded ratio over published statistics: the precision and recall keys already cited on this line, pinned in test_half_wrong_and_three_in_ten_found. The false-positive half of is that same word used rhetorically for the precision side of the pair -->
Precision was `[[stats:benchmark.juice_shop.included.0.precision]]` and recall `[[stats:benchmark.juice_shop.included.0.recall]]`. Half the reported findings were wrong, and three in ten of the known bugs were found: `[[stats:benchmark.juice_shop.included.0.true_positives]]` of `[[stats:benchmark.juice_shop.included.0.ground_truth_count]]`. Chapter 02 already quoted the false-positive half of that for its own argument. The recall half is the part I would put in front of anyone who thinks a system like this replaces a tester.

The baseline's zero needs its own paragraph, because a reader who takes it as proof of anything has been handed the wrong impression by me. The unpublished measurement procedure was described as pairing vulnerability type and URL after dropping findings it classified as non-vulnerabilities, but this repository cannot audit that procedure. The baseline row reports `[[stats:benchmark.zap_baseline.findings_count]]` findings and zero true positives against a `ground_truth_count` of `[[stats:benchmark.zap_baseline.ground_truth_count]]`. A passive scan can produce header and cookie findings for which an injection-and-access-control ground truth has no slots. Without the raw output and ground truth, this is an author-recorded data point about one scoring run, not evidence that the baseline is useless or that the two systems were compared fairly.

## One run, three attempts

Here is the part that decides whether the rest of this handbook is worth your time.

`n` is `[[stats:benchmark.juice_shop.n]]`. One run. The standard deviation published beside the mean is null, and it is null because a spread over one sample is not a thing that exists; the file says so in its own words under `benchmark.juice_shop._unmeasured_reason`. Every figure in the two paragraphs above is a single sample, and a single sample of a system with a model in the loop is a story, not a measurement.

<!-- num-ok: three times the is a spelled quantity, a worded ratio over published statistics: the published f1 mean against the mean of the same metric over all three attempts in benchmark.juice_shop, pinned in test_the_headline_is_one_of_three_attempts_and_triple_their_mean -->
Worse, and this is the sentence I want a reader to leave with: that single sample was selected. Three runs exist. Two were excluded, both published in full under `benchmark.juice_shop.excluded` in `data/stats.json` with their real metrics and their real reasons, and both scored zero. The published headline is therefore exactly three times the mean over every attempt that was made, which is arithmetic and not a coincidence: two of the three scored zero, so the multiple is just the count.

The two exclusions are not equally defensible. Presenting them as one policy applied twice would be the comfortable version, and it would be wrong.

The first is well evidenced. `[[stats:benchmark.juice_shop.excluded.0.reason]]`: the orchestrating agent was killed by a watchdog partway through, at half coverage with two URLs tested, and it never reached active testing at all. That run measures the harness. Averaging it into a scanner's score would understate the scanner as dishonestly as dropping a bad run would flatter it, and the evidence for non-comparability is hard, external to the score, and independent of what the score turned out to be.

The second is weaker, and part of the argument for it is circular. `[[stats:benchmark.juice_shop.excluded.1.reason]]`: the run carries the label "sanity", it was early scaffolding, it was not protocol-complete, and it was not cited as a baseline in the published verdict. Read those in order and the first two are about a string somebody typed and a judgement about maturity, the third is a claim I cannot show you a protocol transcript for, and the last one amounts to it not having been used before, which is not a property of the run. If that run had scored well I would want to know whether the same reasons would have been reached for. I think they would have been. I cannot prove it, and neither can you, and that is the point of writing it down.

So take the headline as what it is: one of three attempts, kept on a criterion that is defensible for one exclusion and partly subjective for the other, scored once, against one target. It is not a benchmark result. It is a data point with its selection published beside it, which is the most I can offer and less than the number looks like when it appears on a slide.

The honest version of the practice, for anyone doing this next: run it enough times to report a spread, decide the exclusion rule before you see the scores, and write the rule down where it can be held against you.

The discipline can fail on its own side of the table, and it did, once, in the same project. A blinded re-adjudication pass fed its adjudicator only one evidence field on findings whose proof actually lived in another, so the model scoring them saw nothing to confirm and marked real findings unproven; the arm that came out looking worst on that pass had simply had more of its proof stored somewhere the packet never looked. Reconciliation caught it by tracing where the storage differed between arms, not by re-reading any single verdict, and the fix was a second, corrected pass rather than a quiet edit to the first. Both packets are kept, wrong result beside the right one, because an evaluation method shown to have been wrong once and then silently corrected is not one anybody should trust the next time it agrees with them. If your own scoring tooling can be the thing lying to you, the record has to survive finding that out.

## Measuring a thing you are changing

The coverage counts in the published statistics are a snapshot, not a query you can re-run and reproduce. That is not sloppiness in the pipeline. It is what happens when the instrument is inside the thing it measures.

The turn-ratio measurement in chapter 01 reads native session transcripts out of a directory on disk and maps each one to a scan. That directory is where the coding-agent sessions for this project land, including the sessions that wrote this handbook. Writing these chapters put new transcripts into the corpus being measured. Re-run the measurement today and the transcript count differs from `[[stats:llm_ratio.coverage.cc_transcripts_seen]]` for no reason connected to any scan of any target.

The published pair says plainly how little of the corpus this is: `[[stats:llm_ratio.coverage.scans_measured]]` scans measured of `[[stats:llm_ratio.coverage.scans_total]]`, split between the two transcript sources and extrapolated to nothing.

<!-- num-ok: 18 per cent is the rise in llm_turns_per_tool_execution between the two measurement passes recorded in this repository's history, arithmetic over two already-published measurements rather than any measurement of a target, and it is computed and pinned in tests/test_chapter_claims.py; it also names thirteen and eighteen on that line, the findings delta and the earlier measured-subset size across that same pair of snapshots, both asserted in that file against its pinned PRIOR_SNAPSHOT constants; it exempts nothing else on the line -->
The corpus of scans also grew mid-project, and that one moved a headline. Between the two measurement passes recorded in this repository's history the corpus gained one scan, thirteen findings and six tool executions, the measured subset went from eighteen scans to `[[stats:llm_ratio.coverage.scans_measured]]`, and `[[stats:llm_ratio.llm_turns_per_tool_execution]]` came out 18 per cent higher on the second pass. Chapter 01 had to rewrite every gloss of that ratio, its section heading included, and it now carries a warning about the shape of the number rather than the number.

Three things I would do differently, and the first is the only one I actually did.

Publish the snapshot, with its date and its coverage counts, and never present it as a live query. Freeze the measured population before you start writing about it, which I did not, and pay for that in restatements. And keep the measurement corpus somewhere your own work does not write, which is obvious in hindsight and was not obvious when the directory in question was simply where the transcripts happened to be.

None of this invalidates the figures. It does mean the honest unit of publication is a snapshot with a timestamp, and that a reader who re-runs my pipeline and gets a different number has not caught me in an error. What they have caught is a measurement whose corpus my own writing keeps adding to. If you want the number to be reproducible, copy the transcripts out to a directory nobody writes to and measure that copy; the script already takes the path as an argument.

## The experiment I still owe

The central claim of this handbook is that moving decisions out of the model and into deterministic layers makes an offensive agent better: more reproducible, more auditable, and not worse at finding things. Chapter 00 conceded that the study is not run. Here is why, in enough detail that you can judge whether the excuse is any good.

The layers carry the switches. `[[code:scheduler.py:HARNESS_SCHEDULER_ENABLED]]` sits beside a fatigue switch and a category-budget switch in the scheduler's constructor, and they work. Off, the adjust pass hands the Layer 1 ranking straight back:

```
flag on : test_cors 18.0 [new_tool×1.5]; test_xxe 13.5 [new_tool×1.5]; test_sqli 7.68 [fatigue×0.64; low_sr_global×0.60]
flag off: test_sqli 20.0; test_cors 12.0; test_xxe 9.0
```

Two recorded failures are enough to move the injection tool from first to last with the flag on, and change nothing at all with it off. So the switch does what it says on the tin.

The problem is where the flag bites, and I had this wrong in the first draft in a way that matters: I wrote that the agent-driven path never constructs the scheduler at all. It does. Every tool execution on that path builds an executor, and the executor builds a scheduler and a recommender in its constructor, flags and all. What it never calls is the ranking entry point that the scheduler flag guards. Tool selection on that path comes from the orchestrator's own plan, so setting that flag to zero changes nothing a scan could notice, and an ablation arm built out of it would be identical to its control.

That fact is an obstacle to the ablation, and it is also the qualification chapter 01's central rebuttal needs, which I left implicit for a draft too long. Chapter 01 answers the turn ratio by saying the model is not choosing which tools run, and that answer describes the ranking; on the path this section is about, the choosing is the plan the orchestrating model wrote. Chapter 00 and chapter 01 now scope the claim at the point they make it, and this section is where the fact that forces the scoping turned up.

The other two switches are not in one position either, and grouping all three together was the sloppy part. The fatigue switch sits in the same ranking function as the scheduler switch, so it is in the same predicament. The record path runs on every execution, on both the success and the error branches, and it reads the category-budget flag there. So that one does change what gets written on the default path. Whether the change reaches a decision is a separate question, and on this path the answer is no, because nothing consults the budget without going through the ranking nobody calls. So: two flags read only inside a ranking function the default scan never calls, and one read on every execution whose only effect is on counters that nothing on this path reads back.

Those are not the whole switch surface, and the rest of it has gone undescribed here until now, which is the omission in this section rather than in the ones it is about. The two flags just discussed are `[[code:scheduler.py:HARNESS_FATIGUE_ENABLED]]` and `[[code:scheduler.py:HARNESS_CATEGORY_BUDGETS_ENABLED]]`, and beside them the scheduler reads `[[code:scheduler.py:HARNESS_AGGRESSION_LEVEL]]` on every execution -- live, and named by no sentence in this handbook before this one. The governor's are `[[code:severity_governor.py:HARNESS_GOVERNANCE]]` and `[[code:severity_governor.py:HARNESS_GOVERNANCE_EVIDENCE_CEILING]]`, and chapter 03 states the limit they carry. What chapter 03 does not say, and what matters to an ablation rather than to a control, is that the first of those names is read by consolidation as well: `[[code:consolidator.py:consolidate]]` returns an empty record under it, so a governor arm cannot be run without switching off a second subsystem in the same breath. And both switches gate the scan-wide pass only. `[[code:severity_governor.py:govern_finding]]` is unswitched, deliberately, so the per-finding write path -- the one a deliverable is actually built out of -- cannot be ablated from a shell at all. The grounding critic's pair is the sharpest of them: `[[code:critic.py:HARNESS_DT_CRITIC]]` and `[[code:critic.py:HARNESS_DT_CRITIC_THRESHOLD]]` are consulted by nothing in this repository. `[[code:critic.py:score_grounded]]` never asks, and the accessors are left unwired here on purpose, because an off switch documented inside a scoring function is a control and not a guarantee -- the sentence chapters 03 and 04 each turn on a control of their own. So the arm a reader would reach for first, the grounding gate, is the one arm this tree cannot switch. `tests/test_environment_switches.py` holds the inventory of environment reads under `core/` and holds every name in it against this chapter, so a switch added to a module reddens a test instead of arriving undisclosed.

A real study means either porting the ranking layer onto the agent-driven path and toggling it there, or running the whole benchmark on the server-driven path, where the layers are live and the corpus is not. Both are a few days of work. Neither is done.

Until one of them is, the thesis of this handbook is argued and not measured. The reproducibility claims in chapter 01 are structural and hold on inspection: same profile and same statistics file, same ranked list, no model in the path. The claim that this produces better security outcomes than an improvising agent has no experiment behind it. I believe it, on the evidence of operating the thing for months, and belief on that evidence is exactly what this chapter tells you not to accept from a report. The study is two arms of ten runs each against the same public target, with the exclusion rule written down before the first run. Somebody should just run it.

<!-- num-ok: ninety names the follow-up study's pre-registered non-inferiority margin, a design constant frozen before its first run, not a measurement -->
Somebody did run the closest thing to it: not the ranking layer this section is about, but the verifier -- a model verifier plus the deterministic handling of its verdicts, ablated together as a pair, not a purely deterministic rule tested alone. Unlike the scheduler and governor flags just discussed, which this section found dead on the default path, the verifier actually changes what a run ships by default, which is why it was the control worth measuring first. The pair on against the pair off, ten cold runs per arm, the exclusion rule frozen before the first run, exact statistics throughout. Pre-report suppression fell from a median of [[stats:benchmark.verifier_ablation.suppression.FULL_median]] per run to [[stats:benchmark.verifier_ablation.suppression.NOVERIFY_median]] with the pair off, [[stats:benchmark.verifier_ablation.suppression.p_one_sided]] -- the chance of that pattern under pure noise, one-sided since a direction was pre-registered. Blinded shipped precision moved with it, [[stats:benchmark.verifier_ablation.blinded_precision.FULL_median]] against [[stats:benchmark.verifier_ablation.blinded_precision.NOVERIFY_median]] ([[stats:benchmark.verifier_ablation.blinded_precision.p_one_sided]], supported rather than confirmed on this model-blinded pass), though the two arms' precision runs overlap at the edges, the adjudicator that scored them was a model, and the human blind pass on the same packet is still the gate that number is waiting on. Recall carried no such pre-registered direction and, reported two-sided as that requires, showed no significant difference either way. The ranking layer is still the study I have not run, and none of this should be read as a substitute for it. The design, the six deviations -- two of them mid-study mass-write incidents -- the ground-truth double-count, the two prompt periods, and what it still does not show are in [Appendix D](appendix-d-verifier-study.md). A follow-up factorial study has since pulled that pair apart, each switch thrown independently across two targets: the model verifier carried the suppression effect on its own ([[stats:benchmark.factorial.h1_suppression.p_one_sided]], Holm-adjusted [[stats:benchmark.factorial.h1_suppression.holm_adjusted]]), the deterministic acceptance layer marked [[stats:benchmark.factorial.layers.governor_fp_marks]] false positives in [[stats:benchmark.factorial.n_total]] runs and did not move blinded precision by itself, no interaction between the two was detected, and the shipped design failed one pre-registered bar -- it could not demonstrate it keeps at least ninety percent of true findings. All of it, including the replication of this paragraph's headline comparison, is in [Appendix E](appendix-e-factorial-study.md).

## What it costs to build this

Reporting what you did not do costs you the comfortable report. A page that says coverage was partial, the gate came back limited, four hosts were skipped and two of them for budget, invites questions that a clean-looking summary does not. Those questions are the value. They are also work, and the work lands on the person who wrote the honest version.

A denominator fixed before testing costs you the number going up. Lock the baseline at the gate and every endpoint you fail to reach is visible for the rest of the run, which is the point and is not pleasant when somebody is watching the dashboard.

Consolidation costs you detail in exchange for a readable risk table, and the exchange rate is set by a signature function somebody wrote in an afternoon. Mine drops the URL, which is a defensible simplification for sibling hosts and the wrong call for one class spread over many endpoints, and the absorbed rows are hidden behind a flag that means something else.

And the honesty items in this chapter cost the argument some of its force. An `n` of one with a published selection criterion is a weaker thing to bring to a conference than a mean over ten runs. The alternative is to bring the mean over ten runs I did not do, which is a different kind of cost, paid by whoever believes it.
