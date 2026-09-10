# Rendered handbook

This is a generated, reader-facing copy of the chapters under `handbook/`.
The `[[stats:...]]` macros have been resolved to their values in `data/stats.json`, the `[[code:...]]` macros have become relative links into `core/`, and the inline num-ok annotations have been collected into a footer on each chapter.

Do not edit these files by hand. They are produced by `scripts/render.py` and held byte-identical to a fresh render by `tests/test_rendered_is_in_sync.py`. To regenerate them after a change to a chapter or to `data/stats.json`, run:

```
python3 scripts/render.py
```

The source of truth is `handbook/`, which keeps the macros and stays under the citation gates. Read the source there if you want to see what a number is cited as; read here if you want to see the number.

`scripts/prose_check.sh` is run against `handbook/` and not against this tree, and that is deliberate rather than an omission. Its rules are rules about authoring, and this tree is generated: the punctuation it forbids reaches these files from a `data/stats.json` string reproduced verbatim, not from a sentence anybody wrote here, so gating this copy would make the rule enforceable only by editing the data it is quoting.

## Chapters

- [00-thesis.md](00-thesis.md)
- [01-fixed-procedure.md](01-fixed-procedure.md)
- [02-narrow-waist.md](02-narrow-waist.md)
- [03-asymmetric-trust.md](03-asymmetric-trust.md)
- [04-scope-as-code.md](04-scope-as-code.md)
- [05-honest-reporting.md](05-honest-reporting.md)
- [06-build-your-own.md](06-build-your-own.md)
- [07-harness-lab.md](07-harness-lab.md)
- [appendix-a-orchestrator-contract.md](appendix-a-orchestrator-contract.md)
- [appendix-b-schemas.md](appendix-b-schemas.md)
- [appendix-c-failure-museum.md](appendix-c-failure-museum.md)
- [appendix-d-verifier-study.md](appendix-d-verifier-study.md)
- [appendix-e-factorial-study.md](appendix-e-factorial-study.md)
