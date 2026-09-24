# Lesson 8: from a tool result to a reviewed finding

Everything before this lesson produced records; this lesson is where records become claims, and claims meet resistance. The pipeline runs capture, then proposal, then deterministic grading, then an isolated verifier whose verdict the host validates, then consolidation, and it ends where it must: at a human decision nothing in the pipeline can make. Three points in this design are deliberately stricter than the originating implementation, and each one is labeled where it is built, because teaching a corrected control while implying the original had it would be exactly the kind of quiet claim this book exists to refuse.

## Build this

`core/run/verify.py`: the evidence-grade function and its severity ceilings, the isolated verifier packet, host-validated verdicts with every mistake class demonstrated, and the digit-stripped consolidation signature with its recorded collisions reproduced on purpose. Plus the committed demo artifact carrying one verdict of every kind.

## Start from here

[Lesson 7](07-context-assembly.md) reached on the core route; the code here depends only on [lesson 5](05-candidates-and-dispatch.md)'s dispatcher recording captures through the write boundary, with `tests/test_run_dispatch.py` green.

## Inputs and outputs

The pipeline consumes the run's own records (captures and findings from lesson 2's recorder) and produces three new record shapes. A governed finding:

```json
{"finding_id": "9c41...", "original_severity": "high", "severity": "high",
 "evidence_grade": "strong", "ceiling_enforced": false,
 "false_positive": false, "status": "governed", "verdicts": []}
```

A verifier packet, which is everything the verifier is allowed to see:

```json
{"finding": {"finding_id": "9c41...", "kind": "unauth_data_leak",
             "title": "Wildcard origin", "severity": "high",
             "quote": "Access-Control-Allow-Origin: *"},
 "capture": {"capture_id": "60c4...", "status": 200, "body": "..."},
 "verdict_schema": {"verdict": ["accept", "reject", "needs_review",
                                "adjust_severity"]}}
```

And a verdict entry, applied or refused, always with a reason. The verdict vocabulary is closed: `accept`, `reject`, `needs_review`, `adjust_severity`, nothing else.

## Implement it

1. **Grade the evidence.** `[[code:run/verify.py:evidence_grade]]` answers `strong` when both sides of the exchange are recorded, `moderate` for one side or a long enough bare string, `thin` otherwise; the grade measures record completeness, not truth. `[[code:run/verify.py:apply_ceiling]]` caps what a grade may hold (thin evidence holds at most `medium`) and `[[code:run/verify.py:govern_finding]]` applies it monotonically. The deterministic policy layer never raises; that asymmetry is the same one the fixture lab's governor carries, and the completed verifier ablation in [appendix D](../appendix-d-verifier-study.md) measured what the verifier-plus-acceptance package changes about what ships; see [the evidence register](../appendix-f-evidence-register.md) for that study's exact status.

2. **Build the packet.** `[[code:run/verify.py:verifier_packet]]` assembles the finding, its own capture and the verdict schema, and refuses a capture that is not the finding's. Isolation is structural rather than promised: the verifier cannot read a foreign capture because no foreign capture is in front of it. The verifier sees exactly one finding and its own capture, and nothing else.

3. **Call the verifier.** `[[code:run/verify.py:run_verifier]]` wraps any provider callable, reuses the strict JSON parsing from lesson 4, and refuses replies with unknown fields. A provider error is a report, and a verdict that cannot be parsed changes nothing either.

4. **Validate the verdict in host code.** `[[code:run/verify.py:VerificationPipeline]]` applies what a verdict may do and refuses the rest. An unknown verdict changes nothing, and this is the first labeled correction: the originating implementation read any unrecognized verdict string as a confirmation, because confirmation was its untyped else-branch. Here the vocabulary is closed and a misspelled verdict is a recorded refusal.

5. **Apply the easy verdicts, and keep the mistakes visible.** `accept` keeps the severity. `reject` marks the finding false-positive with the verifier's reason, and nothing is deleted: a rejected finding stays visible with its evidence, so a human can overrule a wrong rejection. `needs_review` applies the skeptical default the originating implementation also carries: an unverified `high` or `critical` is capped to `medium`. Downward `adjust_severity` applies freely, which cuts both ways: a wrong downward adjustment applies freely and stays visible in the record, before beside after. Downward mistakes hide real vulnerabilities, and they get equal billing with invalid raises in the demo and the tests.

6. **Gate the raise.** A raise happens only against contained proof and within what the evidence grade allows. The proof quote must occur verbatim in the finding's own capture, checked by the host, byte for byte. This is the second labeled correction: the originating implementation checked only that a raise carried a non-empty quote at verdict time; quote length fed the next governance pass, and verbatim-ness lived in a prompt contract rather than in server code. And the raise ceiling here is deliberately stricter than the holding ceiling (`moderate` evidence may hold `critical` but may only be raised to `high`) a teaching policy the code names beside the originating single-table behavior. Exact-quote containment is still not exploitability proof; it is citation integrity, and the raise gate demands it as a floor, not as the whole argument.

7. **Consolidate without losing anything.** `[[code:run/verify.py:VerificationPipeline]]`'s `consolidate` implements the source-shaped signature exactly: finding kind, plus the title with digits stripped, whitespace collapsed, lowercased. A signature spanning two or more distinct hosts collapses into its highest-severity primary carrying `affected_hosts`. Findings with no resolvable host never group. The third labeled correction is what happens to the absorbed members: an absorbed finding keeps its evidence and gets its own status, `absorbed`, pointing at its primary, where the originating implementation set the absorbed members' false-positive flag, giving a column that means "not real" a second meaning, the hazard chapter 05 documents.

8. **Leave acceptance to a person.** Acceptance is a separate human decision; no verdict flips a finding to accepted. The recorder's review records from lesson 2 carry that decision, with the actor named.

## Run it

```bash
python3 -m pytest tests/test_run_verify.py -q
python3 -m core.run.demo_verify --out /tmp/verify-demo.json
diff -u data/course/verify-demo.json /tmp/verify-demo.json
```

The `diff` prints nothing; the committed artifact is byte-identical to a fresh run.

## Inspect it

[![The verdict path: a content-addressed capture, a quote-bound finding, deterministic governance, the isolated verifier packet, host validation of the reply against the closed vocabulary, and the four verdicts, with human acceptance kept a separate recorded decision.](../../docs/assets/course/verification-sequence.svg)](../../docs/assets/course/verification-sequence.svg)

Open `/tmp/verify-demo.json`. The `verdicts` list holds an entry per finding, and it reads as a tour of the mistake classes: an `accept` that keeps a strong finding at `high`; a `reject` whose reason admits it is a wrong call, kept visible; a wrong downward adjustment from `medium` to `low`, applied, with before and after in the entry; a `needs_review` capping an unverified `high` at `medium`; a refused raise where a `moderate` grade would not reach `critical`; and a proof-carried raise from `medium` to `high` whose quote you can find verbatim in the capture body. `host_refusals` carries the unknown verdict (`CONFIRMED` is not a verdict here) and the fabricated raise quote. `consolidation` shows the two recorded collisions reproduced deliberately: two byte-size titles (`3389-byte` against `1602-byte`) sharing one signature because the digits are exactly what the signature strips, and the `TLS 1.0 supported` and `TLS 1.2 supported` pair merging because the version is the digits. The [failure museum](../appendix-c-failure-museum.md) carries the recorded history behind both shapes; the fix direction (a URL component in the signature, or version-aware stripping) is stated here rather than silently taught, because the collision is the trade the source-shaped signature makes.

Also read the rejected finding's row in `pipeline.governed`: `status` is `rejected`, `false_positive` is true, and the quote and capture are still there. One absorbed row shows `status: absorbed` with `consolidated_into`, and `false_positive: false`, which is the point of the third correction.

## Break it

Three refusals at the host's validation points:

```bash
python3 - <<'PY'
from core.run.demo_verify import BODIES, build_policy
from core.run.dispatch import Dispatcher
from core.run.recorder import Recorder
from core.run.records import Finding, make_run
from core.run.verify import VerificationPipeline

policy = build_policy()
run = make_run(policy.snapshot(), {"world": "break-it"})
recorder = Recorder(run, policy)
dispatcher = Dispatcher(recorder, policy,
                        {"inspect_headers": lambda url: {
                            "status": 200,
                            "body": BODIES[("inspect_headers", url)]}})
capture_id = dispatcher.dispatch("inspect_headers",
                                 "https://lab.example/")["capture_id"]

fabricated = recorder.record("finding", {
    "run_id": run.run_id, "capture_id": capture_id,
    "kind": "unauth_data_leak", "title": "Invented", "severity": "critical",
    "quote": "ADMIN_TOKEN=deadbeef"})
print(fabricated)

real = recorder.record("finding", {
    "run_id": run.run_id, "capture_id": capture_id,
    "kind": "unauth_data_leak", "title": "Wildcard origin",
    "severity": "high", "quote": "Access-Control-Allow-Origin: *"})
pipeline = VerificationPipeline(recorder)
finding = Finding(**next(f for f in recorder.snapshot()["findings"]
                         if f["finding_id"] == real["finding_id"]))
pipeline.govern(finding)

print(pipeline.apply_verdict(finding.finding_id, {
    "parsed": True, "reply": {"verdict": "CONFIRMED", "reason": "trust me"}}))
print(pipeline.apply_verdict(finding.finding_id, {
    "parsed": True, "reply": {"verdict": "adjust_severity",
                              "severity": "critical",
                              "quote": "ADMIN_TOKEN=deadbeef",
                              "reason": "invented proof"}}))
PY
```

Expected output:

```text
{'recorded': False, 'reason': 'quote does not occur verbatim in the cited capture'}
{'finding_id': 'eac4e6b21a9fa30f04054531c8e6c7212ad66fa1695f539900d215d841ace846', 'applied': False, 'reason': "unknown verdict 'CONFIRMED'; a verdict is one of accept, reject, needs_review, adjust_severity"}
{'finding_id': 'eac4e6b21a9fa30f04054531c8e6c7212ad66fa1695f539900d215d841ace846', 'applied': False, 'reason': "the raise quote does not occur verbatim in the finding's own capture"}
```

(The finding identifiers are digests over deterministic inputs, so they reproduce exactly too; every byte above is exact.) The first refusal happens at the write boundary before the pipeline ever sees the claim. The second and third are the two labeled corrections doing their work: the confirmation-by-default is gone, and the raise proof is checked against the bytes.

## Check completion

- At the write boundary, a finding cites a capture this run holds, and its quote occurs verbatim in that capture, or it is refused with a recorded reason.
- The verifier sees exactly one finding and its own capture, and nothing else.
- An unknown verdict changes nothing, and a verdict that cannot be parsed changes nothing either; the originating implementation read any unrecognized verdict string as a confirmation, and this pipeline corrects that.
- A rejected finding stays visible with its evidence, so a human can overrule a wrong rejection. Likewise a wrong downward adjustment applies freely and stays visible in the record, before beside after.
- A raise happens only against contained proof and within what the evidence grade allows. The deterministic policy layer never raises, and the grade measures record completeness, not truth.
- Two findings that differ only in their digits share a signature; an absorbed finding keeps its evidence and gets its own status; the false-positive flag keeps one meaning. Findings with no resolvable host never group.
- Acceptance is a separate human decision; no verdict flips a finding to accepted.
- The pipeline governs only findings this run's recorder holds.

Each sentence is a named test in `tests/test_run_verify.py`; completion is that suite green plus the byte-identical `diff` above.

## Continue

[Lesson 9](09-stop-recover-finish.md) closes the run: budgets, cancellation, recovery from an interrupted write, and a terminal record that accounts for everything, including the verdicts this lesson produced. Deliberate simplification to carry forward: this pipeline keeps its verdict ledger beside the recorder rather than inside it, and refused verdicts flow through the write boundary's refusal door; folding admitted verdicts into the recorder's own vocabulary is an integration the course revisits when the full application is assembled.
