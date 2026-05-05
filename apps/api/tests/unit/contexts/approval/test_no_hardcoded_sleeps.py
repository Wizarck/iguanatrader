"""CI assertion: no hardcoded `time.sleep` / `asyncio.sleep` literals
inside the approval channels package (per slice P1 task 4.6 + design D3).

Channels MUST inherit reconnect timing from
:class:`HeartbeatMixin` which delegates to
:func:`iguanatrader.shared.backoff.backoff_seconds`. Hardcoded sleep
durations are an ADR-required deviation (NFR-R7).
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest


def _channels_root() -> Path:
    pkg = importlib.import_module(
        "iguanatrader.contexts.approval.channels"
    )
    paths = list(getattr(pkg, "__path__", []))
    if not paths:
        raise RuntimeError("could not resolve channels package path")
    return Path(paths[0])


@pytest.mark.parametrize(
    "module_path",
    sorted(_channels_root().rglob("*.py")),
    ids=lambda p: p.name,
)
def test_no_hardcoded_sleep_literals(module_path: Path) -> None:
    """Forbid ``time.sleep(N)`` / ``asyncio.sleep(N)`` for numeric N inside channels."""
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module_path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # We're looking for `<module>.sleep(...)`; both qualified
        # (``time.sleep``, ``asyncio.sleep``) and bare (``sleep``)
        # forms are checked — bare is unlikely but defensive.
        is_sleep_call = False
        if isinstance(func, ast.Attribute) and func.attr == "sleep":
            is_sleep_call = True
        elif isinstance(func, ast.Name) and func.id == "sleep":
            is_sleep_call = True
        if not is_sleep_call:
            continue
        if not node.args:
            continue
        first_arg = node.args[0]
        if isinstance(first_arg, ast.Constant) and isinstance(
            first_arg.value, (int, float)
        ):
            raise AssertionError(
                f"Hardcoded sleep literal in {module_path}:{node.lineno} — "
                "channels MUST use `iguanatrader.shared.backoff.backoff_seconds` "
                "or inherit reconnect timing from HeartbeatMixin."
            )
