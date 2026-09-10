# Asymmetric trust

Open an early report out of this system and the first page is a wall of red. Critical, critical, high, critical, critical. A development lead reads the first two, skims the third, and forwards the rest to a queue where work gets done in the order it arrives. That reaction is correct. A column where most cells say the same thing has no information in it, and the reader who stops consulting it has worked that out faster than the person who sent it.

The diagnosis is not that the model is bad at judging impact. Ask a model how bad something is and you have asked it to emit a word. "Critical" costs exactly what "medium" costs, which is nothing, and everything the thing was ever trained on rewards the answer that sounds like it was taken seriously. The cost of the wrong answer lands somewhere else entirely: on a stranger, weeks later, in a meeting you are not in. Nothing inside a next-token objective prices a false critical.

Instruction does not add that price either, for the reason chapter 02 gave, and severity has a wrinkle of its own on top of it. The model grading the finding is looking at a window that still contains the finding, so whatever made that sentence sound serious the first time around is sitting right there, being read again by the thing that wrote it.

So severity cannot be something the model decides. It also cannot be something the model is kept away from entirely, and getting that second half wrong is how chapter 00's first law shipped broken.

## What this system published

The opening example is mine, and it is not a hypothetical.

When the governance layer described in this chapter was finally run over the whole corpus, the critical-and-high band moved by `-54`. From `384` down to `330`, split `-18` in the critical band and `-36` in the high band. Roughly one finding in seven that this system had published as critical or high could not hold that band once a mechanical check ran across it.

Those numbers are a backfill. The governor did not exist for most of the window between `2026-05-06` and `2026-08-18`; it landed nearer the end and was then run backwards over everything. So this is not a story about a control catching things before they went out. The reports went out first. The check came later and told me what had been in them.

The transition table is worth reading row by row rather than as a total, because the rows reconcile with the band counts, and a number somebody can check is a number somebody can argue with:

| Transition | Count |
|---|---|
| critical to high | `12` |
| critical to medium | `6` |
| high to medium | `48` |
| medium to low | `3` |

[num-ok 1]
Every transition in it goes down. The critical band's loss is the two rows that leave it; the high band's loss is what it shipped to medium less what it received from critical; and the movement out of the combined band is the two rows that land on medium, which is exactly the combined delta above. Nothing appears from nowhere.

No transition in that table ends at informational. A false-positive mark is the one action here that sets a finding to informational, so its absence from the table means the governor never once removed a finding from the published population across the whole pass. That second step is an inference from how the mark works rather than something the table proves on its own; the mark itself is the `mark_fp` branch of [`severity_governor.py:govern_finding`](../core/severity_governor.py), which sets a finding to informational.

One precision, because I would rather give it than have someone find it. Those counts are rows, and a handful of identifiers turn up twice, under two separate scans of the same host: mostly the same day, hours apart, and in one case a day later. A finding's identifier is a hash of its type, its URL and its title rather than something minted per row, so a repeat scan that rediscovers the same issue lands on the same identifier. The band counts are computed over the same rows, so the two sides agree, but read the totals as rows moved and not as distinct vulnerabilities found. I had this down as a parent scan and its child sharing a finding until I went and looked. Then I wrote that the repeat scans were on different days, which is true of one pair out of the four. Two corrections to one sentence, both of the species chapter 01 kept hitting, and the second arrived inside the fix for the first.

The audit of that pass split the changes into `17` it recognised as intended behaviour and `52` it refused to bless, and the flagged ones went to a human. I come back to that split near the end, along with what was wrong with the first version of it.

## The last word

Chapter 00's first law originally read that the model never sets a severity. That was wrong, and it was wrong in an instructive way: it contradicted the third law two paragraphs below it. The third law says severity rises only against proof, and the thing that supplies proof and asks for a raise is a model. Both sentences cannot be true. The law now says the model never has the last word on severity, and this chapter is what that phrase has to mean if it is going to mean anything.

Two components, pointed in opposite directions.

<!-- govern_finding in core/severity_governor.py is the pass this section describes, and every severity-changing branch in it either compares the two bands before writing or writes the floor band outright -->
The governor is deterministic and can only move severity down. Not "is instructed not to raise", not "does not raise in practice". Every place in [`severity_governor.py:govern_finding`](../core/severity_governor.py) that can change a severity takes one of two shapes: it is guarded by the same comparison, which writes the new band only when the new band is lower, or it writes the floor band outright, which is what the false-positive branch does and which is why that branch needs no comparison. Neither shape has an upward case. Raising was not disabled. It was never expressible.

The historical verifier is a model that can request changes in either direction; the asymmetry is in what the recording endpoint requires for a raise. A quote is mechanically checkable there, but its presence is not proof that the vulnerability exists. A new implementation needs a domain proof policy as well as quote containment. The offline lab in chapter 07 demonstrates that separation with synthetic predicates.

The governor cannot do the verifier's raising job. That is the useful split, and it took me longer to arrive at than it should have. The separation is about permissions and independent acceptance checks, not a claim that a verifier can never recommend a downgrade. Both components can be wrong. Keep the rationale, capture and applied policy beside a change so that somebody outside the component can challenge it, and test the false negative a lowering rule could create as carefully as the false positive a raise could preserve.

Before the mechanism, an accounting of what now runs and what does not. The governor, its rules file and the consolidation pass behind them ship in `core/` -- [`severity_governor.py:govern_finding`](../core/severity_governor.py), the rules file it loads, and [`consolidator.py:consolidate_scan`](../core/consolidator.py) -- so the deterministic side of this chapter is something you can run from this repository. The verifier is not here: it makes a model call and stays in the working system, the way chapters 01 and 02 flagged their own withheld pieces. The measurements are real and were taken against the corpus, whose governance predates parts of the shipped code; where the two part company, the section says so rather than papering over it.

## A governor that cannot escalate

The governor reconciles a severity from three signals, in a fixed order.

<!-- cvss_base_score in core/cvss.py scores the vector and band_from_score maps that score to a band; the reconciliation reads the result -->
First, a CVSS reconciliation. If the finding carries a vector, the vector is scored by [`cvss.py:cvss_base_score`](../core/cvss.py) and mapped to a band. Vectors the system derived from the severity it already claimed are meant to be skipped, and the reason is good: a derived vector is the severity wearing a different notation, so letting it vote would be the finding agreeing with itself.

The test for that is where I got the chapter wrong on my first pass, and where the public re-expression and the corpus part company. I wrote that the branch admits authored vectors, because that is what the surrounding comment in the working system said. [`severity_governor.py:_reconcile_cvss`](../core/severity_governor.py) asks the question positively instead: only a vector whose recorded source is `authored` reconciles. A `derived` vector is skipped in silence, since a vector computed from a band is not evidence against that band; anything else -- no label at all, or a label the module does not recognise -- is skipped and recorded as `cvss-reconcile-skipped-unattributed`. That is fail-closed. An unattributed vector could have been written by anything, a model included, so lowering a severity on it would suppress a finding on evidence nobody vouched for, and the conservative outcome is to leave the asserted severity where it stands.

The corpus reads the other way, and the gap is the point rather than a footnote. Those downgrades were taken under the older fail-open rule the working system ran at the time -- a known open finding, since closed in the re-expression -- which asked only whether the provenance began with the word derived and treated a missing label as authored. Under that rule, of the rows the branch downgraded, all but one carried no provenance field whatsoever and exactly one was labelled authored, so the reconciliation was mostly running on vectors whose origin nobody recorded. The module in `core/` would skip every one of those today. So the corpus figure describes the data under the rule that produced it, and the fail-closed behaviour describes the code you can run; both only ever lower, which is why the damage was bounded either way.

Second, the semantic ruleset, which is the next section but one.

Third, the evidence ceiling: a grade computed from how replayable the finding is, and a cap that grade imposes.

Each of the three writes a new band only when the new band ranks below the current one. That comparison, repeated three times, is the whole of the no-escalation property. No separate guard clause, no flag, nothing to switch off.

I swept it rather than trusting the reading. Every severity the system uses, crossed with every finding type any rule names by hand plus several that no rule mentions, crossed with the three evidence shapes, an authored vector at the top of the scale and one near the bottom and none at all, both environments, and titles, URLs and evidence text written to trip the rules that key on regular expressions. No input produced an output above the severity it was given. Every rule in the file fired somewhere in that sweep, which is the check that makes the result worth reporting: a sweep that never wakes the rules is a measurement of the sweep, not of the governor.

A sweep proves the behaviour and says nothing about the cause, so I went and broke the mechanism I was crediting. Replace that one-way comparison in the CVSS branch with a plain inequality, hand the patched governor a finding at low severity carrying an authored vector that scores critical, and it comes back critical. The unmodified governor hands the identical finding back at low. Same input, different behaviour, so the comparison is the thing doing the work and not a bystander I happened to be pointing at.

What the governor writes alongside the decision is the part I would keep if I had to throw the rest away. Each governed finding carries the severity it arrived with, the severity it left with, every rule that fired with the rationale that rule was written with, the evidence grade, whether the CVSS vector was authored or derived, whether the target was a production or a pre-production host, and whether the ceiling was enforced on that pass. When a client asks why the critical in the draft is a medium in the final, the answer is a row rather than a recollection. I have had that conversation from the other side, holding a scanner report that could only offer a paragraph of intent, and it goes badly in a specific way: you end up defending the tool instead of discussing the finding.

Two honest limits, one of which chapter 02 already named and I am not going to quietly drop here. The governor sits behind environment switches, one for governance as a whole and one for the evidence ceiling specifically, both defaulting to on, and the whole pass no-ops when the first is off. A control with a documented off switch is a control, not a guarantee. And the record-count statistic looks like a coverage number and is not one: `124` findings in the corpus carry a governance record and `2864` do not, and the second figure is not a population that escaped governance. The mechanism is not, as I first wrote, that the record is only written on change: the governor builds that record on every call, and the write-time path stores it whether or not anything moved. Of the records in the corpus, better than a third carry an empty list of fired rules, meaning evaluated and left alone. What varies is which passes persist the row, not whether the record was produced. Coverage is established by a different pair, `206` scans governed of `206`. I published the misleading pair anyway, with a note on it, because the alternative is a reader reconstructing it wrongly from something else.

## Evidence is the currency

The grade is computed from what the row can prove, not from what it claims.

<!-- evidence_grade in core/severity_governor.py computes strong, moderate or thin from the artifacts a row carries; the captured response it reads is built by capture_response in core/http_evidence.py -->
A captured request and a captured response is strong: someone can replay it. That grade is [`severity_governor.py:evidence_grade`](../core/severity_governor.py)'s, computed from the artifacts and not from what the finding says about itself, and the response half is what [`http_evidence.py:capture_response`](../core/http_evidence.py) builds. A proof-of-concept command with its recorded output counts the same way, for the same reason. One side of the exchange, or a command with no output, or a written account with some substance to it, is moderate. Nothing of the sort is thin.

Thin caps at medium. That is the rule, and it applies regardless of what the finding says about itself.

The reason this works is the reason chapter 02 gave for preferring a substring search to a rubric: there is nothing in it to argue with. A model can write a more forceful impact paragraph, cite a higher CVSS band, and describe the consequences in more vivid terms, and none of it puts a request into the row. The check is not asking whether the finding is convincing. It is asking whether there is an exchange in the record, and that question has an answer that does not depend on how the question is asked.

Now the part I want to be precise about, and I was not precise about it myself until I counted.

Three mechanisms moved findings out of the critical-and-high band. The evidence ceiling accounts for more of them than the other two put together, which comes to a little over half. The sentence I had written down before counting said the large majority failed on evidence. A little over half is a bare majority, not a large one, and I had to go back and change the sentence. It leads. It does not dominate.

Second, and not far behind, is one rule that caps a single class at medium. Third and smallest are findings whose own authored CVSS vector scored into a band below the severity they claimed, which is a finding disagreeing with itself rather than anyone disagreeing with it.

So the picture where a reviewer sat down with each downgraded finding and formed a different opinion about how bad it was fits the second group and nothing else, and even the second group is one rule applied uniformly rather than a run of judgements. Nobody argued with these findings one at a time. Most of them could not show their working.

Which brings me to what thin actually means, because "thin evidence" reads like a polite word for weak or unconvincing and it is not that. It is a statement about which columns are empty.

Take a broken access control finding from the corpus. Real work went into it: a request was made under one role and repeated under another, and the responses differed. What got recorded was a status code and a response size, written into the row as a short piece of JSON-shaped text. No request. No response body. Nothing to replay, nothing to read. It graded thin and it was capped, and given what is in that row I cannot argue with the cap. The finding may well have been a genuine critical. The row cannot support the claim.

The exploit-output findings are worse and more instructive. Several of the capped ones are of a type that exists only because something was extracted, and the row carries the credential material that came back. The credential is right there. The exchange that produced it is not, because the tool that ran the extraction wrote its output and never wrote the request or the response. So a finding was capped for lacking evidence while carrying the loot.

That is a tooling defect presenting as a severity decision, and the severity is not the broken part. Given a row with no exchange in it, medium is the honest band. The fix belongs upstream in the tools, and each of those cappings points at a capture path that somebody, meaning me, never wired up.

## The only way up

The verifier is the only thing in the system that can raise a severity, and it is a model.

Its historical contract is written adversarially on purpose. It is told it is a reviewer, told to default to false positive or to a lower severity unless the attached evidence proves otherwise, told to quote the exact line that proves the claim, and told that if it cannot quote proof the verdict is "needs review". Downgrades and false-positive marks need no justification beyond the verdict itself in that contract. That is a defect to fix, not free scepticism: a mistaken dismissal can hide a real issue. Require a reviewable reason and counterexample tests for lowering rules as well as raising rules.

The raise itself is gated where it is recorded. A verdict arrives as a small payload: the finding, the verdict, a target severity, an optional CVSS vector, a quote, a rationale. If the verdict raises the band and carries a quote, the raise applies and the quote is stored beside it. If it raises the band and carries no quote, the raise does not happen, and the verdict is written down as needing review rather than as the true positive it claimed to be. The model is not consulted about whether that was fair. Nothing is returned to it that would let it try again.

I ran the paths rather than reading them, because a gate is exactly the kind of thing that is described correctly and implemented approximately.

| Verdict offered | What the endpoint did |
|---|---|
| Raise, quote present, strong evidence | Raised, and the raise survived the reconciliation pass |
| Raise, no quote, strong evidence | Did not raise, recorded as needing review |
| Raise, quote present, thin evidence | Raised, then the reconciliation pass put it back to medium |
| Raise, quote present, no CVSS vector | Raised |
| False positive, nothing offered | Applied |

Read the third and fourth rows, because that is where the honest version diverges from the contract. The contract states three conditions for a raise, all required: a verbatim quote, an authored CVSS vector, and an evidence grade of moderate or better. The endpoint itself enforces one of them. The evidence grade is enforced, but one stage later and by a different component, when the governor's ceiling runs on the reconciliation pass and pulls a thin finding back down. The CVSS vector is not enforced anywhere: the endpoint reads it, stores it when present, and raises without it.

Between the verdict call and the reconciliation call, a thin finding sits at the raised band in a live table the dashboard is polling. In the pipeline those two calls are adjacent, so the window is small, and a window that is small because of call ordering is not a window that is closed.

[num-ok 2]
The fix is one condition, in the branch that already has everything it needs. That branch has the finding row in hand, and the function that computes the evidence grade lives in the module the same function already imports from, and the CVSS vector is already being read one line further down. I patched it to require all three and re-ran the same five cases: the thin-evidence raise and the vectorless raise both stop raising and are recorded as needing review, and the fully-evidenced raise still goes through. That is a two-line change and it is not shipped.

[num-ok 3]
What the corpus says about all this is modest and I would rather state it small. The verifier landed near the end of the window, so its operating history is a few weeks and not the whole corpus. In that time it recorded verdicts on a small set of findings, and exactly one of them raised a severity. That one carried moderate evidence, which is the floor the contract asks for.

[num-ok 4]
One raise. That admits two readings and the data does not separate them: either the asymmetry is working as designed and raises are genuinely rare, or the raise path is decorative and nobody exercises it. I had written that the verifier issued plenty of downgrades over the same set and so was clearly awake, which is not what the verdicts say. Almost all of them were true-positive verdicts that changed no severity at all. That is a component agreeing with the existing severity nearly every time. It does not tell me whether raises are rare because the bar works or because nobody pushes on it, and I am leaving the question open rather than settling it with a number I rounded in my own favour.

## The chains cannot be proved

This is the admission I would keep if the chapter had to be cut to one section.

An attack chain is the most valuable thing a report contains. Individual findings are facts; a chain is the argument that turns three moderate facts into an account of how somebody actually gets in. It is what a client reads first and what a reviewer remembers. It is also the claim in the whole deliverable that most needs proof, because it asserts something no single tool observed.

Every attack chain that reached the governor graded as thin evidence and was capped. Not most of them. All of them. The audit records `17` attack-chain changes, the corpus holds exactly that many chain findings, each entered at high, each left at medium, and the rule that moved every one was the evidence ceiling.

[num-ok 5]
That sentence needs a qualifier, and the qualifier is bigger than the sentence. Those are the chains that became findings, and there are `17` of them. The same corpus holds `210` chain objects that were written into the analysis store instead, never became findings, and were therefore never evaluated by anything. Out of `227` chains altogether, that is better than nine in ten which the governor never saw. The exact share is stored in the same block and I am not going to print it here: two counts that size do not support the decimals it carries.

[num-ok 6]
Chain data of some kind turns up in `101` of the `206` scans in the corpus, which is a little under half of them. I first wrote that as "most", which it is not, in the paragraph whose job was to correct an over-claim. The universal above is true of the governed population and true of nothing wider, and I wrote the wider version first.

The mechanism is unglamorous. The synthesis stage is handed the run's critical and high findings rendered one per line as severity, title and URL. It returns chain objects: a name, an ordered list of steps, an impact paragraph, and a list of references to what the chain builds on. The writer stores that object as the finding's raw data under a fixed severity. Then the grader goes looking for a request and a response inside it and finds a list of prose references instead.

Nothing in that path copies evidence from the findings the chain combines, and nothing in it could. The identifiers of the constituent findings are never put in front of the model: the summary line it reads is severity, title and URL, so it has no identifier to cite even if the schema asked for one, and the writer therefore has nothing to resolve. The evidence assembler, for its part, reads only the single finding handed to it. There is no path today by which one finding's captured exchange can reach another finding's row.

I checked the cause the same way I checked the governor's, by breaking it. Take a real chain out of the corpus, restore it to the state synthesis wrote it in, and run the governor: high becomes medium, grade thin, ceiling fired. Take the identical chain, attach a request and a response copied from a finding sitting beside it in the same scan, and it keeps its high and grades strong and no rule fires at all. Take the bare chain again with the ceiling switched off and it also keeps its high. So the cap is caused by the absent evidence, acting through the ceiling, and by nothing else in the pass.

The part that stings is where the evidence was sitting the whole time. Every one of those chains lives in a scan that also holds at least one finding graded moderate or better, and around two in five sit beside a finding graded strong. The proof was in the same database, one join away, attached to the findings the chain was built out of. It never travelled.

The cap is correct. I want to be unambiguous about that, because the tempting move is to carve out an exception for chains on the grounds that a chain is a different kind of object and the ceiling is unfair to it. That reasoning is how ceilings die. A chain that cannot show a single captured exchange is a narrative, and a narrative that reaches a client wearing a high severity is precisely the failure this chapter opened on.

[num-ok 7]
The synthesis is what is broken. The system generates its strongest claims through the one path in it that discards evidence, and then a control correctly refuses to let those claims outrank a header misconfiguration. Both halves of that sentence are working as designed and the combination is indefensible.

The fix has two parts and neither is hard. Put the finding identifier in the summary line the synthesizer reads, and require the chain schema to cite identifiers rather than prose. Then resolve those identifiers at write time and copy the constituent findings' captured exchanges into the chain's evidence before the row exists. After that a chain is graded on the evidence of its parts, which is the only grading of a chain that means anything, and a chain built from three thin findings stays capped, which is also correct.

Both parts of that fix reach the chains that become findings and neither reaches the rest. A chain object in the analysis store is not a finding, so there is nothing there for a grade to attach to and nothing for the ceiling to cap. Governing the larger population needs a different change: either the analysis store's chains get graded where they are written, or the report stops rendering an ungraded narrative beside graded findings, which is a change to the generator and so sits on chapter 05's side of the deliverable. I have not decided which, and until one of them exists the fix above improves the smaller half.

Here is where those two populations come from, and it is not where I expected to find the split. I went looking while writing this section, which is the best argument I have for writing chapters about your own system.

The server-driven path writes a chain twice: once into the analysis store, and again into the findings table, where the governor meets it. The agent-driven path, which chapter 02 named as the default, writes only the analysis-store copy. And the report generator's attack-chain section reads the analysis store on both paths alike. It looks for a chains key among the stored analyses and prints the steps under a heading. It never consults the findings table, so the governed copy is not what the client is reading even on the path that produces one.

No severity. No evidence grade. No governor, because the governor governs findings and the object being printed is not one.

So the strongest narrative claim in the report is, on either path, the one thing in it that no control in this handbook has ever looked at. It does not inflate a severity count, because it carries no severity to inflate. It goes into the PDF as prose, under a heading, above a numbered list. There is no capped version of it to prefer: the governed chain finding is an extra card the server-driven path also emits, sitting beside the same ungoverned narrative rather than replacing it.

## Rules as institutional memory

The middle of the governor's three signals is a file of rules, and the file is the answer to a question I got wrong for a long time: what to do with an operator correction.

The natural thing is to remember it. Someone reviews a report, spots that the tokenization identifier the scanner flagged as a leaked secret is public by design, says so, and the severity comes down. Everyone involved now knows. The knowledge lives in the people who were in that conversation, gets applied when one of them happens to be reviewing, and leaves when they do.

<!-- load_rules in core/severity_governor.py parses the JSON rules file and validates each rule; the three actions are the _ACTIONS tuple mark_fp, downgrade_to and cap_at -->
The alternative is to write it as a rule with an identifier, a match block, an action, and the reason in prose. Three actions exist: mark false positive, downgrade to a band, cap at a band, with the cap allowed to differ between a production and a pre-production host, because the same public-by-design identifier is a different conversation on a live payment page. This file is JSON in the public repository -- `core/` is kept to the standard library, so no YAML parser is available to it -- and [`severity_governor.py:load_rules`](../core/severity_governor.py) parses it and refuses a rule with no id, an action it does not recognise, or a pattern that will not compile, rather than skipping the broken rule in silence. The rule then applies to every finding of that shape, forever, carrying its reason with it. When it turns out to be wrong there is a diff, with a date and a commit message, instead of an argument about what was decided.

<!-- resolve_environment in core/severity_governor.py is the host classifier this paragraph describes; it matches non-production markers on whole dot- or hyphen-delimited segments -->
Which raises how the system knows which kind of host it is looking at, and the answer is a small piece of code I like more than its size warrants. [`severity_governor.py:resolve_environment`](../core/severity_governor.py) splits the hostname on dots and hyphens and asks whether any whole segment is a non-production marker, optionally prefixed with www and optionally carrying trailing digits. Whole segments, because the obvious substring version finds "sit" inside deposits, website, positions and visitor, and "test" inside latest. Five perfectly ordinary hostnames that a substring check would demote to test environments and cap a band below what they had earned, on the strength of a pattern that was almost right. The version in the code splits first and anchors the match, and gets all five correct. I checked, because a rule whose cap depends on the answer deserves better than my confidence in a regular expression.

The evidence that this is worth doing is the file's own history, and it does not flatter the file. One rule, the one that marks single-page-application fallback responses as false positives, has been corrected three separate times, each correction making it match less: first to more distinctive markers, then gated on finding type, then gated again so it could not fire on access-control or injection findings at all. Every one of those edits exists because the rule as written was burying real findings behind a match that was too broad.

That is the right failure mode for the most dangerous action in the system. A rule that marks a finding false positive removes it from every published count, and it does so silently, and the finding it removes might be the one that mattered. Three corrections to one rule reads to me as a control being watched rather than a control being wrong.

In this corpus that action never fired. No finding in the whole governance pass was marked false positive; the non-false-positive population came out of the pass exactly as large as it went in. I do not read that as vindication. It is one corpus, and a rule that has never fired is a rule nobody has tested against real data. The factorial study in appendix E has since widened that corpus by 40 runs across two targets, and the count stayed where it was: 0 firings. Measured against a blinded adjudication, the false-positive suppression this system actually achieves comes from the verifier, not from this ruleset -- so the claim this chapter is allowed to make for these rules is severity governance, duplicate control and auditability, and the mark-false-positive action is a guarded emergency brake that field data has still never justified pulling.

The obvious weakness is that these matches are regular expressions over titles, URLs and a concatenated blob of evidence text. That is brittle in the ordinary way. A rule keyed on a phrase in a login bounce page stops firing the day the application rewrites that page, and nothing announces it, and the false positives quietly come back. I would rather have brittle rules I can read than robust judgement I cannot, but those are the terms of the trade and they should be stated.

There is a second-order version of the same problem, and it caught me. The script that audits the governance pass classifies each change as expected behaviour or as something a human has to look at, and it decides by matching the finding type against a list of categories the ruleset was written to cap. I wrote that list the way I think about the categories. The database spells several of them differently. So a good fraction of the entries matched nothing at all, and the published split between `17` and `52` was on its way to being a statement about one finding type versus everything else, wearing a broader list as costume. The check that now catches it asserts that no entry in the list matches nothing in the corpus, which is a strange-looking test and the only one that would have helped.

The flagged half is the half that matters, and it is conservative on purpose. A finding type the list does not recognise is flagged. A false-positive mark is flagged unconditionally, regardless of type and regardless of whether severity moved. The attack chains are all in there, which is how I came to spend an afternoon on them. An audit that only flags what the author expected to be flagged has told you nothing you did not already believe.

## Gravity points down

The third law says severity falls by default and rises only against proof, and the consequence is that this system's failure mode is under-reporting.

I want to defend that direction properly rather than assert it, because the obvious objection is good. A missed critical is found by an attacker; an inflated one is found by a client. Surely the asymmetry runs the other way.

It does not, and the reason is what the output is. The output is a report a human reads and acts on, and the human is downstream of every control in this handbook. An under-scored finding is still in the report. It is still described, still has a URL, still gets read, and a reviewer who thinks it deserves better can promote it, because the evidence for the promotion is sitting right there in the row. The cost of under-scoring is queue position.

An over-scored finding is a different kind of defect, because it does not damage itself. It damages the column. Once a reader learns that critical does not mean critical in your reports, every finding you ever send them is degraded, including the ones that were right, and there is no per-finding fix for that. You cannot promote your way out of a severity column nobody consults. The first page of this chapter is what that looks like from the receiving end.

That argument has a bill attached and I have already shown part of it. Capping on evidence means a genuine critical whose tool failed to record the exchange lands at medium and is triaged at medium. The corpus contains exactly those: findings that carry extracted credential material and were capped because nothing wrote down the request. Their band is wrong in the safe direction, which is still wrong. How often that happened across the corpus I cannot tell you, because measuring it means someone re-testing each capped finding by hand, and nobody has.

So the honest summary is that the direction is chosen rather than proven. I think it is the right choice for a client-facing deliverable and I would make it again. I have no measurement showing that the findings this system buried were less costly than the findings it would have inflated.

## What it costs to build this

The ruleset is a permanent obligation, and it is the same obligation chapter 01 described for the relevance table with worse consequences attached. A stale scoring entry wastes a tool execution. A stale suppression rule deletes a vulnerability from a report. Both rot silently, both are invisible until somebody enumerates them, and only one of them ends up in a breach retrospective.

The evidence ceiling imposes a requirement on every tool, retroactively. Turn it on before the tools capture evidence and the whole corpus under-scores at once, for reasons that have nothing to do with the targets. That is why the ceiling has a switch of its own, separate from the switch for governance as a whole. Both default to on today; the separate switch exists because there was a phase where evidence capture had not landed in the tools yet and enforcing a ceiling against it would have punished every finding for a gap in the plumbing. The ordering is load-bearing and easy to get backwards, and backwards produces a system that looks calibrated and is blind.

The verifier costs a model call for every finding in the gray area, and it is the single place in this design where a model is permitted to move a number upward. All of that trust is paid for by the check at the recording site, and that check is currently one condition of the three the contract advertises. I have known that for the length of one section and it is still true at the end of the chapter.

The last cost is the one nobody warns you about. An honestly governed report looks worse. Two highs and a page of mediums is a harder document to hand to a client than nine criticals, and it is a harder document to show your own management, and the pressure to loosen the ceiling arrives from your own side of the table wearing the language of not underselling the work. Every mechanism in this chapter exists because I do not trust myself in that meeting either. A structural incapacity to escalate is a promise you make once, in code, at a moment when nobody is asking you to break it.

---

## Number annotations

These notes were written inline in the handbook source beside the numbers they explain; the renderer collects them here and leaves a `[num-ok N]` marker at each point of use above.

**[num-ok 1]** two rows is a spelled quantity counting a code artifact, used twice on this line for rows of the transition table immediately above: the two that leave critical, and the two that land on medium

**[num-ok 2]** one line is a spelled quantity counting a code artifact: the distance between two reads in the branch this paragraph patches, in the verifier this repository withholds rather than in core/

**[num-ok 3]** exactly one is a spelled quantity counting a corpus query rather than a published figure: the verifier verdicts that raised a severity, counted in the engagement database this repository does not carry, with no data/stats.json key behind it. No pattern in this gate reads it, which is the below-twenty exemption working as documented. The hedges beside it, a small set and a few weeks, assert no quantity on purpose

**[num-ok 4]** One raise is the same spelled quantity as the paragraph above restated as a sentence: the single verifier verdict that raised a severity, from the same uncited corpus query, with no data/stats.json key behind it

**[num-ok 5]** nine in ten is a spelled quantity, a worded ratio over published statistics: corpus.chains.ungoverned over corpus.chains.total in data/stats.json. The inequality behind the words is pinned in test_the_chain_populations_partition_the_total, and the exact share this paragraph declines to print is the ungoverned_share key in the same block

**[num-ok 6]** a little under half of is a spelled quantity, a worded ratio over published statistics: corpus.chains.scans_with_chain_objects over corpus.scans.total in data/stats.json, pinned as a bounded fraction in test_scans_with_chain_data_are_a_little_under_half_the_corpus

**[num-ok 7]** halves of is a spelled quantity used rhetorically: it names the two clauses of the sentence immediately before it and quantifies nothing
