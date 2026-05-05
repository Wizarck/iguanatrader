"""17-command canonical registry — single source of truth (FR37, design D2).

Each command lives in its own module under
:mod:`iguanatrader.contexts.approval.channels.commands.<name>` exporting
``SPEC: CommandSpec``. This package's loader walks
:func:`pkgutil.iter_modules`, imports each module, and folds ``m.SPEC``
into the canonical :data:`COMMANDS` mapping. Adding a command is a
single-file edit (drop a new module under this package); no edit to
the dispatcher, the channels, or the registry is required.

Anti-collision pattern mirrors slice 5's routes/SSE/CLI loaders.

Per spec ``approval`` Requirement 7: the registry MUST contain exactly
17 entries with names matching the canonical set. The
:func:`iguanatrader.contexts.approval.channels.commands.assert_canonical`
helper is exposed for tests.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Mapping
from typing import cast

from iguanatrader.contexts.approval.channels.types import CommandSpec

#: The canonical set of 17 user-facing commands per slice P1 design D2.
#: Tests use this constant to assert no command drift.
CANONICAL_COMMAND_NAMES: frozenset[str] = frozenset(
    {
        "/approve",
        "/reject",
        "/halt",
        "/resume",
        "/status",
        "/positions",
        "/equity",
        "/strategies",
        "/risk",
        "/override",
        "/cost",
        "/budget",
        "/help",
        "/whoami",
        "/lock",
        "/unlock",
        "/logout",
    }
)


def _discover_specs() -> dict[str, CommandSpec]:
    """Walk this package's modules and fold each module's ``SPEC``."""
    package = importlib.import_module(__name__)
    package_path: list[str] = list(getattr(package, "__path__", []))
    out: dict[str, CommandSpec] = {}
    for _finder, module_name, _is_pkg in pkgutil.iter_modules(package_path):
        full_name = f"{__name__}.{module_name}"
        module = importlib.import_module(full_name)
        spec = getattr(module, "SPEC", None)
        if not isinstance(spec, CommandSpec):
            continue
        out[spec.name] = spec
    return out


#: Canonical command map. Built once at import time. Iterating this is
#: how channels enumerate available commands; ``COMMANDS["/approve"]``
#: returns the :class:`CommandSpec` whose handler accepts a
#: :class:`CommandContext` and returns a :class:`CommandResult`.
COMMANDS: Mapping[str, CommandSpec] = _discover_specs()


def assert_canonical() -> None:
    """Raise :class:`AssertionError` if the registry diverges from the spec.

    Sanity check used by ``test_command_registry`` and at app boot.
    """
    actual = frozenset(COMMANDS.keys())
    if actual != CANONICAL_COMMAND_NAMES:
        missing = CANONICAL_COMMAND_NAMES - actual
        extra = actual - CANONICAL_COMMAND_NAMES
        raise AssertionError(
            "approval command registry diverges from canonical set: "
            f"missing={sorted(missing)} extra={sorted(extra)}"
        )
    if len(COMMANDS) != 17:
        raise AssertionError(
            f"approval command registry must have 17 entries; got {len(COMMANDS)}"
        )


__all__ = [
    "CANONICAL_COMMAND_NAMES",
    "COMMANDS",
    "assert_canonical",
]


# Re-export for test convenience — tests use ``cast`` to narrow the
# Mapping value type when iterating.
_ = cast
