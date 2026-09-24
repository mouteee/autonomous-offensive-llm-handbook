"""Persistent memory for the teaching agent: records, store, search, lanes, context.

Four record tiers share one storage shape with first-class provenance and scope
keys. Retrieval comes in two deliberately different flavors: free-text search
(`search.py`, keyword ranking with an optional vector lane) and deterministic
structured lanes (`lanes.py`, plain SQL over the same store). Context assembly
(`context.py`) turns retrieved material into a budgeted prompt section and a
record of what was left out.

Everything retrieved here is advisory. A recalled record is data with a
provenance reference; authorization, tool eligibility and budgets live in the
host's policy objects, outside every prompt this package helps build.
"""

from .records import (MEMORY_SCHEMA_VERSION, TIERS, MemoryRecord,
                      anonymize_target, normalize_endpoint, tactic_signature)
from .store import MemoryStore, MemoryStoreError

__all__ = [
    "MEMORY_SCHEMA_VERSION", "TIERS", "MemoryRecord", "MemoryStore",
    "MemoryStoreError", "anonymize_target", "normalize_endpoint",
    "tactic_signature",
]
