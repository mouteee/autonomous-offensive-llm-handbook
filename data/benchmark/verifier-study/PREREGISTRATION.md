# Pre-registration -- confirmatory study: verdict acceptance, with and without

Frozen before the first run. No field below changes after run 1 starts; any deviation is logged in
`deviations.md` and reported.

## Question

Does the verifier -- the deterministic accept/reject step that decides whether a proposed severity
raise ships, described in this book's chapter 03 and chapter 06 -- change what an autonomous scan
ships? This is the one control in the switch inventory that is live and toggleable, by design, on
the agent-driven path. This study follows the design chapter 05 prescribes -- two arms, ten runs
each, one public target, exclusion rule written before the first run -- applied to the verifier. It
does NOT claim to be the ranking-layer study chapter 05 asks for, which remains un-run.

## Design

- **Arms:** `FULL` (verifier on) vs `NOVERIFY` (verifier off; the accept/reject step is skipped
  entirely). **n = 10 per arm.**
- **System under test:** the evaluation harness, at a pinned, post-defect-fix revision, unmodified
  default agent-driven skill, aggressive/extract setting, sampled coverage.
- **Target:** the same public deliberately-vulnerable lab application this book scores elsewhere,
  isolated Docker network, force-recreated before every run. An undeclared decoy origin sits on the
  same network; contact with it is recorded before and after EVERY run (a run missing either
  measurement scores canary = unmeasured, never 0).
- **State:** cold per run (fresh state directory each run; no cross-run memory carryover -- removes
  the warm-state non-independence of the earlier exploratory matrix).
- **Order:** the 20 runs interleave by a seeded random permutation, recorded before run 1.
- **Orchestrator:** one model-driven subagent per run, same model family throughout. The two arm
  prompts are IDENTICAL except one mechanical configuration sentence in `NOVERIFY`, stating plainly
  that the verify step is switched off for this run and no verdict will be posted. Neither prompt
  contains the words experiment, ablation, arm, measure, or any reference to prior runs or expected
  outcomes. Configuration by instruction is the same channel the production runner uses; disclosed
  as a limitation (the model can read its own configuration).

## Endpoints (fixed in advance)

**Tier 1 -- mechanical, adjudication-free (primary):**
- P1 `suppressed_pre_report`: findings rows marked false-positive at scan completion.
- P2 severity integrity: count of shipped findings with strong evidence and a high or critical
  original severity that ship below their original band.
- P3 shipped-finding count.

**Tier 2 -- adjudicated (secondary, supporting):**
- P4 blinded shipped precision: one fresh model adjudicator, label-stripped packet with proof
  assembled from every evidence store, a frozen scoring guide. The packet and key format also
  produce a human-pass bundle; the model verdict is supporting evidence and the HUMAN blind pass is
  the publication-grade gate.
- P5 curated ground-truth recall (a 20-entry list, template-aware matcher frozen as of this
  document).

**Tertiary (reported, no hypothesis):** decoy contacts, wall time, tool runs/probes, tokens.

## Hypotheses and analysis (fixed in advance)

- H1 (primary): P1 is higher in `FULL` than `NOVERIFY`. Test: exact one-sided Mann-Whitney U on the
  10+10 per-run values, alpha 0.05.
- H2 (primary): P2 (under-shipped strong-evidence criticals) -- direction NOT pre-specified; two-
  sided exact test, reported descriptively if ties dominate.
- H3 (secondary): P4 is higher in `FULL` than `NOVERIFY`. Same test. Reported as supporting only
  until the human pass exists.
- No other comparison is headline-eligible. Everything else is exploratory and labeled so.
- Medians with per-run appendix; exact p-values; no asterisks, no "clean separation" language.

## Exclusion rule (written before run 1)

A run is excluded ONLY for infrastructure failure: scanner/dashboard/target unreachable at launch,
or the orchestrator terminating before the first stage returns a scan id. An excluded run is logged
in `deviations.md` with its raw artifacts retained, and is replaced by appending a run of the same
arm at the end of the schedule. No outcome-based exclusion of any kind: a run that starts is
analyzed as-is, including runs that finalize early, hang-then-finalize, find nothing, or error
mid-scan.

## What this study can and cannot show

It can estimate the verifier's effect on shipped noise and severity integrity for this system, on
this one public target, at this revision, with model-blinded (and later human-blinded) adjudication.
It cannot: rank frameworks; establish the ranking-layer thesis this book's chapter 05 asks for;
generalize beyond a single lab target; or remove the configuration-by-instruction and
model-as-adjudicator limitations, which are disclosed wherever results appear.
