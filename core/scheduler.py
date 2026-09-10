"""
core/scheduler.py — Layer 3: Learning-Based Tool Prioritization

Adjusts recommender scores from execution history so the agent naturally
converges on the tools that work best *for this target type*.

Three independent adjustment axes:

1. **Fatigue** — consecutive failures decay a tool's effective score by
   ``0.8 ** consecutive_failures``, floored at 0.3.  Aggressive mode
   disables fatigue so productive tools aren't soft-capped.

2. **Contextual learning** — maintains per-tool histograms keyed by
   ``TargetProfile.profile_hash()``.  Fuzzy profile matching lets a tool score
   derived from php:mysql data carry over, partially, to a fresh php:postgresql
   target.
   num-ok: 70 % is the backend and database weights added together, 0.35 each out of a vector summing to 1.0 in TargetProfile.hash_similarity -- a sum of two source literals, not a measurement
   The match is a weighted similarity, and backend + database account for 70 %
   of the weight.

3. **Tool correlations** — when tool A and tool B frequently succeed
   together on the same URL, finding something with A raises B's score.
   Correlation rate = cooccurrence / tool_a_successes; threshold 0.4.

Also tracks **category budgets** (configurable iteration ceilings per
vulnerability class) and applies aggression-level scaling.

Public API
----------
``ExecutionResult``   — Enum (SUCCESS / PARTIAL / FAIL / ERROR / BLOCKED).
``CATEGORY_BUDGETS``  — dict[str, int] of documented iteration ceilings.
``SmartScheduler``    — call ``adjust()`` then ``record()`` in the testing loop.

The ``adjust`` / ``record`` names are this reference implementation's own;
the underlying source used ``get_adjusted_priority`` / ``record_execution``
with different signatures — those are intentionally simplified here.

v2 persistence schema (``to_dict`` / ``from_dict``)::

    {
      "version": 2,
      "tool_stats":         {tool: {total_executions, successes,
                                    consecutive_failures}},
      "contextual_stats":   {tool: {profile_hash: {total, successes, findings}}},
      "correlations":       {\"A→B\": {cooccurrence, tool1_successes}},
      "tool_success_count": {tool: success_count}
    }

The last two are not decoration. Restore from a dict with no
``consecutive_failures`` and fatigue starts from a clean slate. Restore from one
with no ``tool_success_count`` and the counters survive the load itself, because
``correlations`` carries its own copy; what is lost is the denominator's source.
``_successful_targets`` is not persisted either, so the damage is deferred
rather than absent: the first post-restore success by a tool that has since
gained a partner there rewrites every denominator it touches down to the
successes counted since the restore, while the co-occurrence numerator keeps its
restored history -- so the rate comes out inflated.

Example usage::

    scheduler = SmartScheduler(aggression_level="moderate")
    recommendations = recommender.recommend(profile, security)
    adjusted = scheduler.adjust(recommendations)
    # ... run the top-ranked tool ...
    scheduler.record("test_sqli", ExecutionResult.SUCCESS,
                     profile.profile_hash(), found=3)
"""

from __future__ import annotations

import os
import time
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from core.fingerprint import TargetProfile

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ExecutionResult
# ---------------------------------------------------------------------------

class ExecutionResult(Enum):
    """Outcome of a single tool execution."""
    SUCCESS = "success"   # tool ran and found something
    PARTIAL = "partial"   # ran; low-confidence / inconclusive results
    FAIL    = "fail"      # ran; found nothing
    ERROR   = "error"     # crashed or timed out
    BLOCKED = "blocked"   # WAF / rate-limit prevented execution


# ---------------------------------------------------------------------------
# Category budgets — documented per-session iteration ceilings
# ---------------------------------------------------------------------------

CATEGORY_BUDGETS: Dict[str, int] = {
    "INJECTION_SQL":   15,
    "INJECTION_NOSQL": 10,
    "INJECTION_XXE":    8,
    "INJECTION_SSTI":  10,
    "INJECTION_OTHER": 15,
    "XSS":             15,
    "IDOR":            12,
    "AUTH":            12,
    "UPLOAD":          10,
    "RACE":             8,
    "API":             10,
    "FUZZING":         15,
}

# Map tool-name prefixes / substrings → category keys
_TOOL_TO_CATEGORY: Dict[str, str] = {
    "test_sqli":             "INJECTION_SQL",
    "test_injection_sqli":   "INJECTION_SQL",
    "exploit_sqli":          "INJECTION_SQL",
    "test_injection_nosql":  "INJECTION_NOSQL",
    "test_injection_xxe":    "INJECTION_XXE",
    "test_injection_ssti":   "INJECTION_SSTI",
    "test_injection_lfi":    "INJECTION_OTHER",
    "test_injection_ssrf":   "INJECTION_OTHER",
    "test_injection_cmdi":   "INJECTION_OTHER",
    "test_injection_crlf":   "INJECTION_OTHER",
    "test_injection_hostheader": "INJECTION_OTHER",
    "test_injection_prototype":  "INJECTION_OTHER",
    "exploit_lfi":           "INJECTION_OTHER",
    "exploit_ssrf":          "INJECTION_OTHER",
    "test_deserialize":      "INJECTION_OTHER",
    "test_xss":              "XSS",
    "test_csp":              "XSS",
    "test_idor":             "IDOR",
    "fuzz_idor":             "IDOR",
    "test_cors":             "AUTH",
    "test_auth":             "AUTH",
    "test_redirect":         "AUTH",
    "test_clickjacking":     "AUTH",
    "test_method_override":  "AUTH",
    "test_upload":           "UPLOAD",
    "test_race":             "RACE",
    "test_graphql":          "API",
    "test_websocket":        "API",
    "fuzz_endpoint":         "FUZZING",
    "fuzz_authenticated":    "FUZZING",
    "fuzz_injection":        "FUZZING",
    "discover_hidden_params":"FUZZING",
}

# ---------------------------------------------------------------------------
# Internal state containers
# ---------------------------------------------------------------------------

@dataclass
class _ToolStats:
    """Per-tool aggregate counters (in-memory only)."""
    total_executions: int = 0
    successes: int = 0
    consecutive_failures: int = 0
    total_findings: int = 0

    @property
    def success_rate(self) -> float:
        if self.total_executions == 0:
            return 0.5  # neutral for unseen tools
        return self.successes / self.total_executions


@dataclass
class _ContextualStats:
    """Per-tool-per-profile-hash counters."""
    total: int = 0
    successes: int = 0
    findings: int = 0

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.successes / self.total

    def to_dict(self) -> dict:
        return {"total": self.total, "successes": self.successes,
                "findings": self.findings}

    @classmethod
    def from_dict(cls, d: dict) -> "_ContextualStats":
        return cls(total=d.get("total", 0), successes=d.get("successes", 0),
                   findings=d.get("findings", 0))


@dataclass
class _CategoryState:
    """Runtime budget tracker for one category."""
    ceiling: int = 10          # maximum iterations this session
    used: int = 0
    consecutive_failures: int = 0

    @property
    def exhausted(self) -> bool:
        return self.used >= self.ceiling

    @property
    def remaining(self) -> int:
        return max(0, self.ceiling - self.used)


# ---------------------------------------------------------------------------
# SmartScheduler
# ---------------------------------------------------------------------------

class SmartScheduler:
    """
    Layer 3 — Learning-based tool priority adjuster.

    Instantiate once per scan, call ``adjust()`` before each tool selection,
    and call ``record()`` after each execution.

    Args:
        aggression_level:  ``"passive"`` | ``"moderate"`` (default) | ``"aggressive"``
            - passive:    budget multiplier 0.5×; fatigue enabled.
            - moderate:   budget multiplier 1×; fatigue enabled.
            - aggressive: budget multiplier 2×; fatigue **disabled**.
        stats_file:  Optional path for JSON persistence.  When omitted the
            scheduler starts cold each session (no cross-session learning).
    """

    # Tuning constants -------------------------------------------------------
    FATIGUE_DECAY    = 0.8   # multiplier per consecutive failure
    FATIGUE_FLOOR    = 0.3   # minimum fatigue multiplier
    SUCCESS_BOOST    = 1.3   # max boost for >50 % contextual success rate
    COVERAGE_BONUS   = 1.5   # first-time tool/category bonus
    BUDGET_PENALTY   = 0.1   # score multiplier when category exhausted
    CORRELATION_THRESHOLD = 0.4  # minimum rate for a significant correlation

    # Minimum data points before contextual / correlation data is trusted
    _CTX_MIN_TOTAL  = 2
    _CORR_MIN_TOTAL = 3

    def __init__(
        self,
        aggression_level: str = "moderate",
        stats_file: Optional[str] = None,
    ) -> None:
        self._aggression = (
            os.getenv("HARNESS_AGGRESSION_LEVEL", aggression_level or "moderate")
        )

        # Feature flags (for ablation studies)
        self._scheduler_enabled = os.getenv("HARNESS_SCHEDULER_ENABLED", "1") != "0"
        self._fatigue_enabled = (
            os.getenv("HARNESS_FATIGUE_ENABLED", "1") != "0"
            and self._aggression != "aggressive"
        )
        self._budgets_enabled = (
            os.getenv("HARNESS_CATEGORY_BUDGETS_ENABLED", "1") != "0"
        )

        # Per-tool aggregate stats
        self._tool_stats: Dict[str, _ToolStats] = defaultdict(_ToolStats)

        # Contextual stats: tool → profile_hash → _ContextualStats
        self._contextual: Dict[str, Dict[str, _ContextualStats]] = defaultdict(
            lambda: defaultdict(_ContextualStats)
        )

        # Correlation counters: "A→B" → {cooccurrence, tool1_successes}
        self._correlations: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"cooccurrence": 0, "tool1_successes": 0}
        )

        # Successful targets per tool (for correlation tracking)
        self._successful_targets: Dict[str, set] = defaultdict(set)

        # Category runtime state
        self._categories: Dict[str, _CategoryState] = {}
        self._init_category_budgets()

        # Coverage tracking
        self._tools_tried: set = set()
        self._categories_tried: set = set()

        # Contextual profile binding (set via set_profile())
        self._current_profile_hash: str = ""

        # Per-tool success count for correlation denominator (separate from _ToolStats)
        self._tool_success_count: Dict[str, int] = defaultdict(int)

        # Recently successful tools (de-duped list for correlation_boost input)
        self._recently_successful: List[str] = []

        # Persistence
        self._stats_file = stats_file
        self._executions_since_save = 0
        self._auto_save_interval = 5

        if self._stats_file:
            self._load()

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def adjust(
        self,
        recommendations: List[Tuple[str, float, str]],
    ) -> List[Tuple[str, float, str]]:
        """Apply learning-based adjustments to recommender output.

        Args:
            recommendations: ``[(tool_name, score, reason), ...]`` as produced
                by ``ToolRecommender.recommend()``.

        Returns:
            Same shape, scores adjusted, sorted descending by adjusted score.
            The *reason* string is appended with a brief adjustment summary.
        """
        if not self._scheduler_enabled:
            return sorted(recommendations, key=lambda x: x[1], reverse=True)

        adjusted: List[Tuple[str, float, str]] = []
        for tool, base_score, reason in recommendations:
            adj_score, summary = self._compute_adjustment(tool, base_score)
            new_reason = f"{reason} [{summary}]" if summary else reason
            adjusted.append((tool, adj_score, new_reason))

        adjusted.sort(key=lambda x: x[1], reverse=True)
        return adjusted

    def set_profile(self, profile_hash: str) -> None:
        """Bind the current target's profile hash so adjust() uses contextual rates.

        Call this once after fingerprinting the target; adjust() will then
        prefer contextual success rates for this profile over the global
        aggregate.  Passing an empty string or never calling this method
        causes adjust() to fall back to global stats (safe default).
        """
        self._current_profile_hash = profile_hash or ""

    def record(
        self,
        tool: str,
        result: ExecutionResult,
        profile_hash: str,
        found: int = 0,
        target: str = "",
    ) -> None:
        """Record one tool execution outcome and update all learning state.

        Args:
            tool:         Tool name (matches keys used in ``adjust()``).
            result:       Outcome enum value.
            profile_hash: ``TargetProfile.profile_hash()`` string for the
                          target this tool ran against.
            found:        Number of findings produced (0 if not SUCCESS).
            target:       Optional URL/parameter; used for correlation tracking.
        """
        stats = self._tool_stats[tool]
        stats.total_executions += 1

        success = result == ExecutionResult.SUCCESS
        if success:
            stats.successes += 1
            stats.consecutive_failures = 0
            stats.total_findings += found
        elif result in (ExecutionResult.FAIL, ExecutionResult.ERROR,
                        ExecutionResult.BLOCKED):
            stats.consecutive_failures += 1

        # Contextual stats
        ctx = self._contextual[tool][profile_hash]
        ctx.total += 1
        if success:
            ctx.successes += 1
            ctx.findings += found

        # Category budget
        cat = self._get_category(tool)
        if cat and self._budgets_enabled:
            state = self._categories.get(cat)
            if state:
                state.used += 1
                if result in (ExecutionResult.FAIL, ExecutionResult.ERROR):
                    state.consecutive_failures += 1
                else:
                    state.consecutive_failures = 0

        # Coverage
        self._tools_tried.add(tool)
        if cat:
            self._categories_tried.add(cat)

        # Correlation tracking
        if success:
            self._tool_success_count[tool] += 1
            if tool not in self._recently_successful:
                self._recently_successful.append(tool)
        if success and target:
            self._update_correlations(tool, target)
            self._successful_targets[tool].add(target)

        # Auto-save
        self._executions_since_save += 1
        if (self._stats_file
                and self._executions_since_save >= self._auto_save_interval):
            self.save()
            self._executions_since_save = 0

    # -----------------------------------------------------------------------
    # Persistence (v2 format)
    # -----------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialise learning state to the v2 stats dict."""
        tool_stats_out: Dict[str, dict] = {}
        for name, s in self._tool_stats.items():
            if s.total_executions > 0:
                tool_stats_out[name] = {
                    "total_executions": s.total_executions,
                    "successes": s.successes,
                    "consecutive_failures": s.consecutive_failures,
                }

        contextual_out: Dict[str, Dict[str, dict]] = {}
        for tool_name, profiles in self._contextual.items():
            profile_data = {
                ph: ctx.to_dict()
                for ph, ctx in profiles.items()
                if ctx.total > 0
            }
            if profile_data:
                contextual_out[tool_name] = profile_data

        correlations_out = {
            k: dict(v)
            for k, v in self._correlations.items()
            if v["tool1_successes"] > 0
        }

        # Per-tool success counts (used as correlation denominator)
        tool_success_count_out = {
            t: c for t, c in self._tool_success_count.items() if c > 0
        }

        return {
            "version": 2,
            "tool_stats": tool_stats_out,
            "contextual_stats": contextual_out,
            "correlations": correlations_out,
            "tool_success_count": tool_success_count_out,
        }

    @classmethod
    def from_dict(cls, data: dict, **kwargs) -> "SmartScheduler":
        """Reconstruct a SmartScheduler from a v2 stats dict.

        Extra keyword arguments (e.g. ``aggression_level``) are forwarded to
        ``__init__``, which will skip auto-loading from file since no
        *stats_file* is passed.
        """
        scheduler = cls(**kwargs)  # no stats_file → clean state

        for name, s in data.get("tool_stats", {}).items():
            stats = scheduler._tool_stats[name]
            stats.total_executions = s.get("total_executions", 0)
            stats.successes = s.get("successes", 0)
            stats.consecutive_failures = s.get("consecutive_failures", 0)

        for tool_name, profiles in data.get("contextual_stats", {}).items():
            for ph, ctx_data in profiles.items():
                scheduler._contextual[tool_name][ph] = (
                    _ContextualStats.from_dict(ctx_data)
                )

        for key, corr_data in data.get("correlations", {}).items():
            scheduler._correlations[key] = {
                "cooccurrence":   corr_data.get("cooccurrence", 0),
                "tool1_successes": corr_data.get("tool1_successes", 0),
            }

        for tool_name, count in data.get("tool_success_count", {}).items():
            scheduler._tool_success_count[tool_name] = count

        return scheduler

    def save(self) -> bool:
        """Write current stats to *stats_file* (JSON, atomic rename).

        Returns True on success, False on error.
        """
        if not self._stats_file:
            return False
        try:
            tmp = self._stats_file + ".tmp"
            stats_dir = os.path.dirname(self._stats_file)
            if stats_dir:
                os.makedirs(stats_dir, exist_ok=True)
            with open(tmp, "w") as fh:
                json.dump(self.to_dict(), fh, indent=2)
            os.replace(tmp, self._stats_file)
            return True
        except Exception as exc:
            logger.error("scheduler: save failed: %s", exc)
            return False

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _init_category_budgets(self) -> None:
        """Initialise _CategoryState for every documented category."""
        multiplier = {"passive": 0.5, "moderate": 1.0, "aggressive": 2.0}.get(
            self._aggression, 1.0
        )
        for cat, ceiling in CATEGORY_BUDGETS.items():
            self._categories[cat] = _CategoryState(
                ceiling=max(1, int(ceiling * multiplier))
            )

    def _load(self) -> None:
        """Load stats from *stats_file* if it exists."""
        if not self._stats_file or not os.path.exists(self._stats_file):
            return
        try:
            with open(self._stats_file) as fh:
                data = json.load(fh)
            loaded = self.from_dict(data)
            self._tool_stats         = loaded._tool_stats
            self._contextual         = loaded._contextual
            self._correlations       = loaded._correlations
            self._tool_success_count = loaded._tool_success_count
        except Exception as exc:
            logger.warning("scheduler: failed to load stats: %s", exc)

    def _get_category(self, tool: str) -> Optional[str]:
        """Return the CATEGORY_BUDGETS key for *tool*, or None."""
        if tool in _TOOL_TO_CATEGORY:
            return _TOOL_TO_CATEGORY[tool]
        # Prefix/substring fallback
        for prefix, cat in _TOOL_TO_CATEGORY.items():
            if tool.startswith(prefix):
                return cat
        lower = tool.lower()
        if "sqli" in lower or ("sql" in lower and "nosql" not in lower):
            return "INJECTION_SQL"
        if "nosql" in lower:
            return "INJECTION_NOSQL"
        if "xss" in lower:
            return "XSS"
        if "idor" in lower:
            return "IDOR"
        if "injection" in lower or "deserializ" in lower:
            return "INJECTION_OTHER"
        if "fuzz" in lower:
            return "FUZZING"
        if "graphql" in lower or "websocket" in lower:
            return "API"
        return None

    def _compute_adjustment(
        self,
        tool: str,
        base_score: float,
    ) -> Tuple[float, str]:
        """Return (adjusted_score, summary_label) for one tool."""
        multiplier = 1.0
        parts: List[str] = []

        stats = self._tool_stats.get(tool)

        # 1. Fatigue (consecutive failures)
        if self._fatigue_enabled and stats and stats.consecutive_failures > 0:
            fatigue = max(
                self.FATIGUE_FLOOR,
                self.FATIGUE_DECAY ** stats.consecutive_failures,
            )
            multiplier *= fatigue
            parts.append(f"fatigue×{fatigue:.2f}")

        # 2. Contextual success-rate (profile-aware) or global fallback
        # Prefer the contextual rate for the bound profile hash; fall back to
        # the global aggregate rate (or neutral 0.5) when no data is available.
        sr: Optional[float] = None
        ctx_label = "global"
        if self._current_profile_hash:
            ctx_rate, ctx_match = self._contextual_rate_for_hash(
                tool, self._current_profile_hash
            )
            if ctx_rate is not None:
                sr = ctx_rate
                ctx_label = ctx_match  # "exact" or "similar"
        if sr is None and stats and stats.total_executions >= self._CTX_MIN_TOTAL:
            sr = stats.success_rate
        # Apply rate adjustment only when we have a meaningful sample
        min_execs = self._CTX_MIN_TOTAL
        has_global = stats and stats.total_executions >= min_execs
        has_ctx = (self._current_profile_hash and
                   self._contextual.get(tool, {}).get(
                       self._current_profile_hash
                   ) is not None and
                   self._contextual[tool][self._current_profile_hash].total >= min_execs)
        if sr is not None and (has_global or has_ctx):
            if sr > 0.5:
                boost = 1.0 + (sr - 0.5) * 0.6  # ≤ 1.3 at sr=1.0
                multiplier *= boost
                parts.append(f"sr_{ctx_label}×{boost:.2f}")
            elif sr < 0.2:
                penalty = 0.6 + sr * 2.0  # 0.6 at sr=0, 1.0 at sr=0.2
                multiplier *= penalty
                parts.append(f"low_sr_{ctx_label}×{penalty:.2f}")

        # 3. Coverage bonus (first time this tool / category is tried)
        cat = self._get_category(tool)
        if tool not in self._tools_tried:
            multiplier *= self.COVERAGE_BONUS
            parts.append(f"new_tool×{self.COVERAGE_BONUS}")
        elif cat and cat not in self._categories_tried:
            bonus = self.COVERAGE_BONUS * 0.8
            multiplier *= bonus
            parts.append(f"new_cat×{bonus:.2f}")

        # 4. Category budget exhaustion
        if cat and self._budgets_enabled:
            state = self._categories.get(cat)
            if state and state.exhausted:
                multiplier *= self.BUDGET_PENALTY
                parts.append(f"exhausted×{self.BUDGET_PENALTY}")
            elif state and state.remaining < 3:
                multiplier *= 0.5
                parts.append(f"low_budget×0.5")

        # 5. Productivity boost (tools that find things per execution)
        if stats and stats.total_executions > 0:
            fpe = stats.total_findings / stats.total_executions
            if fpe > 0.5:
                prod_boost = min(1.5, 1.0 + fpe * 0.2)
                multiplier *= prod_boost
                parts.append(f"productive×{prod_boost:.2f}")

        # 6. Correlation boost (recently successful sibling tools)
        if self._recently_successful:
            corr_boost, corr_src = self.correlation_boost(
                tool, self._recently_successful
            )
            if corr_boost > 1.0 and corr_src:
                multiplier *= corr_boost
                parts.append(f"corr({corr_src})×{corr_boost:.2f}")

        adjusted = base_score * multiplier
        return adjusted, "; ".join(parts)

    def _contextual_rate_for_hash(
        self,
        tool: str,
        profile_hash: str,
    ) -> Tuple[Optional[float], str]:
        """Return the best available contextual success rate for *tool* on
        targets matching *profile_hash*.

        Resolution order:
        1. Exact profile hash match (if ≥ _CTX_MIN_TOTAL data points).
        2. Fuzzy profile match via ``TargetProfile.hash_similarity``, over
           stored hashes scoring ≥ 0.6, and only once those aggregate to at
           least 3 data points -- below that floor this returns "no_data"
           even though a similar profile is on hand.
        3. Returns (None, "no_data") when nothing clears either bar.
        """
        tool_ctx = self._contextual.get(tool, {})

        # Exact match
        exact = tool_ctx.get(profile_hash)
        if exact and exact.total >= self._CTX_MIN_TOTAL:
            return exact.success_rate, "exact"

        # Fuzzy match — aggregate similar profiles
        similar_stats = []
        for stored_hash, ctx in tool_ctx.items():
            if stored_hash == profile_hash:
                continue
            sim = TargetProfile.hash_similarity(profile_hash, stored_hash)
            if sim >= 0.6:
                similar_stats.append(ctx)

        if similar_stats:
            total    = sum(s.total     for s in similar_stats)
            successes = sum(s.successes for s in similar_stats)
            if total >= 3:
                return successes / total, "similar"

        return None, "no_data"

    def _update_correlations(self, successful_tool: str, target: str) -> None:
        """Update correlation counters after *successful_tool* succeeds on *target*.

        tool1_successes is derived from _tool_success_count (incremented once
        per success in record()) rather than being incremented here, so it is
        never over-counted by the number of other tracked tools.
        """
        src_successes = self._tool_success_count[successful_tool]
        for other_tool, targets in self._successful_targets.items():
            if other_tool == successful_tool:
                continue
            key = f"{successful_tool}→{other_tool}"
            # A→B co-occurrence: other_tool also succeeded on the same target
            if target in targets:
                self._correlations[key]["cooccurrence"] += 1
            # Sync tool1_successes to the canonical per-tool success count
            self._correlations[key]["tool1_successes"] = src_successes

    def correlation_boost(
        self,
        tool: str,
        recently_successful: List[str],
    ) -> Tuple[float, Optional[str]]:
        """Return (boost_multiplier, source_tool) for *tool* given recent hits.

        ``boost_multiplier`` is 1.0 when no significant correlation is found.
        The strongest single correlation drives the result.

        Correlation rate = cooccurrence / tool1_successes; threshold 0.4.
        """
        best_boost = 1.0
        best_source: Optional[str] = None

        for src in recently_successful:
            key = f"{src}→{tool}"
            data = self._correlations.get(key)
            if data is None:
                continue
            t1 = data["tool1_successes"]
            if t1 < self._CORR_MIN_TOTAL:
                continue
            rate = data["cooccurrence"] / t1
            if rate >= self.CORRELATION_THRESHOLD:
                boost = 1.0 + rate * 0.5  # 1.2 at 0.4 → 1.5 at 1.0
                if boost > best_boost:
                    best_boost = boost
                    best_source = src

        return best_boost, best_source
