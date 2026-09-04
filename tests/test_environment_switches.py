"""Every environment switch under `core/`, and what this repository does about each.

The switches are the ablation's only ready-made arms, so what they reach and what
they do not is the most load-bearing fact in chapter 05's account of why the study
has not been run. Before this file existed, nothing held that account: a switch
could be added to a module and reach no chapter, and the grounding gate's pair
could be wired into a scoring function without any test noticing either way.

Four properties, and they fail in different directions on purpose. The inventory
is a declared allowlist, so a new `getenv` under `core/` reddens rather than
arriving undisclosed. The per-finding write path reads no environment at all,
which is why it cannot be ablated from a shell and why saying "the governor sits
behind a switch" without that qualification overstates the switch. The grounding
gate's accessors are consulted by nothing here, which is deliberate and is the
reason the review's best arm is not runnable. And every switch in the inventory
has to be named in the handbook, so the disclosure cannot be quietly dropped.

The names are read out of the syntax rather than by grepping for the prefix,
because a switch whose name is held in a module constant is invisible to a grep
for the literal at the call site, and most of these are.
"""

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
HANDBOOK = ROOT / "handbook"

# switch -> the module basenames that read it. Declared, not derived, because a
# right-hand side computed from the same walk as the left could only ever agree.
SWITCHES = {
    "AUTOMATOR_AGGRESSION_LEVEL": ("scheduler.py",),
    "AUTOMATOR_CATEGORY_BUDGETS_ENABLED": ("scheduler.py",),
    "AUTOMATOR_DT_CRITIC": ("critic.py",),
    "AUTOMATOR_DT_CRITIC_THRESHOLD": ("critic.py",),
    "AUTOMATOR_FATIGUE_ENABLED": ("scheduler.py",),
    "AUTOMATOR_GOVERNANCE": ("consolidator.py", "severity_governor.py"),
    "AUTOMATOR_GOVERNANCE_EVIDENCE_CEILING": ("severity_governor.py",),
    "AUTOMATOR_SCHEDULER_ENABLED": ("scheduler.py",),
    "AUTOMATOR_SCOPE_TRACKING": ("scope_guard.py",),
}

# The grounding gate's accessors. Their being unwired is the property; see the
# comment above `critic_enabled` in core/critic.py for why they stay that way.
GROUNDING_ACCESSORS = ("critic_enabled", "critic_threshold")

# The per-finding governance entry point, which callers reach directly.
UNSWITCHED_ENTRY = "govern_finding"


def _string_constants(tree):
    """Module-level `NAME = "literal"` bindings, for resolving a getenv argument."""
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value.value
    return out


def _env_names_in(node, constants):
    """Environment variable names this subtree reads, however it reads them."""
    names = set()
    for child in ast.walk(node):
        key = None
        if isinstance(child, ast.Call):
            func = child.func
            attr = getattr(func, "attr", None) or getattr(func, "id", None)
            is_getenv = attr == "getenv"
            is_environ_get = (
                attr == "get" and isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Attribute) and func.value.attr == "environ"
            )
            if (is_getenv or is_environ_get) and child.args:
                key = child.args[0]
        elif isinstance(child, ast.Subscript) and isinstance(child.value, ast.Attribute) \
                and child.value.attr == "environ":
            key = child.slice
        if key is None:
            continue
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            names.add(key.value)
        elif isinstance(key, ast.Name) and key.id in constants:
            names.add(constants[key.id])
        else:
            names.add(f"<unresolved at line {getattr(key, 'lineno', 0)}>")
    return names


def _inventory():
    """switch -> sorted module basenames, read off the syntax of every core module."""
    found = {}
    for path in sorted(CORE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for name in _env_names_in(tree, _string_constants(tree)):
            found.setdefault(name, set()).add(path.name)
    return {k: tuple(sorted(v)) for k, v in found.items()}


def _function(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node, tree
    raise AssertionError(f"{path.name} no longer defines {name}")


def test_the_environment_switch_inventory_is_the_one_declared_here():
    """A switch added to a module has to be declared, and a switch that moves
    module has to be re-declared.

    The comparison is name to reading modules, not a count and not a set of
    names, because a switch relocating between modules is the drift
    that changes what an arm reaches while leaving every total intact. An
    unresolved argument is reported rather than skipped: a name assembled at
    runtime would otherwise leave a switch outside every property below.
    """
    found = _inventory()
    unresolved = sorted(k for k in found if k.startswith("<"))
    assert not unresolved, unresolved
    assert found == {k: tuple(v) for k, v in SWITCHES.items()}, {
        "only in the tree": {k: v for k, v in found.items() if SWITCHES.get(k) != v},
        "only declared here": {k: v for k, v in SWITCHES.items() if found.get(k) != v},
    }


def test_the_per_finding_write_path_reads_no_environment():
    """`govern_finding` is unswitched, and that is the qualification a sentence
    about the governor sitting behind a switch needs.

    The module docstring of core/severity_governor.py states it; nothing checked
    it. A caller reaching the per-finding entry point directly is governed
    whatever the environment says, so the governor cannot be ablated from a shell
    on the path a report is built from, only on the scan-wide pass.
    """
    node, _ = _function(CORE / "severity_governor.py", UNSWITCHED_ENTRY)
    tree = ast.parse((CORE / "severity_governor.py").read_text(encoding="utf-8"))
    reads = _env_names_in(node, _string_constants(tree))
    assert not reads, f"{UNSWITCHED_ENTRY} now reads {sorted(reads)}"


def test_the_grounding_gate_accessors_are_consulted_by_nothing_here():
    """The review's best ablation arm is not wired, and this is what says so.

    Both accessors are called only from the test suite. Wiring either into the
    scoring function would install an undocumented off switch inside a core
    scoring path, in a document that argues twice over that a documented off
    switch is a control and not a guarantee, so the property asserted here is
    that they stay unconsulted rather than that they work.
    """
    callers = {}
    for path in sorted(CORE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if name in GROUNDING_ACCESSORS:
                    callers.setdefault(name, []).append(f"{path.name}:{node.lineno}")
    assert not callers, callers


def test_every_switch_is_named_in_the_handbook():
    """The disclosure itself, held as a property.

    Every switch in the inventory has to appear by name somewhere under
    `handbook/`, so removing a chapter's disclosure of one reddens here instead
    of leaving the surface wider than the document admits. Naming is a citation
    the claim gate already resolves, not a typed file and line, so a switch that
    moves module breaks the citation rather than going stale silently.
    """
    prose = "\n".join(p.read_text(encoding="utf-8") for p in sorted(HANDBOOK.glob("*.md")))
    unnamed = sorted(name for name in SWITCHES if name not in prose)
    assert not unnamed, unnamed
