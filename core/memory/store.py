"""The SQLite memory store: one records table, one full-text index, three
writers with different powers.

`record_success` is the only writer that creates a long-term tactic, and it
dedupes on the tactic signature: a repeat lands on the existing row as an
attempt/success increment and an anonymized target append, not a duplicate.
`record_failure` updates counters on an existing tactic and creates nothing.
`record_refuted` is the correction path, and it is an in-place flag rather than
a tombstone or a supersede chain: the row stays, marked refuted, its evidence
grade forced back to hypothesis and its confidence reduced; readers exclude it.
Deletion is a separate, harder operation that removes the row outright. The
lesson demonstrates both and says which one the originating implementation has.

Full-text search rides SQLite's FTS5 with an external-content table kept in
sync by triggers, the same pattern the originating implementation uses; the
store raises at construction when the interpreter's SQLite lacks FTS5, because
a keyword lane that silently indexes nothing is worse than a loud missing
dependency. Teaching simplifications: synchronous API, a single database file, no pruning
strategies or migration machinery.
"""

import json
import sqlite3
import time

from .records import (MEMORY_SCHEMA_VERSION, TIERS, MemoryRecord,
                      anonymize_target, new_tactic_metadata, normalize_endpoint,
                      tactic_signature)


class MemoryStoreError(RuntimeError):
    """The store could not be built or a write violated its contract."""


_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS memory_records (
    record_id     TEXT UNIQUE NOT NULL,
    tier          TEXT NOT NULL CHECK (tier IN {TIERS!r}),
    record_type   TEXT NOT NULL,
    content       TEXT NOT NULL,
    metadata      TEXT NOT NULL DEFAULT '{{}}',
    signature     TEXT,
    confidence    REAL NOT NULL DEFAULT 1.0,
    profile_hash  TEXT NOT NULL DEFAULT '',
    engagement    TEXT NOT NULL DEFAULT '',
    tool_name     TEXT NOT NULL DEFAULT '',
    url_pattern   TEXT NOT NULL DEFAULT '',
    run_id        TEXT NOT NULL DEFAULT '',
    source        TEXT NOT NULL DEFAULT '',
    refuted       INTEGER NOT NULL DEFAULT 0,
    embedding     TEXT,
    created_at    REAL NOT NULL,
    first_seen    REAL NOT NULL DEFAULT 0,
    last_seen     REAL NOT NULL DEFAULT 0,
    expires_at    REAL NOT NULL DEFAULT 0,
    schema_version TEXT NOT NULL DEFAULT '{MEMORY_SCHEMA_VERSION}'
);
CREATE INDEX IF NOT EXISTS idx_memory_tier ON memory_records(tier);
CREATE INDEX IF NOT EXISTS idx_memory_signature ON memory_records(signature);
CREATE INDEX IF NOT EXISTS idx_memory_profile ON memory_records(profile_hash);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    content, record_type, tool_name, url_pattern,
    content='memory_records', content_rowid='rowid',
    tokenize='porter unicode61');

CREATE TRIGGER IF NOT EXISTS memory_ai AFTER INSERT ON memory_records BEGIN
    INSERT INTO memory_fts(rowid, content, record_type, tool_name, url_pattern)
    VALUES (new.rowid, new.content, new.record_type, new.tool_name, new.url_pattern);
END;
CREATE TRIGGER IF NOT EXISTS memory_ad AFTER DELETE ON memory_records BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, content, record_type, tool_name, url_pattern)
    VALUES ('delete', old.rowid, old.content, old.record_type, old.tool_name, old.url_pattern);
END;
CREATE TRIGGER IF NOT EXISTS memory_au AFTER UPDATE ON memory_records BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, content, record_type, tool_name, url_pattern)
    VALUES ('delete', old.rowid, old.content, old.record_type, old.tool_name, old.url_pattern);
    INSERT INTO memory_fts(rowid, content, record_type, tool_name, url_pattern)
    VALUES (new.rowid, new.content, new.record_type, new.tool_name, new.url_pattern);
END;

CREATE TABLE IF NOT EXISTS tool_stats (
    tool_name     TEXT NOT NULL,
    profile_hash  TEXT NOT NULL DEFAULT '__global__',
    executions    INTEGER NOT NULL DEFAULT 0,
    hits          INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (tool_name, profile_hash)
);

CREATE TABLE IF NOT EXISTS findings (
    finding_id    TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL,
    engagement    TEXT NOT NULL,
    severity      TEXT NOT NULL,
    title         TEXT NOT NULL,
    url           TEXT NOT NULL,
    type          TEXT NOT NULL,
    false_positive INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL
);
"""

# The scope keys a read may filter on. Key names are interpolated into SQL only
# after membership here; values are always parameterized.
FILTER_ALLOWLIST = ("profile_hash", "tool_name", "engagement", "tier",
                    "record_type", "signature")


def _fts5_available():
    probe = sqlite3.connect(":memory:")
    try:
        probe.execute("CREATE VIRTUAL TABLE _p USING fts5(c)")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        probe.close()


class MemoryStore:
    """The single writer for every memory table."""

    def __init__(self, path=":memory:"):
        if not _fts5_available():
            raise MemoryStoreError(
                "this Python's sqlite3 lacks the FTS5 extension; the keyword "
                "search lane depends on it, so the store refuses to start "
                "rather than index nothing")
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    # Generic records ----------------------------------------------------------

    def add(self, record, embedding=None):
        """Store one validated record; returns its record_id."""
        if not isinstance(record, MemoryRecord):
            raise MemoryStoreError("add() takes a MemoryRecord")
        self._conn.execute(
            "INSERT INTO memory_records (record_id, tier, record_type, content,"
            " metadata, signature, confidence, profile_hash, engagement,"
            " tool_name, url_pattern, run_id, source, refuted, embedding,"
            " created_at, first_seen, last_seen, expires_at, schema_version)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (record.record_id, record.tier, record.record_type, record.content,
             json.dumps(record.metadata, sort_keys=True),
             record.metadata.get("signature"), record.confidence,
             record.profile_hash, record.engagement, record.tool_name,
             record.url_pattern, record.run_id, record.source,
             1 if record.metadata.get("refuted") else 0,
             json.dumps(embedding) if embedding is not None else None,
             record.created_at, record.first_seen or record.created_at,
             record.last_seen or record.created_at, record.expires_at,
             record.schema_version))
        self._conn.commit()
        return record.record_id

    def has(self, record_id):
        """Whether a record with this id is already stored, refuted or not."""
        row = self._conn.execute(
            "SELECT 1 FROM memory_records WHERE record_id = ?",
            (record_id,)).fetchone()
        return row is not None

    def fetch(self, include_refuted=False, **filters):
        """Scope-filtered read; unknown filter keys are refused loudly."""
        clauses, params = [], []
        for key, value in sorted(filters.items()):
            if key not in FILTER_ALLOWLIST:
                raise MemoryStoreError(
                    f"filter {key!r} is not in the scope-key allowlist "
                    f"{FILTER_ALLOWLIST}")
            clauses.append(f"{key} = ?")
            params.append(value)
        if not include_refuted:
            clauses.append("refuted = 0")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM memory_records{where} ORDER BY rowid", params)
        return [dict(row) for row in rows]

    def get_by_signature(self, signature):
        row = self._conn.execute(
            "SELECT * FROM memory_records WHERE signature = ?",
            (signature,)).fetchone()
        return dict(row) if row else None

    def delete(self, record_id):
        """Hard delete: the row is gone, and the FTS index row with it."""
        cur = self._conn.execute(
            "DELETE FROM memory_records WHERE record_id = ?", (record_id,))
        self._conn.commit()
        return cur.rowcount == 1

    # Tactic writers -----------------------------------------------------------

    def record_success(self, *, profile_hash, tool, endpoint, param=None,
                       technique=None, engagement="", target_domain=None,
                       proof=None, content=None, now=None):
        """Create a long-term tactic, or fold a repeat into the existing row.

        The evidence grade only moves up here: a repeat carrying proof upgrades
        a hypothesis row to proven; a repeat without proof leaves a proven row
        proven. Target domains are stored anonymized.
        """
        now = now if now is not None else time.time()
        signature = tactic_signature(profile_hash, tool, endpoint, param, technique)
        existing = self.get_by_signature(signature)
        if existing and existing["refuted"]:
            # Refutation is an explicit correction; a later success does not
            # quietly overwrite it. The write is declined loudly so the caller
            # knows the record still stands refuted, instead of handing back a
            # record id for a row every default read path excludes.
            raise MemoryStoreError(
                "tactic is refuted; a new success does not silently "
                "rehabilitate it -- record a fresh tactic or lift the "
                "refutation explicitly")
        if existing:
            meta = json.loads(existing["metadata"])
            meta["total_attempts"] += 1
            meta["total_successes"] += 1
            meta["success_rate"] = round(
                meta["total_successes"] / meta["total_attempts"], 6)
            if proof:
                meta["evidence_grade"] = "proven"
                meta.setdefault("proof", str(proof)[:500])
            if target_domain:
                token = anonymize_target(target_domain)
                if token not in meta["targets_seen"]:
                    meta["targets_seen"].append(token)
            self._conn.execute(
                "UPDATE memory_records SET metadata = ?, confidence = confidence + 1,"
                " last_seen = ? WHERE signature = ?",
                (json.dumps(meta, sort_keys=True), now, signature))
            self._conn.commit()
            return existing["record_id"]
        meta = new_tactic_metadata(signature=signature, param=param,
                                   technique=technique, proof=proof,
                                   target_domain=target_domain)
        record = MemoryRecord(
            record_id=f"tactic-{signature[:12]}",
            tier="longterm", record_type="tactic",
            content=content or f"{tool} on {normalize_endpoint(endpoint)}"
                               + (f" via {technique}" if technique else ""),
            metadata=meta, source="record_success",
            profile_hash=profile_hash, engagement=engagement,
            tool_name=tool, url_pattern=normalize_endpoint(endpoint),
            created_at=now, first_seen=now, last_seen=now)
        return self.add(record)

    def record_failure(self, *, profile_hash, tool, endpoint, param=None,
                       technique=None):
        """Bump the attempt counter on an existing tactic; creates nothing."""
        signature = tactic_signature(profile_hash, tool, endpoint, param, technique)
        existing = self.get_by_signature(signature)
        if not existing:
            return False
        meta = json.loads(existing["metadata"])
        meta["total_attempts"] += 1
        meta["success_rate"] = round(
            meta["total_successes"] / meta["total_attempts"], 6)
        self._conn.execute(
            "UPDATE memory_records SET metadata = ? WHERE signature = ?",
            (json.dumps(meta, sort_keys=True), signature))
        self._conn.commit()
        return True

    def record_refuted(self, *, profile_hash, tool, endpoint, param=None,
                       technique=None):
        """Mark a tactic refuted in place: flag set, grade back to hypothesis,
        confidence reduced. The row remains readable with include_refuted."""
        signature = tactic_signature(profile_hash, tool, endpoint, param, technique)
        existing = self.get_by_signature(signature)
        if not existing:
            return False
        meta = json.loads(existing["metadata"])
        meta["refuted"] = True
        meta["evidence_grade"] = "hypothesis"
        self._conn.execute(
            "UPDATE memory_records SET metadata = ?, refuted = 1,"
            " confidence = MAX(0, confidence - 2) WHERE signature = ?",
            (json.dumps(meta, sort_keys=True), signature))
        self._conn.commit()
        return True

    # Structured-lane inputs ---------------------------------------------------

    def record_tool_run(self, *, tool, profile_hash, hit):
        self._conn.execute(
            "INSERT INTO tool_stats (tool_name, profile_hash, executions, hits)"
            " VALUES (?,?,1,?) ON CONFLICT(tool_name, profile_hash) DO UPDATE"
            " SET executions = executions + 1, hits = hits + ?",
            (tool, profile_hash, 1 if hit else 0, 1 if hit else 0))
        self._conn.commit()

    def record_finding(self, *, finding_id, run_id, engagement, severity,
                       title, url, type, false_positive=False, now=None):
        self._conn.execute(
            "INSERT OR REPLACE INTO findings VALUES (?,?,?,?,?,?,?,?,?)",
            (finding_id, run_id, engagement, severity, title, url, type,
             1 if false_positive else 0,
             now if now is not None else time.time()))
        self._conn.commit()

    # Plumbing -----------------------------------------------------------------

    @property
    def connection(self):
        return self._conn

    def close(self):
        self._conn.close()
