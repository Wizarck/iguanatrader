"""Slice 5 — Typer CLI auto-discovery tests.

Covers the spec ``api-foundation`` Requirement 5 scenarios:

* ``python -m iguanatrader.cli --version`` → exit 0 + version string.
* New subcommand module added → registered without any edit to ``main.py``.

The subprocess form is required because Typer's ``Exit`` is raised in
the parent process when invoked in-process; running via ``python -m``
isolates the exit semantics from pytest's runner.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest


def _cli_pkg_dir() -> Path:
    """Path to ``apps/api/src/iguanatrader/cli/``."""
    package = importlib.import_module("iguanatrader.cli")
    package_paths = list(getattr(package, "__path__", []))
    if not package_paths:
        raise RuntimeError("could not resolve iguanatrader.cli path")
    return Path(package_paths[0])


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke ``python -m iguanatrader.cli ...`` with PYTHONPATH wired.

    Uses the same interpreter pytest is running under so the venv's
    typer / iguanatrader install is used.
    """
    # Test file is at apps/api/tests/integration/test_cli_discovery.py;
    # parents[0]=integration, [1]=tests, [2]=api → apps/api/src.
    src_root = Path(__file__).resolve().parents[2] / "src"
    env_path = sys.executable
    return subprocess.run(
        [env_path, "-m", "iguanatrader.cli", *args],
        capture_output=True,
        text=True,
        env={
            **_passthrough_env(),
            "PYTHONPATH": str(src_root),
        },
        timeout=30,
        check=False,
    )


def _passthrough_env() -> dict[str, str]:
    """Shallow copy of the current environment for subprocess inheritance."""
    import os

    return dict(os.environ)


@pytest.fixture
def stub_subcommand() -> Iterator[Path]:
    """Drop a stub ``iguanatrader.cli.zztest_subcommand`` module.

    The module exports ``app: typer.Typer`` with one ``hello`` command;
    discovery should pick it up under the kebab-case CLI name
    ``zztest-subcommand`` (underscore → hyphen).

    Name uses a ``zz`` prefix to sort last in the package directory so
    test pollution from a transient module is at the end of the auto-
    discovery iteration. Avoids a leading underscore (which Typer would
    parse as a short-option flag in the subprocess invocation).
    """
    pkg_dir = _cli_pkg_dir()
    stub_path = pkg_dir / "zztest_subcommand.py"
    stub_path.write_text(
        '"""Test-only subcommand stub — see test_cli_discovery.py."""\n'
        "from __future__ import annotations\n\n"
        "import typer\n\n"
        'app = typer.Typer(help="Stub for discovery test.")\n\n\n'
        "@app.command()\n"
        "def hello() -> None:\n"
        '    """Print a deterministic greeting."""\n'
        '    typer.echo("hello-from-stub")\n',
        encoding="utf-8",
    )
    try:
        yield stub_path
    finally:
        stub_path.unlink(missing_ok=True)
        sys.modules.pop("iguanatrader.cli.zztest_subcommand", None)
        # The auto-registration runs at import of cli.main; drop the
        # cached main module so the next subprocess re-imports cleanly.
        sys.modules.pop("iguanatrader.cli.main", None)


def test_cli_version_exits_zero_with_version_string() -> None:
    """``--version`` prints a non-empty token and exits 0."""
    result = _run_cli("--version")

    assert result.returncode == 0, result.stderr
    out = result.stdout.strip()
    assert out, "version output is empty"
    # Either the installed version (semver-ish) or the source-tree fallback.
    assert out == "0.0.0+local" or out[0].isdigit(), out


def test_cli_help_lists_root_options() -> None:
    """``--help`` shows the root callback's options (sanity)."""
    result = _run_cli("--help")

    assert result.returncode == 0, result.stderr
    assert "--version" in result.stdout


def test_new_subcommand_appears_in_help(stub_subcommand: Path) -> None:
    """A stub ``cli/<name>.py`` exporting ``app`` is registered + listed."""
    result = _run_cli("--help")

    assert result.returncode == 0, result.stderr
    # Module name 'zztest_subcommand' renders as 'zztest-subcommand' in
    # the kebab-case CLI surface (underscore → hyphen replacement).
    assert "zztest-subcommand" in result.stdout, result.stdout


def test_new_subcommand_invocable(stub_subcommand: Path) -> None:
    """The stub's ``hello`` command runs and prints the deterministic token."""
    result = _run_cli("zztest-subcommand", "hello")

    assert result.returncode == 0, result.stderr
    assert "hello-from-stub" in result.stdout
