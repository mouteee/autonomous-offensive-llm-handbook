"""
core/llm_control.py — LLM Control Layer: Schema Validation + JSON-Repair Loop

Anti-hallucination story: every tool call emitted by an LLM is validated through
a four-stage pipeline before it reaches the executor.  If validation fails the
repair loop re-prompts the LLM (via an injected callable) up to ``max_retries``
times, re-running the full pipeline on each corrected response.

Validation pipeline
-------------------
1. **JSON parse** — raw LLM response is parsed as JSON; trailing/leading
   whitespace and markdown code fences are stripped first.
2. **Required fields** — ``name`` (str) and ``arguments`` (dict) must be present.
3. **Tool-name-in-registry** — ``name`` must exist in the schema registry that
   ``ToolCallValidator`` was constructed with.
4. **Type match** — each argument is checked against the corresponding JSON
   Schema ``type`` (string, integer, number, boolean, object, array).  Required
   parameters must be present; unknown parameters are dropped.

Public API
----------
``ToolCall``           — dataclass carrying a validated (name, arguments) pair.
``ValidationError``    — raised by ``validate()`` at any pipeline stage.
``ToolCallValidator``  — main entry point: ``validate()`` and ``repair_loop()``.
``_demo_ask_llm``      — module-level stub; inject a real LLM callable instead.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class ToolCall:
    """A validated, normalised tool call ready for execution.

    Attributes
    ----------
    name:
        Exact tool name from the registry.
    arguments:
        Normalised argument dict (required fields present, types coerced,
        unknown keys dropped).
    """

    name: str
    arguments: dict = field(default_factory=dict)


class ValidationError(Exception):
    """Raised by :meth:`ToolCallValidator.validate` on any pipeline failure.

    The message describes the stage and reason so the repair-loop prompt can
    convey precise remediation instructions to the LLM.
    """


# ---------------------------------------------------------------------------
# Stub LLM provider (injected callable)
# ---------------------------------------------------------------------------


def _demo_ask_llm(prompt: str) -> str:  # noqa: ARG001
    """Default injectable LLM callable — **withheld from this public repository**.

    Replace this with a real provider when embedding
    ``ToolCallValidator.repair_loop`` in a live agent.

    Raises
    ------
    NotImplementedError:
        Always — the actual LLM provider call is withheld from this repository.
    """
    raise NotImplementedError("LLM provider withheld from this public repository")


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


class ToolCallValidator:
    """Validate and repair LLM-emitted tool calls against registered schemas.

    Parameters
    ----------
    tool_schemas:
        Mapping of tool name → JSON Schema parameter object.  Each value is
        a dict with optional keys ``properties`` (dict), ``required`` (list),
        and per-property ``type``/``default`` entries::

            {
                "fetch_url": {
                    "properties": {
                        "url": {"type": "string"},
                        "timeout": {"type": "integer", "default": 10},
                    },
                    "required": ["url"],
                },
            }

    Example
    -------
    >>> schemas = {"greet": {"properties": {"name": {"type": "string"}},
    ...                       "required": ["name"]}}
    >>> v = ToolCallValidator(schemas)
    >>> tc = v.validate('{"name": "greet", "arguments": {"name": "world"}}')
    >>> tc.name
    'greet'
    """

    def __init__(self, tool_schemas: Dict[str, Dict[str, Any]]) -> None:
        self._schemas: Dict[str, Dict[str, Any]] = dict(tool_schemas)

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def validate(self, raw: str) -> ToolCall:
        """Run the full four-stage validation pipeline.

        Parameters
        ----------
        raw:
            Raw string emitted by the LLM (may contain markdown fences).

        Returns
        -------
        ToolCall:
            Normalised, registry-checked tool call.

        Raises
        ------
        ValidationError:
            At the first failing stage, with a message that names the stage
            and gives a precise reason.
        """
        # Stage 1: JSON parse
        parsed = self._parse_json(raw)

        # Stage 2: required fields
        name, args = self._check_required_fields(parsed)

        # Stage 3: tool name in registry
        self._check_tool_in_registry(name)

        # Stage 4: type match against schema
        schema = self._schemas[name]
        ok, normalised, err = self._validate_args(args, schema)
        if not ok:
            raise ValidationError(
                f"[stage:type_match] tool '{name}': {err}"
            )

        return ToolCall(name=name, arguments=normalised)

    def repair_loop(
        self,
        raw: str,
        ask_llm: Callable[[str], str] = _demo_ask_llm,
        max_retries: int = 3,
    ) -> ToolCall:
        """Validate with automatic repair via LLM re-prompting.

        On validation failure the loop:

        1. Builds a repair prompt that includes the original response,
           the exact error, and the schema for the expected tool (when known).
        2. Calls ``ask_llm(prompt)`` to get a corrected response.
        3. Re-runs the full validation pipeline on the new response.

        This repeats up to ``max_retries`` times.  If the last attempt also
        fails the final ``ValidationError`` is re-raised.

        Parameters
        ----------
        raw:
            Initial LLM response string.
        ask_llm:
            Callable that accepts a repair prompt and returns a new LLM
            response string.  Defaults to :func:`_demo_ask_llm` (raises
            ``NotImplementedError`` — inject a real provider for live use).
        max_retries:
            Maximum number of repair attempts (default: 3).

        Returns
        -------
        ToolCall:
            First successfully validated tool call.

        Raises
        ------
        ValidationError:
            When the final attempt fails validation.
        NotImplementedError:
            Propagated from ``ask_llm`` when the default stub is used and
            validation fails while a repair attempt is still allowed. With
            ``max_retries`` at zero there is no repair call to make, so the
            ``ValidationError`` surfaces instead.
        """
        current = raw
        last_error: Optional[ValidationError] = None

        for attempt in range(max_retries + 1):
            try:
                return self.validate(current)
            except ValidationError as exc:
                last_error = exc
                if attempt == max_retries:
                    break
                prompt = self._build_repair_prompt(current, exc)
                current = ask_llm(prompt)

        assert last_error is not None  # always set when we reach here
        raise last_error

    # ------------------------------------------------------------------
    # Private helpers — pipeline stages
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_fences(raw: str) -> str:
        """Remove markdown code fences (```json ... ``` or ``` ... ```)."""
        stripped = raw.strip()
        # Remove opening fence (```json or ```)
        stripped = re.sub(r"^```(?:json)?\s*\n?", "", stripped, flags=re.IGNORECASE)
        # Remove closing fence
        stripped = re.sub(r"\n?```\s*$", "", stripped)
        return stripped.strip()

    def _parse_json(self, raw: str) -> Any:
        """Stage 1: parse JSON, stripping markdown fences first."""
        cleaned = self._strip_fences(raw)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValidationError(
                f"[stage:json_parse] invalid JSON: {exc.msg} at position {exc.pos}"
            ) from exc

    @staticmethod
    def _check_required_fields(parsed: Any) -> Tuple[str, Any]:
        """Stage 2: ensure ``name`` (str) and ``arguments`` (dict) are present."""
        if not isinstance(parsed, dict):
            raise ValidationError(
                "[stage:required_fields] top-level value must be a JSON object"
            )
        name = parsed.get("name")
        if not name or not isinstance(name, str):
            raise ValidationError(
                "[stage:required_fields] missing or non-string 'name' field"
            )
        if "arguments" not in parsed:
            raise ValidationError(
                f"[stage:required_fields] missing 'arguments' field for tool '{name}'"
            )
        args = parsed["arguments"]
        if not isinstance(args, dict):
            raise ValidationError(
                f"[stage:required_fields] 'arguments' must be an object for tool '{name}'"
            )
        return name, args

    def _check_tool_in_registry(self, name: str) -> None:
        """Stage 3: verify tool name exists in the registry."""
        if name not in self._schemas:
            known = sorted(self._schemas.keys())
            raise ValidationError(
                f"[stage:tool_registry] unknown tool '{name}'. "
                f"Known tools: {known}"
            )

    # ------------------------------------------------------------------
    # Private helpers — argument validation/normalisation
    # ------------------------------------------------------------------

    def _validate_args(
        self,
        args: Any,
        schema: Dict[str, Any],
    ) -> Tuple[bool, Dict[str, Any], str]:
        """Validate and normalise args against a JSON Schema parameter object."""
        if not isinstance(args, dict):
            return False, {}, "arguments is not an object"

        props: Dict[str, Any] = schema.get("properties", {}) if isinstance(schema, dict) else {}
        required: set = set(schema.get("required", [])) if isinstance(schema, dict) else set()

        normalised: Dict[str, Any] = {}

        for key, value in args.items():
            if key not in props:
                # Drop unknown keys — strict control prevents payload injection
                continue
            ok, coerced, err = self._validate_type(value, props[key])
            if not ok:
                return False, {}, f"argument '{key}': {err}"
            normalised[key] = coerced

        # Apply schema defaults for omitted optional fields
        for key, spec in props.items():
            if key not in normalised and "default" in spec:
                normalised[key] = spec["default"]

        missing = required - set(normalised.keys())
        if missing:
            return False, {}, f"missing required argument(s): {', '.join(sorted(missing))}"

        return True, normalised, ""

    @staticmethod
    def _validate_type(
        value: Any,
        spec: Dict[str, Any],
    ) -> Tuple[bool, Any, str]:
        """Type-check and lightly coerce a single value against a JSON Schema type."""
        expected = spec.get("type")
        if expected is None:
            # No type constraint — accept as-is
            return True, value, ""

        # JSON Schema allows a list of types
        if isinstance(expected, list):
            for t in expected:
                ok, coerced, _ = ToolCallValidator._validate_type(value, {"type": t})
                if ok:
                    return True, coerced, ""
            return False, value, f"expected one of {expected}, got {type(value).__name__}"

        if expected == "string":
            if isinstance(value, str):
                return True, value, ""
            # Coerce scalars to string (LLMs often emit numbers for string fields)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return True, str(value), ""
            return False, value, f"expected string, got {type(value).__name__}"

        if expected == "integer":
            if isinstance(value, bool):
                return False, value, "expected integer, got boolean"
            if isinstance(value, int):
                return True, value, ""
            # Coerce digit strings (LLMs sometimes quote numeric IDs)
            if isinstance(value, str) and re.fullmatch(r"-?\d+", value):
                return True, int(value), ""
            return False, value, f"expected integer, got {type(value).__name__}"

        if expected == "number":
            if isinstance(value, bool):
                return False, value, "expected number, got boolean"
            if isinstance(value, (int, float)):
                return True, value, ""
            if isinstance(value, str):
                try:
                    return True, float(value), ""
                except ValueError:
                    pass
            return False, value, f"expected number, got {type(value).__name__}"

        if expected == "boolean":
            if isinstance(value, bool):
                return True, value, ""
            if isinstance(value, str):
                lower = value.strip().lower()
                if lower in ("true", "false"):
                    return True, lower == "true", ""
            return False, value, f"expected boolean, got {type(value).__name__}"

        if expected == "object":
            if isinstance(value, dict):
                return True, value, ""
            return False, value, f"expected object, got {type(value).__name__}"

        if expected == "array":
            if not isinstance(value, list):
                return False, value, f"expected array, got {type(value).__name__}"
            item_spec = spec.get("items")
            if item_spec:
                coerced_items: List[Any] = []
                for i, item in enumerate(value):
                    ok, coerced, err = ToolCallValidator._validate_type(item, item_spec)
                    if not ok:
                        return False, value, f"array item [{i}]: {err}"
                    coerced_items.append(coerced)
                return True, coerced_items, ""
            return True, value, ""

        # Unknown type keyword — accept as-is (forward-compatibility)
        return True, value, ""

    # ------------------------------------------------------------------
    # Private helpers — repair prompt construction
    # ------------------------------------------------------------------

    def _build_repair_prompt(self, bad_response: str, error: ValidationError) -> str:
        """Build a concise repair prompt describing exactly what went wrong.

        The prompt includes:
        - the original (failing) response
        - the exact validation error stage and message
        - the expected JSON shape (with schema when the tool name is recoverable)
        """
        error_msg = str(error)

        # Try to extract the tool name from the error message so we can attach schema
        schema_hint = ""
        name_match = re.search(r"tool '([^']+)'", error_msg)
        if name_match:
            tool_name = name_match.group(1)
            if tool_name in self._schemas:
                schema_hint = (
                    f"\nExpected schema for '{tool_name}':\n"
                    + json.dumps(self._schemas[tool_name], indent=2)
                )

        known_tools = sorted(self._schemas.keys())

        return (
            "Your previous response contained an invalid tool call.\n"
            "\n"
            f"Validation error: {error_msg}\n"
            f"\nKnown tools: {known_tools}"
            f"{schema_hint}\n"
            "\n"
            "Please respond with ONLY a corrected JSON object of the form:\n"
            '{"name": "<tool_name>", "arguments": {<key>: <value>, ...}}\n'
            "\n"
            "No markdown fences, no explanation — just the JSON object.\n"
            "\n"
            f"Original response that failed:\n{bad_response}"
        )
