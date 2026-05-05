"""Top-level Typer app + subcommand auto-discovery (slice 5).

Per design D8: this module wires :data:`cli_app` (the entrypoint
:class:`typer.Typer` instance) and registers every subcommand module
under :mod:`iguanatrader.cli` automatically. Slice 5 ships zero
subcommands; the auto-registration loop runs on every CLI invocation
and is a no-op until subsequent slices add modules under
``apps/api/src/iguanatrader/cli/<name>.py`` exporting ``app: typer.Typer``.

Subcommand naming convention: the module's bare name is converted from
``snake_case`` to ``kebab-case`` for the CLI surface — e.g.
``bootstrap_tenant.py`` registers as ``iguanatrader bootstrap-tenant``.
Underscores in module names are not allowed by the CLI grammar; the
conversion happens in :func:`_register_subcommands`.

Performance contract (per gotcha #29): subcommand modules SHOULD use
lazy imports for heavy dependencies. The discovery loop imports every
candidate eagerly at startup so ``--help`` / ``--version`` invocations
pay the import cost of every subcommand. Defer numpy / pandas /
ib_async loads inside the command body to keep ``--version`` fast.
"""

from __future__ import annotations

import importlib
import pkgutil
from importlib.metadata import PackageNotFoundError, version

import typer

cli_app: typer.Typer = typer.Typer(
    name="iguanatrader",
    help="iguanatrader operator CLI.",
    no_args_is_help=True,
    add_completion=False,
)


def _read_package_version() -> str:
    """Resolve the project version from installed-package metadata.

    Falls back to ``"0.0.0+local"`` when running from a source tree
    without ``poetry install`` (e.g. the integration-test smoke). The
    fallback is intentional — running ``--version`` should never raise.
    """
    try:
        return version("iguanatrader")
    except PackageNotFoundError:
        return "0.0.0+local"


def _version_callback(value: bool) -> None:
    """``--version`` short-circuit. Raises :class:`typer.Exit` after print."""
    if value:
        typer.echo(_read_package_version())
        raise typer.Exit(code=0)


@cli_app.callback()
def _root_callback(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Print the iguanatrader version and exit.",
        is_eager=True,
        callback=_version_callback,
    ),
) -> None:
    """Root CLI callback — wires the eager ``--version`` short-circuit."""


def _register_subcommands(app: typer.Typer) -> None:
    """Auto-discover every ``cli/<name>.py`` (excluding ``main``) and register.

    Each candidate module MUST export a top-level ``app: typer.Typer``
    instance; modules without one are silently skipped (no warning —
    helper modules and shared utilities under ``cli/`` are legitimate).

    Subcommand name = module bare name with ``_`` → ``-``. Module is
    imported via :func:`importlib.import_module`; ``ImportError`` from
    a malformed subcommand bubbles up so CLI startup fails loudly
    rather than silently dropping a subcommand.
    """
    # Late import: the package itself is what we iterate; importing it
    # at module scope works, but doing it lazily keeps the module
    # import-light when callers only want ``cli_app`` for testing.
    package = importlib.import_module(__package__)
    package_path: list[str] = list(getattr(package, "__path__", []))

    for _finder, module_name, _is_pkg in pkgutil.iter_modules(package_path):
        if module_name in {"main", "__main__"}:
            continue

        full_name = f"{__package__}.{module_name}"
        module = importlib.import_module(full_name)

        sub_app = getattr(module, "app", None)
        if not isinstance(sub_app, typer.Typer):
            continue

        cli_name = module_name.replace("_", "-")
        app.add_typer(sub_app, name=cli_name)


_register_subcommands(cli_app)


__all__ = [
    "cli_app",
]
