"""The store contract: the surface it declares, and the rule that keeps it honest."""
import ast
import inspect
import pathlib

from core.store_protocol import FindingStore

# A declared member whose consumer has not been written yet, with the module
# that will call it. The entries for get_findings and update_finding_governed
# went when the governor landed and really called them; scan_id went when the
# consolidator landed and read store.scan_id; and add_finding went when
# result_processor landed and called it -- the same module that added the tool,
# coverage, rollup and status members, each of which it reaches directly. An
# entry excuses a MEMBER rather than a module, so it is spent as soon as ANY
# consumer calls that member. Nothing is pending now: every declared member has
# a live caller under core/, so this map is empty and the stale arm below has
# nothing to expire.
PENDING_CONSUMERS = {}


def _declared_members():
    """Every member name ``FindingStore`` declares, read off the class itself.

    Derived rather than transcribed: a hand-kept list is a copy, and a copy
    drifts the first time a member is added without it. Methods come from the
    class dict and annotated attributes from ``__annotations__``, and the union
    is cross-checked against ``__protocol_attrs__`` where the interpreter
    provides it -- that check is what catches a member declared in a shape
    neither branch reads, a ``property`` being the obvious one.
    """
    methods = {name for name, value in vars(FindingStore).items()
               if not name.startswith("_") and inspect.isfunction(value)}
    attributes = set(getattr(FindingStore, "__annotations__", {}))
    derived = methods | attributes
    authority = getattr(FindingStore, "__protocol_attrs__", None)
    if authority is not None:
        assert derived == set(authority), (
            f"the derivation missed a declared member: {sorted(set(authority) - derived)}"
        )
    return derived


def _member_names_read_on_a_store():
    """Every member name a module under ``core/`` reads on a ``store``.

    Narrowed to ``store.X``, and the narrowing is the whole point. Counting every
    attribute name in the package left this check evadable by coincidence: a dead
    member named ``save`` or ``findings`` was excused outright, because
    ``core/scheduler.py`` reads ``self.save()`` and ``self.findings`` on an object
    with no relationship to a store, while the same dead member named
    ``flush_to_disk`` was caught. The difference was the name and nothing else, so
    the guarantee held only for the names the package happened not to use -- and
    that surface grows with every module added to it.

    What this check is for: it catches a member declared on the Protocol and
    never wired up to anything. That is a real defect class and not a
    hypothetical one, and this repository has shipped it: a module under ``core/``
    raised ``AttributeError`` on its own documented second parameter, because the
    accessor that parameter was asked for lived on a different class from the one
    the annotation, the docstring and the usage example all named. Nothing had
    ever executed the parameter, so nothing had ever found out --
    ``test_recommend_runs_on_both_of_its_documented_signatures`` in
    tests/test_chapter_claims.py exercises both arities now, and the comment above
    it records why no citation check could have caught this: the symbol both
    modules named did exist, in the wrong class. A Protocol whose whole job is to
    document a contract is the worst place to repeat that. The check is not a
    proof that a declared member is reachable, and must not be read as one.

    What the orphan arm matches is a floor: any syntactic ``store.X`` under
    ``core/``, whatever the object is and whatever is being done to it. It asks
    nothing about the object -- ``store`` can be a local dict -- and nothing
    about the operation, so a read, an assignment and a deletion all count
    alike: ``store.absorb(rows)``, ``store.absorb = None`` and
    ``del store.absorb`` each satisfy it for a member named ``absorb`` -- the
    first on a line nothing ever executes, and the other two in modules holding
    no call at all. Name-shaped matching is all it is.

    The consequence runs two ways, and these are the shapes to recognise rather
    than a catalogue of them. It can excuse silently: a module keeping a local
    cache as ``store = {}`` and touching ``store.update`` leaves a dead member
    named ``update`` unreported. It can accuse loudly: a genuine consumer holding
    its store on an attribute, or reaching it through an alias such as
    ``self._store``, is not matched at all, so its member is reported as an
    orphan.

    The Protocol's own file is skipped as a guard, not because it currently
    matters: measured, ``core/store_protocol.py`` contributes no attribute reads
    at all, because a declaration parses as an ``AnnAssign`` or a
    ``FunctionDef`` and never as an attribute read.
    """
    root = pathlib.Path(__file__).resolve().parents[1]
    used = set()
    for path in sorted((root / "core").glob("**/*.py")):
        if path.name == "store_protocol.py" or "__pycache__" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "store"):
                used.add(node.attr)
    return used


def test_no_member_is_declared_that_nothing_under_core_calls():
    """A declared member nobody calls is a contract a reader cannot implement.

    This repository has shipped that defect before, in this same shape: a
    published module raised ``AttributeError`` on its own documented signature,
    because the documentation and the call sites were written from different
    ideas of the surface. A Protocol whose whole job is to document a contract is
    the worst place to repeat it, so the declared members are checked against the
    calls that exist.

    While the consumers are still being written the check would name every
    member, so each one is exempted by an entry in ``PENDING_CONSUMERS`` naming
    the module that will call it. The exemption expires by itself: the stale arm
    fails as soon as a module under ``core/`` really does call the member, so
    whoever ships that consumer must delete the entry rather than leave a
    permanent excuse behind. A member that is neither called nor pending fails
    the first arm and is named in the message.
    """
    declared = _declared_members()
    used = _member_names_read_on_a_store()

    orphans = sorted(m for m in declared if m not in used and m not in PENDING_CONSUMERS)
    assert not orphans, (
        "declared on FindingStore but called by nothing under core/, and not "
        f"listed as pending: {orphans}"
    )

    stale = sorted(m for m in PENDING_CONSUMERS if m in used)
    assert not stale, (
        "PENDING_CONSUMERS entries whose member is now really called under "
        f"core/ -- delete them: {stale}"
    )

    unknown = sorted(m for m in PENDING_CONSUMERS if m not in declared)
    assert not unknown, (
        f"PENDING_CONSUMERS names members FindingStore no longer declares: {unknown}"
    )


def test_the_governed_write_is_the_one_member_that_is_not_a_coroutine():
    """The asymmetry the contract reproduces, pinned so it cannot be tidied away.

    ``update_finding_governed`` is synchronous and its callers invoke it as a
    bare statement, so turning it into an ``async def`` makes the write vanish
    with no exception raised and nothing failing -- Python reports only a
    ``RuntimeWarning`` about a coroutine that was never awaited. A uniform
    all-coroutine surface would read better and would be wrong in exactly the
    direction nothing catches, so this asserts the split rather than trusting a
    docstring to preserve it.
    """
    assert inspect.iscoroutinefunction(FindingStore.add_finding)
    assert inspect.iscoroutinefunction(FindingStore.get_findings)
    assert not inspect.iscoroutinefunction(FindingStore.update_finding_governed)
