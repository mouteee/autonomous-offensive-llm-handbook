"""The retrieval lesson's demonstration: ingest, search, lanes, refute, delete.

Everything is driven from the committed fictional corpus, with fixed timestamps
and a deterministic fake embedder, so the emitted artifact is byte-stable.

Run it from the repository root:

    python3 -m core.memory.demo_memory --out /tmp/memory-demo.json

The committed copy is data/course/memory-demo.json; a sync test re-derives it.
"""

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from .lanes import (host_history, learned_tactics, profile_priors,
                    render_negative_evidence, wilson_lower_bound)
from .records import MemoryRecord
from .search import HybridSearch
from .store import MemoryStore


CORPUS = Path(__file__).resolve().parents[2] / "data" / "course" / "memory-corpus.json"
PROFILE = "python:postgresql:waf_present:generic_waf:rest:flask"
EMBEDDING_DIM = 8
T0 = 1_700_000_000.0  # fixed ingest timestamp for byte-stable artifacts


def fake_embedding(text):
    """A deterministic stand-in for an embedding model.

    Each word lands in one of a few dimensions by hash and the vector counts
    words per dimension. It preserves nothing about meaning beyond shared
    vocabulary, which is exactly enough to demonstrate the vector lane's
    plumbing without a model dependency.
    """
    vector = [0.0] * EMBEDDING_DIM
    for token in text.lower().split():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        vector[digest[0] % EMBEDDING_DIM] += 1.0
    return vector


def build_store(corpus):
    store = MemoryStore(":memory:")
    for i, spec in enumerate(corpus["records"]):
        record = MemoryRecord(created_at=T0 + i, **spec)
        store.add(record, embedding=fake_embedding(record.content))
    for i, tactic in enumerate(corpus["tactics"]):
        keys = dict(profile_hash=tactic["profile_hash"], tool=tactic["tool"],
                    endpoint=tactic["endpoint"], param=tactic["param"],
                    technique=tactic["technique"])
        store.record_success(engagement=tactic["engagement"],
                             target_domain=tactic["target_domain"],
                             proof=tactic["proof"], content=tactic["content"],
                             now=T0 + 100 + i, **keys)
        for _ in range(tactic["extra_successes"]):
            store.record_success(engagement=tactic["engagement"],
                                 target_domain=tactic["target_domain"],
                                 now=T0 + 100 + i, **keys)
        for _ in range(tactic["failures"]):
            store.record_failure(**keys)
    for run in corpus["tool_runs"]:
        for i in range(run["executions"]):
            store.record_tool_run(tool=run["tool"],
                                  profile_hash=run["profile_hash"],
                                  hit=i < run["hits"])
    for finding in corpus["findings"]:
        store.record_finding(now=T0, **finding)
    return store


def run_demo():
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    store = build_store(corpus)

    # Dedup: replay the first tactic's success and show the row count holding.
    first = corpus["tactics"][0]
    before = len(store.fetch(tier="longterm"))
    store.record_success(profile_hash=first["profile_hash"], tool=first["tool"],
                         endpoint=first["endpoint"], param=first["param"],
                         technique=first["technique"],
                         engagement=first["engagement"],
                         target_domain=first["target_domain"], now=T0 + 500)
    dedup = {"longterm_rows_before": before,
             "longterm_rows_after": len(store.fetch(tier="longterm"))}

    query = "sql injection on the items api"
    hybrid_results, hybrid_trace = HybridSearch(
        store, embedder=fake_embedding).search(query, limit=5)
    keyword_results, keyword_trace = HybridSearch(
        store, embedder=None).search(query, limit=5)

    priors = profile_priors(store, PROFILE)
    history = host_history(store, "engagement-a", exclude_run_id="run-9")
    tactics_before = learned_tactics(store, PROFILE)

    refuted = store.record_refuted(
        profile_hash=PROFILE, tool="test_idor", endpoint="/api/9/orders",
        param="order_id", technique=None)
    tactics_after_refute = learned_tactics(store, PROFILE)

    backup_row = store.fetch(tool_name="fetch_url", tier="longterm")[0]
    deleted = store.delete(backup_row["record_id"])
    tactics_after_delete = learned_tactics(store, PROFILE)

    return {
        "schema": "memory-lesson-demo/v1",
        "profile": PROFILE,
        "dedup": dedup,
        "hybrid": {"results": [asdict(r) for r in hybrid_results],
                   "trace": hybrid_trace},
        "keyword_only": {"results": [asdict(r) for r in keyword_results],
                         "trace": keyword_trace},
        "lanes": {
            "profile_priors": priors,
            "negative_evidence": render_negative_evidence(priors),
            "host_history": history,
            "learned_tactics": tactics_before,
        },
        "wilson_example": {
            "one_of_one": round(wilson_lower_bound(1, 1), 6),
            "twelve_of_twenty_three": round(wilson_lower_bound(12, 23), 6),
        },
        "refutation": {"applied": refuted,
                       "tactics_after": tactics_after_refute},
        "deletion": {"applied": deleted,
                     "tactics_after": tactics_after_delete},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(run_demo(), indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
