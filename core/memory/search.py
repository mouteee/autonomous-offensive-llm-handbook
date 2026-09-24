"""Hybrid retrieval: a keyword lane, an optional vector lane, one merge rule.

The keyword lane is SQLite FTS5's BM25 ranking. BM25 comes back negative
(lower is better), so the lane negates it and then min-max normalizes over the
candidate pool; when every candidate scores the same, every normalized score is
1.0, because a pool with no internal ordering information should not invent
one. The vector lane is brute-force cosine similarity over stored float lists,
fed by an injected embedding function. The merge is a fixed weighted sum,
vector 0.7 and keyword 0.3 by default, and when no embedder is configured or
the embedder raises, the weights become 0 and 1: keyword-only fallback, flagged
in the result rather than performed silently.

One fidelity note the lesson repeats: in the originating implementation no
embedder is wired on any production path, so its hybrid engine always runs the
keyword-only branch. Both lanes exist and are tested there; one operates. This
module implements both and keeps that distinction explicit, the same
implementation-versus-configuration separation the evidence register keeps for
studies.

Query sanitization strips FTS5 operator characters to spaces. Stripping, not
escaping: quoted phrases and NEAR queries are impossible by design, and each
remaining word joins the implicit AND. Teaching simplifications: synchronous
embedder, no embedding cache, plain JSON float lists instead of packed blobs.
"""

import json
import math
import sqlite3
from dataclasses import dataclass

from .store import MemoryStoreError


VECTOR_WEIGHT = 0.7
KEYWORD_WEIGHT = 0.3
POOL_FACTOR = 3  # each lane over-fetches limit * POOL_FACTOR candidates

_FTS_SPECIALS = "'\"*(){}[]^~:-+"

SEARCH_FILTER_ALLOWLIST = ("profile_hash", "tool_name", "engagement")


@dataclass(frozen=True)
class SearchResult:
    record_id: str
    tier: str
    content: str
    keyword_score: float
    vector_score: float
    score: float
    metadata: dict
    # The stored row's own clock fields, carried so a consumer can honor the
    # record's expiry instead of silently restarting it at retrieval time.
    created_at: float = 0.0
    expires_at: float = 0.0


def sanitize_query(query):
    """Strip FTS5 operator characters, lowercase, and collapse the words.

    Lowercasing is load-bearing, not cosmetic: FTS5's AND, OR and NOT are
    case-sensitive bare-word operators, so a hostile or accidental uppercase
    token would otherwise change the query's meaning instead of being one more
    search word. The tokenizer folds case on the content side, so matching is
    unaffected.
    """
    cleaned = "".join(" " if c in _FTS_SPECIALS else c for c in (query or ""))
    return " ".join(cleaned.split()).lower()


def cosine_similarity(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def _normalize(scores):
    """Min-max to [0, 1]; a degenerate pool maps every member to 1.0."""
    if not scores:
        return {}
    low, high = min(scores.values()), max(scores.values())
    if high == low:
        return {k: 1.0 for k in scores}
    return {k: (v - low) / (high - low) for k, v in scores.items()}


class HybridSearch:
    """Search over a MemoryStore; see the module docstring for the lanes."""

    def __init__(self, store, embedder=None, *, vector_weight=VECTOR_WEIGHT,
                 keyword_weight=KEYWORD_WEIGHT):
        self._store = store
        self._embedder = embedder
        self.vector_weight = float(vector_weight)
        self.keyword_weight = float(keyword_weight)

    def _keyword_lane(self, query, limit, filters):
        text = sanitize_query(query)
        if not text:
            return {}
        clauses, params = ["memory_fts MATCH ?"], [text]
        for key, value in sorted(filters.items()):
            if key not in SEARCH_FILTER_ALLOWLIST:
                raise MemoryStoreError(
                    f"search filter {key!r} is not in the allowlist "
                    f"{SEARCH_FILTER_ALLOWLIST}")
            clauses.append(f"mr.{key} = ?")
            params.append(value)
        params.append(limit * POOL_FACTOR)
        try:
            rows = self._store.connection.execute(
                "SELECT mr.record_id, bm25(memory_fts) AS s FROM memory_fts"
                " JOIN memory_records mr ON memory_fts.rowid = mr.rowid"
                f" WHERE {' AND '.join(clauses)} AND mr.refuted = 0"
                " ORDER BY s LIMIT ?", params)
        except sqlite3.OperationalError as exc:
            # An empty lane and a failed lane are different facts; the trace
            # carries the difference instead of letting silence look clean.
            self._keyword_lane_error = f"{type(exc).__name__}: {exc}"
            return {}
        self._keyword_lane_error = None
        return {row["record_id"]: -row["s"] for row in rows}

    def _vector_lane(self, query_vector, limit, filters):
        rows = self._store.connection.execute(
            "SELECT record_id, embedding, profile_hash, tool_name, engagement"
            " FROM memory_records WHERE embedding IS NOT NULL AND refuted = 0")
        scores = {}
        for row in rows:
            if any(row[key] != value for key, value in filters.items()):
                continue
            similarity = cosine_similarity(query_vector,
                                           json.loads(row["embedding"]))
            if similarity > 0:
                scores[row["record_id"]] = similarity
        top = sorted(scores.items(), key=lambda kv: -kv[1])[:limit * POOL_FACTOR]
        return dict(top)

    def search(self, query, *, limit=10, **filters):
        """Both lanes, normalized and merged; returns results and a trace.

        The trace records each lane's raw and normalized scores plus the
        weights actually used, so a reader can recompute any final score by
        hand. `fallback` is true when the vector lane did not run.
        """
        for key in filters:
            if key not in SEARCH_FILTER_ALLOWLIST:
                raise MemoryStoreError(
                    f"search filter {key!r} is not in the allowlist "
                    f"{SEARCH_FILTER_ALLOWLIST}")
        # A fresh search starts with a clean lane-error flag; the keyword lane
        # sets it when its query fails, and a stale flag from an earlier search
        # must not survive into this trace.
        self._keyword_lane_error = None
        keyword_raw = self._keyword_lane(query, limit, filters)
        vector_raw = {}
        fallback_reason = None
        if self._embedder is None:
            fallback_reason = "no embedder configured"
        else:
            try:
                vector_raw = self._vector_lane(self._embedder(query), limit,
                                               filters)
            except Exception as exc:
                fallback_reason = f"embedder raised {type(exc).__name__}"
        vector_weight, keyword_weight = self.vector_weight, self.keyword_weight
        if fallback_reason is not None:
            vector_weight, keyword_weight = 0.0, 1.0
        keyword_norm = _normalize(keyword_raw)
        vector_norm = _normalize(vector_raw)
        merged = {}
        for record_id in set(keyword_norm) | set(vector_norm):
            merged[record_id] = (vector_weight * vector_norm.get(record_id, 0.0)
                                 + keyword_weight * keyword_norm.get(record_id, 0.0))
        ranked = sorted(merged.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
        results = []
        for record_id, score in ranked:
            row = self._store.connection.execute(
                "SELECT * FROM memory_records WHERE record_id = ?",
                (record_id,)).fetchone()
            results.append(SearchResult(
                record_id=record_id, tier=row["tier"], content=row["content"],
                keyword_score=round(keyword_norm.get(record_id, 0.0), 6),
                vector_score=round(vector_norm.get(record_id, 0.0), 6),
                score=round(score, 6), metadata=json.loads(row["metadata"]),
                created_at=row["created_at"], expires_at=row["expires_at"]))
        trace = {
            "query": query,
            "sanitized": sanitize_query(query),
            "keyword_lane_error": getattr(self, "_keyword_lane_error", None),
            "fallback": fallback_reason is not None,
            "fallback_reason": fallback_reason,
            "weights": {"vector": vector_weight, "keyword": keyword_weight},
            "keyword_raw": {k: round(v, 6) for k, v in sorted(keyword_raw.items())},
            "keyword_normalized": {k: round(v, 6) for k, v in sorted(keyword_norm.items())},
            "vector_normalized": {k: round(v, 6) for k, v in sorted(vector_norm.items())},
        }
        return results, trace
