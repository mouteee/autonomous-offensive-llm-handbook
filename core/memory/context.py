"""Context assembly: budgeted blocks in, one prompt section and an omissions
record out.

Every block belongs to a tier through its source, every tier gets a fixed
fraction of the total budget, and blocks are kept or dropped whole -- nothing
is truncated mid-sentence into a different claim. The assembler's second return
value is as important as the first: the omissions record names every block that
did not make it and why, so "the model was not shown X" is a fact you can read
rather than an absence you have to infer.

Token counts here are character-derived estimates (a flat divisor), marked as
estimates; a provider's real accounting is the number that bills, and the
lesson shows how to compare the two without depending on any provider.

One teaching correction, labeled: the originating implementation carries block
expiry only in a cache path that nothing calls, so its assembler cannot expire
anything in practice. Here expiry is applied at assembly time, where it is
observable.
"""

import time
from dataclasses import dataclass, field


CHARS_PER_TOKEN = 4

# Fractions of the total budget per tier -- the originating implementation's
# split, kept verbatim.
TIER_FRACTIONS = {
    "working": 0.40,
    "episodic": 0.20,
    "longterm": 0.25,
    "knowledge": 0.15,
}

# Which tier a block's source lands in; unrecognized sources are working
# memory, the shortest-lived assumption.
SOURCE_TO_TIER = {
    "memory": "longterm",
    "tactics": "longterm",
    "coverage": "working",
    "tool_results": "working",
    "episodes": "episodic",
    "session_summary": "episodic",
    "knowledge": "knowledge",
    "waf_info": "knowledge",
}


def estimate_tokens(text):
    """A character-derived token estimate: an approximation, not accounting."""
    return max(1, len(text) // CHARS_PER_TOKEN)


@dataclass(frozen=True)
class ContextBlock:
    """One candidate piece of recalled or computed context."""

    block_id: str
    source: str
    content: str
    priority: float = 1.0
    created_at: float = field(default_factory=lambda: time.time())
    ttl_seconds: float = 0.0

    @property
    def tier(self):
        return SOURCE_TO_TIER.get(self.source, "working")

    @property
    def token_estimate(self):
        return estimate_tokens(self.content)

    def expired(self, now):
        return self.ttl_seconds > 0 and now > self.created_at + self.ttl_seconds


def assemble(blocks, *, total_budget, now=None):
    """Fill each tier greedily by priority, then spend leftover budget.

    Per tier, blocks are taken in priority order and admitted when they fit the
    tier's remaining budget; a too-large block is skipped while a later smaller
    one may still fit, so the cut is per-block, not a prefix. Whatever budget
    the tiers leave unused becomes one overflow pool that admits the remaining
    blocks across tiers by priority. Expired blocks are omitted before any
    budgeting. Returns a dict with the rendered context, the included block
    ids in render order, and the omissions record.
    """
    now = now if now is not None else time.time()
    live, omissions = [], []
    for block in blocks:
        if block.expired(now):
            omissions.append({"block_id": block.block_id, "reason": "expired"})
        else:
            live.append(block)

    budgets = {tier: int(total_budget * fraction)
               for tier, fraction in TIER_FRACTIONS.items()}
    selected, leftovers = [], []
    for tier in sorted(TIER_FRACTIONS):
        members = sorted((b for b in live if b.tier == tier),
                         key=lambda b: (-b.priority, b.block_id))
        used = 0
        for block in members:
            if used + block.token_estimate <= budgets[tier]:
                selected.append(block)
                used += block.token_estimate
            else:
                leftovers.append((block, "tier budget exhausted"))
        budgets[tier] -= used

    overflow_pool = sum(budgets.values())
    for block, tier_reason in sorted(leftovers,
                                     key=lambda item: (-item[0].priority,
                                                       item[0].block_id)):
        if block.token_estimate <= overflow_pool:
            selected.append(block)
            overflow_pool -= block.token_estimate
        else:
            omissions.append({"block_id": block.block_id,
                              "reason": tier_reason + "; overflow pool exhausted"})

    selected.sort(key=lambda b: (b.source, -b.priority, b.block_id))
    rendered = "\n\n".join(
        f"[{b.source} · {b.block_id}]\n{b.content}" for b in selected)
    return {
        "context": rendered,
        "included": [b.block_id for b in selected],
        "estimated_tokens": sum(b.token_estimate for b in selected),
        "total_budget": total_budget,
        "omissions": omissions,
    }
