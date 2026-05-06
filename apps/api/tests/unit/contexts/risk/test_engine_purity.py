"""Engine purity test — AST inspector that fails the build on impurity regression.

Per slice K1 design D1 + Risks/Trade-offs section: the engine module
MUST stay free of I/O — no ``import datetime``, ``import time``,
``sqlalchemy``, ``requests``, ``httpx``; no ``.now()``, ``.utcnow()``,
``.commit()``, ``.execute()``, ``.add()``, ``.delete()`` call
patterns. Hypothesis property-tests are tractable only because the
function under test is pure.

Implementation: parse the source file with :mod:`ast`, walk the tree,
flag any forbidden node. Failure prints the offending node's line +
context so a developer can revert the offending change quickly.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

# Forbidden module imports — first level only. ``from datetime import
# UTC`` IS forbidden too because it lets engine.py read the clock via
# ``UTC.now()`` indirectly. The check is conservative: if it sees any
# of these names in any import context, it fails.
_FORBIDDEN_IMPORT_MODULES: frozenset[str] = frozenset(
    {
        "datetime",
        "time",
        "sqlalchemy",
        "requests",
        "httpx",
        "aiohttp",
        "asyncpg",
        "aiosqlite",
        "iguanatrader.persistence",
        "iguanatrader.shared.time",
    }
)

# Forbidden attribute access patterns (last component of dotted name).
_FORBIDDEN_CALL_ATTRS: frozenset[str] = frozenset(
    {
        "now",
        "utcnow",
        "commit",
        "execute",
        "add",
        "delete",
    }
)


def _resolve_engine_path() -> Path:
    """Return the absolute path to ``iguanatrader/contexts/risk/engine.py``."""
    spec = importlib.util.find_spec("iguanatrader.contexts.risk.engine")
    if spec is None or spec.origin is None:
        raise RuntimeError("could not resolve iguanatrader.contexts.risk.engine")
    return Path(spec.origin)


def _collect_violations(tree: ast.AST) -> list[str]:
    """Walk ``tree`` and return human-readable violation messages."""
    violations: list[str] = []

    for node in ast.walk(tree):
        # ``import x`` / ``import x as y``
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                full = alias.name
                if root in _FORBIDDEN_IMPORT_MODULES or full in _FORBIDDEN_IMPORT_MODULES:
                    violations.append(
                        f"line {node.lineno}: forbidden 'import {alias.name}' "
                        f"in engine.py (purity invariant)"
                    )
        # ``from x import y``
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            root = mod.split(".")[0]
            if mod in _FORBIDDEN_IMPORT_MODULES or root in _FORBIDDEN_IMPORT_MODULES:
                violations.append(
                    f"line {node.lineno}: forbidden 'from {mod} import ...' "
                    f"in engine.py (purity invariant)"
                )
        # ``foo.bar()`` where bar in forbidden list
        elif isinstance(node, ast.Call):
            func = node.func
            attr_name: str | None = None
            if isinstance(func, ast.Attribute):
                attr_name = func.attr
            elif isinstance(func, ast.Name):
                attr_name = func.id
            if attr_name in _FORBIDDEN_CALL_ATTRS:
                violations.append(
                    f"line {node.lineno}: forbidden call '.{attr_name}(...)' "
                    f"in engine.py (purity invariant)"
                )

    return violations


def test_engine_module_has_no_forbidden_imports_or_calls() -> None:
    """Walk ``engine.py`` AST; assert no forbidden imports or call patterns.

    On failure prints every offending line; reviewers can pinpoint the
    regression without re-reading the source manually.
    """
    path = _resolve_engine_path()
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    violations = _collect_violations(tree)
    assert not violations, (
        "engine.py purity violation(s) — engine MUST stay free of I/O so "
        "the property test is tractable:\n  " + "\n  ".join(violations)
    )


def test_engine_protections_module_has_no_forbidden_imports() -> None:
    """Each protection module MUST stay pure for the same reason.

    Same AST inspection over the 5 protection files; protections are
    composed by the engine, so impurity in any of them poisons the
    composition.
    """
    package_spec = importlib.util.find_spec("iguanatrader.contexts.risk.protections")
    assert package_spec is not None and package_spec.submodule_search_locations
    package_dir = Path(next(iter(package_spec.submodule_search_locations)))

    failures: list[str] = []
    for module_path in package_dir.glob("*.py"):
        if module_path.name == "__init__.py":
            continue
        source = module_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(module_path))
        violations = _collect_violations(tree)
        if violations:
            failures.append(f"{module_path.name}:")
            failures.extend([f"  {v}" for v in violations])

    assert not failures, "protection module purity violation(s):\n" + "\n".join(failures)
