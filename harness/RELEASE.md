# Conference reference release

This is an offline teaching implementation, not a deployable autonomous penetration tester. It sends no network traffic, calls no model, and marks every finding as requiring human review. It does not implement a person's acceptance or report-signing workflow. Authorization applies only to calls through the provided API; the Python host and adapters are trusted.

Start with [chapter 07](../handbook/07-harness-lab.md), run `python3 -m harness.demo --out /tmp/harness-report.json`, then run `python3 -m pytest tests/`. The report is deterministic for frozen fixtures, manifest and implementation. Identical bytes are not proof of correct findings.

## Reviewed boundaries

Independent review found and corrected port-zero aliasing, action reordering under a budget, kind/tool rule bypass, nonfinite derived scores, and proof tests that failed on the wrong condition. The status and marker predicates now have separate same-kind/same-tool negative cases; deleting either predicate causes its respective test to fail.

The suite also recounts historical store coverage from actual stored records, rather than trusting the committed summary or its generator alone. The original `core/` and `walkthrough/` remain historical case-study implementations; the new package does not retroactively fix every path described in those chapters.

## Publication clearance

<!-- num-ok: 2026-09-03 is the date of the owner's publication authorization in the review conversation, not a measurement from a target -->
The owner confirmed publication clearance on 2026-09-03, with the condition that employer, client and target specifics are not named. Public attribution uses neutral handbook-author wording. This records the owner's authorization; it is not an independent private-identifier or legal-rights audit. The published-pattern audit remains a limited check, not a substitute for that authorization.

## Not established

- Live model repeatability, exploitation correctness or measured cost savings.
- Resistance to hostile Python code, re-entrant or concurrent adapters, DNS changes, redirects or unrestricted shell access.
- Correct proof semantics for an arbitrary target domain.
- An independent private-identifier audit. The owner has provided clearance, but the private denylist is not part of this repository.

Do not connect this example to a live target until the port owner supplies transport containment, authorization verification, reviewed domain evidence semantics, and a controlled evaluation. The evaluation protocol in this folder is a plan, not completed results.
