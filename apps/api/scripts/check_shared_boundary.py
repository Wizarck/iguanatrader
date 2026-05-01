"""Boundary check: ``apps/api/src/iguanatrader/shared/`` has no domain deps.

Per the spec requirement "shared/ has no domain dependencies"
(`openspec/changes/shared-primitives/specs/shared-kernel/spec.md`):
the shared kernel MUST NOT import anything from
``iguanatrader.contexts``, ``iguanatrader.api``,
``iguanatrader.persistence``, or ``iguanatrader.cli``.

This script scans every ``.py`` file under ``apps/api/src/iguanatrader/
shared/`` for lines matching::

    from iguanatrader.<contexts|api|persistence|cli>...
    import iguanatrader.<contexts|api|persistence|cli>...

…and exits non-zero with a list of offending file:line entries on
the first violation. Idempotent + zero-output on success.

Wired into ``.pre-commit-config.yaml`` (and CI by extension).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SHARED_DIR = Path("apps/api/src/iguanatrader/shared")
FORBIDDEN_TARGETS = ("contexts", "api", "persistence", "cli")

# Match `from iguanatrader.X` or `import iguanatrader.X` where X is one of
# the forbidden top-level packages. We match the dotted path strictly so
# `iguanatrader.shared.X` (an internal sibling under shared/) does not
# trigger.
_FORBIDDEN_RE = re.compile(
    r"^\s*(from|import)\s+iguanatrader\.(" + "|".join(FORBIDDEN_TARGETS) + r")(?:\.|\s|$)"
)


def scan(root: Path) -> list[tuple[Path, int, str]]:
    """Return a list of ``(file, line_no, line)`` for every violation."""
    violations: list[tuple[Path, int, str]] = []
    if not root.is_dir():
        # No source directory — trivially clean (covers the empty repo case).
        return violations
    for path in sorted(root.rglob("*.py")):
        with path.open(encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if _FORBIDDEN_RE.match(line):
                    violations.append((path, line_no, line.rstrip()))
    return violations


def main() -> int:
    repo_root = Path(__file__).resolve().parents[3]
    violations = scan(repo_root / SHARED_DIR)
    if not violations:
        return 0

    print(
        "shared-kernel boundary check failed — these imports are forbidden:",
        file=sys.stderr,
    )
    for path, line_no, line in violations:
        rel = path.relative_to(repo_root) if path.is_absolute() else path
        print(f"  {rel}:{line_no}: {line}", file=sys.stderr)
    print(
        "\n"
        "shared/ MUST NOT depend on contexts/, api/, persistence/, or cli/. "
        "Move the import to a bounded context, or invert the dependency "
        "(define an interface in shared/ports and have the consumer pass it in).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
