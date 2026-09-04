"""
core/fingerprint.py — Layer 1: Target Profiling

Passive heuristic fingerprinting of a web target from already-collected HTTP
responses (headers, body, URL).  No live requests are issued here; the caller
is responsible for gathering responses and passing them to ``Fingerprinter.analyze()``.

Active-probe methods (GraphQL introspection POST, WebSocket upgrade) keep their
signatures but raise ``NotImplementedError`` — they are withheld from this
public repository because they send live network requests.

Profile-hash format consumed by downstream layers (recommender / scheduler / memory):
    ``"backend:database:waf_status:waf_vendor:api_type:framework"``

Examples:
    ``"php:mysql:waf:cloudflare:rest:laravel"``
    ``"nodejs:mongodb:nowaf:none:rest:express"``
    ``"java:postgresql:waf:akamai:rest:spring"``
"""

import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Detection signature tables
# ---------------------------------------------------------------------------

# Each entry: list of (regex_pattern, confidence_weight) tuples.
# Weights are additive across evidence sources; the language/framework with
# the highest cumulative score wins (threshold 0.5).

BACKEND_SIGNATURES: Dict[str, Dict[str, List]] = {
    "php": {
        "headers": [
            (r"X-Powered-By.*PHP", 0.9),
            (r"Set-Cookie.*PHPSESSID", 0.95),
        ],
        "urls": [
            (r"\.php(\?|$|/)", 0.9),
            (r"/wp-content/", 0.8),
            (r"/wp-admin/", 0.8),
        ],
        "body": [
            (r"<\?php", 0.95),
            (r"Parse error.*\.php", 0.9),
            (r"Fatal error.*\.php", 0.9),
            (r'(href|action|src)\s*=\s*["\'][^"\']*\.php', 0.85),
            (r"\.php\?", 0.8),
        ],
        "errors": [
            (r"mysql_", 0.7),
            (r"mysqli_", 0.7),
            (r"pg_query", 0.6),
        ],
    },
    "python": {
        "headers": [
            (r"X-Powered-By.*Python", 0.9),
            (r"Server.*Python", 0.8),
            (r"Server.*Gunicorn", 0.85),
            (r"Server.*uWSGI", 0.85),
            (r"Server.*Waitress", 0.8),
        ],
        "urls": [
            (r"\.py(\?|$)", 0.7),
        ],
        "body": [
            (r"Traceback \(most recent call last\)", 0.95),
            (r"File \".*\.py\"", 0.9),
            (r"django\.core", 0.9),
            (r"flask\.app", 0.9),
        ],
        "errors": [
            (r"psycopg2", 0.7),
            (r"pymongo", 0.7),
            (r"SQLAlchemy", 0.7),
        ],
    },
    "java": {
        "headers": [
            (r"X-Powered-By.*Servlet", 0.9),
            (r"X-Powered-By.*JSP", 0.9),
            (r"Set-Cookie.*JSESSIONID", 0.95),
            (r"Server.*Tomcat", 0.9),
            (r"Server.*JBoss", 0.9),
            (r"Server.*WildFly", 0.9),
            (r"Server.*WebLogic", 0.9),
            (r"Server.*WebSphere", 0.9),
        ],
        "urls": [
            (r"\.jsp(\?|$)", 0.9),
            (r"\.do(\?|$)", 0.8),
            (r"\.action(\?|$)", 0.8),
            (r"/servlet/", 0.85),
        ],
        "body": [
            (r"java\.lang\.", 0.95),
            (r"javax\.", 0.9),
            (r"org\.springframework", 0.9),
            (r"at .+\.java:\d+", 0.9),
        ],
        "errors": [
            (r"java\.sql\.SQLException", 0.85),
            (r"SQLException", 0.4),
            (r"JDBCException", 0.8),
            (r"HibernateException", 0.8),
        ],
    },
    "node": {
        "headers": [
            (r"X-Powered-By.*Express", 0.95),
            (r"Set-Cookie.*connect\.sid", 0.9),
        ],
        "urls": [],
        "body": [
            (r"Cannot (GET|POST|PUT|DELETE)", 0.85),
            (r"at .+\.js:\d+:\d+", 0.85),
            (r"node_modules", 0.8),
            (r"ReferenceError:", 0.7),
            (r"TypeError:", 0.6),
        ],
        "errors": [
            (r"MongoError", 0.8),
            (r"SequelizeError", 0.8),
        ],
    },
    "ruby": {
        "headers": [
            (r"X-Powered-By.*Phusion", 0.9),
            (r"X-Runtime", 0.6),
            (r"Set-Cookie.*_session", 0.5),
            (r"Server.*Puma", 0.9),
            (r"Server.*Unicorn", 0.9),
        ],
        "urls": [
            (r"\.rb(\?|$)", 0.8),
        ],
        "body": [
            (r"ActionController", 0.9),
            (r"ActiveRecord", 0.9),
            (r"\.rb:\d+:in", 0.9),
        ],
        "errors": [
            (r"PG::Error", 0.8),
            (r"Mysql2::Error", 0.8),
        ],
    },
    "dotnet": {
        "headers": [
            (r"X-Powered-By.*ASP\.NET", 0.95),
            (r"X-AspNet-Version", 0.95),
            (r"X-AspNetMvc-Version", 0.95),
            (r"Set-Cookie.*ASP\.NET_SessionId", 0.95),
            (r"Set-Cookie.*\.AspNetCore", 0.95),
            (r"Server.*Microsoft-IIS", 0.9),
        ],
        "urls": [
            (r"\.aspx?(\?|$)", 0.95),
            (r"\.ashx(\?|$)", 0.9),
            (r"\.asmx(\?|$)", 0.9),
        ],
        "body": [
            (r"System\.Web", 0.9),
            (r"__VIEWSTATE", 0.95),
            (r"__EVENTVALIDATION", 0.9),
            (r"at .+\.cs:line \d+", 0.9),
        ],
        "errors": [
            (r"System\.Data\.SqlClient", 0.8),
            (r"SqlException", 0.4),
        ],
    },
    "go": {
        "headers": [
            (r"Server.*Go-http-server", 0.9),
        ],
        "urls": [],
        "body": [
            (r"runtime error:", 0.8),
            (r"goroutine \d+", 0.9),
            (r"\.go:\d+", 0.85),
        ],
        "errors": [],
    },
}

FRAMEWORK_SIGNATURES: Dict[str, Dict[str, List]] = {
    # PHP
    "laravel": {
        "headers": [(r"Set-Cookie.*laravel_session", 0.95)],
        "body": [
            (r"laravel", 0.7),
            (r"Illuminate\\", 0.95),
            (r"csrf_token", 0.5),
        ],
        "urls": [(r"/storage/", 0.5)],
    },
    "wordpress": {
        "headers": [],
        "body": [
            (r"wp-content", 0.9),
            (r"wp-includes", 0.9),
            (r"WordPress", 0.8),
        ],
        "urls": [
            (r"/wp-admin", 0.95),
            (r"/wp-json/", 0.9),
            (r"/xmlrpc\.php", 0.9),
        ],
    },
    "drupal": {
        "headers": [(r"X-Drupal-Cache", 0.95), (r"X-Generator.*Drupal", 0.95)],
        "body": [(r"Drupal", 0.7), (r"drupal\.js", 0.9)],
        "urls": [(r"/sites/default/", 0.8)],
    },
    "symfony": {
        "headers": [],
        "body": [(r"symfony", 0.7), (r"Symfony\\", 0.95)],
        "urls": [(r"/app\.php", 0.8), (r"/app_dev\.php", 0.9)],
    },
    # Python
    "django": {
        "headers": [],
        "body": [
            (r"csrfmiddlewaretoken", 0.9),
            (r"django", 0.6),
            (r"__debug__", 0.7),
        ],
        "urls": [(r"/admin/", 0.4)],
    },
    "flask": {
        "headers": [],
        "body": [(r"flask", 0.6), (r"Werkzeug", 0.85)],
        "urls": [],
    },
    "fastapi": {
        "headers": [],
        "body": [(r"fastapi", 0.8)],
        "urls": [(r"/docs", 0.5), (r"/openapi\.json", 0.8)],
    },
    # Java
    "spring": {
        "headers": [],
        "body": [
            (r"org\.springframework", 0.95),
            (r"Spring Framework", 0.9),
            (r"Whitelabel Error Page", 0.9),
        ],
        "urls": [(r"/actuator", 0.9)],
    },
    "struts": {
        "headers": [],
        "body": [(r"struts", 0.7), (r"org\.apache\.struts", 0.95)],
        "urls": [(r"\.action(\?|$)", 0.7)],
    },
    # Node
    "express": {
        "headers": [(r"X-Powered-By.*Express", 0.95)],
        "body": [(r"Cannot (GET|POST)", 0.7)],
        "urls": [],
    },
    "nextjs": {
        "headers": [(r"X-Powered-By.*Next\.js", 0.95)],
        "body": [(r"__NEXT_DATA__", 0.95), (r"_next/static", 0.9)],
        "urls": [(r"/_next/", 0.9)],
    },
    "nuxt": {
        "headers": [],
        "body": [(r"__NUXT__", 0.95), (r"_nuxt/", 0.9)],
        "urls": [(r"/_nuxt/", 0.9)],
    },
    # Ruby
    "rails": {
        "headers": [(r"X-Runtime", 0.5)],
        "body": [
            (r"Rails", 0.6),
            (r"ActionController", 0.95),
            (r"data-turbo", 0.8),
        ],
        "urls": [],
    },
    # .NET
    "aspnet_mvc": {
        "headers": [(r"X-AspNetMvc-Version", 0.95)],
        "body": [(r"@Html\.", 0.8)],
        "urls": [],
    },
    "aspnet_core": {
        "headers": [(r"Set-Cookie.*\.AspNetCore", 0.95)],
        "body": [],
        "urls": [],
    },
}

WAF_SIGNATURES: Dict[str, Dict[str, List]] = {
    "cloudflare": {
        "headers": [
            (r"Server.*cloudflare", 0.95),
            (r"CF-RAY", 0.95),
            (r"cf-cache-status", 0.9),
        ],
        "body": [(r"Cloudflare", 0.7), (r"cloudflare\.com", 0.8)],
        "status_codes": [403, 503],
    },
    "akamai": {
        "headers": [
            (r"X-Akamai", 0.95),
            (r"Akamai-Origin-Hop", 0.95),
            (r"Server.*AkamaiGHost", 0.95),
        ],
        "body": [(r"Access Denied.*akamai", 0.8)],
        "status_codes": [403],
    },
    "aws_waf": {
        "headers": [(r"X-AMZ", 0.7), (r"x-amzn-RequestId", 0.8)],
        "body": [(r"Request blocked", 0.5)],
        "status_codes": [403],
    },
    "imperva": {
        "headers": [(r"X-Iinfo", 0.95)],
        "body": [(r"Incapsula", 0.9), (r"_Incapsula_Resource", 0.95)],
        "status_codes": [403],
    },
    "f5_bigip": {
        "headers": [(r"X-WA-Info", 0.9), (r"Server.*BigIP", 0.95)],
        "body": [(r"Request Rejected", 0.5)],
        "status_codes": [403],
    },
    "modsecurity": {
        "headers": [(r"Server.*mod_security", 0.95)],
        "body": [(r"ModSecurity", 0.9), (r"OWASP", 0.5)],
        "status_codes": [403, 406],
    },
    "sucuri": {
        "headers": [(r"X-Sucuri", 0.95), (r"Server.*Sucuri", 0.95)],
        "body": [(r"sucuri", 0.8), (r"Sucuri WebSite Firewall", 0.95)],
        "status_codes": [403],
    },
    "wordfence": {
        "headers": [],
        "body": [(r"wordfence", 0.9), (r"Wordfence", 0.9)],
        "status_codes": [403],
    },
}

DATABASE_SIGNATURES: Dict[str, Dict[str, List]] = {
    "mysql": {
        "errors": [
            (r"mysql", 0.6),
            (r"MySQL", 0.7),
            (r"mysqli", 0.8),
            (r"You have an error in your SQL syntax", 0.95),
            (r"mysql_fetch", 0.9),
            (r"SQLSTATE\[42000\]", 0.8),
            (r"MariaDB", 0.9),
        ],
    },
    "postgresql": {
        "errors": [
            (r"PostgreSQL", 0.9),
            (r"psycopg2", 0.9),
            (r"pg_query", 0.9),
            (r"PG::Error", 0.9),
            (r"SQLSTATE\[42P", 0.85),
            (r"unterminated quoted string", 0.8),
        ],
    },
    "mssql": {
        "errors": [
            (r"Microsoft SQL Server", 0.95),
            (r"ODBC SQL Server Driver", 0.9),
            (r"System\.Data\.SqlClient\.SqlException", 0.9),
            (r"Unclosed quotation mark", 0.85),
            (r"\[SQL Server\]", 0.9),
            (r"SqlException", 0.3),
        ],
    },
    "oracle": {
        "errors": [
            (r"ORA-\d{5}", 0.95),
            (r"Oracle error", 0.9),
            (r"Oracle.*Driver", 0.85),
            (r"quoted string not properly terminated", 0.8),
        ],
    },
    "sqlite": {
        "errors": [
            (r"SQLite", 0.9),
            (r"sqlite3", 0.9),
            (r"SQLITE_ERROR", 0.95),
            (r"near \".*\": syntax error", 0.8),
        ],
    },
    "mongodb": {
        "errors": [
            (r"MongoError", 0.95),
            (r"MongoDB", 0.8),
            (r"pymongo", 0.9),
            (r"mongoose", 0.85),
            (r"BSON", 0.7),
            (r"\$where", 0.6),
        ],
    },
    "redis": {
        "errors": [
            (r"Redis", 0.7),
            (r"redis-py", 0.9),
            (r"WRONGTYPE", 0.9),
        ],
    },
}

FRONTEND_SIGNATURES: Dict[str, Dict[str, List]] = {
    "react": {
        "body": [
            (r"react", 0.5),
            (r"React", 0.6),
            (r"__REACT", 0.9),
            (r"data-reactroot", 0.95),
            (r"_reactRootContainer", 0.95),
        ],
    },
    "angular": {
        "body": [
            (r"ng-version", 0.95),
            (r"ng-app", 0.9),
            (r"angular", 0.6),
            (r"ng-controller", 0.9),
            (r"<app-root", 0.9),
            (r"<app-[a-z][a-z0-9-]*[\s/>]", 0.5),
        ],
    },
    "vue": {
        "body": [
            (r"Vue", 0.5),
            (r"__vue__", 0.95),
            (r"v-cloak", 0.9),
            (r"data-v-", 0.9),
        ],
    },
    "jquery": {
        "body": [
            (r"jquery", 0.7),
            (r"jQuery", 0.8),
            (r"\$\(document\)", 0.6),
        ],
    },
}

# Backend → most likely database (used when no error-page signal exists).
# Confidence for this inference is intentionally low (0.3).
_BACKEND_DB_INFERENCE: Dict[str, str] = {
    "php": "mysql",
    "python": "postgresql",
    "ruby": "postgresql",
    "java": "mysql",
    "dotnet": "mssql",
    "node": "mongodb",
}

# Cross-constraint multipliers: boost/penalise database scores based on
# detected backend language.
_BACKEND_DB_AFFINITY: Dict[str, Dict[str, float]] = {
    "php":    {"mysql": 1.5, "postgresql": 1.0, "mssql": 0.3, "mongodb": 0.5},
    "python": {"postgresql": 1.3, "mysql": 1.0, "sqlite": 1.2, "mongodb": 1.0, "mssql": 0.5},
    "ruby":   {"postgresql": 1.3, "mysql": 1.0, "sqlite": 1.2, "mssql": 0.3},
    "java":   {"mysql": 1.2, "postgresql": 1.2, "oracle": 1.3, "mssql": 1.0},
    "dotnet": {"mssql": 1.5, "mysql": 0.7, "postgresql": 0.7},
    "node":   {"mongodb": 1.5, "postgresql": 1.0, "mysql": 1.0, "mssql": 0.3},
}


# ---------------------------------------------------------------------------
# TargetProfile dataclass
# ---------------------------------------------------------------------------

@dataclass
class TargetProfile:
    """
    Comprehensive profile of a web target built from passive fingerprinting.

    Used by the recommender (Layer 2) to filter and score tools, and by the
    scheduler (Layer 3) / memory engine for contextual learning via
    ``profile_hash()``.
    """

    # -- Identity --
    target_url: str = ""
    base_domain: str = ""

    # -- Technology stack --
    backend_language: str = "unknown"   # php | python | java | node | ruby | go | dotnet | unknown
    backend_confidence: float = 0.0
    framework: str = "unknown"          # laravel | django | flask | express | rails | spring | aspnet | …
    framework_confidence: float = 0.0
    frontend_framework: str = "unknown" # react | angular | vue | jquery | vanilla
    server_software: str = "unknown"    # nginx | apache | iis | …

    # -- API characteristics --
    api_types: List[str] = field(default_factory=list)          # rest | graphql | soap | websocket | grpc
    content_types_accepted: List[str] = field(default_factory=list)
    has_graphql: bool = False
    has_websocket: bool = False

    # -- Security posture --
    waf_detected: bool = False
    waf_vendor: Optional[str] = None    # cloudflare | akamai | aws_waf | imperva | …
    waf_confidence: float = 0.0
    rate_limited: bool = False
    security_headers: Dict[str, bool] = field(default_factory=dict)
    cors_enabled: bool = False
    cors_permissive: bool = False

    # -- Authentication mechanisms --
    auth_mechanisms: List[str] = field(default_factory=list)    # jwt | session | oauth | apikey | basic
    session_cookie_name: Optional[str] = None
    jwt_detected: bool = False

    # -- Database hints --
    likely_database: Optional[str] = None  # mysql | postgresql | mssql | oracle | sqlite | mongodb | redis
    database_confidence: float = 0.0
    database_hints: List[str] = field(default_factory=list)

    # -- Attack surface --
    has_file_upload: bool = False
    has_search: bool = False
    accepts_xml: bool = False
    error_verbosity: str = "low"        # low | medium | high

    # -- Evidence collected during analysis --
    evidence: Dict[str, List[str]] = field(default_factory=dict)

    # -----------------------------------------------------------------------
    # Profile hash — consumed by recommender / scheduler / memory engine
    # -----------------------------------------------------------------------

    def profile_hash(self) -> str:
        """Return a compact profile key for contextual learning lookups.

        Format: ``"backend:database:waf_status:waf_vendor:api_type:framework"``

        All components are lowercased. An absent backend, database or framework
        becomes the string literal ``"unknown"`` and an absent WAF vendor
        ``"none"``, so downstream matchers can use simple equality checks;
        ``waf_status`` is a boolean projection and has no absent case. The
        api_type slot is the exception: with nothing detected it is filled with
        ``"rest"``, a positive value rather than an admission of ignorance, so a
        target where no API type was found hashes identically to one where REST
        was identified.

        Examples::

            "php:mysql:waf:cloudflare:rest:laravel"
            "nodejs:mongodb:nowaf:none:rest:express"
            "java:postgresql:waf:akamai:rest:spring"
        """
        waf_status = "waf" if self.waf_detected else "nowaf"
        waf_vendor = (self.waf_vendor or "none") if self.waf_detected else "none"
        api_type = self.api_types[0] if self.api_types else "rest"
        components = [
            self.backend_language or "unknown",
            self.likely_database or "unknown",
            waf_status,
            waf_vendor,
            api_type,
            self.framework or "unknown",
        ]
        return ":".join(c.lower() for c in components)

    # -----------------------------------------------------------------------
    # Helpers for profile matching (used by memory engine / scheduler)
    # -----------------------------------------------------------------------

    def profile_components(self) -> Dict[str, str]:
        """Return individual hash components as a named dict."""
        parts = self.profile_hash().split(":")
        keys = ["backend", "database", "waf_status", "waf_vendor", "api_type", "framework"]
        return dict(zip(keys, parts))

    @staticmethod
    def hash_matches(profile_hash: str, pattern: str) -> bool:
        """Check whether *profile_hash* matches *pattern* (``*`` = wildcard).

        Both strings must have exactly 6 colon-separated components.
        """
        ph = profile_hash.split(":")
        pp = pattern.split(":")
        if len(ph) != 6 or len(pp) != 6:
            return False
        return all(pv == "*" or pv == hv for hv, pv in zip(ph, pp))

    @staticmethod
    def hash_similarity(hash_a: str, hash_b: str) -> float:
        """Weighted similarity between two profile hashes (0.0 – 1.0).

        Component weights reflect their importance for tool selection:
        - backend (0.35), database (0.35), waf_status (0.15),
          framework (0.10), api_type (0.025), waf_vendor (0.025).
        """
        weights = [0.35, 0.35, 0.15, 0.025, 0.025, 0.10]
        pa, pb = hash_a.split(":"), hash_b.split(":")
        if len(pa) != 6 or len(pb) != 6:
            return 0.0
        score = 0.0
        for a, b, w in zip(pa, pb, weights):
            if a == b:
                score += w
            elif a == "unknown" or b == "unknown":
                score += w * 0.3   # partial credit for unknowns
        return score


# ---------------------------------------------------------------------------
# Fingerprinter — passive analysis only
# ---------------------------------------------------------------------------

class Fingerprinter:
    """
    Passive target fingerprinter.

    ``analyze(response_headers, body, url)`` accepts a single HTTP exchange
    already collected by the caller and returns a populated ``TargetProfile``.
    Pass multiple exchanges by calling ``analyze()`` once per response and
    merging with ``merge()``, or use ``analyze_many()`` to process a list in
    one call.

    No network I/O is performed here.  Methods that would send live probes
    (GraphQL introspection, WebSocket upgrade) are stubbed and raise
    ``NotImplementedError``.
    """

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def analyze(
        self,
        response_headers: Dict[str, str],
        body: str,
        url: str,
        status_code: int = 200,
        cookies: Optional[Dict[str, str]] = None,
    ) -> "TargetProfile":
        """Fingerprint a target from a single already-collected HTTP response.

        Args:
            response_headers: Mapping of header name → value (case-insensitive
                matching is applied internally, on every path: the detectors
                that regex the serialised headers use re.I, the
                security-header check lowercases each key, and the three
                direct lookups go through ``_header``).
            body: Response body text (large bodies are fine; patterns are
                applied only against the first 50 000 characters internally).
            url: Full request URL — used for path-extension heuristics
                (``.php``, ``.aspx``, ``/api/``).
            status_code: HTTP status code of the response.
            cookies: Optional dict of cookie name → value from the response.

        Returns:
            A ``TargetProfile`` populated from this single response.
        """
        from urllib.parse import urlparse

        profile = TargetProfile(target_url=url)
        parsed = urlparse(url)
        profile.base_domain = parsed.netloc

        responses = [
            {
                "url": url,
                "status": status_code,
                "headers": response_headers,
                "body": body[:50_000],
                "cookies": cookies or {},
            }
        ]

        self._detect_server(profile, responses)
        self._detect_backend(profile, responses)
        self._detect_framework(profile, responses)
        self._detect_frontend(profile, responses)
        self._detect_waf(profile, responses)
        self._detect_database(profile, responses)
        self._detect_auth_mechanisms(profile, responses)
        self._detect_security_headers(profile, responses)
        self._infer_api_types(profile, url)
        self._analyze_attack_surface(profile, url, body)
        return profile

    def analyze_many(
        self,
        responses: List[Dict],
    ) -> "TargetProfile":
        """Fingerprint from a list of already-collected HTTP response dicts.

        Reads ``url``, ``status``, ``headers``, ``body`` and ``cookies`` from
        each dict, and every one of them is optional: a missing key is
        normalised to an empty value rather than refused, so a response dict
        with no ``body`` fingerprints as one whose body was empty. Only the
        first dict's ``url`` sets ``target_url`` and ``base_domain``.

        Returns a single merged ``TargetProfile``.
        """
        if not responses:
            return TargetProfile()

        from urllib.parse import urlparse

        profile = TargetProfile(
            target_url=responses[0].get("url", ""),
            base_domain=urlparse(responses[0].get("url", "")).netloc,
        )

        normed = [
            {
                "url": r.get("url", ""),
                "status": r.get("status", 200),
                "headers": r.get("headers", {}),
                "body": r.get("body", "")[:50_000],
                "cookies": r.get("cookies", {}),
            }
            for r in responses
        ]

        self._detect_server(profile, normed)
        self._detect_backend(profile, normed)
        self._detect_framework(profile, normed)
        self._detect_frontend(profile, normed)
        self._detect_waf(profile, normed)
        self._detect_database(profile, normed)
        self._detect_auth_mechanisms(profile, normed)
        self._detect_security_headers(profile, normed)
        for r in normed:
            self._infer_api_types(profile, r["url"])
            self._analyze_attack_surface(profile, r["url"], r["body"])
        return profile

    # ------------------------------------------------------------------
    # Stubbed active-probe methods
    # ------------------------------------------------------------------

    def probe_graphql(self, base_url: str) -> bool:
        """Send a GraphQL introspection POST to common paths to detect GraphQL.

        In production this issues live HTTP POST requests to paths such as
        ``/graphql``, ``/api/graphql``, ``/gql`` with the introspection query
        ``{ __schema { queryType { name } } }`` and inspects the JSON response
        for ``"data"`` or ``"errors"`` keys.

        Raises:
            NotImplementedError: live probe withheld from this public repository.
        """
        raise NotImplementedError("live probe withheld from this public repository")

    def probe_websocket(self, base_url: str) -> bool:
        """Probe for WebSocket endpoints by sending HTTP Upgrade requests.

        In production this issues GET requests with ``Upgrade: websocket`` and
        ``Connection: Upgrade`` headers to common paths (``/ws``, ``/socket.io``,
        ``/cable``, etc.).
        num-ok: 101, 400 and 426 are HTTP status codes -- protocol constants naming a response, not counting anything; the probe that reads them is withheld here, so they appear in no source literal
        It interprets HTTP 101/400/426 as a WebSocket signal.

        Raises:
            NotImplementedError: live probe withheld from this public repository.
        """
        raise NotImplementedError("live probe withheld from this public repository")

    def probe_xml_support(self, base_url: str) -> bool:
        """POST a minimal XML document to detect whether the target accepts XML.

        In production this sends ``Content-Type: application/xml`` to the root
        and ``/api`` paths.
        num-ok: 415 is the HTTP status code for Unsupported Media Type, a protocol constant naming a response rather than a measurement
        Any non-415 response is treated as acceptance.

        Raises:
            NotImplementedError: live probe withheld from this public repository.
        """
        raise NotImplementedError("live probe withheld from this public repository")

    def probe_error_verbosity(self, base_url: str) -> str:
        """Trigger error pages to gauge stack-trace verbosity.

        In production this issues requests with SQL-injection and LFI probes
        (``/?id='``, ``/?file=../etc/passwd``) and counts verbose error
        indicators (stack traces, file paths, exception class names) in the
        response body.

        Returns:
            ``"high"`` | ``"medium"`` | ``"low"`` (never reached — raises).

        Raises:
            NotImplementedError: live probe withheld from this public repository.
        """
        raise NotImplementedError("live probe withheld from this public repository")

    # ------------------------------------------------------------------
    # Internal passive detectors
    # ------------------------------------------------------------------

    def _headers_as_str(self, headers: Dict[str, str]) -> str:
        """Serialise headers dict to a JSON string for regex matching."""
        return json.dumps(headers)

    @staticmethod
    def _header(headers: Dict[str, str], name: str) -> str:
        """One case-insensitive header lookup, because the field name is.

        num-ok: 7230 is the number of the RFC that specifies HTTP header fields, a document identifier and not a measurement
        Header field names are case-insensitive per RFC 7230.

        The call sites that use this each used to try two exact spellings --
        ``headers.get("Server") or headers.get("server")`` -- which answers
        correctly for the casings somebody thought of and wrongly for every
        other legal one: a response carrying ``sErVeR: nginx`` was read as
        carrying no Server header at all. A further spelling would have been
        the same defect with better odds, so the keys are normalised once here
        instead.

        An empty value cannot mask a real one: a header whose value is blank is
        skipped, so a dict holding both a blank ``Server`` and a real
        ``server`` resolves to the real one whichever order it was built in.
        With two non-empty spellings of one name the first in iteration order
        wins, which is the same "first non-empty wins" rule the response loops
        use.
        """
        wanted = name.lower()
        for key, value in (headers or {}).items():
            if str(key).lower() == wanted and value:
                return str(value)
        return ""

    def _detect_server(self, profile: TargetProfile, responses: List[Dict]) -> None:
        """Detect web server software from the ``Server`` header."""
        for resp in responses:
            headers = resp.get("headers", {})
            server = self._header(headers, "Server")
            if not server:
                continue
            sl = server.lower()
            if "nginx" in sl:
                profile.server_software = "nginx"
            elif "apache" in sl:
                profile.server_software = "apache"
            elif "iis" in sl or "microsoft" in sl:
                profile.server_software = "iis"
            elif "cloudflare" in sl:
                profile.server_software = "cloudflare"
            elif "gunicorn" in sl:
                profile.server_software = "gunicorn"
            elif "tomcat" in sl:
                profile.server_software = "tomcat"
            else:
                profile.server_software = server[:50]
            break  # First non-empty Server header wins

    def _score_signatures(
        self,
        responses: List[Dict],
        sig_table: Dict[str, Dict[str, List]],
    ) -> tuple:
        """Apply a signature table to all responses and return (scores, evidence) dicts."""
        scores: Dict[str, float] = {k: 0.0 for k in sig_table}
        evidence: Dict[str, List[str]] = {k: [] for k in sig_table}

        for resp in responses:
            headers_str = self._headers_as_str(resp.get("headers", {}))
            body = resp.get("body", "")
            url = resp.get("url", "")
            status = resp.get("status", 200)

            for name, sigs in sig_table.items():
                for pattern, weight in sigs.get("headers", []):
                    if re.search(pattern, headers_str, re.I):
                        scores[name] += weight
                        evidence[name].append(f"header:{pattern}")

                for pattern, weight in sigs.get("urls", []):
                    if re.search(pattern, url, re.I):
                        scores[name] += weight
                        evidence[name].append(f"url:{pattern}")

                for pattern, weight in sigs.get("body", []):
                    if re.search(pattern, body, re.I):
                        scores[name] += weight
                        evidence[name].append(f"body:{pattern}")

                for pattern, weight in sigs.get("errors", []):
                    if re.search(pattern, body, re.I):
                        scores[name] += weight
                        evidence[name].append(f"error:{pattern}")

                # Status-code bonus (WAF and similar)
                if status in sigs.get("status_codes", []):
                    scores[name] += 0.3

        return scores, evidence

    def _detect_backend(self, profile: TargetProfile, responses: List[Dict]) -> None:
        scores, evidence = self._score_signatures(responses, BACKEND_SIGNATURES)
        if not scores:
            return
        best = max(scores, key=scores.__getitem__)
        if scores[best] > 0.5:
            profile.backend_language = best
            profile.backend_confidence = min(scores[best], 1.0)
            profile.evidence["backend"] = evidence[best][:5]

    def _detect_framework(self, profile: TargetProfile, responses: List[Dict]) -> None:
        scores, evidence = self._score_signatures(responses, FRAMEWORK_SIGNATURES)
        if not scores:
            return
        best = max(scores, key=scores.__getitem__)
        if scores[best] > 0.5:
            profile.framework = best
            profile.framework_confidence = min(scores[best], 1.0)
            profile.evidence["framework"] = evidence[best][:5]

    def _detect_frontend(self, profile: TargetProfile, responses: List[Dict]) -> None:
        scores, _ = self._score_signatures(responses, FRONTEND_SIGNATURES)
        if not scores:
            return
        best = max(scores, key=scores.__getitem__)
        if scores[best] > 0.5:
            profile.frontend_framework = best

    def _detect_waf(self, profile: TargetProfile, responses: List[Dict]) -> None:
        """Detect WAF presence and vendor from headers, body, and status codes."""
        scores: Dict[str, float] = {k: 0.0 for k in WAF_SIGNATURES}

        for resp in responses:
            headers_str = self._headers_as_str(resp.get("headers", {}))
            body = resp.get("body", "")
            status = resp.get("status", 200)

            for waf, sigs in WAF_SIGNATURES.items():
                for pattern, weight in sigs.get("headers", []):
                    if re.search(pattern, headers_str, re.I):
                        scores[waf] += weight

                for pattern, weight in sigs.get("body", []):
                    if re.search(pattern, body, re.I):
                        scores[waf] += weight

                if status in sigs.get("status_codes", []):
                    scores[waf] += 0.3

        if scores:
            best = max(scores, key=scores.__getitem__)
            if scores[best] > 0.5:
                profile.waf_detected = True
                profile.waf_vendor = best
                profile.waf_confidence = min(scores[best], 1.0)

    def _detect_database(self, profile: TargetProfile, responses: List[Dict]) -> None:
        """Infer database type from error-message patterns and backend affinity."""
        scores: Dict[str, float] = {k: 0.0 for k in DATABASE_SIGNATURES}
        hints: List[str] = []

        for resp in responses:
            body = resp.get("body", "")
            for db, sigs in DATABASE_SIGNATURES.items():
                for pattern, weight in sigs.get("errors", []):
                    if re.search(pattern, body, re.I):
                        scores[db] += weight
                        hints.append(f"{db}:{pattern}")

        # Apply backend-database affinity cross-constraints
        backend = profile.backend_language
        if backend != "unknown":
            affinity = _BACKEND_DB_AFFINITY.get(backend, {})
            for db in scores:
                if scores[db] > 0:
                    scores[db] *= affinity.get(db, 1.0)

        if scores:
            best = max(scores, key=scores.__getitem__)
            if scores[best] > 0.5:
                profile.likely_database = best
                profile.database_confidence = min(scores[best], 1.0)
                profile.database_hints = hints[:5]

        # Fall back to inference when no error signal was found
        if not profile.likely_database and backend in _BACKEND_DB_INFERENCE:
            profile.likely_database = _BACKEND_DB_INFERENCE[backend]
            profile.database_confidence = 0.3

    def _detect_auth_mechanisms(self, profile: TargetProfile, responses: List[Dict]) -> None:
        """Detect authentication mechanisms from headers, cookies, and body."""
        found: set = set()

        for resp in responses:
            headers = resp.get("headers", {})
            cookies = resp.get("cookies", {})
            body = resp.get("body", "")

            # JWT via Authorization header
            auth_header = self._header(headers, "Authorization")
            if "bearer" in auth_header.lower():
                found.add("jwt")
                profile.jwt_detected = True

            # Session / JWT cookies
            for cookie_name in cookies:
                cn = cookie_name.lower()
                if "session" in cn or "sess" in cn:
                    found.add("session")
                    profile.session_cookie_name = cookie_name
                if "jwt" in cn or "token" in cn:
                    found.add("jwt")
                    profile.jwt_detected = True

            # OAuth patterns in body
            if re.search(r"oauth|authorize|callback.*code", body, re.I):
                found.add("oauth")

            # API key patterns
            if re.search(r"api[_-]?key|apikey|x-api-key", body, re.I):
                found.add("apikey")

            # HTTP Basic auth challenge
            www_auth = self._header(headers, "WWW-Authenticate")
            if "basic" in www_auth.lower():
                found.add("basic")

        profile.auth_mechanisms = sorted(found)

    def _detect_security_headers(self, profile: TargetProfile, responses: List[Dict]) -> None:
        """Check presence of common security response headers."""
        tracked = {
            "X-Frame-Options": False,
            "X-Content-Type-Options": False,
            "X-XSS-Protection": False,
            "Content-Security-Policy": False,
            "Strict-Transport-Security": False,
            "Referrer-Policy": False,
        }

        for resp in responses:
            headers = resp.get("headers", {})
            headers_lower = {k.lower(): v for k, v in headers.items()}

            for hdr in list(tracked.keys()):
                if hdr.lower() in headers_lower:
                    tracked[hdr] = True

            # CORS
            acao = headers_lower.get("access-control-allow-origin", "")
            if acao:
                profile.cors_enabled = True
                if acao.strip() == "*":
                    profile.cors_permissive = True

        profile.security_headers = tracked

    def _infer_api_types(self, profile: TargetProfile, url: str) -> None:
        """Infer REST API presence from URL path patterns."""
        if re.search(r"(/api/|/api$|/v\d+/|/rest/)", url, re.I):
            if "rest" not in profile.api_types:
                profile.api_types.append("rest")

    def _analyze_attack_surface(
        self,
        profile: TargetProfile,
        url: str,
        body: str,
    ) -> None:
        """Detect attack-surface indicators from URL and response body."""
        # File upload
        if re.search(r"(input[^>]+type=[\"']file|upload|attach|dropzone)", body, re.I):
            profile.has_file_upload = True

        # Search functionality
        if re.search(r"(input[^>]+type=[\"']search|name=[\"']q[\"']|search=|/search\b)", body + url, re.I):
            profile.has_search = True

        # XML acceptance
        if re.search(r"(application/xml|text/xml|content-type.*xml)", body, re.I):
            profile.accepts_xml = True

        # Error verbosity from body text
        verbose_patterns = [
            r"stack trace",
            r"traceback",
            r"exception",
            r"at .+\.(java|php|py|rb|cs|js):\d+",
            r"line \d+",
        ]
        verbosity_score = sum(1 for p in verbose_patterns if re.search(p, body, re.I))
        if verbosity_score >= 3:
            profile.error_verbosity = "high"
        elif verbosity_score >= 1:
            profile.error_verbosity = "medium"
