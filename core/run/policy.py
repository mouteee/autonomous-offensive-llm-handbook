"""Operator policy as data: who authorized what, which tools exist, how much.

A policy is declared by the operator, outside anything a model writes. Its
answers are decision records -- an `allowed` flag plus the reason -- rather
than bare booleans, because the reason is what gets recorded when work is
turned away, and an unexplained refusal is unfinished work.

`origin` here is a deliberate twin of the fixture lab's canonicalizer in
harness/runtime.py: the import-consistency gate keeps core/ standard-library
and core-only, so the function is restated rather than imported, and
tests/test_run_policy_equivalence.py holds the two implementations to identical
behavior over a shared case table so they age together instead of apart.
"""

from dataclasses import dataclass, field
import posixpath
from urllib.parse import urlsplit

from .records import RecordError, canonical_bytes, digest, is_finite_number


TOOL_ACTIVITIES = ("passive", "active")


class PolicyError(RecordError):
    """A policy declaration that does not satisfy the contract."""


def origin(url):
    """Canonical origin of an absolute HTTP(S) URL: scheme, host, port."""
    if not isinstance(url, str) or not url or any(c.isspace() for c in url) or "\\" in url:
        raise PolicyError("invalid URL")
    try:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise PolicyError("only absolute HTTP(S) URLs are supported")
        if parts.username is not None or parts.password is not None or parts.fragment:
            raise PolicyError("credentials and fragments are outside the scope grammar")
        host = parts.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        if "%" in host or not host or host.startswith(".") or ".." in host:
            raise PolicyError("invalid hostname")
        port = parts.port if parts.port is not None else (443 if parts.scheme == "https" else 80)
        if port == 0:
            raise PolicyError("port zero is not an authorized service")
    except (ValueError, UnicodeError) as exc:
        raise PolicyError("invalid URL") from exc
    return f"{parts.scheme}://{host}:{port}"


def normalize_destination(url):
    """Canonical origin plus path: the destination part of an action identity.

    Query strings and fragments are deliberately outside the identity: two
    probes against the same path differ by arguments, and arguments live on
    the action record where they are visible, not inside the identity where
    they would fragment feedback.
    """
    base = origin(url)
    path = urlsplit(url).path or "/"
    # Dot segments collapse so one path has one spelling: /a/../b and /b are
    # the same act. The origin check has already run, so normalization cannot
    # move a destination out of its origin.
    path = posixpath.normpath(path)
    # normpath preserves a leading double slash by POSIX rule; collapse it so
    # //x and /x cannot be two identities for one path.
    while path.startswith("//"):
        path = path[1:]
    return f"{base}{path}"


def _decision(allowed, reason):
    return {"allowed": bool(allowed), "reason": reason}


@dataclass(frozen=True)
class Tool:
    """One declared capability: identity, activity class, needs and costs."""

    tool_id: str
    activity: str
    requires: dict = field(default_factory=dict)
    family: str = ""
    weight: float = 1.0
    cost: float = 1.0

    def __post_init__(self):
        if not isinstance(self.tool_id, str) or not self.tool_id.strip():
            raise PolicyError("tool_id needs a nonempty string")
        if self.activity not in TOOL_ACTIVITIES:
            raise PolicyError(f"unknown tool activity {self.activity!r}")
        if not isinstance(self.requires, dict):
            raise PolicyError("requires needs an object of observed fields")
        if not is_finite_number(self.weight) or self.weight < 0:
            raise PolicyError("weight needs a finite number of at least zero")
        if not is_finite_number(self.cost) or self.cost <= 0:
            raise PolicyError("cost needs a positive finite number")
        if not self.family:
            object.__setattr__(self, "family", self.tool_id)


class Policy:
    """The operator's declaration: reference, origins, tools and budgets."""

    def __init__(self, *, reference, origins, tools, max_actions,
                 max_model_calls):
        if not isinstance(reference, str) or not reference.strip():
            raise PolicyError("authorization reference is required")
        if not isinstance(origins, (list, tuple)) or not origins:
            raise PolicyError("explicit authorized origins are required")
        canonical = [origin(url) for url in origins]
        if len(set(canonical)) != len(canonical):
            raise PolicyError("duplicate authorized origin")
        if not tools:
            raise PolicyError("tool catalogue is required")
        ids = [tool.tool_id for tool in tools]
        if len(set(ids)) != len(ids):
            raise PolicyError("duplicate tool id")
        for budget, name in ((max_actions, "max_actions"),
                             (max_model_calls, "max_model_calls")):
            if type(budget) is not int or budget < 1:
                raise PolicyError(f"{name} needs an integer of at least one")
        self.reference = reference
        self.allowed_origins = frozenset(canonical)
        self.tools = {tool.tool_id: tool for tool in tools}
        self.max_actions = max_actions
        self.max_model_calls = max_model_calls

    def snapshot(self):
        """The policy as plain data, for digests and reports."""
        return {
            "reference": self.reference,
            "allowed_origins": sorted(self.allowed_origins),
            "tools": [{
                "tool_id": tool.tool_id, "activity": tool.activity,
                "requires": dict(tool.requires), "family": tool.family,
                "weight": tool.weight, "cost": tool.cost,
            } for _, tool in sorted(self.tools.items())],
            "max_actions": self.max_actions,
            "max_model_calls": self.max_model_calls,
        }

    def digest(self):
        return digest(self.snapshot())

    # Decisions ---------------------------------------------------------------

    def allows_destination(self, url):
        try:
            candidate = origin(url)
        except PolicyError as exc:
            return _decision(False, f"unusable destination: {exc}")
        if candidate not in self.allowed_origins:
            return _decision(False,
                             f"destination {candidate} is outside the "
                             "explicit authorized origins")
        return _decision(True, "destination inside authorized origins")

    def knows_tool(self, tool_id):
        if tool_id not in self.tools:
            return _decision(False, f"tool {tool_id!r} is not declared in the "
                                    "catalogue")
        return _decision(True, "declared tool")

    def allows_action(self, tool_id, url, arguments=None):
        """One answer combining tool, destination and argument shape."""
        for part in (self.knows_tool(tool_id), self.allows_destination(url)):
            if not part["allowed"]:
                return part
        try:
            canonical_bytes(arguments or {})
        except (TypeError, ValueError):
            return _decision(False, "arguments are not plain JSON data")
        return _decision(True, "declared tool, authorized destination, "
                               "plain arguments")
