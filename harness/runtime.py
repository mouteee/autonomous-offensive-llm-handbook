"""Reference controls for a fixture-only conference tutorial.

This is an application boundary, not an operating-system sandbox. Python code,
adapters and policy authors are trusted. No network or model client is included.
"""

import copy
import hashlib
import json
import math
from urllib.parse import urlsplit


STAGES = ("observe", "plan", "execute", "review", "report")
SEVERITIES = ("info", "low", "medium", "high", "critical")
GATE_KEYS = ("waf_detected", "total_responses", "error_rate", "parameters_found",
             "forms_found", "pages_crawled", "scripts_found")


class PolicyError(ValueError):
    pass


def canonical_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise PolicyError(f"{name} must be an integer >= {minimum}")
    return value


def _number(value, name, minimum=0):
    if type(value) not in (int, float) or not math.isfinite(value) or value < minimum:
        raise PolicyError(f"{name} must be finite and >= {minimum}")
    return value


def origin(url):
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


def strict_gate(signals):
    if not isinstance(signals, dict):
        raise PolicyError("gate input must be an object")
    unknown = set(signals) - set(GATE_KEYS)
    if unknown:
        raise PolicyError(f"unknown gate inputs: {sorted(unknown)}")
    if "waf_detected" in signals and type(signals["waf_detected"]) is not bool:
        raise PolicyError("waf_detected must be a measured boolean")
    for key in signals:
        if key not in ("waf_detected", "error_rate"):
            _integer(signals[key], key)
    rate = _number(signals.get("error_rate", 0), "error_rate")
    if rate > 1:
        raise PolicyError("error_rate must be <= 1")
    missing = [key for key in GATE_KEYS if key not in signals]
    if missing:
        return {"status": "indeterminate", "mode": "stop", "missing": missing,
                "inputs": copy.deepcopy(signals)}
    if signals["total_responses"] == 0:
        status, mode = "indeterminate", "stop"
    elif rate > .8:
        status, mode = "limited", "passive"
    else:
        status, mode = "proceed", "full"
    return {"status": status, "mode": mode, "missing": [],
            "inputs": copy.deepcopy(signals)}


def validate_manifest(manifest):
    required = {"schema", "name", "authorization", "profile", "tools", "rules", "proof_rules",
                "max_actions"}
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise PolicyError(f"manifest keys must be {sorted(required)}")
    if manifest["schema"] != "harness-port/v1":
        raise PolicyError("unsupported manifest schema")
    _integer(manifest["max_actions"], "max_actions", 1)
    auth = manifest["authorization"]
    if not isinstance(auth, dict) or set(auth) != {"reference", "origins"}:
        raise PolicyError("authorization needs reference and origins")
    if not isinstance(auth["reference"], str) or not auth["reference"].strip():
        raise PolicyError("authorization reference is required")
    if not isinstance(auth["origins"], list) or not auth["origins"]:
        raise PolicyError("explicit authorized origins are required")
    origins = [origin(url) for url in auth["origins"]]
    if any(urlsplit(url).path not in ("", "/") or urlsplit(url).query for url in auth["origins"]):
        raise PolicyError("authorized origins cannot contain a path or query restriction")
    if len(set(origins)) != len(origins):
        raise PolicyError("duplicate authorized origin")
    profile = manifest["profile"]
    if not isinstance(profile, dict):
        raise PolicyError("profile must be an object")
    for key, field in profile.items():
        if not isinstance(field, dict) or set(field) != {"state", "value", "source"}:
            raise PolicyError(f"profile field {key} needs state, value and source")
        if field["state"] not in ("measured", "unknown"):
            raise PolicyError(f"invalid observation state for {key}")
        if field["state"] == "unknown" and field["value"] is not None:
            raise PolicyError(f"unknown field {key} cannot carry a measured value")
        if field["state"] == "measured" and (not isinstance(field["source"], str) or not field["source"].strip()):
            raise PolicyError(f"measured field {key} needs a source")
    if not isinstance(manifest["tools"], list) or not manifest["tools"]:
        raise PolicyError("tool catalogue must not be empty")
    ids = []
    for tool in manifest["tools"]:
        if not isinstance(tool, dict) or set(tool) != {"id", "requires", "weight", "cost", "activity", "fixture"}:
            raise PolicyError("tool entry has unknown or missing keys")
        ids.append(tool["id"])
        if not isinstance(tool["id"], str) or not tool["id"]:
            raise PolicyError("tool id is required")
        if not isinstance(tool["requires"], dict) or set(tool["requires"]) - set(profile):
            raise PolicyError(f"unknown profile field in {tool['id']}")
        _number(tool["weight"], "weight")
        if _number(tool["cost"], "cost") == 0:
            raise PolicyError("tool cost must be positive")
        _number(tool["weight"] / tool["cost"], "derived score")
        if tool["activity"] not in ("passive", "active") or not tool["fixture"]:
            raise PolicyError("tool needs activity and fixture")
    if len(set(ids)) != len(ids):
        raise PolicyError("duplicate tool id")
    for collection, keys in (("rules", {"id", "kind", "tool", "ceiling", "fixture"}),
                              ("proof_rules", {"id", "kind", "tool", "status", "marker", "ceiling", "fixture"})):
        if not isinstance(manifest[collection], list):
            raise PolicyError(f"{collection} must be a list")
        seen = set()
        for rule in manifest[collection]:
            if not isinstance(rule, dict) or set(rule) != keys:
                raise PolicyError(f"invalid {collection} entry")
            if not rule["id"] or rule["id"] in seen or not rule["fixture"]:
                raise PolicyError(f"{collection} needs unique ids and fixtures")
            seen.add(rule["id"])
            if rule["ceiling"] not in SEVERITIES:
                raise PolicyError("unknown severity ceiling")
            if rule["tool"] not in ids or not isinstance(rule["kind"], str) or not rule["kind"].strip():
                raise PolicyError("rule needs a declared tool and finding kind")
            if collection == "proof_rules":
                _integer(rule["status"], "status", 100)
                if rule["status"] > 599 or rule["tool"] not in ids or not rule["kind"]:
                    raise PolicyError("proof rule needs a valid response status, kind and declared tool")
                if not isinstance(rule["marker"], str) or not rule["marker"].strip():
                    raise PolicyError("proof marker must be nonempty")
    canonical_bytes(manifest)
    return copy.deepcopy(manifest)


class Harness:
    def __init__(self, manifest, adapters, fixtures):
        self._manifest = validate_manifest(manifest)
        self._adapters = dict(adapters)
        self._fixtures = copy.deepcopy(fixtures)
        expected = {tool["id"] for tool in self._manifest["tools"]}
        if set(self._adapters) != expected:
            raise PolicyError("adapter registry must equal the declared catalogue")
        for group in ("tools", "rules", "proof_rules"):
            for item in self._manifest[group]:
                if item["fixture"] not in self._fixtures:
                    raise PolicyError(f"missing fixture for {item['id']}")
        for rule in self._manifest["proof_rules"]:
            fixture = self._fixtures[rule["fixture"]]
            if fixture.get("status") != rule["status"] or rule["marker"] not in fixture.get("body", ""):
                raise PolicyError(f"proof rule {rule['id']} needs a matching positive fixture")
        self._run_id = digest({"manifest": self._manifest, "fixtures": self._fixtures})
        self._allowed = frozenset(origin(u) for u in self._manifest["authorization"]["origins"])
        self._stage_index = 0
        self._events = [{"event": "stage", "stage": STAGES[0]}]
        self._gate = None
        self._plan = []
        self._plan_frozen = False
        self._outcomes = {}
        self._evidence = {}
        self._findings = {}
        self._actions = 0
        self._finished = False

    def _at(self, stage):
        if self._finished or STAGES[self._stage_index] != stage:
            raise PolicyError(f"operation requires open stage {stage}")

    def advance(self, stage):
        if self._finished or self._stage_index + 1 >= len(STAGES) or STAGES[self._stage_index + 1] != stage:
            raise PolicyError("stage transition is not the next declared stage")
        if stage == "plan" and self._gate is None:
            raise PolicyError("gate inputs must be recorded first")
        if stage == "execute" and not self._plan_frozen:
            raise PolicyError("plan must be recorded first")
        if stage == "review" and len(self._outcomes) != len(self._plan):
            raise PolicyError("every planned action needs an outcome or skip")
        self._stage_index += 1
        self._events.append({"event": "stage", "stage": stage})

    def observe(self, signals):
        self._at("observe")
        self._gate = strict_gate(signals)
        self._events.append({"event": "gate", **copy.deepcopy(self._gate)})
        return copy.deepcopy(self._gate)

    def plan(self, url):
        self._at("plan")
        if self._plan_frozen:
            raise PolicyError("plan already frozen")
        origin(url)
        rows = []
        for tool in self._manifest["tools"]:
            reasons = []
            eligible = True
            for key, wanted in sorted(tool["requires"].items()):
                field = self._manifest["profile"][key]
                if field["state"] != "measured" or type(field["value"]) is not type(wanted) or field["value"] != wanted:
                    eligible = False
                    reasons.append(f"{key}: unknown or not matched")
            if eligible:
                rows.append({"tool": tool["id"], "url": url,
                             "score": tool["weight"] / tool["cost"],
                             "reason": "declared requirements matched; weight / cost"})
            else:
                self._events.append({"event": "not_selected", "tool": tool["id"], "reasons": reasons})
        self._plan = sorted(rows, key=lambda row: (-row["score"], row["tool"]))
        self._plan_frozen = True
        self._events.append({"event": "plan", "items": copy.deepcopy(self._plan)})
        return copy.deepcopy(self._plan)

    def execute(self, tool_id, url):
        self._at("execute")
        key = (tool_id, url)
        if key in self._outcomes or not any((p["tool"], p["url"]) == key for p in self._plan):
            raise PolicyError("action is not pending in the frozen plan")
        self._next_action(key)
        tool = next(t for t in self._manifest["tools"] if t["id"] == tool_id)
        reason = None
        if origin(url) not in self._allowed:
            reason = "outside explicit authorized origins"
        elif self._gate["mode"] == "stop":
            reason = "gate indeterminate"
        elif self._gate["mode"] == "passive" and tool["activity"] != "passive":
            reason = "gate permits passive work only"
        elif self._actions >= self._manifest["max_actions"]:
            reason = "action budget exhausted"
        if reason:
            return self.skip(tool_id, url, reason)
        self._actions += 1
        self._events.append({"event": "authorized", "tool": tool_id, "url": url})
        try:
            raw = copy.deepcopy(self._adapters[tool_id](url))
            if not isinstance(raw, dict) or set(raw) != {"status", "body"}:
                raise PolicyError("adapter result needs exactly status and body")
            _integer(raw["status"], "status", 100)
            if raw["status"] > 599 or not isinstance(raw["body"], str):
                raise PolicyError("invalid captured response")
            record = {"run_id": self._run_id, "tool": tool_id, "url": url, **raw}
            evidence_id = digest(record)
            self._evidence[evidence_id] = record
            outcome = {"status": "executed", "tool": tool_id, "url": url, "evidence_id": evidence_id}
        except Exception as exc:
            outcome = {"status": "error", "tool": tool_id, "url": url, "error_type": type(exc).__name__}
        self._outcomes[key] = outcome
        self._events.append({"event": "action", **copy.deepcopy(outcome)})
        return copy.deepcopy(outcome)

    def skip(self, tool_id, url, reason):
        self._at("execute")
        key = (tool_id, url)
        if key in self._outcomes or not any((p["tool"], p["url"]) == key for p in self._plan):
            raise PolicyError("skip must name a pending planned action")
        self._next_action(key)
        if not isinstance(reason, str) or not reason.strip():
            raise PolicyError("skip reason is required")
        row = {"status": "skipped", "tool": tool_id, "url": url, "reason": reason}
        self._outcomes[key] = row
        self._events.append({"event": "action", **row})
        return copy.deepcopy(row)

    def _next_action(self, key):
        pending = next(((p["tool"], p["url"]) for p in self._plan
                        if (p["tool"], p["url"]) not in self._outcomes), None)
        if key != pending:
            raise PolicyError("action must be the next pending item in score order")

    def _quote(self, evidence_id, quote):
        record = self._evidence.get(evidence_id)
        if record is None or digest(record) != evidence_id or record["run_id"] != self._run_id:
            raise PolicyError("evidence is not an intact capture from this run")
        if not isinstance(quote, str) or not quote.strip() or quote not in record["body"]:
            raise PolicyError("quote does not occur verbatim in the bound capture")
        return record

    def propose_finding(self, *, finding_id, title, kind, severity, evidence_id, quote):
        self._at("review")
        if any(not isinstance(value, str) or not value.strip() for value in (finding_id, title, kind)):
            raise PolicyError("finding id, title and kind must be nonempty strings")
        if finding_id in self._findings or severity not in SEVERITIES:
            raise PolicyError("finding needs unique id and known severity")
        capture = self._quote(evidence_id, quote)
        applicable = [r for r in self._manifest["rules"] if r["kind"] == kind and r["tool"] == capture["tool"]]
        if not applicable:
            raise PolicyError("finding kind is not authorized for this capture tool")
        final = severity
        fired = []
        for rule in applicable:
            if rule["kind"] == kind and SEVERITIES.index(rule["ceiling"]) < SEVERITIES.index(final):
                final = rule["ceiling"]
                fired.append(rule["id"])
        row = {"id": finding_id, "title": title, "kind": kind, "severity": final,
               "proposed_severity": severity, "evidence_id": evidence_id, "quote": quote,
               "rules_fired": fired, "acceptance": "human_review_required"}
        self._findings[finding_id] = row
        self._events.append({"event": "governed_write", **copy.deepcopy(row)})
        return copy.deepcopy(row)

    def verify_raise(self, *, finding_id, evidence_id, quote, severity, rule_id):
        self._at("review")
        finding = self._findings.get(finding_id)
        if finding is None or evidence_id != finding["evidence_id"] or severity not in SEVERITIES:
            raise PolicyError("verdict does not bind to a stored finding and its evidence")
        record = self._quote(evidence_id, quote)
        rule = next((r for r in self._manifest["proof_rules"] if r["id"] == rule_id), None)
        if (rule is None or rule["kind"] != finding["kind"] or rule["tool"] != record["tool"]
                or record["status"] != rule["status"] or rule["marker"] not in record["body"]):
            raise PolicyError("independent policy predicate did not match the capture")
        if not SEVERITIES.index(finding["severity"]) < SEVERITIES.index(severity) <= SEVERITIES.index(rule["ceiling"]):
            raise PolicyError("raise is outside the policy ceiling")
        previous = finding["severity"]
        finding["severity"] = severity
        self._events.append({"event": "policy_validated_raise", "finding_id": finding_id,
                             "evidence_id": evidence_id, "quote": quote, "rule_id": rule_id,
                             "before": previous, "after": severity})
        return copy.deepcopy(finding)

    def finish(self):
        self._at("report")
        self._finished = True
        self._events.append({"event": "finished", "acceptance": "human_review_required"})
        return self.snapshot()

    def abort(self, reason):
        if self._finished or not isinstance(reason, str) or not reason.strip():
            raise PolicyError("abort requires an open run and a reason")
        for item in self._plan:
            key = (item["tool"], item["url"])
            if key not in self._outcomes:
                row = {"status": "skipped", "tool": item["tool"], "url": item["url"],
                       "reason": f"run aborted: {reason}"}
                self._outcomes[key] = row
                self._events.append({"event": "action", **row})
        self._events.append({"event": "aborted", "reason": reason})
        self._finished = True
        return self.snapshot()

    def snapshot(self):
        outcomes = list(self._outcomes.values())
        counts = {state: sum(row["status"] == state for row in outcomes)
                  for state in ("executed", "error", "skipped")}
        return copy.deepcopy({"schema": "harness-report/v1", "run_id": self._run_id,
            "mode": "offline_reference", "finished": self._finished,
            "acceptance": "human_review_required", "policy_digest": digest(self._manifest),
            "gate": self._gate, "plan": self._plan, "outcomes": outcomes,
            "coverage": {"denominator": "planned tool-and-URL actions", "planned": len(self._plan),
                         **counts, "pending": len(self._plan) - len(outcomes)},
            "evidence": self._evidence, "findings": list(self._findings.values()), "events": self._events})
