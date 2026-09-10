- Before run 4: the first `FULL` run surfaced a residual redaction gap at the pinned revision -- the
  redaction pass masks known-sensitive field shapes (tokens, auth headers, password fields, API
  keys) but not bare hex-looking hashes, so a probe auto-attach carried lab-only hash values into
  stored evidence despite the curated evidence itself being correctly redacted. DECISION: no
  mid-study code change (the revision stays pinned per the pre-registration; the gap is
  arm-symmetric). Fixed after the study, with every affected row scrubbed from every run's stored
  data afterward. Orchestrators flag the gap per run via a redaction-compliance note.
- Both arms exhibit one new pipeline stage, unrelated to the verifier, uniformly; no arm asymmetry.
- One `NOVERIFY` run: a probe briefly held an unbounded extraction before the orchestrator re-probed
  with a row limit in place; the stored finding used the bounded probe only.
- One `NOVERIFY` run: a stale scratchpad file from a prior run caused one write to land on an
  unrelated, already-completed scan (verified as touching no real data, corrected immediately) --
  a recurring shared-scratchpad hazard, third occurrence across studies; per-run scratchpad
  isolation remains a queued infrastructure fix. Not an endpoint-affecting event.
- Observation, not a deviation, from the same `NOVERIFY` run: the deterministic write-time governor
  auto-marked a REAL finding false-positive (a null-byte bypass on an upload path, 200 plus file
  content served back) via a block-response rule keying on an embedded negative-control response --
  and with the verifier off there is no repair path. The repair mechanism this book's chapter 03
  argues for is now observed doing damage in both directions: shipping a false positive when absent,
  and losing a real finding to a misfire when absent.
- After run 11 (the sixth `FULL` run): SAFETY DEVIATION, an arm-symmetric prompt amendment. That
  run's proof-of-concept for a filter-style injection (a not-equal filter used as the injection
  payload against a bulk-update endpoint) mass-updated every row in a table without per-action
  confirmation (an earlier `NOVERIFY` run had performed the same class of write). Both
  self-reported. Blast radius confined to that run's own disposable container, force-recreated
  before every run, so seed data was pristine again for the next one. From run 12 onward, both arm
  prompts gained one identical sentence prohibiting any multi-record-capable injection write
  (single-record proofs only). Prompt identity between arms is preserved; the amendment is disclosed
  as a mid-study change affecting runs 12 through 20 of both arms equally.
- One `NOVERIFY` run flagged a suspected (unconfirmed) external contact: a cloud-misconfiguration
  check ran for roughly forty seconds, with timing consistent with outbound calls to public
  cloud-provider APIs using target-derived names. Flagged for verification from code and artifacts;
  if real, disclosed as the same class as the crawler's redirect-follow behavior (a benign,
  tool-internal, arm-symmetric metadata request). No mid-study change made on the strength of the
  suspicion alone.
- RESOLVED, after the study, from the code itself: the suspicion above is downgraded. Every
  provider-specific check is reference-gated -- a bucket or account name has to appear in the
  target's own pages or scripts before any provider-specific HTTP call fires, and the lab target
  references none, so none fired. The one unconditional external touch is a single DNS lookup for
  the target's own name, via the system resolver, in one of the checks. No provider HTTP contact
  occurred in any run. An improvement to gate that lookup for non-public targets is queued.
