# The build sequence

This page is the course map: from a clean clone to a configuration-driven agent you assembled yourself, with every decision inspectable in a saved artifact. Each lesson opens from a named checkpoint and ends with a working component, a run command, an expected artifact, a failure exercise and a completion check.

There are two routes, and the second is optional:

**Build a working agent:** the core route and shortest path to your own assembled application: [the first run](../rendered/course/01-first-run.md) → [policy and records](../rendered/course/02-policy-and-records.md) → [stages and observations](../rendered/course/03-stages-and-observations.md) → [model proposals](../rendered/course/04-model-proposals.md) → one marked detour into [the controller laboratory](../rendered/course/10-controller-laboratory.md) for the selection contract, the baselines and the factory (from the top down to the bold return line at the end of step seven, then come straight back) → [candidates and dispatch](../rendered/course/05-candidates-and-dispatch.md) → [retrieval and memory](../rendered/course/06-retrieval-and-memory.md) → [context assembly](../rendered/course/07-context-assembly.md) → [evidence and verification](../rendered/course/08-evidence-and-verification.md) → [stop, recover, finish](../rendered/course/09-stop-recover-finish.md) → [the assembly capstone](../rendered/course/16-package-your-agent.md). The assembled application runs the frozen priority baseline; nothing adaptive is a prerequisite for finishing it or for connecting your own model through `examples/app_agent.py`.

**Investigate adaptive selection:** the advanced route, taken after the core or interleaved with it: the rest of [the controller laboratory](../rendered/course/10-controller-laboratory.md), then [LinUCB](../rendered/course/11-linucb.md) → [the sparse controller](../rendered/course/12-mushroom-body-controller.md) → [plasticity](../rendered/course/13-plasticity-and-credit.md) → optionally [graph experiments](../rendered/course/14-graph-controller-experiments.md) → [the comparison protocol](../rendered/course/15-comparisons-and-interpretation.md), which is required before making any improvement claim and does not require the graph lesson. The named controllers on this route reconnect to the same application through the configuration's controller key; the graph lesson's experimental arm deliberately stays a research construction outside the factory. The route's additional prerequisites (a little linear algebra, comfort with SQL) are declared where they bite.

Start with [the offline lab](../rendered/07-harness-lab.md) if you have not run it: it needs no API key or network and it is lesson 1's starting point. Connect a real model only when [the model connection guide](CONNECT_YOUR_MODEL.md) tells you what to replace and what to keep.

## The lessons

| Lesson | You leave with |
|---|---|
| [Run the whole thing first](../rendered/course/01-first-run.md) | A reproduced fixture report you can explain line by line |
| [Policy, records, write boundary](../rendered/course/02-policy-and-records.md) | One recording door; refusals as recorded events |
| [Stages and observations](../rendered/course/03-stages-and-observations.md) | An enforced stage machine and measured-or-unknown observations |
| [Model proposals](../rendered/course/04-model-proposals.md) | Validated hypotheses, bounded repair, hostile text refused by policy |
| [Candidates and dispatch](../rendered/course/05-candidates-and-dispatch.md) | An eligible work set with reasons, and six outcome statuses that never blur |
| [Retrieval and memory](../rendered/course/06-retrieval-and-memory.md) | Hybrid search with component scores, structured lanes, refutation that sticks |
| [Context assembly](../rendered/course/07-context-assembly.md) | Tier budgets, whole-block drops, and the omissions record |
| [Evidence and verification](../rendered/course/08-evidence-and-verification.md) | Capture-bound findings, an isolated verifier, verdicts validated in host code |
| [Stop, recover, finish](../rendered/course/09-stop-recover-finish.md) | Budgets with owners, resume without invented success, a gated finish |
| [The controller laboratory](../rendered/course/10-controller-laboratory.md) | One selection contract, shared feedback, two baselines |
| [LinUCB step by step](../rendered/course/11-linucb.md) | The bandit arithmetic, worked by hand and recomputed by test |
| [The mushroom-body controller](../rendered/course/12-mushroom-body-controller.md) | Sparse coding, soft competition and habituation you can replay |
| [Plasticity and credit](../rendered/course/13-plasticity-and-credit.md) | Eligibility traces, clipped local updates, cross-run priors and their recorded defect |
| [Graph controller experiments](../rendered/course/14-graph-controller-experiments.md) | The experimental edge-plastic arm and its controls |
| [Comparisons and interpretation](../rendered/course/15-comparisons-and-interpretation.md) | The frozen-manifest protocol and scoped readings |
| [Package your agent](../rendered/course/16-package-your-agent.md) | The assembled, configuration-driven application |

The table lists every lesson; the two routes above tell you which to read first. Each lesson's "Start from here" and "Continue" sections follow those routes. The controller lessons compare adaptive selection with fixed baselines on synthetic worlds. The ordinary application keeps learning off; research constructors turn it on explicitly. The priority baseline is the default. Choose an adaptive controller only when the [comparison protocol](../rendered/course/15-comparisons-and-interpretation.md) gives you evidence for your use case, and check the [evidence register](../rendered/appendix-f-evidence-register.md) for what the earlier studies did and did not show.

## The shape of every practical lesson

Build this; start from here; inputs and outputs; implement it; run it; inspect it; break it; check completion; continue. The explanation lives beside the implementation it explains, every run command is copyable from the repository root, every expected artifact is committed and held byte-identical by a sync test, and every completion sentence is pinned to a named test. "Run the tests" is never the whole instruction.

## Where the theory went

The design essays that used to be the main reading path are now [the design notes](../rendered/00-thesis.md): the determinism argument, the historical case study and its recorded defects, and the controls each failure demanded. Read them when a lesson makes you ask why a control exists; the [failure museum](../rendered/appendix-c-failure-museum.md) and the [study appendices](../rendered/appendix-d-verifier-study.md) carry the evidence.

## After the course

A live adapter is a separate milestone with its own review: every destination, redirects, credentials and secondary requests, plus process restrictions and approved authorization. The offline dispatcher alone cannot contain arbitrary adapter behavior, and no lesson claims otherwise. Evaluate before extending the environment: [the evaluation protocol](../harness/EVALUATION.md) and the completed [verifier](../rendered/appendix-d-verifier-study.md) and [factorial](../rendered/appendix-e-factorial-study.md) studies show what a defensible measurement looks like, and [the evidence register](../rendered/appendix-f-evidence-register.md) keeps every claim's status honest.
