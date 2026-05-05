"""``python -m iguanatrader.cli`` shim.

Delegates to :func:`iguanatrader.cli.main.cli_app`. Kept tiny on purpose
so the same entrypoint is reused by the ``poetry run iguanatrader``
script alias declared in ``pyproject.toml``.
"""

from __future__ import annotations

from iguanatrader.cli.main import cli_app

if __name__ == "__main__":  # pragma: no cover — exercised via subprocess in tests
    cli_app()
