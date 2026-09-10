# Appendix E -- the factorial study

## What this is

Appendix D reports a study of a package: a model verifier plus the deterministic handling
of its verdicts, ablated together, because turning the pair off together was the only arm
run. That appendix says so out loud -- "this study does not isolate that deterministic
handling from the model verifier feeding it" -- and this appendix is the study that does
the isolating. Same discipline: design frozen before run one, 40
runs in one cohort, zero exclusions, every deviation logged the day it happened. Two
switches this time instead of one, each on and off independently: the model verifier, and
the deterministic acceptance layer (the governor and the accept-or-refuse-or-raise verdict
policy). Four configurations, 5 cold runs each,
against two lab targets (OWASP Juice Shop + VAmPI) instead of one. The
deterministic switch was thrown in the environment, not in the instructions --
environment-enforced (HARNESS_GOVERNANCE, HARNESS_VERDICT_POLICY), invisible to the orchestrator's instructions; verified in the container env and in every verdict's recorded policy field -- so unlike the verifier sentence appendix D
discloses, the model was never told which acceptance policy it was running under.

## The two questions, and their two answers

The first pre-registered question: does the verifier alone -- no deterministic acceptance
behind it -- still change what ships? Yes. Pre-report suppression, verifier-only against
neither (exact permutation of summed Mann-Whitney U within targets, one-sided):
p = 0.002, holding up under the
pre-registered multiple-comparison correction at
p = 0.004. The effect lives on the richer
target -- Juice Shop medians 2
against 1 per run; the small
API produced almost nothing suppressible in any arm.

The second pre-registered question: do the two layers interact -- is the deterministic
acceptance worth something *on top of* the raw verifier, or the verifier worth more *with*
the rules behind it? No detectable interaction:
p = 0.72 on blinded precision, a null this
book committed in advance to publishing at equal billing. And the null is not a
technicality hiding a near-miss. Blinded precision on the informative target, per arm,
medians: neither 0.4, rules alone
0.312, verifier alone
0.444, both
0.5. The rules-alone arm did not beat the
raw agent. The second target sat at the ceiling and discriminated nothing:
all four arms at or near 1.0 -- the small wholly-vulnerable API sits at the precision ceiling and carries no discrimination power.

The bluntest number in the study is this one:
0. That is the firing count of the
deterministic governor's mark-false-positive action across all
40 runs. Chapter 03 reported the same action never
firing on its original corpus and refused to read that as vindication; 40 more runs
across two targets read the same way, and now with a verdict attached: on these targets,
false-positive suppression is the verifier's work, not the ruleset's.
the deterministic governor's mark-false-positive action fired zero times in all 40 runs; base write-time heuristics false-killed 5 genuine findings, and only verifier-equipped arms could restore them (3 restored via verdicts) -- which cuts the other way too: a write-time
heuristic that misfires against a real finding stays wrong forever in a run with no
verifier, because nothing else in the pipeline is allowed to overrule it.

## What the verifier costs

Sensitivity -- the fraction of adjudicated-true findings that survived to the report --
per arm: neither 0.962 (76/79), rules alone
1.000 (68/68), verifier alone
0.989 (87/88), both
0.938 (76/81). Specificity -- the fraction of
adjudicated-false findings caught before the report -- climbs the same ladder the other
way: 0.017 (1/60),
0.000 (0/59),
0.175 (10/57),
0.226 (14/62).

[num-ok 1]
The pre-registered bar was that the full design keep at least ninety percent of true findings, demonstrated at 95 percent confidence.
It did not clear it: non-inferiority NOT established -- the full design discards about 6 percent of adjudicated-true candidates and this study cannot rule out a true sensitivity below 0.90
(point 0.938 (76/81), lower bound
0.875 against the
0.9 margin). Part of that loss has a name
and a fix: one run's genuinely-performed account takeover was rejected because the stored
evidence had its identity-bearing header redacted so thoroughly the verifier could not
quote the proof it demanded -- a redaction defect, logged the day it happened, queued for
repair, and exactly the kind of cost a chapter recommending a prove-it-or-lose-it gate
owes its reader.

Recall, this time with a pre-registered margin instead of appendix D's silence: medians
identical across all four arms on both targets
(0.158 and
0.571 against deduplicated
ground-truth lists), within the one-item margin. Turning every switch off found the same
bugs. The layers under study decide what a run ships, not what a model can find --
appendix D said it of one pair, and it now holds for each half separately.

One replication note, because it is the strongest sentence in this appendix: the
shipped-design-against-rules-alone comparison inside this study is, in different runs on a
different day under a different randomization, the same comparison appendix D ran -- and
A3 vs A1 juice precision 0.500 vs 0.312 independently reproduces the two-arm study's package effect (0.471 vs 0.353).

## The honesty ledger

The adjudication behind the precision and sensitivity numbers is
model_blinded_human_pass_pending (Opus adjudicator; distinct model from the Sonnet orchestrators, same family -- no non-Claude adjudicator available) -- same standing as appendix D's: supported,
model-blinded, and waiting on the same human blind pass before any of it graduates. The
packet the human will see includes the 34
rejected findings alongside the 527 shipped
ones, indistinguishable, so the gate's mistakes are as visible as its saves. The decoy
host logged 0 contacts in
40 runs; the crawler's habit of following
the lab target's own redirect out to a public code-hosting page recurred in roughly half
the Juice Shop runs (engine-dependent, both arms equally, flagged per run), one run issued
a certificate-transparency lookup on a bare container name, and one run read the target's
own container source through the container runtime rather than HTTP -- each logged, each
arm-symmetric, none touching the comparison. The verdict-policy audit trail recorded the
expected policy in every verdict of every run, no verdicts existed in any verifier-off
run, and the asymmetric raise gate had nothing to do all study:
0 unproven raises were attempted
anywhere, so that rule remains tested by construction and by unit test, not by field data.

## What this changes in this book, and what it does not show

Where earlier drafts let the deterministic layer share credit for a cleaner report, the
measured split now reads: the verifier carries the suppression and precision effect; the
deterministic acceptance layer earns its place as severity governance, duplicate control,
and the backstop that makes verifier verdicts auditable -- not as a false-positive filter.
Chapter 03's asymmetric-trust design is unchanged by this: its severity rules fired
throughout, its raise gate is untouched, and nothing here says the rules are free to
delete. What it does say is narrower and more defensible: if you build only one of the two
layers, build the verifier.

Still true and still binding: two lab targets, one of them at the precision ceiling; model
orchestrators and a same-family model adjudicator, human pass pending; the verifier switch
communicated in-instruction while only the acceptance switch was environment-enforced;
five runs per cell, so the interaction null is "no effect detected", not "no effect";
ranking and scheduling untouched, exactly where chapter 05 left them.

---

## Number annotations

These notes were written inline in the handbook source beside the numbers they explain; the renderer collects them here and leaves a `[num-ok N]` marker at each point of use above.

**[num-ok 1]** ninety and 95 name the pre-registered non-inferiority margin and its confidence level, design constants frozen before run one, not measurements
