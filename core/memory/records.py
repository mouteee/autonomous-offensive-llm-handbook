"""The memory record vocabulary: one storage shape, four tiers.

A record's tier says how long it should live and what may consume it. Working
memory is the current run's scratch state, discarded or promoted at run end.
Episodic memory is what happened, run by run, with a decay constant. Long-term
memory is distilled tactics that earned their keep. Knowledge is imported or
authored reference material. All four share the same storage row, so provenance,
scope and retention are uniform rather than per-tier afterthoughts.

Scope keys are the isolation mechanism, and they are explicit fields rather
than conventions buried in metadata: `engagement` scopes host-bound records to
one engagement, `profile_hash` scopes tactics to a stack fingerprint that
carries no host identity, and target domains are stored only as short one-way
hashes. The lesson's isolation tests exercise these fields, not a comment.
"""

import hashlib
import re
import time
from dataclasses import dataclass, field


MEMORY_SCHEMA_VERSION = "memory-v1"

TIERS = ("working", "episodic", "longterm", "knowledge")

# Evidence grades for long-term tactics. "proven" means proof text was stored
# beside the tactic; "hypothesis" means a tool accepted it but no impact was
# demonstrated. A grade moves upward on new proof and back down only through an
# explicit refutation.
EVIDENCE_GRADES = ("hypothesis", "proven")

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_NUM_SEGMENT_RE = re.compile(r"/\d+(?=/|$)")


class RecordError(ValueError):
    """A memory record that does not satisfy the vocabulary."""


def normalize_endpoint(path):
    """Collapse volatile path segments so equivalent endpoints share a key.

    UUIDs and purely numeric segments become `*`: `/api/7/users` and
    `/api/9/users` are the same surface for dedup purposes, which is what a
    tactic signature needs. Everything else is preserved as written.
    """
    if not isinstance(path, str) or not path:
        return path
    out = _UUID_RE.sub("*", path)
    return _NUM_SEGMENT_RE.sub("/*", out)


def tactic_signature(profile_hash, tool, endpoint, param=None, technique=None):
    """The dedup key for a long-term tactic, stable across reruns."""
    parts = [profile_hash or "", tool or "", normalize_endpoint(endpoint or ""),
             param or "", technique or ""]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def anonymize_target(domain):
    """A short one-way hash standing in for a target domain.

    Long-term tactics travel across engagements by design, so the record keeps
    evidence that a tactic worked somewhere without keeping where. Eight hex
    characters is a recognizer for someone who already knows the domain, not a
    recovery path.
    """
    return hashlib.sha256((domain or "").encode("utf-8")).hexdigest()[:8]


def new_tactic_metadata(*, signature, param=None, technique=None, proof=None,
                        target_domain=None):
    """The metadata block a fresh long-term tactic record starts with."""
    grade = "proven" if proof else "hypothesis"
    meta = {
        "signature": signature,
        "param_name": param,
        "bypass_technique": technique,
        "total_attempts": 1,
        "total_successes": 1,
        "success_rate": 1.0,
        "evidence_grade": grade,
        "targets_seen": [anonymize_target(target_domain)] if target_domain else [],
        "refuted": False,
    }
    if proof:
        meta["proof"] = str(proof)[:500]
    return meta


@dataclass(frozen=True)
class MemoryRecord:
    """One stored memory, in any tier."""

    record_id: str
    tier: str
    record_type: str
    content: str
    metadata: dict = field(default_factory=dict)
    source: str = ""
    run_id: str = ""
    profile_hash: str = ""
    engagement: str = ""
    tool_name: str = ""
    url_pattern: str = ""
    confidence: float = 1.0
    created_at: float = field(default_factory=lambda: time.time())
    first_seen: float = 0.0
    last_seen: float = 0.0
    expires_at: float = 0.0
    schema_version: str = MEMORY_SCHEMA_VERSION

    def __post_init__(self):
        if self.tier not in TIERS:
            raise RecordError(f"unknown tier {self.tier!r}; known: {', '.join(TIERS)}")
        if not isinstance(self.record_id, str) or not self.record_id.strip():
            raise RecordError("record_id is required")
        if not isinstance(self.content, str) or not self.content.strip():
            raise RecordError("content is required")
        if not isinstance(self.metadata, dict):
            raise RecordError("metadata is a dict")
