"""
core/response_analyzer.py — HTTP Response Intelligence

Analyzes HTTP responses to extract security-relevant signals that feed into
the intelligent tool-selection pipeline (Recommender, Scheduler).

For each response the analyzer produces a ``SecurityProfile`` capturing
aggregated findings across all analyzed URLs: header and cookie posture,
error patterns, version disclosures, and high-confidence vulnerability
indicators.

Indicator tags returned by ``ResponseAnalyzer.indicators()`` are the stable
contract consumed by downstream layers:

    ``reflection``      — user-controlled input echoed in the response body
    ``sql_error``       — database error message detected
    ``nosql_error``     — NoSQL engine error detected
    ``stack_trace``     — framework / runtime stack trace visible
    ``ssti_pattern``    — server-side template syntax reflected
    ``idor_pattern``    — sequential or user-object ID pattern detected

Usage::

    analyzer = ResponseAnalyzer()
    profile = analyzer.analyze(url, status_code, headers, body)
    tags = analyzer.indicators()      # list[str] of active indicator tags
    summary = profile.get_summary()   # formatted string for LLM context
"""

import hashlib
import json as _json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class _Severity(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class _IndicatorType(Enum):
    REFLECTION = "reflection"
    SQL_ERROR = "sql_error"
    NOSQL_ERROR = "nosql_error"
    STACK_TRACE = "stack_trace"
    PATH_DISCLOSURE = "path_disclosure"
    DEBUG_INFO = "debug_info"
    SSTI_PATTERN = "ssti_pattern"
    IDOR_PATTERN = "idor_pattern"
    SENSITIVE_DATA = "sensitive_data"
    OPEN_REDIRECT = "open_redirect"
    RATE_LIMIT = "rate_limit"
    WAF_BLOCK = "waf_block"


# ---------------------------------------------------------------------------
# Detection pattern tables  (stdlib-only; no network, no weaponization)
# ---------------------------------------------------------------------------

# SQL error signatures — (pattern, db_label)
_SQL_ERROR_PATTERNS: List[Tuple[str, str]] = [
    # MySQL / MariaDB
    (r"SQL syntax.*MySQL", "mysql"),
    (r"Warning.*mysql_", "mysql"),
    (r"MySqlException", "mysql"),
    (r"valid MySQL result", "mysql"),
    (r"mysql_fetch_array\(\)", "mysql"),
    (r"mysql_num_rows\(\)", "mysql"),
    (r"com\.mysql\.jdbc", "mysql"),
    (r"MariaDB server version", "mysql"),
    (r"MySqlClient\.", "mysql"),
    # PostgreSQL
    (r"PostgreSQL.*ERROR", "postgresql"),
    (r"pg_query\(\)", "postgresql"),
    (r"PSQLException", "postgresql"),
    (r"unterminated quoted string at or near", "postgresql"),
    (r"pg_catalog", "postgresql"),
    (r"current_schema\(\)", "postgresql"),
    # Oracle
    (r"ORA-\d{5}", "oracle"),
    (r"Oracle.*Driver", "oracle"),
    (r"quoted string not properly ended", "oracle"),
    (r"oracle\.jdbc", "oracle"),
    # MSSQL
    (r"Microsoft.*ODBC.*SQL Server", "mssql"),
    (r"SQLServer JDBC Driver", "mssql"),
    (r"SqlException", "mssql"),
    (r"System\.Data\.SqlClient", "mssql"),
    (r"\.Net SqlClient Data Provider", "mssql"),
    (r"Msg \d+, Level \d+, State \d+", "mssql"),
    (r"Incorrect syntax near", "mssql"),
    # SQLite
    (r"SQLite.*error", "sqlite"),
    (r"sqlite3\.OperationalError", "sqlite"),
    (r"SQLITE_ERROR", "sqlite"),
    # JDBC / OLE DB
    (r"java\.sql\.SQLException", "sql"),
    (r"JDBC.*Exception", "sql"),
    (r"OLE DB.*error", "sql"),
    (r"Microsoft OLE DB Provider", "sql"),
    # Firebird / MS Access / DB2 / Sybase / Ingres
    (r"Firebird.*error", "firebird"),
    (r"Dynamic SQL Error", "firebird"),
    (r"Microsoft Access Driver", "msaccess"),
    (r"JET Database Engine", "msaccess"),
    (r"DB2 SQL error", "db2"),
    (r"SQLCODE", "db2"),
    (r"Sybase.*error", "sybase"),
    (r"Ingres SQLSTATE", "ingres"),
    # Generic SQL
    (r"SQLSTATE\[", "sql"),
    (r"syntax error at or near", "sql"),
    (r"Unclosed quotation mark", "sql"),
    (r"quoted string not properly terminated", "sql"),
    (r"column count doesn't match", "sql"),
    (r"the used select statements have a different number of columns", "sql"),
]

# NoSQL error signatures
_NOSQL_ERROR_PATTERNS: List[Tuple[str, str]] = [
    (r"MongoError", "mongodb"),
    (r"MongoDB.*Error", "mongodb"),
    (r"E11000 duplicate key", "mongodb"),
    (r"\$where.*function", "mongodb"),
    (r"CouchDB", "couchdb"),
    (r"Redis.*Error", "redis"),
    (r"WRONGTYPE Operation", "redis"),
    (r"RedisSentinelError", "redis"),
    (r"ReplyError", "redis"),
    (r"Elastica\\Exception", "elasticsearch"),
    (r"SearchPhaseExecutionException", "elasticsearch"),
    (r"ArangoDB", "arangodb"),
    (r"CassandraException", "cassandra"),
]

# Stack trace signatures — (pattern, language)
_STACK_TRACE_PATTERNS: List[Tuple[str, str]] = [
    (r"Traceback \(most recent call last\)", "python"),
    (r'File ".*\.py", line \d+', "python"),
    (r"at .*\.java:\d+\)", "java"),
    (r"java\.lang\.\w+Exception", "java"),
    (r"at .*\.php:\d+", "php"),
    (r"Stack trace:.*#\d+", "php"),
    (r"Fatal error:.*in .*\.php", "php"),
    (r"at .*\.rb:\d+", "ruby"),
    (r"from .*\.rb:\d+", "ruby"),
    (r"at .*\.js:\d+:\d+", "node"),
    (r"Error:.*\n.*at ", "node"),
    (r"at .*\.cs:\d+", "dotnet"),
    (r"System\.\w+Exception", "dotnet"),
    (r"panic:.*goroutine", "go"),
]

# Filesystem path disclosure
_PATH_DISCLOSURE_PATTERNS: List[str] = [
    r"/var/www/",
    r"/home/\w+/",
    r"/usr/share/",
    r"C:\\inetpub\\",
    r"C:\\Users\\",
    r"D:\\wwwroot\\",
    r"/opt/\w+/",
    r"/srv/\w+/",
]

# Debug mode indicators
_DEBUG_PATTERNS: List[str] = [
    r"DEBUG\s*=\s*True",
    r"debug.*mode.*enabled",
    r"DJANGO_DEBUG",
    r"APP_DEBUG.*true",
    r"development.*mode",
    r'<div id="debug',
    r"__debug__",
]

# Server-side template injection patterns — (pattern, engine)
_SSTI_PATTERNS: List[Tuple[str, str]] = [
    (r"\{\{.*config.*\}\}", "jinja2"),
    (r"\{\{.*self.*\}\}", "jinja2"),
    (r"<%=.*%>", "erb"),
    (r"\$\{.*\}", "freemarker"),
    (r"#\{.*\}", "thymeleaf"),
    (r"\{\{.*constructor.*\}\}", "angular"),
]

# WAF detection signatures — vendor → [header/body patterns]
_WAF_SIGNATURES: Dict[str, List[str]] = {
    "cloudflare": [r"cloudflare", r"cf-ray", r"__cfduid", r"cf-request-id"],
    "akamai": [r"akamai", r"ak_bmsc", r"akamaitech"],
    "aws_waf": [r"aws", r"x-amzn-requestid", r"awselb"],
    "imperva": [r"incapsula", r"visid_incap", r"imperva"],
    "f5": [
        r"BigIP", r"F5", r"TS[a-f0-9]{8}",
        r"Request Rejected", r"support ID is:", r"The requested URL was rejected",
    ],
    "modsecurity": [r"mod_security", r"NOYB", r"modsec"],
    "sucuri": [r"sucuri", r"x-sucuri"],
    "barracuda": [r"barracuda", r"barra_counter"],
    "fortinet": [r"fortigate", r"fortiweb", r"FortiGuard"],
    "citrix": [r"ns_af", r"citrix", r"NetScaler"],
    "radware": [r"radware", r"appwall"],
}

# Sensitive data patterns — (pattern, data_type_label)
_SENSITIVE_DATA_PATTERNS: List[Tuple[str, str]] = [
    (r"password\s*[=:]\s*['\"][^'\"]+['\"]", "password"),
    (r"api[_-]?key\s*[=:]\s*['\"][^'\"]+['\"]", "api_key"),
    (r"secret\s*[=:]\s*['\"][^'\"]+['\"]", "secret"),
    (r"token\s*[=:]\s*['\"][^'\"]+['\"]", "token"),
    (r"Bearer\s+[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+", "jwt"),
    (r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----", "private_key"),
    (r"-----BEGIN\s+EC\s+PRIVATE\s+KEY-----", "private_key"),
    (r"-----BEGIN\s+OPENSSH\s+PRIVATE\s+KEY-----", "private_key"),
    # Cloud provider keys
    (r"AKIA[A-Z0-9]{16}", "aws_key"),
    (r"ASIA[A-Z0-9]{16}", "aws_temp_key"),
    (r"aws_access_key_id\s*[=:]\s*[A-Z0-9]{20}", "aws_key"),
    (r"aws_secret_access_key\s*[=:]\s*[A-Za-z0-9/+=]{40}", "aws_secret"),
    # SCM tokens
    (r"ghp_[A-Za-z0-9]{36}", "github_pat"),
    (r"gho_[A-Za-z0-9]{36}", "github_oauth"),
    (r"github_pat_[A-Za-z0-9_]{82}", "github_fine_grained"),
    (r"glpat-[A-Za-z0-9\-]{20}", "gitlab_pat"),
    # SaaS keys
    (r"sk-[A-Za-z0-9]{32,}", "openai_style_key"),
    (r"sk_live_[A-Za-z0-9]{24,}", "stripe_live_key"),
    (r"rk_live_[A-Za-z0-9]{24,}", "stripe_restricted_key"),
    (r"sk_test_[A-Za-z0-9]{24,}", "stripe_test_key"),
    (r"xox[baprs]-[A-Za-z0-9\-]{10,}", "slack_token"),
    (r"https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+", "slack_webhook"),
    (r"SG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43}", "sendgrid_key"),
    (r"key-[A-Za-z0-9]{32}", "mailgun_style_key"),
    (r"AIza[A-Za-z0-9\-_]{35}", "google_api_key"),
    (r"ya29\.[A-Za-z0-9_\-]{50,}", "google_oauth"),
    # Connection strings
    (r"mongodb(\+srv)?://[^\s'\"<>]+", "connection_string"),
    (r"postgres(ql)?://[^\s'\"<>]+", "connection_string"),
    (r"mysql://[^\s'\"<>]+", "connection_string"),
    (r"redis://[^\s'\"<>]+", "connection_string"),
    (r"amqp://[^\s'\"<>]+", "connection_string"),
    # PII
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "email"),
    (r"\b\d{3}-\d{2}-\d{4}\b", "ssn"),
    (r"\b\d{16}\b", "card_number"),
]

# Indicator tag → suggested tools mapping
_INDICATOR_TOOL_MAP: Dict[str, List[str]] = {
    "reflection":    ["test_xss"],
    "sql_error":     ["test_sqli"],
    "nosql_error":   ["test_injection_nosql"],
    "stack_trace":   ["test_injection_lfi", "test_injection_ssti"],
    "ssti_pattern":  ["test_injection_ssti"],
    "idor_pattern":  ["test_idor"],
    "path_disclosure": ["test_injection_lfi"],
    "debug_info":    ["test_injection_ssti", "test_injection_lfi"],
    "sensitive_data": [],
    "open_redirect": ["test_open_redirect"],
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class _VulnSignal:
    """Internal — a single potential vulnerability signal."""
    itype: _IndicatorType
    severity: _Severity
    url: str
    evidence: str
    context: str = ""
    parameter: str = ""
    confidence: float = 0.5
    suggested_tools: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "type": self.itype.value,
            "severity": self.severity.value,
            "url": self.url,
            "evidence": self.evidence[:500],
            "context": self.context,
            "parameter": self.parameter,
            "confidence": self.confidence,
            "suggested_tools": self.suggested_tools,
        }


@dataclass
class _HeaderPosture:
    """Header-level security posture for a single response."""
    has_csp: bool = False
    has_hsts: bool = False
    has_x_frame_options: bool = False
    has_x_content_type_options: bool = False
    has_x_xss_protection: bool = False
    has_referrer_policy: bool = False
    has_permissions_policy: bool = False

    csp_policy: str = ""
    hsts_max_age: int = 0
    x_frame_options: str = ""

    server_header: str = ""
    x_powered_by: str = ""
    x_aspnet_version: str = ""
    x_debug: str = ""

    cors_allow_origin: str = ""
    cors_allow_credentials: bool = False
    cors_allow_methods: List[str] = field(default_factory=list)
    content_type: str = ""

    issues: List[str] = field(default_factory=list)

    def security_score(self) -> int:
        """0-100 score — higher is more secure."""
        score = 0
        if self.has_csp:
            score += 20
        if self.has_hsts and self.hsts_max_age >= 31_536_000:
            score += 15
        if self.has_x_frame_options:
            score += 10
        if self.has_x_content_type_options:
            score += 10
        if self.has_referrer_policy:
            score += 10
        if not self.server_header:
            score += 10
        if not self.x_powered_by:
            score += 10
        if self.cors_allow_origin != "*":
            score += 15
        return score


@dataclass
class _CookiePosture:
    """Cookie-level security posture."""
    name: str
    value_hash: str
    secure: bool = False
    http_only: bool = False
    same_site: str = "none"
    is_session: bool = False
    looks_like_token: bool = False
    looks_like_jwt: bool = False
    issues: List[str] = field(default_factory=list)

    def risk_score(self) -> int:
        score = 0
        if not self.secure:
            score += 3
        if not self.http_only:
            score += 3
        if self.same_site == "none":
            score += 2
        if self.looks_like_token and not self.http_only:
            score += 2
        return min(10, score)


@dataclass
class SecurityProfile:
    """
    Aggregated security profile built from all responses analyzed so far.

    This is the primary output of ``ResponseAnalyzer`` and is passed directly
    to the Recommender (Task 4) which reads ``suggested_tools`` and the
    indicator-count fields to score tool relevance.
    """
    total_responses: int = 0

    # Header posture
    avg_header_security_score: float = 0.0
    missing_security_headers: Set[str] = field(default_factory=set)

    # Cookie posture
    insecure_cookies: int = 0
    session_cookies_without_httponly: int = 0
    cookies_without_secure: int = 0

    # Disclosure
    server_versions_found: Set[str] = field(default_factory=set)
    technologies_detected: Set[str] = field(default_factory=set)

    # Vulnerability indicator counts  (key = _IndicatorType.value string)
    indicator_counts: Dict[str, int] = field(default_factory=dict)
    # Signals with confidence >= 0.7 stored for summary / LLM context
    high_confidence_signals: List[_VulnSignal] = field(default_factory=list)

    # Behavioral
    error_rate: float = 0.0
    rate_limit_detected: bool = False
    waf_detected: bool = False
    waf_vendors: Set[str] = field(default_factory=set)

    # Status distribution
    status_code_distribution: Dict[int, int] = field(default_factory=dict)
    avg_response_time: float = 0.0

    # Tool suggestions derived from indicators — tool_name → max_confidence
    suggested_tools: Dict[str, float] = field(default_factory=dict)

    # Active indicator tag strings (the stable contract for the Recommender)
    _active_tags: Set[str] = field(default_factory=set, repr=False, compare=False)

    def indicators(self) -> List[str]:
        """Return the active indicator tag strings, sorted.

        The accessor lives here because the profile is what travels: the
        Recommender's ``recommend(profile, security)`` is handed a
        ``SecurityProfile`` and reads the tags off it, so an accessor that
        existed only on ``ResponseAnalyzer`` left that signature raising
        ``AttributeError`` on its first call.  ``ResponseAnalyzer.indicators()``
        delegates here, so there is one implementation and one tag set.
        """
        return sorted(self._active_tags)

    def get_summary(self) -> str:
        """Human-readable summary suitable for LLM context injection."""
        lines = ["## Response Analysis Profile"]
        lines.append(f"Responses analyzed: {self.total_responses}")
        lines.append(f"Header security score: {self.avg_header_security_score:.0f}/100")

        if self.missing_security_headers:
            lines.append(
                "Missing headers: " + ", ".join(sorted(self.missing_security_headers)[:5])
            )
        if self.insecure_cookies > 0:
            lines.append(f"Insecure cookies: {self.insecure_cookies}")
        if self.technologies_detected:
            lines.append(
                "Technologies: " + ", ".join(sorted(self.technologies_detected)[:10])
            )
        if self.high_confidence_signals:
            lines.append("\n**High-Confidence Vulnerability Indicators:**")
            for sig in self.high_confidence_signals[:5]:
                lines.append(
                    f"  - [{sig.severity.value.upper()}] "
                    f"{sig.itype.value}: {sig.evidence[:100]}"
                )
        if self.suggested_tools:
            lines.append("\n**Suggested Tools (from response analysis):**")
            for tool, conf in sorted(
                self.suggested_tools.items(), key=lambda x: x[1], reverse=True
            )[:7]:
                lines.append(f"  - {tool}: {conf:.0%} confidence")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main analyzer
# ---------------------------------------------------------------------------

class ResponseAnalyzer:
    """
    Stateful HTTP response analyzer.

    Call ``analyze(url, status, headers, body)`` for each response.  The
    method updates an internal ``SecurityProfile`` and returns it.

    ``indicators()`` returns the set of active indicator tag strings so
    the Recommender can map them directly to suggested tools.
    """

    def __init__(self) -> None:
        self._profile = SecurityProfile()
        self._header_scores: List[int] = []
        self._response_times: List[float] = []
        self._reflected_params: Dict[str, Set[str]] = defaultdict(set)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def analyze(
        self,
        url: str,
        status: int,
        headers: Dict[str, str],
        body: str,
        *,
        response_time: float = 0.0,
        request_params: Optional[Dict[str, str]] = None,
        cookies: Optional[List[Dict]] = None,
    ) -> "SecurityProfile":
        """
        Analyze a single HTTP response and update the cumulative profile.

        Args:
            url:            The request URL.
            status:         HTTP status code.
            headers:        Response headers (case-insensitive matching applied
                            internally).
            body:           Response body text.
            response_time:  Round-trip time in seconds (optional).
            request_params: Parameters sent in the request — used for
                            reflection detection.
            cookies:        List of cookie dicts with keys ``name``,
                            ``value``, ``secure``, ``httpOnly``,
                            ``sameSite`` (optional).

        Returns:
            The updated ``SecurityProfile``.
        """
        hdrs = {k.lower(): v for k, v in (headers or {}).items()}
        params = request_params or {}
        cookie_list = cookies or []

        signals: List[_VulnSignal] = []

        # --- header posture ---
        header_posture = self._parse_headers(hdrs, url, signals)
        self._header_scores.append(header_posture.security_score())
        self._response_times.append(response_time)

        # --- cookie posture ---
        cookie_postures = [self._parse_cookie(c) for c in cookie_list]

        # --- rate-limit / WAF detection ---
        if self._is_rate_limited(status, hdrs, body):
            signals.append(
                _VulnSignal(
                    _IndicatorType.RATE_LIMIT, _Severity.INFO, url,
                    "Rate-limiting signal detected", confidence=0.9,
                    suggested_tools=[],
                )
            )
            self._profile.rate_limit_detected = True

        waf_hit = self._detect_waf(status, hdrs, body)
        if waf_hit:
            self._profile.waf_detected = True
            self._profile.waf_vendors.update(waf_hit)

        # --- redirect open-redirect check ---
        if status in (301, 302, 303, 307, 308):
            redirect_target = hdrs.get("location", "")
            self._check_open_redirect(url, redirect_target, params, signals)

        # --- body analysis ---
        if body and status not in (301, 302, 303, 307, 308):
            self._analyze_body(url, body, params, hdrs, signals)

        # --- aggregate into profile ---
        self._update_profile(
            url, status, response_time,
            header_posture, cookie_postures, signals,
        )

        return self._profile

    def indicators(self) -> List[str]:
        """
        Return the list of active indicator tag strings.

        Tags are drawn from the stable set:
            ``reflection``, ``sql_error``, ``nosql_error``,
            ``stack_trace``, ``ssti_pattern``, ``idor_pattern``
        (plus lower-priority tags when present).

        The Recommender uses these tags to boost tool scores.
        """
        return self._profile.indicators()

    def get_security_profile(self) -> SecurityProfile:
        """Return the current aggregated SecurityProfile."""
        return self._profile

    def get_reflected_parameters(self) -> Dict[str, List[str]]:
        """Return {param_name: [url, ...]} for all reflected parameters."""
        return {p: sorted(urls) for p, urls in self._reflected_params.items()}

    def reset(self) -> None:
        """Reset all state — starts a fresh analysis session."""
        self._profile = SecurityProfile()
        self._header_scores = []
        self._response_times = []
        self._reflected_params = defaultdict(set)

    # ------------------------------------------------------------------
    # Internal — header / cookie parsing
    # ------------------------------------------------------------------

    def _parse_headers(
        self,
        hdrs: Dict[str, str],
        url: str,
        signals: List[_VulnSignal],
    ) -> _HeaderPosture:
        posture = _HeaderPosture()

        # Security headers presence
        if "content-security-policy" in hdrs:
            posture.has_csp = True
            posture.csp_policy = hdrs["content-security-policy"]
        else:
            posture.issues.append("Missing Content-Security-Policy")

        if "strict-transport-security" in hdrs:
            posture.has_hsts = True
            m = re.search(r"max-age=(\d+)", hdrs["strict-transport-security"])
            if m:
                posture.hsts_max_age = int(m.group(1))
                if posture.hsts_max_age < 31_536_000:
                    posture.issues.append(
                        f"HSTS max-age too short: {posture.hsts_max_age}"
                    )
        else:
            posture.issues.append("Missing Strict-Transport-Security")

        if "x-frame-options" in hdrs:
            posture.has_x_frame_options = True
            posture.x_frame_options = hdrs["x-frame-options"]
        else:
            posture.issues.append("Missing X-Frame-Options")

        if "x-content-type-options" in hdrs:
            posture.has_x_content_type_options = True
        else:
            posture.issues.append("Missing X-Content-Type-Options")

        if "x-xss-protection" in hdrs:
            posture.has_x_xss_protection = True

        if "referrer-policy" in hdrs:
            posture.has_referrer_policy = True
        else:
            posture.issues.append("Missing Referrer-Policy")

        if "permissions-policy" in hdrs or "feature-policy" in hdrs:
            posture.has_permissions_policy = True

        # Information disclosure headers
        if "server" in hdrs:
            posture.server_header = hdrs["server"]
            posture.issues.append(f"Server header discloses: {posture.server_header}")

        if "x-powered-by" in hdrs:
            posture.x_powered_by = hdrs["x-powered-by"]
            posture.issues.append(
                f"X-Powered-By discloses: {posture.x_powered_by}"
            )

        if "x-aspnet-version" in hdrs:
            posture.x_aspnet_version = hdrs["x-aspnet-version"]
            posture.issues.append(
                f"ASP.NET version disclosed: {posture.x_aspnet_version}"
            )

        if "x-debug" in hdrs or "x-debug-token" in hdrs:
            posture.x_debug = hdrs.get("x-debug", hdrs.get("x-debug-token", ""))
            posture.issues.append("Debug header present")

        # CORS
        if "access-control-allow-origin" in hdrs:
            posture.cors_allow_origin = hdrs["access-control-allow-origin"]
            if posture.cors_allow_origin == "*":
                posture.issues.append("CORS allows all origins (*)")

        if "access-control-allow-credentials" in hdrs:
            if hdrs["access-control-allow-credentials"].lower() == "true":
                posture.cors_allow_credentials = True
                if posture.cors_allow_origin == "*":
                    posture.issues.append(
                        "CRITICAL: CORS credentials with wildcard origin"
                    )

        if "access-control-allow-methods" in hdrs:
            posture.cors_allow_methods = [
                m.strip()
                for m in hdrs["access-control-allow-methods"].split(",")
            ]

        posture.content_type = hdrs.get("content-type", "")
        return posture

    def _parse_cookie(self, cookie: Dict) -> _CookiePosture:
        name = cookie.get("name", "")
        value = cookie.get("value", "")
        posture = _CookiePosture(
            name=name,
            value_hash=hashlib.sha256(value.encode()).hexdigest()[:16],
            secure=bool(cookie.get("secure", False)),
            http_only=bool(cookie.get("httpOnly", False)),
            same_site=(cookie.get("sameSite", "none") or "none").lower(),
        )
        session_indicators = {"session", "sess", "sid", "phpsessid", "jsessionid", "asp.net"}
        posture.is_session = any(ind in name.lower() for ind in session_indicators)
        if len(value) > 20:
            posture.looks_like_token = True
        if value.count(".") == 2 and len(value) > 50:
            parts = value.split(".")
            if all(len(p) > 10 for p in parts):
                posture.looks_like_jwt = True

        if not posture.secure:
            posture.issues.append("Cookie missing Secure flag")
        if not posture.http_only:
            posture.issues.append("Cookie missing HttpOnly flag")
            if posture.is_session or posture.looks_like_token:
                posture.issues.append(
                    "CRITICAL: Session/token cookie without HttpOnly"
                )
        if posture.same_site == "none":
            posture.issues.append("Cookie SameSite=None (CSRF risk)")

        return posture

    # ------------------------------------------------------------------
    # Internal — body analysis
    # ------------------------------------------------------------------

    def _analyze_body(
        self,
        url: str,
        body: str,
        params: Dict[str, str],
        hdrs: Dict[str, str],
        signals: List[_VulnSignal],
    ) -> None:
        # Reflection detection
        for param, value in params.items():
            if value and len(value) > 3 and value in body:
                self._reflected_params[param].add(url)
                ctx = self._reflection_context(body, value)
                confidence = 0.7 if ("<" in ctx or "'" in ctx) else 0.5
                signals.append(_VulnSignal(
                    _IndicatorType.REFLECTION,
                    _Severity.MEDIUM if "script" in ctx.lower() else _Severity.LOW,
                    url,
                    f"Parameter '{param}' reflected in response",
                    context=ctx[:200],
                    parameter=param,
                    confidence=confidence,
                    suggested_tools=list(_INDICATOR_TOOL_MAP["reflection"]),
                ))

        # SQL errors
        for pattern, db_label in _SQL_ERROR_PATTERNS:
            m = re.search(pattern, body, re.IGNORECASE)
            if m:
                signals.append(_VulnSignal(
                    _IndicatorType.SQL_ERROR, _Severity.HIGH, url,
                    m.group(0)[:200],
                    confidence=0.9,
                    suggested_tools=list(_INDICATOR_TOOL_MAP["sql_error"]),
                ))
                self._profile.technologies_detected.add(db_label)
                break  # one match is sufficient

        # NoSQL errors
        for pattern, db_label in _NOSQL_ERROR_PATTERNS:
            m = re.search(pattern, body, re.IGNORECASE)
            if m:
                signals.append(_VulnSignal(
                    _IndicatorType.NOSQL_ERROR, _Severity.HIGH, url,
                    m.group(0)[:200],
                    confidence=0.85,
                    suggested_tools=list(_INDICATOR_TOOL_MAP["nosql_error"]),
                ))
                self._profile.technologies_detected.add(db_label)
                break

        # Stack traces
        for pattern, lang in _STACK_TRACE_PATTERNS:
            m = re.search(pattern, body, re.IGNORECASE | re.MULTILINE)
            if m:
                signals.append(_VulnSignal(
                    _IndicatorType.STACK_TRACE, _Severity.MEDIUM, url,
                    m.group(0)[:300],
                    confidence=0.95,
                    suggested_tools=list(_INDICATOR_TOOL_MAP["stack_trace"]),
                ))
                self._profile.technologies_detected.add(lang)
                break

        # Path disclosure
        for pattern in _PATH_DISCLOSURE_PATTERNS:
            m = re.search(pattern, body)
            if m:
                signals.append(_VulnSignal(
                    _IndicatorType.PATH_DISCLOSURE, _Severity.LOW, url,
                    m.group(0),
                    confidence=0.8,
                    suggested_tools=list(_INDICATOR_TOOL_MAP["path_disclosure"]),
                ))
                break

        # Debug mode indicators
        for pattern in _DEBUG_PATTERNS:
            m = re.search(pattern, body, re.IGNORECASE)
            if m:
                signals.append(_VulnSignal(
                    _IndicatorType.DEBUG_INFO, _Severity.MEDIUM, url,
                    m.group(0),
                    confidence=0.9,
                    suggested_tools=list(_INDICATOR_TOOL_MAP["debug_info"]),
                ))
                break

        # SSTI patterns
        for pattern, engine in _SSTI_PATTERNS:
            m = re.search(pattern, body, re.IGNORECASE)
            if m:
                signals.append(_VulnSignal(
                    _IndicatorType.SSTI_PATTERN, _Severity.MEDIUM, url,
                    m.group(0),
                    confidence=0.6,
                    suggested_tools=list(_INDICATOR_TOOL_MAP["ssti_pattern"]),
                ))
                self._profile.technologies_detected.add(engine)
                # Keep going — multiple engine signals are informative

        # Sensitive data
        for pattern, dtype in _SENSITIVE_DATA_PATTERNS:
            matches = re.findall(pattern, body, re.IGNORECASE)
            if matches and len(matches) < 10:
                sev = (
                    _Severity.HIGH
                    if dtype in ("password", "private_key", "aws_key")
                    else _Severity.MEDIUM
                )
                signals.append(_VulnSignal(
                    _IndicatorType.SENSITIVE_DATA, sev, url,
                    f"Found {len(matches)} {dtype} pattern(s)",
                    confidence=0.7,
                    suggested_tools=[],
                ))

        # IDOR — sequential numeric IDs in body
        idor_id_patterns = [
            r'"id"\s*:\s*(\d+)',
            r'"user_id"\s*:\s*(\d+)',
            r'"order_id"\s*:\s*(\d+)',
            r'/api/\w+/(\d+)',
        ]
        for pattern in idor_id_patterns:
            found = re.findall(pattern, body)
            if found:
                try:
                    nums = [int(x) for x in found[:10]]
                    if len(nums) > 1 and (max(nums) - min(nums)) < 100:
                        signals.append(_VulnSignal(
                            _IndicatorType.IDOR_PATTERN, _Severity.MEDIUM, url,
                            f"Sequential numeric IDs: {nums[:5]}",
                            confidence=0.6,
                            suggested_tools=list(_INDICATOR_TOOL_MAP["idor_pattern"]),
                        ))
                        break
                except (ValueError, OverflowError):
                    pass

        # IDOR — JSON user-object field overlap
        ctype = hdrs.get("content-type", "")
        if "json" in ctype and body.strip().startswith("{"):
            try:
                data = _json.loads(body)
                user_fields = {
                    "id", "user_id", "email", "username", "phone", "name",
                    "address", "role", "created_at", "account_id", "profile",
                }
                if isinstance(data, dict):
                    inner: Dict = data
                    for wrapper in ("data", "result", "user", "response", "payload"):
                        if (
                            len(data) <= 3
                            and wrapper in data
                            and isinstance(data[wrapper], dict)
                        ):
                            inner = data[wrapper]
                            break
                    overlap = {k.lower() for k in inner.keys()} & user_fields
                    if len(overlap) >= 3:
                        signals.append(_VulnSignal(
                            _IndicatorType.IDOR_PATTERN, _Severity.HIGH, url,
                            f"JSON user-object fields: {sorted(overlap)}",
                            confidence=0.8,
                            suggested_tools=list(_INDICATOR_TOOL_MAP["idor_pattern"]),
                        ))
            except (ValueError, TypeError, KeyError):
                pass

    # ------------------------------------------------------------------
    # Internal — behavioral checks
    # ------------------------------------------------------------------

    def _is_rate_limited(
        self,
        status: int,
        hdrs: Dict[str, str],
        body: str,
    ) -> bool:
        if status == 429:
            return True
        for h in ("x-ratelimit-remaining", "x-rate-limit-remaining"):
            if h in hdrs:
                try:
                    if int(hdrs[h]) == 0:
                        return True
                except (ValueError, TypeError):
                    pass
        if "retry-after" in hdrs:
            return True
        body_lower = body.lower()
        for pattern in (r"rate.?limit", r"too.?many.?requests", r"throttl", r"slow.?down"):
            if re.search(pattern, body_lower):
                return True
        return False

    def _detect_waf(
        self,
        status: int,
        hdrs: Dict[str, str],
        body: str,
    ) -> List[str]:
        combined = str(hdrs).lower() + body.lower()
        found = []
        for vendor, patterns in _WAF_SIGNATURES.items():
            for pattern in patterns:
                if re.search(pattern, combined, re.IGNORECASE):
                    found.append(vendor)
                    break
        # Blocking status codes are an additional confidence signal, not a precondition.
        # WAFs (e.g. Cloudflare, Akamai) frequently return 200 with a challenge page
        # or set WAF cookies (__cfduid, ak_bmsc) on otherwise-normal responses.
        if status in (403, 406, 501) and not found:
            pass  # status alone is not enough to declare a WAF without a signature
        return found

    def _check_open_redirect(
        self,
        url: str,
        redirect_target: str,
        params: Dict[str, str],
        signals: List[_VulnSignal],
    ) -> None:
        if not redirect_target or not params:
            return
        for param, value in params.items():
            if value and value.lower() in redirect_target.lower():
                try:
                    parsed_redir = urlparse(redirect_target)
                    parsed_orig = urlparse(url)
                    if parsed_redir.netloc and parsed_redir.netloc != parsed_orig.netloc:
                        signals.append(_VulnSignal(
                            _IndicatorType.OPEN_REDIRECT, _Severity.MEDIUM, url,
                            (
                                f"Parameter '{param}' controls redirect to: "
                                f"{redirect_target[:100]}"
                            ),
                            parameter=param,
                            confidence=0.85,
                            suggested_tools=list(_INDICATOR_TOOL_MAP["open_redirect"]),
                        ))
                except ValueError:
                    pass

    # ------------------------------------------------------------------
    # Internal — profile aggregation
    # ------------------------------------------------------------------

    def _update_profile(
        self,
        url: str,
        status: int,
        response_time: float,
        header_posture: _HeaderPosture,
        cookie_postures: List[_CookiePosture],
        signals: List[_VulnSignal],
    ) -> None:
        p = self._profile
        p.total_responses += 1

        # Header stats
        if self._header_scores:
            p.avg_header_security_score = (
                sum(self._header_scores) / len(self._header_scores)
            )
        if not header_posture.has_csp:
            p.missing_security_headers.add("CSP")
        if not header_posture.has_hsts:
            p.missing_security_headers.add("HSTS")
        if not header_posture.has_x_frame_options:
            p.missing_security_headers.add("X-Frame-Options")
        if not header_posture.has_x_content_type_options:
            p.missing_security_headers.add("X-Content-Type-Options")
        if not header_posture.has_referrer_policy:
            p.missing_security_headers.add("Referrer-Policy")

        if header_posture.server_header:
            p.server_versions_found.add(header_posture.server_header)
        if header_posture.x_powered_by:
            p.server_versions_found.add(header_posture.x_powered_by)

        # Cookie stats
        for cp in cookie_postures:
            if not cp.secure:
                p.cookies_without_secure += 1
            if cp.is_session and not cp.http_only:
                p.session_cookies_without_httponly += 1
            if cp.issues:
                p.insecure_cookies += 1

        # Signals / indicators
        for sig in signals:
            tag = sig.itype.value
            p.indicator_counts[tag] = p.indicator_counts.get(tag, 0) + 1
            p._active_tags.add(tag)
            if sig.confidence >= 0.7:
                p.high_confidence_signals.append(sig)
            for tool in sig.suggested_tools:
                current = p.suggested_tools.get(tool, 0.0)
                p.suggested_tools[tool] = max(current, sig.confidence)

        # Status distribution + error rate
        p.status_code_distribution[status] = (
            p.status_code_distribution.get(status, 0) + 1
        )
        error_count = sum(
            cnt for code, cnt in p.status_code_distribution.items() if code >= 400
        )
        p.error_rate = error_count / p.total_responses

        # Response time
        if self._response_times:
            p.avg_response_time = (
                sum(self._response_times) / len(self._response_times)
            )

    # ------------------------------------------------------------------
    # Internal — helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _reflection_context(body: str, value: str) -> str:
        idx = body.find(value)
        if idx < 0:
            return ""
        start = max(0, idx - 50)
        end = min(len(body), idx + len(value) + 50)
        return body[start:end]
