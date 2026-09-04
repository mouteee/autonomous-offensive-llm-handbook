"""Gate-check: whether a scan's own collected signals justify testing further.

`decide_gate_status` is a pure decision tree over seven optional keys already
sitting in one `inputs` dict -- no network call, no clock, no file read, no
randomness, and no mutation of that dict. The same `inputs` gives the same
answer back, forever, which is what lets a decision be replayed rather than
re-run.

Every key defaults if the caller never set it, so an empty dict is not an
error -- it reads as "nothing has been collected yet" and resolves to the
most permissive outcome, `proceed`. That is the fail-open this tree commits
to: missing evidence never blocks a scan on its own, only evidence of an
actual block does.

Four outcomes, each naming how much of `["full", "cache_cors_csp",
"baseline_passive"]` the caller may still run:

  `gated`       -- a near-total response failure, a WAF that fired, and no
                   discovered surface, together. Only `baseline_passive`.
  `gated_soft`  -- a high error rate with no discovered surface, but nothing
                   here confirms the block was total. Only `baseline_passive`.
  `limited`     -- crawlable, but no forms, no scripts and few parameters:
                   public or static content. `baseline_passive` plus
                   `cache_cors_csp`.
  `proceed`     -- richer than all three of the above, including the empty
                   dict. `["full"]`.

They are checked in that order -- most specific first -- and the order is the
whole correctness of the tree, not a style choice: every input that satisfies
`gated` also satisfies `gated_soft`'s weaker condition, so reading the weaker
branch first would report a fully-blocked target as merely soft-gated and
understate it. The same overlap holds for the pair below it, and it is
narrower than it first looks. An input satisfies both `gated_soft` and
`limited` exactly when `error_rate > 0.8`, `parameters_found == 0`,
`forms_found == 0`, `scripts_found == 0` and `pages_crawled >= 1` all hold:
`gated_soft` needs the error rate and its no-surface test
(`parameters_found == 0` and `forms_found == 0`, which also clears
`limited`'s `parameters_found <= 2`), while `limited` additionally needs
`pages_crawled >= 1` and `scripts_found == 0`. That last requirement is the
catch -- `gated_soft` never constrains `scripts_found` -- so a high-error,
no-surface target that did find scripts is `gated_soft` and not `limited` at
all; the branches coincide only when `scripts_found == 0` as well, and there
`gated_soft` is read before `limited`, or a target that errored out with no
surface would be handed `cache_cors_csp` as though it were ordinary static
content. `evidence` in the return value is the seven inputs as this
call actually read them, not the caller's original dict, so whichever branch
fired can be re-derived from the record alone without re-collecting anything.

Which caller supplies which key is where this tree's honesty runs out before
its logic does. In the reference deployment this module is drawn from, the
caller that builds `inputs` is uneven across the seven: the WAF flag and the
two response-shape counts -- three of the seven -- are read from artifacts an
earlier stage wrote, and only if that stage's output happens to exist on disk
by the time this call runs; the form and script counts -- two more -- are set
to a hardcoded zero by that same caller regardless of what was actually seen,
because nothing upstream is wired to report them yet. Only the parameter and
page counts are always live.

Set that asymmetry beside the fact that `gated` -- the branch this docstring
leads with -- has never fired across this project's own recorded scans, and it
is worth being exact about what that observation does and does not support. It
does not support a claim that the branch is dead code: the two zero-pinned
keys make `forms_found == 0` true by construction rather than by observation,
which narrows `gated` to a
condition on the other three, and whether that narrowed condition is
reachable given how those three are actually populated is a fact about the
caller, not about this function. It also does not support a claim that the
caller is at fault: it is equally consistent with the data that no target this
system has scanned was ever, in fact, fully blocked. Both explanations fit the
same outcome, and nothing in this account distinguishes them.
"""
from typing import Any, Dict


def decide_gate_status(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Classify one scan's gate status from its already-collected signals.

    Reads seven optional keys from `inputs` -- `waf_detected`,
    `total_responses`, `error_rate`, `parameters_found`, `forms_found`,
    `pages_crawled`, `scripts_found` -- each defaulted if absent, and returns
    `{status, reason, detail, allowed_stages, evidence}`. See the module
    docstring for the decision tree and what it does and does not tell you.
    """
    waf_detected = bool(inputs.get("waf_detected", False))
    total_responses = int(inputs.get("total_responses", 0))
    error_rate = float(inputs.get("error_rate", 0.0))
    parameters_found = int(inputs.get("parameters_found", 0))
    forms_found = int(inputs.get("forms_found", 0))
    pages_crawled = int(inputs.get("pages_crawled", 0))
    scripts_found = int(inputs.get("scripts_found", 0))

    evidence = {
        "waf_detected": waf_detected,
        "total_responses": total_responses,
        "error_rate": round(error_rate, 2),
        "parameters_found": parameters_found,
        "forms_found": forms_found,
        "pages_crawled": pages_crawled,
        "scripts_found": scripts_found,
    }

    no_surface = parameters_found == 0 and forms_found == 0

    # Most specific first (see module docstring): a fully-blocked target
    # also satisfies the high-error condition just below, so this branch
    # has to be read before that one or the more specific outcome is lost.
    if total_responses <= 1 and error_rate >= 0.99 and waf_detected and no_surface:
        return {
            "status": "gated",
            "reason": "blocked_total",
            "detail": "Almost nothing came back, the WAF fired, and no "
                       "surface was found -- treat this as a hard block.",
            "allowed_stages": ["baseline_passive"],
            "evidence": evidence,
        }

    if error_rate > 0.8 and no_surface:
        return {
            "status": "gated_soft",
            "reason": "high_error_no_surface",
            "detail": f"{error_rate:.0%} of responses errored and no "
                       f"parameters or forms were found, but nothing here "
                       f"confirms a total block.",
            "allowed_stages": ["baseline_passive"],
            "evidence": evidence,
        }

    if pages_crawled >= 1 and forms_found == 0 and scripts_found == 0 and parameters_found <= 2:
        return {
            "status": "limited",
            "reason": "static_or_public_surface_only",
            "detail": "Pages were crawled but nothing interactive turned "
                       "up -- no forms, no scripts, and few if any "
                       "parameters.",
            "allowed_stages": ["baseline_passive", "cache_cors_csp"],
            "evidence": evidence,
        }

    return {
        "status": "proceed",
        "reason": "",
        "detail": "",
        "allowed_stages": ["full"],
        "evidence": evidence,
    }
