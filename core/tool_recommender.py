"""
Layer 2: Profile-Based Tool Scoring (Tool Recommender)

Scores and prioritizes security testing tools based on a ``TargetProfile``
fingerprint and a ``SecurityProfile`` of observed response signals.  This is
the second layer of the three-layer intelligent tool-selection pipeline:

    Layer 1 — fingerprint.py  → TargetProfile
    Layer 2 — tool_recommender.py  → ranked (tool, score, reason) list   ← here
    Layer 3 — scheduler.py  → learning-based priority adjustment

Scoring formula (exact)::

    Score = (Base × Relevance × Impact) / Cost

where:
  num-ok: 1-10 is the scale base_priority is defined on, declared here and nowhere else in the module -- no catalogue entry reaches 10, which is why the upper bound appears in no source literal
  - Base      : inherent tool priority (1–10)
  - Relevance : composite multiplier from profile boosts / penalizes (≥ 0)
  - Impact    : severity if a finding is produced (1–5, 5 = critical)
  num-ok: 1-10 is the declared scale for cost_estimate, the same bound and the same reason as base_priority above
  - Cost      : relative execution cost (1–10, 1 = instant)

Priority tiers::

    HIGH   ≥ 15  — test first
    MEDIUM ≥  8  — test if time permits
    LOW    ≥  3  — comprehensive testing only
    SKIP   <  3  — not relevant for this target

Public API
----------
``ToolRelevance``   — dataclass describing a tool's scoring parameters.
``RELEVANCE``       — dict[str, ToolRelevance] catalog (all registered tools).
``ToolRecommender`` — stateless scorer; call ``.recommend(profile, security)``.
``get_recommender`` — module-level singleton accessor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Tuple, Optional

if TYPE_CHECKING:  # avoid circular imports at runtime when type-checking only
    from core.fingerprint import TargetProfile
    from core.response_analyzer import SecurityProfile

# ---------------------------------------------------------------------------
# Tier thresholds (module-level constants, referenced in decision-system docs)
# ---------------------------------------------------------------------------
TIER_HIGH: float = 15.0
TIER_MEDIUM: float = 8.0
TIER_LOW: float = 3.0

# Map tier label → minimum score (inclusive)
TIERS: Dict[str, float] = {
    "HIGH": TIER_HIGH,
    "MEDIUM": TIER_MEDIUM,
    "LOW": TIER_LOW,
    "SKIP": 0.0,
}


# ---------------------------------------------------------------------------
# ToolRelevance dataclass
# ---------------------------------------------------------------------------

@dataclass
class ToolRelevance:
    """Scoring parameters and profile-match rules for a single tool.

    Attributes:
        tool_name:       Canonical tool name used in tool registry.
        num-ok: 1-10 is the declared scale for base_priority, repeated from the module docstring, whose annotation says why the bound appears in no source literal
        base_priority:   Inherent tool priority (1–10).
        impact_potential: Severity if a finding is produced (1–5, 5 = critical).
        num-ok: 1-10 is the declared scale for cost_estimate, the same bound and the same reason as base_priority above
        cost_estimate:   Relative execution cost (1–10, 1 = instant).
        requires:        List of conditions that ALL must be true for the tool
                         to be considered relevant.
        requires_any:    List of conditions where AT LEAST ONE must be true.
        boosts:          Mapping of condition string → multiplier (> 1.0 =
                         increase score when condition holds).
        penalizes:       Mapping of condition string → multiplier (< 1.0 =
                         decrease score when condition holds; 0.0 = skip).
    """

    tool_name: str
    base_priority: float = 5.0
    impact_potential: float = 3.0
    cost_estimate: float = 3.0
    requires: List[str] = field(default_factory=list)
    requires_any: List[str] = field(default_factory=list)
    boosts: Dict[str, float] = field(default_factory=dict)
    penalizes: Dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# RELEVANCE catalog — the real profile-aware scoring entries
# ---------------------------------------------------------------------------

RELEVANCE: Dict[str, ToolRelevance] = {

    # ------------------------------------------------------------------
    # SQL injection
    # ------------------------------------------------------------------
    "test_sqli": ToolRelevance(
        tool_name="test_sqli",
        base_priority=8.0,
        impact_potential=5.0,   # critical — data breach
        cost_estimate=4.0,
        requires_any=[
            "likely_database in ['mysql', 'postgresql', 'mssql', 'oracle', 'sqlite', 'unknown']",
        ],
        boosts={
            "likely_database == 'mysql'": 1.3,
            "likely_database == 'postgresql'": 1.3,
            "likely_database == 'mssql'": 1.4,     # often more impactful
            "backend_language == 'php'": 1.2,
            "backend_language == 'java'": 1.1,
            "error_verbosity == 'high'": 1.5,       # easier to exploit
            "waf_detected == False": 1.2,
            "'form' in content_types_accepted": 1.2,
            "'json' in content_types_accepted": 1.2,
        },
        penalizes={
            "likely_database == 'mongodb'": 0.1,    # wrong DB type
            "waf_detected == True": 0.7,
        },
    ),

    # ------------------------------------------------------------------
    # XSS
    # ------------------------------------------------------------------
    "test_xss": ToolRelevance(
        tool_name="test_xss",
        base_priority=7.0,
        impact_potential=3.0,
        cost_estimate=4.0,
        boosts={
            "has_search == True": 1.4,
            "frontend_framework == 'jquery'": 1.3,  # more XSS-prone
            "waf_detected == False": 1.2,
            "error_verbosity == 'high'": 1.1,
            "'form' in content_types_accepted": 1.2,
            "'json' in content_types_accepted": 1.1,
        },
        penalizes={
            "waf_detected == True": 0.8,
            "frontend_framework == 'react'": 0.9,   # escapes by default
            "frontend_framework == 'angular'": 0.9,
        },
    ),

    # ------------------------------------------------------------------
    # IDOR / access control
    # ------------------------------------------------------------------
    "test_idor": ToolRelevance(
        tool_name="test_idor",
        base_priority=7.0,
        impact_potential=4.0,
        cost_estimate=4.0,
        boosts={
            "'rest' in api_types": 1.3,
            "'jwt' in auth_mechanisms": 1.2,
            "'session' in auth_mechanisms": 1.2,
            "'json' in content_types_accepted": 1.3,
            "'form' in content_types_accepted": 1.1,
        },
    ),

    # ------------------------------------------------------------------
    # NoSQL injection
    # ------------------------------------------------------------------
    "test_injection_nosql": ToolRelevance(
        tool_name="test_injection_nosql",
        base_priority=7.0,
        impact_potential=4.0,
        cost_estimate=3.0,
        requires=[
            "likely_database == 'mongodb'",
        ],
        boosts={
            "backend_language == 'node'": 1.4,
            "backend_language == 'python'": 1.2,
            "'json' in content_types_accepted": 1.3,
        },
        penalizes={
            "likely_database == 'mysql'": 0.1,
            "likely_database == 'postgresql'": 0.1,
        },
    ),

    # ------------------------------------------------------------------
    # GraphQL
    # ------------------------------------------------------------------
    "test_graphql": ToolRelevance(
        tool_name="test_graphql",
        base_priority=8.0,
        impact_potential=4.0,
        cost_estimate=3.0,
        requires=[
            "has_graphql == True",
        ],
        boosts={
            "has_graphql == True": 2.0,             # strong signal
        },
        penalizes={
            "has_graphql == False": 0.0,            # do not run
        },
    ),

    # ------------------------------------------------------------------
    # XXE
    # ------------------------------------------------------------------
    "test_injection_xxe": ToolRelevance(
        tool_name="test_injection_xxe",
        base_priority=7.0,
        impact_potential=4.0,
        cost_estimate=3.0,
        requires=[
            "accepts_xml == True",
        ],
        boosts={
            "backend_language == 'java'": 1.4,      # XML parsers often vulnerable
            "backend_language == 'php'": 1.2,
            "backend_language == 'dotnet'": 1.3,
            "'soap' in api_types": 1.5,
        },
        penalizes={
            "accepts_xml == False": 0.0,
        },
    ),

    # ------------------------------------------------------------------
    # SSTI
    # ------------------------------------------------------------------
    "test_injection_ssti": ToolRelevance(
        tool_name="test_injection_ssti",
        base_priority=7.0,
        impact_potential=5.0,                       # can lead to RCE
        cost_estimate=3.0,
        requires_any=[
            "framework in ['django', 'flask', 'jinja2', 'laravel', 'twig', 'symfony', 'rails', 'erb']",
            "backend_language in ['python', 'php', 'ruby']",
        ],
        boosts={
            "framework == 'flask'": 1.4,
            "framework == 'django'": 1.3,
            "framework == 'laravel'": 1.3,
            "framework == 'rails'": 1.2,
            "error_verbosity == 'high'": 1.3,
        },
    ),

    # ------------------------------------------------------------------
    # LFI
    # ------------------------------------------------------------------
    "test_injection_lfi": ToolRelevance(
        tool_name="test_injection_lfi",
        base_priority=6.0,
        impact_potential=4.0,
        cost_estimate=2.0,
        boosts={
            "backend_language == 'php'": 1.5,       # PHP most vulnerable
            "has_file_upload == True": 1.3,
            "error_verbosity == 'high'": 1.2,
        },
        penalizes={
            "backend_language == 'node'": 0.7,
        },
    ),

    # ------------------------------------------------------------------
    # SSRF
    # ------------------------------------------------------------------
    "test_injection_ssrf": ToolRelevance(
        tool_name="test_injection_ssrf",
        base_priority=7.0,
        impact_potential=4.0,
        cost_estimate=3.0,
        boosts={
            "has_file_upload == True": 1.2,
        },
    ),

    # ------------------------------------------------------------------
    # Command injection
    # ------------------------------------------------------------------
    "test_injection_cmdi": ToolRelevance(
        tool_name="test_injection_cmdi",
        base_priority=8.0,
        impact_potential=5.0,                       # critical — RCE
        cost_estimate=2.0,
        boosts={
            "backend_language == 'php'": 1.3,
            "backend_language == 'python'": 1.2,
            "error_verbosity == 'high'": 1.3,
        },
    ),

    # ------------------------------------------------------------------
    # Prototype pollution
    # ------------------------------------------------------------------
    "test_injection_prototype": ToolRelevance(
        tool_name="test_injection_prototype",
        base_priority=5.0,
        impact_potential=3.0,
        cost_estimate=2.0,
        requires_any=[
            "backend_language == 'node'",
            "frontend_framework in ['react', 'angular', 'vue']",
        ],
        boosts={
            "backend_language == 'node'": 1.5,
            "'json' in content_types_accepted": 1.3,
        },
    ),

    # ------------------------------------------------------------------
    # WebSocket
    # ------------------------------------------------------------------
    "test_websocket": ToolRelevance(
        tool_name="test_websocket",
        base_priority=7.0,
        impact_potential=4.0,
        cost_estimate=3.0,
        requires=[
            "has_websocket == True",
        ],
        boosts={
            "has_websocket == True": 2.0,
        },
        penalizes={
            "has_websocket == False": 0.0,
        },
    ),

    # ------------------------------------------------------------------
    # CORS
    # ------------------------------------------------------------------
    "test_cors": ToolRelevance(
        tool_name="test_cors",
        base_priority=6.0,
        impact_potential=3.0,
        cost_estimate=2.0,
        boosts={
            "'rest' in api_types": 1.3,
            "cors_enabled == True": 1.4,
            "'jwt' in auth_mechanisms": 1.2,
        },
    ),

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    "test_auth": ToolRelevance(
        tool_name="test_auth",
        base_priority=8.0,
        impact_potential=5.0,                       # critical — auth bypass
        cost_estimate=4.0,
        requires_any=[
            "'jwt' in auth_mechanisms",
            "'session' in auth_mechanisms",
            "'oauth' in auth_mechanisms",
            "jwt_detected == True",
        ],
        boosts={
            "jwt_detected == True": 1.5,
            "'oauth' in auth_mechanisms": 1.4,
            "'jwt' in auth_mechanisms": 1.4,
        },
        penalizes={
            "waf_detected == True": 0.8,
        },
    ),

    # ------------------------------------------------------------------
    # JWT-specific auth
    # ------------------------------------------------------------------
    "test_auth_jwt": ToolRelevance(
        tool_name="test_auth_jwt",
        base_priority=8.0,
        impact_potential=5.0,
        cost_estimate=3.0,
        requires=[
            "jwt_detected == True",
        ],
        boosts={
            "jwt_detected == True": 2.0,
        },
        penalizes={
            "jwt_detected == False": 0.0,
        },
    ),

    # ------------------------------------------------------------------
    # File upload
    # ------------------------------------------------------------------
    "test_upload": ToolRelevance(
        tool_name="test_upload",
        base_priority=8.0,
        impact_potential=5.0,                       # critical — RCE potential
        cost_estimate=4.0,
        requires_any=[
            "has_file_upload == True",
        ],
        boosts={
            "has_file_upload == True": 2.0,
            "backend_language == 'php'": 1.5,
            "backend_language == 'java'": 1.3,
            "waf_detected == False": 1.2,
        },
        penalizes={
            "has_file_upload == False": 0.0,
            "waf_detected == True": 0.7,
        },
    ),

    # ------------------------------------------------------------------
    # Race conditions
    # ------------------------------------------------------------------
    "test_race": ToolRelevance(
        tool_name="test_race",
        base_priority=6.0,
        impact_potential=4.0,
        cost_estimate=3.0,
        boosts={
            "'rest' in api_types": 1.3,
            "'session' in auth_mechanisms": 1.2,
            "backend_language == 'node'": 1.2,
        },
        penalizes={
            "rate_limited == True": 0.5,
            "waf_detected == True": 0.8,
        },
    ),

    # ------------------------------------------------------------------
    # Deserialization
    # ------------------------------------------------------------------
    "test_deserialize": ToolRelevance(
        tool_name="test_deserialize",
        base_priority=7.0,
        impact_potential=5.0,                       # critical — RCE potential
        cost_estimate=5.0,
        requires_any=[
            "backend_language in ['java', 'php', 'python', 'ruby']",
            "framework in ['spring', 'struts', 'laravel', 'symfony', 'django', 'flask', 'rails']",
        ],
        boosts={
            "backend_language == 'java'": 1.5,
            "backend_language == 'php'": 1.3,
            "framework == 'spring'": 1.4,
            "framework == 'struts'": 1.5,
            "error_verbosity == 'high'": 1.2,
        },
        penalizes={
            "backend_language == 'go'": 0.3,
            "waf_detected == True": 0.6,
        },
    ),

    # ------------------------------------------------------------------
    # Subdomain takeover
    # ------------------------------------------------------------------
    "test_takeover": ToolRelevance(
        tool_name="test_takeover",
        base_priority=7.0,
        impact_potential=4.0,
        cost_estimate=3.0,
    ),

    # ------------------------------------------------------------------
    # Open redirect
    # ------------------------------------------------------------------
    "test_redirect": ToolRelevance(
        tool_name="test_redirect",
        base_priority=6.0,
        impact_potential=3.0,
        cost_estimate=2.0,
        boosts={
            "'oauth' in auth_mechanisms": 1.4,      # open redirect critical in OAuth
        },
    ),

    # ------------------------------------------------------------------
    # Clickjacking
    # ------------------------------------------------------------------
    "test_clickjacking": ToolRelevance(
        tool_name="test_clickjacking",
        base_priority=5.0,
        impact_potential=2.0,
        cost_estimate=1.0,                          # very fast header check
    ),

    # ------------------------------------------------------------------
    # Cache poisoning
    # ------------------------------------------------------------------
    "test_cache": ToolRelevance(
        tool_name="test_cache",
        base_priority=6.0,
        impact_potential=4.0,
        cost_estimate=3.0,
    ),

    # ------------------------------------------------------------------
    # HTTP request smuggling
    # ------------------------------------------------------------------
    "test_smuggling": ToolRelevance(
        tool_name="test_smuggling",
        base_priority=7.0,
        impact_potential=5.0,                       # critical — security control bypass
        cost_estimate=4.0,
        boosts={
            "server_software == 'nginx'": 1.2,
            "server_software == 'apache'": 1.2,
        },
    ),

    # ------------------------------------------------------------------
    # CSP analysis
    # ------------------------------------------------------------------
    "test_csp": ToolRelevance(
        tool_name="test_csp",
        base_priority=5.0,
        impact_potential=3.0,
        cost_estimate=1.0,                          # fast header analysis
    ),

    # ------------------------------------------------------------------
    # Business logic
    # ------------------------------------------------------------------
    "test_logic": ToolRelevance(
        tool_name="test_logic",
        base_priority=6.0,
        impact_potential=4.0,
        cost_estimate=4.0,
        boosts={
            "'rest' in api_types": 1.2,
        },
    ),

    # ------------------------------------------------------------------
    # Endpoint fuzzing
    # ------------------------------------------------------------------
    "fuzz_endpoint": ToolRelevance(
        tool_name="fuzz_endpoint",
        base_priority=6.0,
        impact_potential=2.0,
        cost_estimate=5.0,
        boosts={
            "waf_detected == False": 1.2,
        },
        penalizes={
            "rate_limited == True": 0.6,
            "waf_detected == True": 0.7,
        },
    ),
}


# ---------------------------------------------------------------------------
# Indicator → extra boost mapping
# SecurityProfile.indicators() tags that raise a tool's priority
# ---------------------------------------------------------------------------

_INDICATOR_BOOSTS: Dict[str, Dict[str, float]] = {
    "reflection":    {"test_xss": 1.4},
    "sql_error":     {"test_sqli": 1.5},
    "nosql_error":   {"test_injection_nosql": 1.5},
    "stack_trace":   {"test_injection_lfi": 1.3, "test_injection_ssti": 1.3},
    "ssti_pattern":  {"test_injection_ssti": 1.5},
    "idor_pattern":  {"test_idor": 1.4},
}


# ---------------------------------------------------------------------------
# Condition evaluator
# ---------------------------------------------------------------------------

def _evaluate_condition(profile: "TargetProfile", condition: str) -> bool:
    """Evaluate a simple DSL condition string against *profile*.

    Supported patterns::

        field == 'value'
        field == True  /  field == False
        field in ['a', 'b', 'c']
        'value' in field          (list membership)
        field != 'value'
    """
    try:
        ctx: Dict[str, object] = {
            "backend_language":       getattr(profile, "backend_language", "unknown"),
            "framework":              getattr(profile, "framework", "unknown"),
            "frontend_framework":     getattr(profile, "frontend_framework", "unknown"),
            "server_software":        getattr(profile, "server_software", "unknown"),
            "api_types":              getattr(profile, "api_types", []),
            "content_types_accepted": getattr(profile, "content_types_accepted", []),
            "waf_detected":           getattr(profile, "waf_detected", False),
            "waf_vendor":             getattr(profile, "waf_vendor", None),
            "rate_limited":           getattr(profile, "rate_limited", False),
            "cors_enabled":           getattr(profile, "cors_enabled", False),
            "cors_permissive":        getattr(profile, "cors_permissive", False),
            "auth_mechanisms":        getattr(profile, "auth_mechanisms", []),
            "jwt_detected":           getattr(profile, "jwt_detected", False),
            "likely_database":        getattr(profile, "likely_database", None),
            "has_graphql":            getattr(profile, "has_graphql", False),
            "has_websocket":          getattr(profile, "has_websocket", False),
            "has_file_upload":        getattr(profile, "has_file_upload", False),
            "has_search":             getattr(profile, "has_search", False),
            "accepts_xml":            getattr(profile, "accepts_xml", False),
            "error_verbosity":        getattr(profile, "error_verbosity", "low"),
        }

        # ---- field == 'value' (string literal) -------------------------
        if "==" in condition and "'" in condition:
            left, right = condition.split("==", 1)
            field = left.strip()
            value = right.strip().strip("'\"")
            if field in ctx:
                return ctx[field] == value

        # ---- field == True / field == False ----------------------------
        if "== True" in condition or "== False" in condition:
            left, right = condition.split("==", 1)
            field = left.strip()
            want = right.strip() == "True"
            if field in ctx:
                return bool(ctx[field]) == want

        # ---- field in ['a', 'b'] ---------------------------------------
        if " in [" in condition:
            left, right = condition.split(" in ", 1)
            field = left.strip()
            values = [v.strip().strip("'\"") for v in right.strip("[] ").split(",")]
            if field in ctx:
                return ctx[field] in values

        # ---- 'value' in field (list/string membership) -----------------
        if condition.startswith("'") and "' in " in condition:
            left, right = condition.split("' in ", 1)
            value = left.lstrip("'")
            field = right.strip()
            if field in ctx:
                fv = ctx[field]
                if isinstance(fv, (list, str)):
                    return value in fv  # type: ignore[operator]

        # ---- field != 'value' ------------------------------------------
        if "!=" in condition:
            left, right = condition.split("!=", 1)
            field = left.strip()
            value = right.strip().strip("'\"")
            if field in ctx:
                return ctx[field] != value

        return False

    except Exception:  # noqa: BLE001  — conservative: any parse error → False
        return False


# ---------------------------------------------------------------------------
# Condition field-name extractor
# ---------------------------------------------------------------------------

def _condition_field_label(condition: str) -> str:
    """Return the field name referenced by a condition string.

    For ``==`` / ``!=`` conditions the field is the left-hand operand.
    For membership conditions of the form ``'value' in field`` the field is
    the right-hand operand (the container), not the quoted value on the left.
    For ``field in [...]`` conditions the field is the left-hand operand.
    """
    # 'value' in field  →  field (right-hand side)
    if condition.startswith("'") and "' in " in condition:
        _, right = condition.split("' in ", 1)
        return right.strip()
    # field in [...]  →  field (left-hand side)
    if " in [" in condition:
        return condition.split(" in [", 1)[0].strip()
    # field == value  /  field != value  →  field (left-hand side)
    for sep in ("==", "!="):
        if sep in condition:
            return condition.split(sep, 1)[0].strip().strip("'")
    # fallback: return the whole condition stripped
    return condition.strip()


# ---------------------------------------------------------------------------
# ToolRecommender
# ---------------------------------------------------------------------------

class ToolRecommender:
    """Score and rank tools for a given target fingerprint.

    Stateless: safe to instantiate once and reuse across scans.

    Usage::

        rec = ToolRecommender()
        ranked = rec.recommend(profile, security)
        for tool_name, score, reason in ranked:
            print(f"{score:.1f}  {tool_name}  — {reason}")
    """

    def __init__(self, catalog: Optional[Dict[str, ToolRelevance]] = None) -> None:
        self._catalog = catalog if catalog is not None else RELEVANCE

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def recommend(
        self,
        profile: "TargetProfile",
        security: Optional["SecurityProfile"] = None,
    ) -> List[Tuple[str, float, str]]:
        """Return tools ranked by score descending.

        Parameters
        ----------
        profile:
            ``TargetProfile`` from ``core.fingerprint``.
        security:
            Optional ``SecurityProfile`` from ``core.response_analyzer``.
            When provided, active response indicators (e.g. ``sql_error``,
            ``reflection``) apply additional boosts on top of the profile
            boosts.

        Returns
        -------
        list[tuple[str, float, str]]
            Each element is ``(tool_name, score, reason)`` where *reason* is
            a human-readable explanation of what drove the score.  The list
            is sorted by *score* descending; tools that do not meet their
            ``requires`` / ``requires_any`` conditions are omitted.
        """
        # Collect active response-analysis indicator boosts once
        active_indicator_boosts: Dict[str, float] = {}
        if security is not None:
            for indicator in security.indicators():
                for tool, mult in _INDICATOR_BOOSTS.get(indicator, {}).items():
                    # Accumulate: if two indicators both boost the same tool,
                    # take the larger boost rather than multiplying (avoids
                    # runaway scores).
                    existing = active_indicator_boosts.get(tool, 1.0)
                    active_indicator_boosts[tool] = max(existing, mult)

        results: List[Tuple[str, float, str]] = []

        for tool_name, rel in self._catalog.items():
            # ----------------------------------------------------------
            # Gate: requirements
            # ----------------------------------------------------------
            if not self._requirements_met(profile, rel):
                continue

            # ----------------------------------------------------------
            # Compute relevance multiplier from profile boosts/penalizes
            # ----------------------------------------------------------
            relevance_mult = 1.0
            boost_labels: List[str] = []
            penalty_labels: List[str] = []

            for condition, mult in rel.boosts.items():
                if _evaluate_condition(profile, condition):
                    field_label = _condition_field_label(condition)
                    # Confidence-weight: attenuate partial boosts when the
                    # underlying detection is uncertain.
                    confidence = self._field_confidence(profile, field_label)
                    weighted = 1.0 + (mult - 1.0) * confidence
                    relevance_mult *= weighted
                    boost_labels.append(field_label)

            for condition, mult in rel.penalizes.items():
                if _evaluate_condition(profile, condition):
                    field_label = _condition_field_label(condition)
                    confidence = self._field_confidence(profile, field_label)
                    weighted = 1.0 + (mult - 1.0) * confidence
                    relevance_mult *= weighted
                    penalty_labels.append(field_label)

            # ----------------------------------------------------------
            # Apply response-analysis indicator boosts
            # ----------------------------------------------------------
            if tool_name in active_indicator_boosts:
                indicator_mult = active_indicator_boosts[tool_name]
                relevance_mult *= indicator_mult
                boost_labels.append("response_signal")

            # ----------------------------------------------------------
            # Score = (Base × Relevance × Impact) / Cost
            # ----------------------------------------------------------
            score = (rel.base_priority * relevance_mult * rel.impact_potential) / rel.cost_estimate
            score = round(score, 2)

            if score <= 0:
                continue

            # ----------------------------------------------------------
            # Build human-readable reason string
            # ----------------------------------------------------------
            reason = self._build_reason(self.tier(score), boost_labels, penalty_labels, rel)

            results.append((tool_name, score, reason))

        results.sort(key=lambda t: t[1], reverse=True)
        return results

    def tier(self, score: float) -> str:
        """Return the tier label for a given score."""
        if score >= TIER_HIGH:
            return "HIGH"
        if score >= TIER_MEDIUM:
            return "MEDIUM"
        if score >= TIER_LOW:
            return "LOW"
        return "SKIP"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _requirements_met(self, profile: "TargetProfile", rel: ToolRelevance) -> bool:
        """Return True when all ``requires`` and ``requires_any`` conditions hold."""
        for condition in rel.requires:
            if not _evaluate_condition(profile, condition):
                return False

        if rel.requires_any:
            if not any(_evaluate_condition(profile, c) for c in rel.requires_any):
                return False

        return True

    @staticmethod
    def _field_confidence(profile: "TargetProfile", field_label: str) -> float:
        """Return the detection confidence for *field_label*, defaulting to 1.0."""
        _conf_map = {
            "likely_database":  "database_confidence",
            "backend_language": "backend_confidence",
            "framework":        "framework_confidence",
            "waf_detected":     "waf_confidence",
            "waf_vendor":       "waf_confidence",
        }
        attr = _conf_map.get(field_label)
        if attr:
            val = getattr(profile, attr, 1.0)
            # If confidence is 0.0 (never set), treat as 1.0 so we don't
            # silently zero out boosts on profiles that don't track confidence.
            return val if val > 0.0 else 1.0
        return 1.0

    @staticmethod
    def _build_reason(
        tier: str,
        boost_labels: List[str],
        penalty_labels: List[str],
        rel: ToolRelevance,
    ) -> str:
        """Compose a concise human-readable explanation for the score."""
        parts: List[str] = []

        if boost_labels:
            top = ", ".join(boost_labels[:2])
            parts.append(f"boosted by {top}")

        if penalty_labels:
            top = ", ".join(penalty_labels[:2])
            parts.append(f"penalized by {top}")

        _tier_prefix = {
            "HIGH":   "HIGH PRIORITY",
            "MEDIUM": "MEDIUM PRIORITY",
            "LOW":    "LOW PRIORITY",
            "SKIP":   "SKIP",
        }
        parts.insert(0, _tier_prefix.get(tier, tier))

        return "; ".join(parts)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

def get_recommender() -> ToolRecommender:
    """Return a module-level singleton ``ToolRecommender``."""
    if not hasattr(get_recommender, "_instance"):
        get_recommender._instance = ToolRecommender()  # type: ignore[attr-defined]
    return get_recommender._instance  # type: ignore[attr-defined]
