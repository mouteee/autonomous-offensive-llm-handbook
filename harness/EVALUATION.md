# Evaluation protocol, not results

Status: proposed. No controlled savings result is published by this tutorial.

## Question

Does assigning derivable decisions to deterministic controls reduce unsupported findings, redundant execution and review effort without unacceptable recall loss?

## Paired configurations

Compare the same model, prompt, tool catalogue, local authorized target snapshot, initial state, execution budget and timeout. One configuration uses the harness policies; the comparator uses the explicitly declared alternative. Never disable authorization or transport containment for an experiment. Ablate selection, evidence acceptance or reporting controls only inside an isolated lab.

Predeclare the number of repeated trials, target set, exclusions, randomization order and stopping rule before seeing results. Publish every run, including failures and costs. The sample size should follow the variance observed in a pilot, not a convenient headline.

## Record per run

- Model identifier, parameters, prompt hash and policy hash.
- Target image/version and ground-truth version.
- Started, completed, errored and skipped actions with reasons.
- Input/output tokens, provider charges, tool/runtime cost and elapsed time.
- Ground-truth true positives, false positives and false negatives.
- Analyst review minutes and adjudication disagreement.
- Useful coverage, unsupported claims, repeated actions and scope refusals.
- Every exclusion, its predeclared rule and its effect on the result.

## Analysis

Report per-target paired differences and uncertainty, not only pooled averages. Keep cost and quality side by side. Separate run-time savings from development and maintenance cost. A reduction in false positives purchased by missing more real vulnerabilities must remain visible.

The original corpus is operational evidence, not an ablation. The synthetic harness report is a mechanism demonstration, not a detection benchmark. Do not merge those populations.

## Falsification

- The cost claim fails if equivalent useful coverage costs as much or more.
- The precision claim fails if unsupported findings do not decline.
- The time claim fails if review effort does not improve.
- The portability claim fails if a new port needs undeclared control changes.
- The repeatability claim fails if identical frozen inputs produce different control records.

Publish an inconclusive or negative result with the same visibility as a positive one.
