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

## Status update

A pre-registered two-arm study compared the model verifier and deterministic verdict handling as one package, switched on or off against a public lab target: [[stats:benchmark.verifier_ablation.n_per_arm]] cold runs per arm, the exclusion rule frozen before the first run, exact statistics throughout. Pre-report suppression fell from a median of [[stats:benchmark.verifier_ablation.suppression.FULL_median]] to [[stats:benchmark.verifier_ablation.suppression.NOVERIFY_median]] per run (one-sided p = [[stats:benchmark.verifier_ablation.suppression.p_one_sided]], the pre-registered direction), and label-blinded shipped precision moved from a median of [[stats:benchmark.verifier_ablation.blinded_precision.FULL_median]] to [[stats:benchmark.verifier_ablation.blinded_precision.NOVERIFY_median]] (one-sided p = [[stats:benchmark.verifier_ablation.blinded_precision.p_one_sided]]; supported, not confirmed; publication-grade confirmation is pending the human blind pass). Severity-integrity events showed no detected difference across arms ([[stats:benchmark.verifier_ablation.p2.FULL_total]] vs. [[stats:benchmark.verifier_ablation.p2.NOVERIFY_total]] total; two-sided p = [[stats:benchmark.verifier_ablation.p2.p_two_sided]], as pre-registered). Ground-truth recall carried no pre-registered direction and showed no statistically significant difference between the arms (two-sided p = [[stats:benchmark.verifier_ablation.recall.p_two_sided]]); the study was not designed to establish equivalent recall, and the ground-truth list itself double-counts one condition, so a deduplicated recall figure is reported alongside the raw one. Both arms repeatedly found several of the same core vulnerability classes, with substantial per-run variation: a mass-assignment finding, for instance, shipped in [[stats:benchmark.verifier_ablation.mass_assignment_runs.FULL]] runs with the stage on against [[stats:benchmark.verifier_ablation.mass_assignment_runs.NOVERIFY]] with it off. The instrumented on-network canary was contacted zero times in [[stats:benchmark.verifier_ablation.canary.measured_runs]] of [[stats:benchmark.verifier_ablation.n_total]] measured runs, alongside a disclosed crawler redirect-follow and one DNS lookup per run. Full design, deviations and numbers are in `handbook/appendix-d-verifier-study.md` and `data/benchmark/verifier-study/`; the underlying figures resolve to `data/stats.json` under `benchmark.verifier_ablation`.

The ranking-layer study this protocol asks for above remains un-run, and the result above does not claim it. The precision result is model-blinded, not human-blinded, and the human blind pass is still the gate that result is waiting on before it counts as more than supporting evidence.
