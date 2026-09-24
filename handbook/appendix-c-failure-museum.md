# Appendix C: the failure museum

## Failure cases

Real findings this system produced and a human threw away. Each entry says what the finding claimed, what made it look real, what was actually true, and the rule that kills it, and, where the public tree has one, the regression test that holds the rule in place. They are worth reading before you write a single rule of your own, because each one cost somebody a morning, and because the shapes recur: a status code believed over a body, a substring matched outside its context, a best practice filed as an exploit, a public value mistaken for a secret.

These are the author's accounts of historical failures. The public tests use authored inputs, and the walkthrough fixtures describe their reconstruction in `regeneration`; they are not original engagement captures. Running them can reproduce a rule's decision. It cannot independently establish what happened on the original target.

The entries are the spec's own failure museum, in the order it lists them, and chapter 03 argues from a few of them rather than from the set. What a reader building a harness should take from the set is that in most of them the scanner really saw what it reported: the capture was genuine and the inference drawn from it was not, which is why a grounding check that only asks whether the evidence is real lets them through. The analyst-verdict entry is the exception, and it is the reason the distinction is worth drawing. There the text being trusted was written by a model rather than observed at all.

## Regression-test coverage

`read-via-post-bounce`, `csp-weakness`, `cors-wildcard`, `spa-fallback-api-200` and `tokenization-key-public` ship in `core/severity_rules.json` and each carries a named test in `tests/test_failure_museum.py`. The unanchored substring match, the analyst verdict written into `raw_data`, and the access-control downgrade on a response body are genericized historical patterns; nothing under `core/` refuses any of them. Those entries are marked as unenforced where they appear, and no test name is offered for them.

The acceptance criterion behind this appendix asks for a regression test beside every entry. That cannot be met here, and the reason is worth more to a reader than the appearance of meeting it would be: writing a test for a mechanism this repository does not carry produces a test that cannot fail, and a test that cannot fail is the exact defect the entries below are about. The museum's own module docstring reaches the same conclusion in the same words, calling such a test "the decorative-gate failure at test scale". Reporting them as unpinnable is the honest outcome rather than a shortfall to be hidden.

## An unanchored substring match in a tool's negative output

The finding claimed a SQL injection, at critical, with an empty evidence block. What made it look real was that the parser had genuinely matched the words `injectable` and `is vulnerable` in the tool's own output. What was true is that the tool had said the parameter was **not** injectable, and the parser was matching those words unanchored, so the negative sentence containing them scored the same as a positive one. The evidence block was empty because there was nothing to quote: a finding with no quotable evidence and a confident severity is the shape to distrust.

The rule is to anchor the match to the tool's verdict line rather than to its prose, and to refuse a finding whose evidence block is empty regardless of what the parser believes. **This is a genericized historical pattern. Nothing in this repository enforces it**, and the only `injectable` under `core/` is an unrelated dependency-injection hook in `core/llm_control.py`.

<!-- num-ok: 200 is the HTTP status code for OK, the protocol constant this entry is about: the whole defect is a success status believed over the body beneath it. It identifies a response rather than counting anything. -->
## A login bounce behind a 200 read as a successful unauthenticated write

<!-- num-ok: 200 is the HTTP status code for OK, the protocol constant this entry is about: the whole defect is a success status believed over the body beneath it. It identifies a response rather than counting anything. -->
The finding claimed an unauthenticated write had succeeded against a profile endpoint, at high. What made it look real was a `200` status on an unauthenticated POST, which is exactly what a successful write looks like from the status line alone. What was true is that the body was a login page: the request had bounced, the session had expired, and nothing had changed. Read the body before believing the code.

The public reproduction is narrower than that incident account. `walkthrough/fixtures/04-read-via-post-bounce.json` explicitly marks its request body, response body, title and evidence as authored. It contains no before-and-after application-state observation. A login page invalidates the detector's success inference from status alone; it does not by itself prove that an arbitrary server performed no write. A live proof policy must check the claimed state change separately.

The rule is `read-via-post-bounce`, which marks the finding as a false positive and drops it to `info`. It requires **both** halves, a title matching the unauthenticated-write claim and evidence matching the bounce, so a title alone cannot silence a real finding. The test is `test_an_unauthenticated_bounce_page_is_not_a_successful_write`, and what it asserts is the case where both halves are present: `rules_fired` naming that rule alone, `high` in and `info` out, the false-positive flag set on the finding, and `fp_reason` naming the rule. The both-halves requirement is a property of the rule's match block, and the test drives the matching case rather than the title-only one.

## An analyst verdict written into the finding it contradicts

The finding carried an enrichment note asserting a conclusion its own evidence did not support, and downstream consumers read the note rather than the evidence. What made it look real was that the note was well written and sat in the same record as the capture. What was true is that a model had been asked to comment on a finding and its comment had been stored as though it were an observation.

The rule is that a model's commentary never enters the same field as a capture, and that anything written by a model is stored where a reader can tell it apart from a request and a response. **This is a genericized historical pattern.** `analyst_verdict`, `analyst_notes` and `forbidden` appear nowhere under `core/`. Stating the scope of that check needs more care than the museum's own docstring gives it: the first two appear nowhere in this repository at all outside prose about them, while `forbidden` does occur elsewhere, as a body snippet in an evidence test, and inside the symbol `_FORBIDDEN_PROVENANCE` in `walkthrough/fixture_schema.py`, whose entries are `host`, `client`, `scan_id` and `url` rather than anything about an analyst. A bare `analyst` also sits in a fixture's provenance prose. None of those is a governance decision path.

## A response body containing "forbidden" downgrading a real access-control finding

The finding was a genuine access-control break, and it was quietly lowered because the response body contained the word `forbidden`. What made the downgrade look reasonable is that a body carrying that word often does mean the request was refused. What was true is that the word appeared in the page's own content, and the request had in fact succeeded. So a heuristic meant to suppress noise was suppressing the finding class the engagement existed to find.

The rule is that a downgrade may never be driven by a substring in a body when the finding's class is one where that substring is expected to appear, and that any automatic lowering of an access-control finding records what it matched. **This is a genericized historical pattern.** The nearest thing in the public tree is a WAF-block classification constant, `WAF_BLOCK` in `core/response_analyzer.py`, which is defined and read nowhere under `core/`.

## Policy advice holding critical

The finding said a Content-Security-Policy permitted `unsafe-inline`, and it was stored at critical. What made it look real is that it was real: the policy did permit it. What was untrue is the severity. A weakened defence in depth is not an exploited path, and a report whose top of the list is policy advice buries the injection and object-authorization findings a reader came for. This is the entry that does the most damage in aggregate rather than individually.

The rule is `csp-weakness`, which caps rather than dismisses: the finding stays, at `medium`. The test is `test_a_csp_best_practice_finding_cannot_hold_critical`, and it asserts `rules_fired` naming that rule, `critical` in and `medium` out, and that the capture grades `strong`, with a message saying why that grade belongs in the assertion. Its scope is narrower than its name and its own docstring says so: the rule matches on type alone and carries a single severity target with no environment split, so the test drives the production tier and the other tier is a property of the rule's data rather than something asserted there.

## A wildcard CORS origin scored as a credentialed read

The finding said `Access-Control-Allow-Origin: *` and was scored critical as a cross-origin read of authenticated data. What made it look real is the header, which was there. What was true is that a browser refuses to honour the wildcard together with `Access-Control-Allow-Credentials`, so the credentialed read the severity implied is not reachable through it.

The rule is `cors-wildcard`, capping at `medium`. The test is `test_a_wildcard_cors_origin_is_capped_below_critical`, asserting `rules_fired`, `critical` in and `medium` out, and the `strong` evidence grade. That grade assertion is load-bearing rather than decorative, and the reason generalises past this entry. With the rule in place a matching finding fires the rule at either grade; `rules_fired` comes back `cors-wildcard` on thin evidence as much as on strong. What changes is the counterfactual: at thin evidence, deleting the rule still lands the finding on `medium`, this time through `evidence-ceiling`, so a test reading only the final severity could not tell the rule's presence from its absence. Asserting `rules_fired` and the grade is what makes the deletion visible.

## A single-page app's index shell counted as a live API response

<!-- num-ok: 200 is the HTTP status code for OK, the protocol constant this entry is about: the whole defect is a success status believed over the body beneath it. It identifies a response rather than counting anything. -->
The finding said an unauthenticated `/api/` route answered `200`, at high. What made it look real is that the route did answer, with a body. What was true is that a single-page app serves its index shell for any path it does not recognise, so the response proves the app's client-side routing rather than the existence of the endpoint.

The rule is `spa-fallback-api-200`, which marks the finding false-positive and drops it to `info` when the url carries `/api/` and the evidence carries a shell marker. It also carries a list of excluded types covering the classes where a reflected shell can still be the real bug, so an injection or access-control finding is never silenced by it. The test is `test_an_spa_index_shell_is_not_a_live_api_response`, asserting `rules_fired`, `high` in and `info` out, the flag, and `fp_reason`. The exclusion list is a property of the rule's match block that the test does not assert, its fixture being an ordinary endpoint finding, and the test's own docstring says so rather than leaving it as an unbacked aside.

## A public-by-design gateway key scored as a leaked secret

The finding reported a payment-gateway authorization key in a front-end bundle, at critical. What made it look real is that the key was there, in the bundle, exactly as reported. What was true is that the key is shipped to the browser deliberately: it cannot process a transaction and it cannot read the vault. Real, and not a secret.

The rule is `tokenization-key-public`, and it caps rather than dismisses, because the finding is not a false positive; somebody should still know the value is published. The cap splits by environment, and the test asserts both halves: `test_a_public_by_design_gateway_key_is_not_a_leaked_secret` drives a production host and a uat host through the governor and asserts, for each, the rule that fired, the environment the governor resolved from the hostname, `critical` in, `high` out in production and `medium` in uat, the evidence grade, and that the finding was **not** marked false-positive. Asserting one half alone could not show that the environment key had been consulted at all.

## The rule in this file that nothing here demonstrates

`source-map-disclosure` ships in `core/severity_rules.json` beside the five above. It has no fixture under `walkthrough/fixtures/`, where the others each have one, and no test in the failure museum. What holds it is weaker than it looks, and the difference is worth measuring rather than asserting.

Its presence and its position are pinned. `test_every_shipped_rule_parses_and_carries_a_rationale` asserts the rules file's id list in order, and `test_a_relative_rules_path_is_resolved_against_the_module_not_the_cwd` and `test_validating_the_same_rules_twice_is_not_an_error` each assert the same length, so deleting the rule reddens all three. Its pattern is compiled by `test_every_regex_in_the_rules_file_compiles`. And its matching is exercised, which is more than the absent fixture would suggest: `test_no_combination_of_the_three_signals_can_raise_a_severity` in `tests/test_severity_governor.py` (the wider sweep, not the narrower `test_the_governor_never_escalates_over_the_whole_space` beside it) carries a source-map probe among its matching fixtures, asserts that the probe matches some rule, and asserts that no combination of signals raises a severity. So the deletion reddens that sweep too, on the matching assertion rather than on any severity it produces.

**What nothing pins is the cap itself.** Raise the rule's target from `low` to `high`, or to `critical`, and the whole suite stays green: the sweep still passes, because a cap that never lowers anything cannot escalate anything either. So the rule that exists to cap a finding can be neutered into a rule that does nothing, and no test in this repository notices. Set beside the others the contrast is sharp: changing `csp-weakness`'s target reddens its museum test, the inventory assertion, the committed walkthrough artifacts and the fixture contracts, and changing `cors-wildcard`'s reddens its own test and the write-path tests as well.

It belongs in this appendix rather than in an errata note, because it is the same family as the withheld verifier in chapter 06's step on the verifier's asymmetric raise and the fail-open in its step on the gate check: a published thing whose demonstration is absent. A reader copying this rules file should copy the fixture discipline with it, and should treat a rule with no fixture as a rule whose value nobody is holding.

## What the museum tests assert, and what that is worth

Each of the five rules was deleted in turn from a copy of the rules file, and each deletion reddened the test naming that rule while the rest of the file stayed green. That is what makes them regression tests for particular rules rather than a suite that would pass on any governor that lowered severities at all. Deletion alone would pin only that a rule exists, so the values are held too: the caps assert the severity that comes out, and the false-positive rules assert the flag and the reason as well as the floor.

The scope worth carrying away is the one the three narrow entries above make explicit. A test named for a claim usually asserts something smaller than the claim, and the gap is where a reader stops being protected. The policy-advice and index-shell tests say so outright, one naming the tier it does not drive and the other the exclusion list it does not exercise. The wildcard test makes the same point from the other side, asserting the rule that fired and the evidence grade because at thin evidence deleting the rule lands the finding on that same severity through `evidence-ceiling`, and a final-severity assertion could not tell a present rule from an absent one. Read the body of a test before citing it, including the ones this appendix cites.

## Failures of the rules themselves

The entries above are findings a human threw away. These five are not findings at all; they are the rules that were supposed to catch a bad finding, quietly failing to, surfaced by a run against the same kind of public lab target the rest of this book measures against.

## The attachment that unredacted the finding

The finding carried a redacted summary, and its author believed that was what it stored. What made it look real is that the summary was redacted: the author had done the careful thing. What was true is that a convenience parameter on the reporting call copied the underlying probe's raw request and response (bearer tokens, password hashes) into the same record, beneath the summary, where the report renderer and every downstream consumer could read them. The finding was redacted the way a postcard is sealed.

The rule is that redaction applies at every copy a record carries, not at the field the author is looking at; an attach path that can write evidence must run the same masking as the field it bypasses. **This is a genericized historical pattern. Nothing in this repository enforces it.**

## The kill-switch that half-killed

An environment flag promised memory disabled. What made it look real is that the memory engine genuinely refused to construct under it, and write paths through that engine genuinely went quiet. What was true is that two read endpoints assembled prior-scan history from the database directly (never asking the flag) and one direct record endpoint fell back to an older writer that predated the flag entirely. A study arm built on that switch measured memory off while receiving the full recall of every previous scan.

The rule is chapter 06's runtime contract taken literally: a capability freeze is every path or it is fiction, and a switch inventory has to hold read lanes and fallbacks, not just the engine constructor. **This is a genericized historical pattern. Nothing in this repository enforces it.**

## Two correct rules, one wrong severity

<!-- num-ok: one field is a spelled quantity counting a code artifact: how far the structured proof sat from the field the grader actually read, in this genericized incident rather than in a shape core/ carries -->
The finding was a proven unauthenticated admin takeover, submitted with verbatim quoted proof in the canonical structured shape. What made the stored severity look real is that every rule that touched it worked as written: the hygiene rule had stripped the secrets, the grader graded what it was shown, the downward governor capped what the grade allowed, and the asymmetric raise rule correctly refused to repair a grade it must not overrule. What was true is that the store's mirror accepted only string evidence, so the structured proof never reached the grader at all (it sat one field away, serialized and ignored) and a verified critical shipped labeled medium. Three separate configurations reproduced it. This is the byte-identity argument of chapter 02 happening in production: every component byte-correct, the composition wrong.

The rule is to grade content wherever the record carries it, to canonicalize at the single write path rather than trusting authors to know the blessed field, and to treat "the safety rule made the evidence look thin" as a composition test case in its own right. **This is a genericized historical pattern. Nothing in this repository enforces it.**

## Dedup ate the correction

An author noticed the under-labeled finding above and resubmitted it with the proof attached. What made the outcome look real is that deduplication did exactly its job: same type, same URL, same title; duplicate, absorbed, existing record returned. What was true is that the resubmission was not a duplicate claim but a correction carrying strictly better evidence, and the absorption meant no governance pass could ever see it. The audit trail recorded a duplicate skipped, not a repair refused: the most dangerous kind of log line, the one that reads as health.

The rule is that a write path which collapses duplicates must distinguish a repeated claim from the same claim now carrying proof, and must let the second kind through to grading. **This is a genericized historical pattern. Nothing in this repository enforces it.**

## Coverage that could not see the work

The coverage metric credited catalogued tool runs against exact URL strings. The metric looked conservative because it had been built after an earlier incident to stop a scan from claiming coverage it had not earned. What was true is that it also could not see the hand-driven probe channel that produced every confirmed exploit in the study, and its denominator contained miner-reconstructed URLs with a malformed origin that nothing could ever test. The same metric family had once reported near-total coverage on a scan that ran no active tool; here it reported near-zero on scans that were dumping tables with bounded proof. Both directions, one root: the denominator was not the work.

The rule is chapter 05's accounting demand pointed at the metric itself: coverage must count the mechanism that produces results, and a denominator entry nothing can test is a defect in the denominator. **This is a genericized historical pattern. Nothing in this repository enforces it.**
