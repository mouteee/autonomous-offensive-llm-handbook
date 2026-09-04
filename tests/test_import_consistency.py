"""Every shipped core.* and walkthrough.* module must import, under stdlib-only, one way up.

The second half used to be an assertion nobody made: this file imported every
module and would have passed just as happily on a core/ that imported requests,
as long as requests happened to be installed. The stdlib-only rule is a binding
constraint on this repository, so it is asserted here rather than described.

walkthrough/ sits on top of core/ and carries the same constraint, so both
packages are swept by the same two checks below rather than by a second,
narrower pair scoped to walkthrough/ alone -- a duplicated loop is exactly the
kind of thing that drifts out of step with the original, which is the same
transcription risk this repository's own citation gate exists to catch in
prose.

One shared loop is not one shared allow-set, and the third clause of the summary
above is that difference. The allow-set was `stdlib | {both package names}`,
symmetric where the dependency is not: it permitted core/ importing
walkthrough/, so the sentence above was description and its inversion was
unasserted -- and core/ is the clean-room artifact a reader of this repository
is invited to trust as self-contained. `_ALLOWED_ROOTS` is keyed per package
instead, which puts the direction inside the same sweep that catches a
third-party dependency rather than beside it: an import of walkthrough from core
is an import of something that is neither the standard library nor core, which
is the one thing that sweep already knew how to say.
"""
import ast, importlib, pkgutil, pathlib, sys
import core
import walkthrough

_PACKAGES = (core, walkthrough)


def _package_paths():
    """(dotted name, directory) for every package this file holds to stdlib-only."""
    return [(pkg.__name__, pathlib.Path(pkg.__file__).parent) for pkg in _PACKAGES]


# The non-stdlib roots each package's own modules may import. A package added to _PACKAGES
# without a row here raises KeyError naming it, rather than being swept under a default that
# would quietly permit whatever the default happened to allow.
_ALLOWED_ROOTS = {"core": {"core"}, "walkthrough": {"core", "walkthrough"}}


def test_no_core_or_walkthrough_module_imports_outside_the_standard_library():
    outside = []
    for name, pkg_path in _package_paths():
        allowed = sys.stdlib_module_names | _ALLOWED_ROOTS[name]
        for src in sorted(pkg_path.rglob("*.py")):
            for node in ast.walk(ast.parse(src.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    roots = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    # A relative import stays inside the package by construction.
                    roots = [] if node.level else [(node.module or "").split(".")[0]]
                else:
                    continue
                outside += [
                    f"{name}/{src.relative_to(pkg_path)}: {r}"
                    for r in roots if r and r not in allowed
                ]
    assert not outside, "imports outside the standard library:\n" + "\n".join(outside)


def test_all_core_and_walkthrough_modules_import():
    failures = []
    for name, pkg_path in _package_paths():
        for mod in pkgutil.walk_packages([str(pkg_path)], prefix=f"{name}."):
            try:
                importlib.import_module(mod.name)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{mod.name}: {exc!r}")
    assert not failures, "import failures:\n" + "\n".join(failures)
